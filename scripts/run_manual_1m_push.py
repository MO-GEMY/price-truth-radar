"""
One-Day Manual High-Volume Catalog Expansion Runner for Asarak (أسعارك).

Prioritizes high-demand Egyptian e-commerce categories in order:
  1. electronics_appliances  (electronics, home_appliances)
  2. fashion                 (fashion)
  3. groceries               (groceries)
  4. beauty_health           (beauty, health)
  5. home_furniture          (home_furniture)
  6. lifestyle               (sports, baby_kids, pet_care)

Features:
  - `--dry-run`: Queries Neon live (read-only), reports current DB size, row/SKU counts,
    per-category & per-batch store counts, checkpoint progress in `raw.scraper_discovery_state`,
    projected per-pass throughput, realistic reachable catalog ceiling across current 200 stores,
    and an explicit gap analysis toward 1,000,000 products.
  - Resumes every store from `raw.scraper_discovery_state` via `run_scrapers.py --mode expand --delta`.
  - Bounded parallel worker pool (`--workers`, default 3) with per-store timeouts and graceful
    handling of HTTP 429 / 5xx / WAF blocks without aborting the push.
  - Runs `--match-db` and incremental `dbt run` automatically at compute-saving milestones
    (default every 40 stores) and runs `dbt test` once at the end of the session.
  - Enforces a Neon storage guard (`--max-db-mb`, default 950 MB for the 1 GB Neon plan)
    that stops cleanly before the limit while preserving all `raw.scraper_discovery_state`
    checkpoints.
  - Emits structured `EXPANSION_PROGRESS` logs to stdout and `logs/manual_1m_push_YYYY-MM-DD.log`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psycopg2
import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "data_platform" / "ingestion" / "stores_registry.yaml"
RUNNER_PY = REPO_ROOT / "data_platform" / "ingestion" / "scrapers" / "run_scrapers.py"
DBT_PY = REPO_ROOT / "data_platform" / "run_dbt.py"
LOG_DIR = REPO_ROOT / "logs"
LOCK_FILE = LOG_DIR / ".manual_1m_push.lock"

# High-demand category priority tiers (order matters!)
PRIORITY_TIERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("electronics_appliances", "1. Electronics, Mobiles & Home Appliances", ("electronics", "home_appliances")),
    ("fashion", "2. Fashion & Footwear", ("fashion",)),
    ("groceries", "3. Groceries & Supermarkets", ("groceries",)),
    ("beauty_health", "4. Beauty, Perfumes & Pharmacies/Health", ("beauty", "health")),
    ("home_furniture", "5. Home & Furniture", ("home_furniture",)),
    ("lifestyle", "6. Lifestyle, Sports, Baby/Kids & Pet Care", ("sports", "baby_kids", "pet_care")),
)

# Realistic per-store reachable unique SKU estimates by platform & store scale in Egypt.
# Used ONLY for dry-run capacity planning (never limits live scraping).
MEGA_STORE_ESTIMATES: dict[str, int] = {
    "amazon_eg": 120000,
    "noon": 90000,
    "jumia": 75000,
    "btech": 18000,
    "homzmart": 40000,
    "carrefour_eg": 20000,
    "raneen": 15000,
    "rayashop": 8000,
    "ikea_eg": 9000,
    "decathlon_eg": 6000,
    "spinneys": 12000,
    "hyperone": 15000,
    "seoudi": 10000,
    "metro_market": 8000,
    "gourmet": 4000,
    "chefaa": 25000,
    "el_ezaby": 15000,
    "seif_pharmacies": 12000,
    "misr_pharmacies": 12000,
    "2b": 6000,
    "sigma": 5000,
    "lc_waikiki_eg": 12000,
    "defacto_eg": 10000,
}

PLATFORM_TYPICAL_CATALOG: dict[str, int] = {
    "shopify": 900,
    "woocommerce": 1200,
    "magento_graphql": 3500,
    "custom": 2500,
}

PLATFORM_PAGE_SIZE: dict[str, int] = {
    "shopify": 250,
    "woocommerce": 40,
    "magento_graphql": 24,
    "custom": 48,
}

_DELTA_RE = re.compile(
    r"DELTA_SUMMARY\s*\|\s*total_scraped=(\d+)\s*\|\s*new=(\d+)\s*\|\s*changed=(\d+)\s*\|\s*skipped_unchanged=(\d+)"
)
_CHECKPOINT_RE = re.compile(
    r"EXPAND_CHECKPOINT(?:\s*\(DRY-RUN\))?\s*\|\s*store=([^\s|]+)\s*\|\s*next_page=(\d+)\s*\|\s*next_cursor=([^|]+?)\s*\|.*?wrapped=(True|False)"
)


@dataclass(frozen=True)
class StoreTarget:
    store_key: str
    display_name: str
    platform: str
    category: str
    vertical: str
    region_mode: str
    batch: str
    tier_key: str


@dataclass
class StoreRunResult:
    target: StoreTarget
    status: str  # OK | WRAPPED | THROTTLED | TIMEOUT | FAILED
    scraped: int = 0
    newly_added: int = 0
    changed: int = 0
    next_page: int = 0
    wrapped: bool = False
    elapsed_s: float = 0.0
    note: str = ""


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


def _load_registry_targets(
    region_mode: str,
    selected_tiers: set[str],
) -> list[StoreTarget]:
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
        rmode = str(entry.get("region_mode") or "cloud").strip()
        if region_mode != "all" and rmode != region_mode:
            continue
        cat = str(entry.get("category") or "electronics").strip()
        tkey = cat_to_tier.get(cat, "lifestyle")
        if selected_tiers and tkey not in selected_tiers:
            continue
        vert = str(entry.get("vertical") or "core").strip()
        if vert not in ("core", "fashion", "groceries"):
            vert = "fashion" if cat == "fashion" else ("groceries" if cat == "groceries" else "core")
        targets.append(
            StoreTarget(
                store_key=str(entry["store_key"]).strip(),
                display_name=str(entry.get("display_name") or entry["store_key"]).strip(),
                platform=str(entry.get("platform") or "custom").strip(),
                category=cat,
                vertical=vert,
                region_mode=rmode,
                batch=str(entry.get("batch") or "local_only").strip(),
                tier_key=tkey,
            )
        )

    tier_order = {tkey: idx for idx, (tkey, _, _) in enumerate(PRIORITY_TIERS)}
    # Order by priority tier -> mega-catalog stores first -> cloud before local_only -> store_key
    targets.sort(
        key=lambda t: (
            tier_order.get(t.tier_key, 99),
            -MEGA_STORE_ESTIMATES.get(t.store_key, PLATFORM_TYPICAL_CATALOG.get(t.platform, 900)),
            0 if t.region_mode == "cloud" else 1,
            t.store_key,
        )
    )
    return targets


def _query_neon_snapshot() -> dict[str, Any]:
    db_url = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL_READONLY")
    if not db_url:
        return {"connected": False}

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database()), pg_size_pretty(pg_database_size(current_database()));")
            db_bytes, db_pretty = cur.fetchone()

            cur.execute("SELECT COUNT(*), COUNT(DISTINCT (store_name, external_id)), COUNT(DISTINCT store_name) FROM raw.raw_product_snapshots;")
            raw_rows, raw_skus, raw_stores = cur.fetchone()

            cur.execute("SELECT COUNT(*) FROM gold.mart_product_verdicts;")
            verdicts_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM gold.fct_price_history;")
            history_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM gold.mart_cross_store_matches;")
            matches_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT category, COUNT(*)
                FROM gold.mart_product_verdicts
                GROUP BY category;
                """
            )
            cat_counts = {str(r[0]): int(r[1]) for r in cur.fetchall()}

            cur.execute(
                """
                SELECT store_name, COUNT(*)
                FROM gold.mart_product_verdicts
                GROUP BY store_name;
                """
            )
            store_counts = {str(r[0]): int(r[1]) for r in cur.fetchall()}

            discovery_rows: dict[str, tuple[int, int]] = {}
            try:
                cur.execute(
                    """
                    SELECT store_id, last_page, products_discovered_total
                    FROM raw.scraper_discovery_state;
                    """
                )
                for sid, lp, tot in cur.fetchall():
                    discovery_rows[str(sid)] = (int(lp or 0), int(tot or 0))
            except psycopg2.Error:
                conn.rollback()

            return {
                "connected": True,
                "db_bytes": int(db_bytes),
                "db_mb": round(int(db_bytes) / (1024 * 1024), 1),
                "db_pretty": str(db_pretty),
                "raw_rows": int(raw_rows),
                "raw_skus": int(raw_skus),
                "raw_stores": int(raw_stores),
                "verdicts_count": int(verdicts_count),
                "history_count": int(history_count),
                "matches_count": int(matches_count),
                "cat_counts": cat_counts,
                "store_counts": store_counts,
                "discovery_rows": discovery_rows,
            }
    finally:
        conn.close()


