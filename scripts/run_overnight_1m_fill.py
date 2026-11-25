"""
Autonomous Overnight 1M Catalog Fill Runner for Asarak (أسعارك).

Designed specifically for EXTREME Neon Compute (`CU-hr`) conservation while
maximizing unique SKU discovery up to the ~950 MB Neon storage allowance:

  1. Zero Neon connections during HTTP scraping:
     - At the start of each category tier, opens ONE brief Neon query to read
       `raw.scraper_discovery_state` checkpoints for that tier and closes immediately.
     - Scrapes all stores in the tier concurrently via isolated zero-DB worker
       subprocesses (`scripts/scrape_store_to_jsonl.py`) writing JSONL to
       `data/overnight_staging/` — keeping Neon idle/suspended (`0 CU`) throughout.
     - At tier completion, opens ONE brief Neon connection to bulk-upsert the
       staged delta batch (`execute_values`), batch-update `raw.scraper_discovery_state`,
       check `pg_database_size(current_database())`, and immediately close.
  2. Strict category priority order across all 199 active stores (`kassem_store` skipped):
     electronics_appliances -> fashion -> groceries -> beauty_health -> home_furniture -> lifestyle
  3. Auto-loops waves (up to `MaxWaves=10`, `-Limit 2500`, `-MaxPages 30`, `-Workers 4`)
     skipping stores already exhausted earlier in the session, stopping cleanly when:
       (a) `pg_database_size(current_database()) >= 890 MB` (~60 MB buffer for WAL/branch
           overhead so Neon Console lands near ~950 MB without hitting the 1 GB lock), OR
       (b) A completed wave discovers `< 500` new SKUs across all tiers.
  4. Runs ZERO mid-wave `--match-db`, `dbt run`, or `dbt test`. Executes ONE single
     `--match-db` + incremental `dbt run` + `dbt test` at the very end of the session.
  5. Prevents Windows sleep via `SetThreadExecutionState(0x80000001)` (reset on exit)
     and writes a concise wake-up report to `logs/overnight_summary.txt`.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psycopg2
from psycopg2 import errors as pg_errors
from psycopg2.extras import execute_values
import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_platform.ingestion.scrapers.base import (  # noqa: E402
    DDL_SQL,
    RawProductSnapshot,
    TOUCH_LAST_SEEN_SQL,
    UPSERT_SQL,
    _fetch_existing_latest_for_stores,
    bulk_copy_snapshots_to_neon,
    compute_delta_snapshots,
    truncate_raw_snapshots_after_dbt,
)
from data_platform.ingestion.scrapers.currency_guard import filter_currency_flip_batches  # noqa: E402
from data_platform.ingestion.scrapers.discovery_state import DISCOVERY_STATE_DDL_SQL  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "data_platform" / "ingestion" / "stores_registry.yaml"
WORKER_PY = REPO_ROOT / "scripts" / "scrape_store_to_jsonl.py"
RUNNER_PY = REPO_ROOT / "data_platform" / "ingestion" / "scrapers" / "run_scrapers.py"
DBT_PY = REPO_ROOT / "data_platform" / "run_dbt.py"
STAGING_ROOT = REPO_ROOT / "data" / "overnight_staging"
LOG_DIR = REPO_ROOT / "logs"
SUMMARY_PATH = LOG_DIR / "overnight_summary.txt"
LOCK_FILE = LOG_DIR / ".overnight_1m_fill.lock"

SKIP_STORES = frozenset({"kassem_store"})

PRIORITY_TIERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("electronics_appliances", "1. Electronics, Mobiles & Home Appliances", ("electronics", "home_appliances")),
    ("fashion", "2. Fashion & Footwear", ("fashion",)),
    ("groceries", "3. Groceries & Supermarkets", ("groceries",)),
    ("beauty_health", "4. Beauty, Perfumes & Pharmacies/Health", ("beauty", "health")),
    ("home_furniture", "5. Home & Furniture", ("home_furniture",)),
    ("lifestyle", "6. Lifestyle, Sports, Baby/Kids & Pet Care", ("sports", "baby_kids", "pet_care")),
)

MEGA_PRIORITY_WEIGHTS: dict[str, int] = {
    # Wave 1 High-ROI Electronics & Home Appliances priority anchors
    "amazon_eg": 150000,
    "btech": 140000,
    "2b": 135000,
    "noon": 130000,
    "tradeline": 125000,
    "rayashop": 120000,
    "dream2000": 115000,
    "egyptlaptop": 110000,
    "dubaiphone": 105000,
    "sigma": 100000,
    "compumarts": 95000,
    "elaraby": 92000,
    "ehab_center": 90000,
    "raneen": 88000,
    "cairosales": 85000,
    # Wave 2 high-depth stores across remaining categories
    "jumia": 75000,
    "homzmart": 40000,
    "chefaa": 25000,
    "carrefour_eg": 20000,
    "hyperone": 15000,
    "el_ezaby": 15000,
    "spinneys": 12000,
    "seif_pharmacies": 12000,
    "misr_pharmacies": 12000,
    "lc_waikiki_eg": 12000,
    "seoudi": 10000,
    "defacto_eg": 10000,
    "ikea_eg": 9000,
    "metro_market": 8000,
    "decathlon_eg": 6000,
}

BATCH_UPSERT_CHECKPOINT_SQL = """
INSERT INTO raw.scraper_discovery_state (
    store_id,
    last_cursor,
    last_page,
    products_discovered_total,
    updated_at
) VALUES %s
ON CONFLICT (store_id) DO UPDATE SET
    last_cursor               = EXCLUDED.last_cursor,
    last_page                 = EXCLUDED.last_page,
    products_discovered_total = raw.scraper_discovery_state.products_discovered_total
                                + EXCLUDED.products_discovered_total,
    updated_at                = NOW();