def _query_db_size_mb() -> Optional[float]:
    """Fast, ultra-lightweight Neon DB size probe in MB (single scalar query)."""
    db_url = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL_READONLY")
    if not db_url:
        return None
    try:
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database());")
                row = cur.fetchone()
                return round(int(row[0]) / (1024 * 1024), 1) if row else None
        finally:
            conn.close()
    except Exception:
        return None


def _estimate_store_ceiling(target: StoreTarget, current_skus: int) -> int:
    base = MEGA_STORE_ESTIMATES.get(target.store_key, PLATFORM_TYPICAL_CATALOG.get(target.platform, 900))
    return max(base, int(round(current_skus * 1.25)))


def _estimate_pass_yield(target: StoreTarget, limit: int, max_pages: int) -> int:
    page_size = PLATFORM_PAGE_SIZE.get(target.platform, 48)
    return min(limit, max_pages * page_size)


def _print_dry_run_report(
    targets: list[StoreTarget],
    neon: dict[str, Any],
    *,
    limit: int,
    max_pages: int,
    workers: int,
    waves: int,
    max_db_mb: float,
    milestone_every: int,
) -> None:
    print("=" * 84)
    print("ASARAK — 1M CATALOG EXPANSION DRY-RUN REPORT (ZERO WRITES)")
    print("=" * 84)

    if neon.get("connected"):
        bytes_per_sku = neon["db_bytes"] / max(1, neon["verdicts_count"])
        est_1m_gb = (bytes_per_sku * 1_000_000) / (1024**3)
        print(f"Neon DB Size               : {neon['db_pretty']} ({neon['db_mb']:.1f} MB)")
        print(f"raw.raw_product_snapshots  : {neon['raw_rows']:,} rows ({neon['raw_skus']:,} distinct SKUs across {neon['raw_stores']} stores)")
        print(f"gold.mart_product_verdicts : {neon['verdicts_count']:,} live products")
        print(f"gold.fct_price_history     : {neon['history_count']:,} history rows")
        print(f"gold.mart_cross_store      : {neon['matches_count']:,} matched groups")
        print(f"scraper_discovery_state    : {len(neon['discovery_rows'])} stores checkpointed")
        print(f"Avg Storage / Product      : {bytes_per_sku / 1024:.2f} KB/SKU  ->  Projected 1M SKU DB size: ~{est_1m_gb:.2f} GB")
        if max_db_mb > 0:
            rem_mb = max(0.0, max_db_mb - neon["db_mb"])
            est_add_skus = int((rem_mb * 1024 * 1024) / max(1.0, bytes_per_sku))
            print(
                f"Storage Guard Ceiling      : {max_db_mb:.0f} MB "
                f"({rem_mb:.1f} MB remaining -> ~+{est_add_skus:,} SKUs headroom, ~{neon['verdicts_count'] + est_add_skus:,} total)"
            )
    else:
        print("Neon DB                    : NOT CONNECTED (DATABASE_URL_ADMIN/READONLY unset)")

    print("-" * 84)
    print(
        f"Push Config                : stores={len(targets)} | limit={limit}/store | max_pages={max_pages}/store "
        f"| workers={workers} | waves={waves} | milestone={milestone_every} | max_db_mb={max_db_mb:.0f}"
    )
    print("-" * 84)
    print(f"{'Priority Tier':<42} {'Stores':>6} {'Cloud/Loc':>9} {'Live SKUs':>10} {'1-Wave Cap':>11} {'Est. Ceiling':>13}")
    print("-" * 84)

    store_counts = neon.get("store_counts") or {}
    by_tier: dict[str, list[StoreTarget]] = defaultdict(list)
    for t in targets:
        by_tier[t.tier_key].append(t)

    grand_live = 0
    grand_wave_cap = 0
    grand_ceiling = 0

    for tkey, label, _ in PRIORITY_TIERS:
        group = by_tier.get(tkey) or []
        if not group:
            continue
        cloud_n = sum(1 for t in group if t.region_mode == "cloud")
        local_n = len(group) - cloud_n
        live_skus = sum(store_counts.get(t.store_key, 0) for t in group)
        wave_cap = sum(_estimate_pass_yield(t, limit, max_pages) for t in group)
        ceiling = sum(_estimate_store_ceiling(t, store_counts.get(t.store_key, 0)) for t in group)
        grand_live += live_skus
        grand_wave_cap += wave_cap
        grand_ceiling += ceiling
        print(
            f"{label:<42} {len(group):>6} {f'{cloud_n}/{local_n}':>9} "
            f"{live_skus:>10,} {wave_cap:>11,} {ceiling:>13,}"
        )

    total_cloud = sum(1 for t in targets if t.region_mode == "cloud")
    total_local = len(targets) - total_cloud
    total_cl_label = f"{total_cloud}/{total_local}"
    print("-" * 84)
    print(
        f"{'TOTAL SELECTED':<42} {len(targets):>6} {total_cl_label:>9} "
        f"{grand_live:>10,} {grand_wave_cap:>11,} {grand_ceiling:>13,}"
    )
    print("=" * 84)

    # Batch summary
    by_batch: dict[str, list[StoreTarget]] = defaultdict(list)
    for t in targets:
        by_batch[t.batch].append(t)
    print("\nPer-Batch Breakdown (selected):")
    for bname in sorted(by_batch.keys()):
        bgroup = by_batch[bname]
        blive = sum(store_counts.get(t.store_key, 0) for t in bgroup)
        bceil = sum(_estimate_store_ceiling(t, store_counts.get(t.store_key, 0)) for t in bgroup)
        print(f"  {bname:<16} stores={len(bgroup):>2} | live_skus={blive:>7,} | est_ceiling={bceil:>8,}")

    # Gap analysis toward 1,000,000 products
    remaining_in_current_200 = max(0, grand_ceiling - grand_live)
    gap_to_1m = max(0, 1_000_000 - grand_ceiling)
    print("\n" + "=" * 84)
    print("REALISTIC 1,000,000-PRODUCT FEASIBILITY & GAP ANALYSIS")
    print("=" * 84)
    print(f"  Current live catalog               : {grand_live:>10,} SKUs")
    print(f"  Estimated reachable ceiling (200)  : {grand_ceiling:>10,} SKUs (+{remaining_in_current_200:,} headroom in current stores)")
    print(f"  Remaining gap to 1,000,000 SKUs    : {gap_to_1m:>10,} SKUs")
    if gap_to_1m > 0:
        print("  VERDICT: Current 200 stores can realistically scale to ~550k–700k unique SKUs via")
        print("           deep multi-wave expansion. Reaching 1,000,000 unique SKUs additionally requires:")
        print("           (1) Deeper category/keyword sweeps on mega-marketplaces (Amazon EG, Noon, Jumia, Homzmart),")
        print("           (2) Onboarding ~80–120 more large Egyptian catalogs / multi-vendor pharmacies & hypermarkets, and")
        print("           (3) Neon paid storage (~2.0–2.3 GB required at ~2.1 KB/SKU; Free tier caps at 512 MB).")
    else:
        print("  VERDICT: Reachable within current store set across multi-wave expansion (ensure >=2.2 GB Neon storage).")
    print("=" * 84)


def _run_single_store(
    target: StoreTarget,
    *,
    python_exe: str,
    limit: int,
    max_pages: int,
    delay: float,
    timeout_s: int,
) -> StoreRunResult:
    started = time.monotonic()
    cmd = [
        python_exe,
        str(RUNNER_PY),
        "--store",
        target.store_key,
        "--vertical",
        target.vertical,
        "--mode",
        "expand",
        "--delta",
        "--limit",
        str(limit),
        "--max-pages",
        str(max_pages),
        "--delay",
        str(delay),
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
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
        return StoreRunResult(
            target=target,
            status="TIMEOUT",
            elapsed_s=round(time.monotonic() - started, 1),
            note=f"exceeded {timeout_s}s timeout",
        )
    except Exception as exc:
        return StoreRunResult(
            target=target,
            status="FAILED",
            elapsed_s=round(time.monotonic() - started, 1),
            note=str(exc)[:120],
        )

    elapsed = round(time.monotonic() - started, 1)
    combined = f"{proc.stdout}\n{proc.stderr}"

    scraped = 0
    newly_added = 0
    changed = 0
    if m := _DELTA_RE.search(combined):
        scraped = int(m.group(1))
        newly_added = int(m.group(2))
        changed = int(m.group(3))

    next_page = 0
    wrapped = False
    if cm := _CHECKPOINT_RE.search(combined):
        next_page = int(cm.group(2))
        wrapped = cm.group(4) == "True"

    if proc.returncode == 0:
        status = "WRAPPED" if wrapped else "OK"
        return StoreRunResult(
            target=target,
            status=status,
            scraped=scraped,
            newly_added=newly_added,
            changed=changed,
            next_page=next_page,
            wrapped=wrapped,
            elapsed_s=elapsed,
        )

    low = combined.lower()
    if "429" in low or "too many requests" in low or "403" in low or "throttle" in low or "waf" in low:
        return StoreRunResult(
            target=target,
            status="THROTTLED",
            scraped=scraped,
            newly_added=newly_added,
            elapsed_s=elapsed,
            note=f"exit={proc.returncode} (HTTP 429/403/WAF)",
        )

    return StoreRunResult(
        target=target,
        status="FAILED",
        scraped=scraped,
        newly_added=newly_added,
        elapsed_s=elapsed,
        note=f"exit={proc.returncode}",
    )


def _run_milestone(
    python_exe: str,
    logger: Logger,
    *,
    skip_match_db: bool,
    skip_dbt: bool,
    run_dbt_test: bool = False,
    label: str,
) -> None:
    logger.log(f"EXPANSION_PROGRESS | MILESTONE_START | label={label}")
    if not skip_match_db:
        t0 = time.monotonic()
        res = subprocess.run(
            [python_exe, str(RUNNER_PY), "--match-db"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        logger.log(
            f"EXPANSION_PROGRESS | MILESTONE_MATCH_DB | label={label} | exit={res.returncode} | elapsed={time.monotonic() - t0:.1f}s"
        )
    if not skip_dbt:
        t0 = time.monotonic()
        res = subprocess.run(
            [python_exe, str(DBT_PY), "run"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        logger.log(
            f"EXPANSION_PROGRESS | MILESTONE_DBT_INCREMENTAL | label={label} | exit={res.returncode} | elapsed={time.monotonic() - t0:.1f}s"
        )
        if run_dbt_test and res.returncode == 0:
            t1 = time.monotonic()
            tres = subprocess.run(
                [python_exe, str(DBT_PY), "test"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
            logger.log(
                f"EXPANSION_PROGRESS | FINAL_DBT_TEST | label={label} | exit={tres.returncode} | elapsed={time.monotonic() - t1:.1f}s"
            )


def _acquire_lock() -> bool:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            pid_str = LOCK_FILE.read_text(encoding="utf-8").strip()
            pid = int(pid_str)
            # Check if PID is alive on Windows/POSIX
            os.kill(pid, 0)
            return False
        except Exception:
            # Stale lockfile; safe to reclaim
            pass
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="One-day manual high-volume prioritized catalog expansion runner for Asarak.",
    )
    p.add_argument("--dry-run", action="store_true", help="Print live Neon stats and 1M catalog feasibility estimate without scraping or writing.")
    p.add_argument("--limit", type=int, default=1500, help="Per-store product cap per expand pass (default: 1500).")
    p.add_argument("--max-pages", type=int, default=15, help="Per-store page cap per expand pass (default: 15).")
    p.add_argument("--workers", type=int, default=3, help="Concurrent store subprocess workers (1-6, default: 3).")
    p.add_argument("--waves", type=int, default=1, help="Number of full prioritized expansion passes to run (default: 1).")
    p.add_argument("--delay", type=float, default=1.2, help="Polite HTTP delay per worker in seconds (default: 1.2).")
    p.add_argument("--store-timeout", type=int, default=240, help="Max seconds per store subprocess before graceful timeout (default: 240).")
    p.add_argument("--categories", default="", help="Optional comma-separated tier keys or categories (e.g. 'electronics_appliances,fashion,groceries').")
    p.add_argument("--region-mode", choices=["all", "cloud", "local_only"], default="all", help="Which stores to include (default: all 200 stores).")
    p.add_argument("--milestone-every", type=int, default=40, help="Run --match-db + incremental dbt every N completed stores (default: 40 for CU-hr savings).")
    p.add_argument("--max-db-mb", type=float, default=950.0, help="Neon DB size stop ceiling in MB (default: 950 for 1 GB Neon plan; 0 = unlimited).")
    p.add_argument("--skip-match-db", action="store_true", help="Skip --match-db at milestones.")
    p.add_argument("--skip-dbt", action="store_true", help="Skip incremental dbt run and final dbt test.")
    p.add_argument("--skip-final-test", action="store_true", help="Skip the single end-of-session dbt test pass.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(REPO_ROOT / ".env")

    args = _build_parser().parse_args(argv)
    workers = max(1, min(6, int(args.workers)))
    limit = max(1, int(args.limit))
    max_pages = max(1, int(args.max_pages))
    waves = max(1, int(args.waves))

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

    targets = _load_registry_targets(args.region_mode, selected_tiers)
    if not targets:
        print("No enabled stores matched the requested filters.")
        return 1

    neon = _query_neon_snapshot()
    if args.dry_run:
        _print_dry_run_report(
            targets,
            neon,
            limit=limit,
            max_pages=max_pages,
            workers=workers,
            waves=waves,
            max_db_mb=args.max_db_mb,
            milestone_every=args.milestone_every,
        )
        return 0

    if args.max_db_mb > 0 and neon.get("connected") and neon["db_mb"] >= args.max_db_mb:
        print(
            f"EXPANSION_PROGRESS | DB_GUARD_PRECHECK_STOP | db_mb={neon['db_mb']:.1f} >= max_db_mb={args.max_db_mb:.0f} "
            f"(no stores launched; checkpoints preserved)."
        )
        return 0

    if not _acquire_lock():
        print(f"ERROR: Another manual push is already running (lockfile active: {LOCK_FILE}).")
        return 2

    log_path = LOG_DIR / f"manual_1m_push_{datetime.now().strftime('%Y-%m-%d')}.log"
    logger = Logger(log_path)
    python_exe = sys.executable

    try:
        logger.log(
            f"EXPANSION_PROGRESS | PUSH_START | stores={len(targets)} | waves={waves} "
            f"| limit={limit} | max_pages={max_pages} | workers={workers} "
            f"| milestone_every={args.milestone_every} | max_db_mb={args.max_db_mb:.0f} | db_mb={neon.get('db_mb', 'n/a')}"
        )

        by_tier: dict[str, list[StoreTarget]] = defaultdict(list)
        for t in targets:
            by_tier[t.tier_key].append(t)

        cumulative_new = 0
        cumulative_scraped = 0
        completed_total = 0
        status_counts: dict[str, int] = defaultdict(int)
        since_milestone = 0
        new_since_milestone = 0
        stopped_by_db_guard = False

        for wave in range(1, waves + 1):
            if stopped_by_db_guard:
                break
            logger.log(f"EXPANSION_PROGRESS | WAVE_START | wave={wave}/{waves}")

            for tkey, tlabel, _ in PRIORITY_TIERS:
                tier_targets = by_tier.get(tkey) or []
                if not tier_targets or stopped_by_db_guard:
                    continue

                logger.log(f"EXPANSION_PROGRESS | TIER_START | wave={wave} | tier={tkey} ({tlabel}) | stores={len(tier_targets)}")

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(
                            _run_single_store,
                            target,
                            python_exe=python_exe,
                            limit=limit,
                            max_pages=max_pages,
                            delay=args.delay,
                            timeout_s=args.store_timeout,
                        ): target
                        for target in tier_targets
                    }

                    for fut in as_completed(futures):
                        if fut.cancelled():
                            continue
                        res = fut.result()
                        completed_total += 1
                        since_milestone += 1
                        status_counts[res.status] += 1
                        cumulative_scraped += res.scraped
                        cumulative_new += res.newly_added
                        new_since_milestone += res.newly_added

                        logger.log(
                            f"EXPANSION_PROGRESS | wave={wave} | tier={tkey} | store={res.target.store_key} "
                            f"| status={res.status} | scraped={res.scraped} | new={res.newly_added} "
                            f"| next_page={res.next_page} | wrapped={res.wrapped} "
                            f"| cumulative_new={cumulative_new} | elapsed={res.elapsed_s}s"
                            + (f" | note={res.note}" if res.note else "")
                        )

                        # Cheap 1-row DB size probe every 10 completed stores to protect the 950 MB ceiling
                        if args.max_db_mb > 0 and (completed_total % 10 == 0 or (args.milestone_every > 0 and since_milestone >= args.milestone_every)):
                            cur_db_mb = _query_db_size_mb()
                            if cur_db_mb is not None and cur_db_mb >= args.max_db_mb:
                                logger.log(
                                    f"EXPANSION_PROGRESS | DB_GUARD_STOP | db_mb={cur_db_mb:.1f} >= max_db_mb={args.max_db_mb:.0f} "
                                    f"(cancelling queued stores; checkpoints preserved)"
                                )
                                stopped_by_db_guard = True
                                for pending in futures:
                                    pending.cancel()
                                break

                        if args.milestone_every > 0 and since_milestone >= args.milestone_every:
                            since_milestone = 0
                            if new_since_milestone > 0:
                                new_since_milestone = 0
                                _run_milestone(
                                    python_exe,
                                    logger,
                                    skip_match_db=args.skip_match_db,
                                    skip_dbt=args.skip_dbt,
                                    run_dbt_test=False,
                                    label=f"wave{wave}_{tkey}_store{completed_total}",
                                )

        # Single final refresh + single end-of-session `dbt test` (maximum CU-hr conservation)
        if cumulative_new > 0 or new_since_milestone > 0:
            _run_milestone(
                python_exe,
                logger,
                skip_match_db=args.skip_match_db,
                skip_dbt=args.skip_dbt,
                run_dbt_test=(not args.skip_final_test),
                label="session_final",
            )

        final_neon = _query_neon_snapshot()
        logger.log(
            f"EXPANSION_PROGRESS | PUSH_COMPLETE | completed_stores={completed_total} "
            f"| total_scraped={cumulative_scraped} | cumulative_new={cumulative_new} "
            f"| statuses={dict(status_counts)} | live_verdicts={final_neon.get('verdicts_count', 'n/a')} "
            f"| db_mb={final_neon.get('db_mb', 'n/a')} | stopped_by_db_guard={stopped_by_db_guard}"
        )
        return 0
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