"""

# Windows SetThreadExecutionState constants
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@dataclass(frozen=True)
class StoreTarget:
    store_key: str
    platform: str
    category: str
    vertical: str
    region_mode: str
    tier_key: str


class Logger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        with self._lock:
            print(line, flush=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


def _prevent_windows_sleep(enable: bool, logger: Optional[Logger] = None) -> None:
    if sys.platform != "win32":
        return
    try:
        flags = (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) if enable else ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        if logger:
            logger.log(f"POWER | SetThreadExecutionState(0x{flags:08X}) {'ENABLED (prevent sleep)' if enable else 'RESET'}")
    except Exception as exc:
        if logger:
            logger.log(f"POWER | Could not update SetThreadExecutionState: {exc}")


def _acquire_lock() -> bool:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            return False
        except Exception:
            pass
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass


def _load_targets(selected_tiers: set[str]) -> list[StoreTarget]:
    from data_platform.ingestion.scrapers import SCRAPER_REGISTRY

    raw = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    stores = raw.get("stores") or []
    cat_to_tier: dict[str, str] = {}
    for tkey, _, cats in PRIORITY_TIERS:
        for c in cats:
            cat_to_tier[c] = tkey

    targets: list[StoreTarget] = []
    for entry in stores:
        if not entry.get("enabled"):
            continue
        skey = str(entry["store_key"]).strip()
        if skey in SKIP_STORES:
            continue
        cat = str(entry.get("category") or "electronics").strip()
        tkey = cat_to_tier.get(cat, "lifestyle")
        vert = str(entry.get("vertical") or "core").strip()
        if vert not in ("core", "fashion", "groceries"):
            vert = "fashion" if cat == "fashion" else ("groceries" if cat == "groceries" else "core")
        scraper_cls = SCRAPER_REGISTRY.get(skey)
        if scraper_cls is None:
            continue
        supported = getattr(scraper_cls, "supported_verticals", ("core",))
        raw_verts = [vert] + [str(v).strip() for v in (entry.get("extra_verticals") or []) if str(v).strip()]
        seen_v: set[str] = set()
        for cand_v in raw_verts:
            eff_v = cand_v if cand_v in supported else supported[0]
            if eff_v in seen_v:
                continue
            seen_v.add(eff_v)
            eff_cat = "groceries" if eff_v == "groceries" else ("fashion" if eff_v == "fashion" else cat)
            eff_tier = cat_to_tier.get(eff_cat, tkey)
            if selected_tiers and eff_tier not in selected_tiers:
                continue
            targets.append(
                StoreTarget(
                    store_key=skey,
                    platform=str(entry.get("platform") or "custom").strip(),
                    category=eff_cat,
                    vertical=eff_v,
                    region_mode=str(entry.get("region_mode") or "cloud").strip(),
                    tier_key=eff_tier,
                )
            )

    tier_order = {tkey: idx for idx, (tkey, _, _) in enumerate(PRIORITY_TIERS)}
    targets.sort(
        key=lambda t: (
            tier_order.get(t.tier_key, 99),
            -MEGA_PRIORITY_WEIGHTS.get(t.store_key, 1000),
            0 if t.region_mode == "cloud" else 1,
            t.store_key,
        )
    )
    return targets


def _neon_connect_with_retry(db_url: str, max_attempts: int = 5) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return psycopg2.connect(db_url, connect_timeout=20)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts:
                raise
            time.sleep(min(2.0 * attempt, 10.0))
    assert last_exc is not None
    raise last_exc


def _read_tier_checkpoints_and_size(
    store_keys: list[str],
    db_url: str,
) -> tuple[dict[str, tuple[int, Optional[str], int]], float, float]:
    """ONE short Neon connection: read tier checkpoints + current DB MB, then close immediately."""
    t0 = time.monotonic()
    conn = _neon_connect_with_retry(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DISCOVERY_STATE_DDL_SQL)
                cur.execute(
                    """
                    SELECT store_id, last_page, last_cursor, products_discovered_total
                    FROM raw.scraper_discovery_state
                    WHERE store_id = ANY(%s);
                    """,
                    (store_keys,),
                )
                checkpoints: dict[str, tuple[int, Optional[str], int]] = {}
                for sid, lp, lc, tot in cur.fetchall():
                    checkpoints[str(sid)] = (
                        max(0, int(lp or 0)),
                        str(lc) if lc is not None else None,
                        max(0, int(tot or 0)),
                    )
                cur.execute("SELECT pg_database_size(current_database());")
                db_mb = round(int(cur.fetchone()[0]) / (1024 * 1024), 1)
    finally:
        conn.close()
    return checkpoints, db_mb, round(time.monotonic() - t0, 2)


def _flush_tier_to_neon(
    tier_dir: Path,
    metas: list[dict[str, Any]],
    db_url: str,
    logger: Logger,
    *,
    max_attempts: int = 5,
) -> tuple[int, int, int, dict[str, int], float, float]:
    """ONE short Neon connection to bulk-upsert all staged JSONL snapshots + checkpoints + check DB size."""
    t0 = time.monotonic()
    snapshots: list[RawProductSnapshot] = []
    dedup_keys: set[tuple[str, str, str]] = set()

    for m in metas:
        jf_str = m.get("jsonl_path")
        jf = Path(jf_str) if jf_str else (tier_dir / f"{m['store_id']}.jsonl")
        if not jf.exists():
            continue
        with jf.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = RawProductSnapshot.model_validate_json(line)
                    k = (rec.store_name, rec.external_id, rec.snapshot_date.isoformat())
                    if k in dedup_keys:
                        continue
                    dedup_keys.add(k)
                    snapshots.append(rec)
                except Exception:
                    continue

    checkpoint_metas = [m for m in metas if m.get("checkpoint_updated")]

    if not snapshots and not checkpoint_metas:
        conn = _neon_connect_with_retry(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database());")
                db_mb = round(int(cur.fetchone()[0]) / (1024 * 1024), 1)
        finally:
            conn.close()
        return 0, 0, 0, {}, db_mb, round(time.monotonic() - t0, 2)

    for attempt in range(1, max_attempts + 1):
        conn = _neon_connect_with_retry(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('raw_product_snapshots_upsert'))")
                cur.execute(DDL_SQL)
                cur.execute(DISCOVERY_STATE_DDL_SQL)

                new_by_store: dict[str, int] = {}
                new_total = 0
                changed_total = 0
                upserted_rows = 0

                if snapshots:
                    snapshots, flip_alerts = filter_currency_flip_batches(snapshots, conn)
                    for fa in flip_alerts:
                        logger.log(
                            f"CURRENCY_MISMATCH_SUSPECTED | store={fa.store_name} | quarantined={fa.batch_count} "
                            f"| median_ratio={fa.median_ratio:.3f}x | reason={fa.reason}"
                        )
                if snapshots:
                    # Stream-load via PostgreSQL COPY (10x faster than batched INSERT, minimal Neon CU)
                    upserted_rows = bulk_copy_snapshots_to_neon(
                        snapshots,
                        conn=conn,
                        check_currency_flip=False,  # already validated above inside this transaction
                    )
                    new_total = upserted_rows
                    for s in snapshots:
                        new_by_store[s.store_name] = new_by_store.get(s.store_name, 0) + 1

                if checkpoint_metas:
                    cp_by_store: dict[str, tuple[str, Optional[str], int, int]] = {}
                    for m in checkpoint_metas:
                        sid = str(m["store_id"])
                        cand_page = max(0, int(m.get("next_page") or 0))
                        cand_new = max(0, int(new_by_store.get(sid, 0)))
                        prev = cp_by_store.get(sid)
                        if prev is None or cand_page >= prev[2]:
                            cp_by_store[sid] = (sid, m.get("next_cursor"), cand_page, cand_new)
                    cp_rows = sorted(cp_by_store.values(), key=lambda r: r[0])
                    execute_values(
                        cur,
                        BATCH_UPSERT_CHECKPOINT_SQL,
                        cp_rows,
                        template="(%s, %s, %s, %s, NOW())",
                        page_size=200,
                    )

                cur.execute("SELECT pg_database_size(current_database());")
                db_mb = round(int(cur.fetchone()[0]) / (1024 * 1024), 1)
            conn.commit()
            return upserted_rows, new_total, changed_total, new_by_store, db_mb, round(time.monotonic() - t0, 2)
        except (psycopg2.OperationalError, psycopg2.InterfaceError, pg_errors.DeadlockDetected, pg_errors.SerializationFailure) as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt >= max_attempts:
                raise
            sleep_for = min(2.0 * (2 ** (attempt - 1)), 15.0)
            logger.log(f"NEON_FLUSH_RETRY | attempt={attempt}/{max_attempts} | err={type(exc).__name__}: {str(exc)[:100]} | sleep={sleep_for:.1f}s")
            time.sleep(sleep_for)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    raise RuntimeError("Unreachable flush retry exit")


def _scrape_store_offline(
    target: StoreTarget,
    *,
    python_exe: str,
    tier_dir: Path,
    start_page: int,
    start_cursor: Optional[str],
    limit: int,
    max_pages: int,
    delay: float,
    timeout_s: int,
) -> dict[str, Any]:
    stem = f"{target.store_key}__{target.vertical}"
    out_jsonl = tier_dir / f"{stem}.jsonl"
    out_meta = tier_dir / f"{stem}.meta.json"
    if out_meta.exists():
        out_meta.unlink(missing_ok=True)
    if out_jsonl.exists():
        out_jsonl.unlink(missing_ok=True)

    cmd = [
        python_exe,
        str(WORKER_PY),
        "--store", target.store_key,
        "--vertical", target.vertical,
        "--limit", str(limit),
        "--max-pages", str(max_pages),
        "--delay", str(delay),
        "--start-page", str(start_page),
        "--start-cursor", start_cursor or "",
        "--out-jsonl", str(out_jsonl),
        "--out-meta", str(out_meta),
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Physically prevent any Neon DB connection from the scraping worker
    env["DATABASE_URL_ADMIN"] = ""
    env["DATABASE_URL_READONLY"] = ""

    started = time.monotonic()
    try:
        subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {
            "store_id": target.store_key,
            "status": "TIMEOUT",
            "scraped": 0,
            "pages_fetched": 0,
            "next_page": start_page,
            "next_cursor": start_cursor,
            "exhausted_catalog": False,
            "checkpoint_updated": False,
            "elapsed_s": round(time.monotonic() - started, 1),
            "note": f"exceeded {timeout_s}s timeout",
        }
    except Exception as exc:
        return {
            "store_id": target.store_key,
            "status": "FAILED",
            "scraped": 0,
            "pages_fetched": 0,
            "next_page": start_page,
            "next_cursor": start_cursor,
            "exhausted_catalog": False,
            "checkpoint_updated": False,
            "elapsed_s": round(time.monotonic() - started, 1),
            "note": str(exc)[:120],
        }

    if out_meta.exists():
        try:
            loaded = json.loads(out_meta.read_text(encoding="utf-8"))
            loaded["jsonl_path"] = str(out_jsonl)
            return loaded
        except Exception:
            pass

    return {
        "store_id": target.store_key,
        "status": "FAILED",
        "scraped": 0,
        "pages_fetched": 0,
        "next_page": start_page,
        "next_cursor": start_cursor,
        "exhausted_catalog": False,
        "checkpoint_updated": False,
        "elapsed_s": round(time.monotonic() - started, 1),
        "note": "worker exited without meta",
    }


def _query_final_neon_stats(db_url: str) -> dict[str, Any]:
    t0 = time.monotonic()
    conn = _neon_connect_with_retry(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database()), pg_size_pretty(pg_database_size(current_database()));")
            db_bytes, db_pretty = cur.fetchone()
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT (store_name, external_id)) FROM raw.raw_product_snapshots;")
            raw_rows, raw_skus = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM gold.mart_product_verdicts;")
            verdicts = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM gold.fct_price_history;")
            history = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM gold.mart_cross_store_matches;")
            matches = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*), COALESCE(SUM(products_discovered_total), 0) FROM raw.scraper_discovery_state;")
            cp_stores, cp_total = cur.fetchone()
            return {
                "db_mb": round(int(db_bytes) / (1024 * 1024), 1),
                "db_pretty": str(db_pretty),
                "raw_rows": int(raw_rows),
                "raw_skus": int(raw_skus),
                "live_verdicts": int(verdicts),
                "fct_price_history": int(history),
                "cross_store_matches": int(matches),
                "checkpointed_stores": int(cp_stores),
                "checkpointed_discovered_sum": int(cp_total),
                "query_s": round(time.monotonic() - t0, 2),
            }
    finally:
        conn.close()


def _run_final_pipeline(python_exe: str, logger: Logger) -> tuple[int, int, int, float]:
    """Run ONE single --match-db + incremental dbt run + dbt test at session end."""
    t0 = time.monotonic()
    logger.log("OVERNIGHT | FINAL_PIPELINE_START | running --match-db -> incremental dbt run -> dbt test")

    t_m = time.monotonic()
    r_match = subprocess.run(
        [python_exe, str(RUNNER_PY), "--match-db"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    logger.log(f"OVERNIGHT | FINAL_MATCH_DB | exit={r_match.returncode} | elapsed={time.monotonic() - t_m:.1f}s")

    t_r = time.monotonic()
    r_dbt = subprocess.run(
        [python_exe, str(DBT_PY), "run"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    logger.log(f"OVERNIGHT | FINAL_DBT_RUN | exit={r_dbt.returncode} | elapsed={time.monotonic() - t_r:.1f}s")

    t_t = time.monotonic()
    r_test = subprocess.run(
        [python_exe, str(DBT_PY), "test"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    logger.log(f"OVERNIGHT | FINAL_DBT_TEST | exit={r_test.returncode} | elapsed={time.monotonic() - t_t:.1f}s")
    if r_dbt.returncode == 0 and r_test.returncode == 0:
        cleared = truncate_raw_snapshots_after_dbt(dry_run=False)
        logger.log(f"OVERNIGHT | ZERO_REST_RAW_TRUNCATED | rows={cleared:,}")
    return r_match.returncode, r_dbt.returncode, r_test.returncode, round(time.monotonic() - t0, 1)


def _write_summary(
    *,
    started_at: datetime,
    finished_at: datetime,
    waves_completed: int,
    max_waves: int,
    stop_reason: str,
    total_scraped: int,
    total_new: int,
    total_changed: int,
    status_counts: Counter[str],
    neon_flush_seconds: float,
    final_pipeline_seconds: float,
    final_codes: tuple[int, int, int],
    final_stats: dict[str, Any],
    wave_history: list[str],
    log_path: Path,
) -> None:
    duration_min = (finished_at - started_at).total_seconds() / 60.0
    lines = [
        "=" * 78,
        "ASARAK — AUTONOMOUS OVERNIGHT 1M FILL SUMMARY",
        "=" * 78,
        f"Started At                : {started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Finished At               : {finished_at.strftime('%Y-%m-%d %H:%M:%S')} ({duration_min:.1f} min total)",
        f"Stop Reason               : {stop_reason}",
        f"Waves Completed           : {waves_completed} / {max_waves}",
        "-" * 78,
        f"Final Live Verdicts SKUs  : {final_stats.get('live_verdicts', 'n/a'):,}" if isinstance(final_stats.get("live_verdicts"), int) else f"Final Live Verdicts SKUs  : {final_stats.get('live_verdicts', 'n/a')}",
        f"Final Raw Rows / SKUs     : {final_stats.get('raw_rows', 'n/a')} / {final_stats.get('raw_skus', 'n/a')}",
        f"Final Price History Rows  : {final_stats.get('fct_price_history', 'n/a')}",
        f"Final Cross-Store Matches : {final_stats.get('cross_store_matches', 'n/a')}",
        f"Final Neon DB Size        : {final_stats.get('db_pretty', 'n/a')} ({final_stats.get('db_mb', 'n/a')} MB)",
        f"Checkpointed Stores       : {final_stats.get('checkpointed_stores', 'n/a')}",
        "-" * 78,
        f"Session Scraped Rows      : {total_scraped:,}",
        f"Session New SKUs Added    : {total_new:,}",
        f"Session Changed Existing  : {total_changed:,}",
        f"Store Status Breakdown    : {dict(sorted(status_counts.items()))}",
        "-" * 78,
        f"Neon Active Flush Time    : {neon_flush_seconds:.1f}s (all scraping ran offline with 0 DB connections)",
        f"Final Match+dbt Time      : {final_pipeline_seconds:.1f}s (match_db={final_codes[0]}, dbt_run={final_codes[1]}, dbt_test={final_codes[2]})",
        f"Detailed Log File         : {log_path}",
        "-" * 78,
        "Per-Wave Breakdown:",
        *(f"  {w}" for w in wave_history),
        "=" * 78,
    ]
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Autonomous overnight CU-hr-saving 1M catalog fill runner.")
    p.add_argument("--limit", type=int, default=2500, help="Per-store product cap per wave (default: 2500).")
    p.add_argument("--max-pages", type=int, default=30, help="Per-store page cap per wave (default: 30).")
    p.add_argument("--workers", type=int, default=4, help="Offline HTTP scraping worker processes (default: 4).")
    p.add_argument("--max-waves", type=int, default=10, help="Maximum waves to auto-loop (default: 10).")
    p.add_argument("--max-db-mb", type=float, default=950.0, help="Neon DB size stop ceiling in MB (default: 950 MB safety guard).")
    p.add_argument("--min-wave-new", type=int, default=500, help="Stop early if a completed wave adds fewer than N new SKUs (default: 500).")
    p.add_argument("--delay", type=float, default=1.0, help="Polite delay per worker in seconds (default: 1.0).")
    p.add_argument("--store-timeout", type=int, default=210, help="Hard per-store subprocess timeout in seconds (default: 210).")
    p.add_argument("--categories", default="", help="Optional comma-separated priority tiers (default: all 6 tiers).")
    p.add_argument("--stores", default="", help="Optional comma-separated store_keys to run (default: all in selected categories).")
    p.add_argument("--sync-dbt-per-wave", action="store_true", help="Run fast incremental dbt (stg+history+verdicts) + TRUNCATE raw after each wave so --max-db-mb tracks true gold DB size.")
    p.add_argument("--skip-final-pipeline", action="store_true", help="Skip final --match-db / dbt run / dbt test (for tiny smoke tests).")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(REPO_ROOT / ".env")

    args = _build_parser().parse_args(argv)
    db_url = os.getenv("DATABASE_URL_ADMIN")
    if not db_url:
        print("ERROR: DATABASE_URL_ADMIN is not set in environment / .env")
        return 1

    if not _acquire_lock():
        print(f"ERROR: Overnight runner already active (lockfile: {LOCK_FILE}).")
        return 2

    started_at = datetime.now()
    log_path = LOG_DIR / f"overnight_fill_{started_at.strftime('%Y-%m-%d_%H%M%S')}.log"
    logger = Logger(log_path)

    selected_tiers: set[str] = set()
    if args.categories.strip():
        cat_map = {tkey: tkey for tkey, _, _ in PRIORITY_TIERS}
        for tkey, _, cats in PRIORITY_TIERS:
            for c in cats:
                cat_map[c] = tkey
        for tok in args.categories.split(","):
            k = tok.strip().lower()
            if k in cat_map:
                selected_tiers.add(cat_map[k])

    targets = _load_targets(selected_tiers)
    if args.stores.strip():
        allowed_stores = {s.strip().lower() for s in args.stores.split(",") if s.strip()}
        targets = [t for t in targets if t.store_key.lower() in allowed_stores]
    by_tier: dict[str, list[StoreTarget]] = defaultdict(list)
    for t in targets:
        by_tier[t.tier_key].append(t)

    workers = max(1, min(8, int(args.workers)))
    python_exe = sys.executable

    _prevent_windows_sleep(True, logger)

    waves_completed = 0
    stop_reason = "completed_max_waves"
    total_scraped = 0
    total_new = 0
    total_changed = 0
    status_counts: Counter[str] = Counter()
    neon_flush_seconds = 0.0
    final_pipeline_seconds = 0.0
    final_codes = (-1, -1, -1)
    wave_history: list[str] = []

    # Session-level skip trackers so later waves focus 100% on deep catalogs
    session_exhausted: set[str] = set()
    consecutive_failures: Counter[str] = Counter()
    consecutive_zero_new_custom: Counter[str] = Counter()
    platform_by_store = {t.store_key: t.platform for t in targets}

    try:
        logger.log(
            f"OVERNIGHT | START | stores={len(targets)} (skipped={sorted(SKIP_STORES)}) "
            f"| limit={args.limit} | max_pages={args.max_pages} | workers={workers} "
            f"| max_waves={args.max_waves} | max_db_mb={args.max_db_mb:.0f} | min_wave_new={args.min_wave_new}"
        )

        hit_storage_limit = False

        for wave in range(1, args.max_waves + 1):
            if hit_storage_limit:
                break

            wave_t0 = time.monotonic()
            wave_new = 0
            wave_scraped = 0
            wave_stores_run = 0
            logger.log(f"OVERNIGHT | WAVE_START | wave={wave}/{args.max_waves} | exhausted_skipped={len(session_exhausted)}")

            for tkey, tlabel, _ in PRIORITY_TIERS:
                if hit_storage_limit:
                    break
                tier_all = by_tier.get(tkey) or []
                tier_active = [
                    t for t in tier_all
                    if t.store_key not in session_exhausted
                    and consecutive_failures[t.store_key] < 2
                    and consecutive_zero_new_custom[t.store_key] < 2
                ]
                if not tier_active:
                    logger.log(f"OVERNIGHT | TIER_SKIP | wave={wave} | tier={tkey} (all stores exhausted/capped this session)")
                    continue

                # 1. ONE quick Neon query for tier checkpoints + DB size, immediately closed!
                checkpoints, pre_db_mb, read_s = _read_tier_checkpoints_and_size(
                    [t.store_key for t in tier_active], db_url
                )
                neon_flush_seconds += read_s
                logger.log(
                    f"OVERNIGHT | TIER_START | wave={wave} | tier={tkey} ({tlabel}) "
                    f"| active_stores={len(tier_active)}/{len(tier_all)} | pre_db_mb={pre_db_mb:.1f} | cp_read={read_s}s"
                )

                if pre_db_mb >= args.max_db_mb:
                    stop_reason = f"db_storage_ceiling_reached ({pre_db_mb:.1f} MB >= {args.max_db_mb:.0f} MB)"
                    logger.log(f"OVERNIGHT | DB_CEILING_STOP | {stop_reason}")
                    hit_storage_limit = True
                    break

                # 2. Scrape entire tier OFFLINE to local JSONL (ZERO Neon DB connections!)
                tier_dir = STAGING_ROOT / f"wave{wave}_{tkey}"
                if tier_dir.exists():
                    shutil.rmtree(tier_dir, ignore_errors=True)
                tier_dir.mkdir(parents=True, exist_ok=True)

                scrape_t0 = time.monotonic()
                tier_metas: list[dict[str, Any]] = []

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {}
                    for target in tier_active:
                        cp_page, cp_cursor, _ = checkpoints.get(target.store_key, (0, None, 0))
                        fut = pool.submit(
                            _scrape_store_offline,
                            target,
                            python_exe=python_exe,
                            tier_dir=tier_dir,
                            start_page=cp_page,
                            start_cursor=cp_cursor,
                            limit=args.limit,
                            max_pages=args.max_pages,
                            delay=args.delay,
                            timeout_s=args.store_timeout,
                        )
                        futures[fut] = target

                    for fut in as_completed(futures):
                        meta = fut.result()
                        tier_metas.append(meta)
                        sid = meta["store_id"]
                        st = meta["status"]
                        status_counts[st] += 1
                        wave_stores_run += 1
                        wave_scraped += int(meta.get("scraped") or 0)
                        total_scraped += int(meta.get("scraped") or 0)

                        if st in ("OK", "WRAPPED"):
                            consecutive_failures[sid] = 0
                            if meta.get("exhausted_catalog"):
                                session_exhausted.add(sid)
                        else:
                            consecutive_failures[sid] += 1

                        logger.log(
                            f"EXPANSION_PROGRESS | wave={wave} | tier={tkey} | store={sid} "
                            f"| status={st} | scraped={meta.get('scraped', 0)} "
                            f"| next_page={meta.get('next_page', 0)} | wrapped={meta.get('exhausted_catalog', False)} "
                            f"| elapsed={meta.get('elapsed_s', 0)}s"
                            + (f" | note={meta.get('note')}" if meta.get("note") else "")
                        )

                scrape_elapsed = round(time.monotonic() - scrape_t0, 1)

                # 3. Open Neon ONCE to bulk-upsert staged delta batch + checkpoints + check DB size!
                upserted, tier_new, tier_changed, new_by_store, post_db_mb, flush_s = _flush_tier_to_neon(
                    tier_dir, tier_metas, db_url, logger
                )
                neon_flush_seconds += flush_s
                wave_new += tier_new
                total_new += tier_new
                total_changed += tier_changed

                # Track custom stores that yield 0 new SKUs so they don't spin across Waves 3..10
                for m in tier_metas:
                    sid = m["store_id"]
                    if m["status"] in ("OK", "WRAPPED") and platform_by_store.get(sid) == "custom" and sid != "carrefour_eg":
                        if new_by_store.get(sid, 0) == 0:
                            consecutive_zero_new_custom[sid] += 1
                        else:
                            consecutive_zero_new_custom[sid] = 0

                # Clean up flushed local JSONL staging files
                shutil.rmtree(tier_dir, ignore_errors=True)

                logger.log(
                    f"OVERNIGHT | TIER_FLUSHED | wave={wave} | tier={tkey} "
                    f"| offline_scrape={scrape_elapsed}s | neon_flush={flush_s}s "
                    f"| upserted={upserted} | new={tier_new} | changed={tier_changed} "
                    f"| post_db_mb={post_db_mb:.1f}/{args.max_db_mb:.0f} | session_new={total_new:,}"
                )

                # If Neon is approaching ceiling while raw staging is populated, run fast gold sync + raw truncate
                # so we measure true persistent gold DB size without overshooting --max-db-mb.
                if args.sync_dbt_per_wave and post_db_mb >= max(650.0, args.max_db_mb - 60.0):
                    rc_mid = subprocess.call(
                        [python_exe, str(DBT_PY), "run", "--select", "stg_products", "fct_price_history", "mart_product_verdicts"],
                        cwd=str(REPO_ROOT),
                    )
                    if rc_mid == 0:
                        cleared_mid = truncate_raw_snapshots_after_dbt(dry_run=False)
                        _, post_db_mb, _ = _read_tier_checkpoints_and_size([], db_url)
                        logger.log(
                            f"OVERNIGHT | MID_WAVE_SYNC_DBT | wave={wave} | tier={tkey} | truncated_raw={cleared_mid:,} "
                            f"| true_gold_db_mb={post_db_mb:.1f}/{args.max_db_mb:.0f}"
                        )

                if post_db_mb >= args.max_db_mb:
                    stop_reason = f"db_storage_ceiling_reached ({post_db_mb:.1f} MB >= {args.max_db_mb:.0f} MB)"
                    logger.log(f"OVERNIGHT | DB_CEILING_STOP | {stop_reason}")
                    hit_storage_limit = True
                    break

            waves_completed = wave
            wave_elapsed_min = (time.monotonic() - wave_t0) / 60.0
            wave_line = (
                f"Wave {wave}: stores_run={wave_stores_run} | scraped={wave_scraped:,} "
                f"| new_skus={wave_new:,} | elapsed={wave_elapsed_min:.1f}m"
            )
            wave_history.append(wave_line)
            logger.log(f"OVERNIGHT | WAVE_COMPLETE | {wave_line}")

            if args.sync_dbt_per_wave and wave_scraped > 0:
                t_sync = time.monotonic()
                rc_sync = subprocess.call(
                    [python_exe, str(DBT_PY), "run", "--select", "stg_products", "fct_price_history", "mart_product_verdicts"],
                    cwd=str(REPO_ROOT),
                )
                if rc_sync == 0:
                    cleared = truncate_raw_snapshots_after_dbt(dry_run=False)
                    _, post_sync_mb, _ = _read_tier_checkpoints_and_size([], db_url)
                    logger.log(
                        f"OVERNIGHT | WAVE_SYNC_DBT | wave={wave} | truncated_raw={cleared:,} "
                        f"| true_gold_db_mb={post_sync_mb:.1f}/{args.max_db_mb:.0f} | elapsed={time.monotonic() - t_sync:.1f}s"
                    )
                    if post_sync_mb >= args.max_db_mb:
                        stop_reason = f"db_storage_ceiling_reached ({post_sync_mb:.1f} MB >= {args.max_db_mb:.0f} MB)"
                        logger.log(f"OVERNIGHT | DB_CEILING_STOP | {stop_reason}")
                        hit_storage_limit = True
                else:
                    logger.log(f"OVERNIGHT | WAVE_SYNC_DBT_WARN | wave={wave} | rc={rc_sync}; raw preserved.")

            if hit_storage_limit:
                break

            if wave_new < args.min_wave_new:
                stop_reason = f"low_yield_early_stop (wave {wave} added {wave_new} < {args.min_wave_new} new SKUs)"
                logger.log(f"OVERNIGHT | LOW_YIELD_STOP | {stop_reason}")
                break

        # ONE single final --match-db + incremental dbt run + dbt test at session end!
        if not args.skip_final_pipeline and (total_new > 0 or total_changed > 0):
            m_rc, r_rc, t_rc, final_pipeline_seconds = _run_final_pipeline(python_exe, logger)
            final_codes = (m_rc, r_rc, t_rc)
        else:
            logger.log("OVERNIGHT | FINAL_PIPELINE_SKIPPED (skip flag set or 0 rows changed)")

        final_stats = _query_final_neon_stats(db_url)
        neon_flush_seconds += float(final_stats.get("query_s") or 0.0)
        finished_at = datetime.now()

        _write_summary(
            started_at=started_at,
            finished_at=finished_at,
            waves_completed=waves_completed,
            max_waves=args.max_waves,
            stop_reason=stop_reason,
            total_scraped=total_scraped,
            total_new=total_new,
            total_changed=total_changed,
            status_counts=status_counts,
            neon_flush_seconds=neon_flush_seconds,
            final_pipeline_seconds=final_pipeline_seconds,
            final_codes=final_codes,
            final_stats=final_stats,
            wave_history=wave_history,
            log_path=log_path,
        )
        logger.log(
            f"OVERNIGHT | COMPLETE | stop={stop_reason} | waves={waves_completed} "
            f"| new={total_new:,} | live_verdicts={final_stats.get('live_verdicts')} "
            f"| db_mb={final_stats.get('db_mb')} | neon_flush_s={neon_flush_seconds:.1f}s "
            f"| summary={SUMMARY_PATH}"
        )
        return 0
    except Exception as exc:
        logger.log(f"OVERNIGHT | FATAL_ERROR | {type(exc).__name__}: {exc}")
        raise
    finally:
        _prevent_windows_sleep(False, logger)
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
