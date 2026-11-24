"""Zero-DB Offline Tiered Pipeline & Single-Session Neon Bulk-COPY Orchestrator.

Implements the ultra-low-compute Asarak catalog expansion architecture:
  1. `plan`               : Zero-DB deterministic wave planner using `stores_registry.yaml`
                            (Priority 1 major_brands daily -> Priority 2 major_stores daily ->
                             Priority 3 Tier-2 rotated every 3 days -> Tier-3 every 5 days).
  2. `scrape-shard`       : 100% offline HTTP scraper worker (unsets all DATABASE_URL* env vars,
                            runs OOS filtering, bilingual brand normalization, attributes compaction,
                            and local deduplication, writing compact `.jsonl.gz` staging artifacts).
  3. `load-and-transform` : Opens Neon ONCE after all HTTP scraping completes:
                              - Evaluates 900 MB / 950 MB storage circuit-breaker (+ Telegram alerts)
                              - Bulk-loads Priority 1 -> Priority 2 -> Priority 3 waves via PostgreSQL `COPY`
                                (re-checking headroom between priority waves!)
                              - Runs incremental `dbt run` (including 45-day OOS hygiene)
                              - Runs gold-backed `--match-db` + `dbt run --select mart_cross_store_matches`
                              - Runs `dbt test`
                              - ONLY AFTER `dbt run` and `dbt test` pass: `TRUNCATE TABLE raw.raw_product_snapshots`
                              - Closes Neon connection immediately.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_platform.ingestion.scrapers import (  # noqa: E402
    PoliteHttpClient,
    RawProductSnapshot,
    SCRAPER_REGISTRY,
    ScrapeMode,
    ScrapeVertical,
    bulk_copy_snapshots_to_neon,
    get_store_tier_map,
    load_stores_registry,
    plan_tiered_waves_for_day,
    truncate_raw_snapshots_after_dbt,
)
from data_platform.ingestion.scrapers.storage_circuit_breaker import (  # noqa: E402
    EXPANSION_CEILING_MB,
    HARD_STOP_CEILING_MB,
    evaluate_storage_mode,
    fetch_tracked_product_sks,
    filter_for_price_update_only,
    inspect_neon_storage,
    send_storage_telegram_alert,
)

logger = logging.getLogger(__name__)


def _cmd_plan(args: argparse.Namespace) -> int:
    day_of_year = args.day_of_year or datetime.now(timezone.utc).timetuple().tm_yday
    region = None if args.include_local else "cloud"
    plan = plan_tiered_waves_for_day(
        day_of_year,
        region_mode=region,
        tier2_cadence_days=args.tier2_cadence,
        tier3_cadence_days=args.tier3_cadence,
        include_all_tiers=args.all_tiers,
    )

    # Optional priority filter (e.g. 'p1', 'p2', 'p3', or comma-separated store keys)
    raw_filter = (args.filter or "all").strip().lower()
    if raw_filter and raw_filter != "all":
        if raw_filter in ("p1", "priority1", "major_brands"):
            plan["shards"] = [s for s in plan["shards"] if s["priority"] == "p1_major_brands"]
        elif raw_filter in ("p2", "priority2", "major_stores"):
            plan["shards"] = [s for s in plan["shards"] if s["priority"] == "p2_major_stores"]
        elif raw_filter in ("p1_p2", "tier1"):
            plan["shards"] = [
                s for s in plan["shards"] if s["priority"] in ("p1_major_brands", "p2_major_stores")
            ]
        elif raw_filter in ("p3", "priority3"):
            plan["shards"] = [
                s for s in plan["shards"] if s["priority"] in ("p3_tier2", "p3_tier3")
            ]
        else:
            allowed = {tok.strip() for tok in raw_filter.split(",") if tok.strip()}
            filtered = [s for s in plan["shards"] if s["shard"].lower() in allowed]
            if not filtered:
                # Match individual store keys
                matched_stores = [
                    e.store_key
                    for e in load_stores_registry(enabled_only=True, region_mode=region)
                    if e.store_key in allowed
                ]
                if matched_stores:
                    filtered = [{"shard": "custom_1", "priority": "p1_major_brands", "stores": matched_stores}]
            plan["shards"] = filtered

    if args.github_output:
        gh_path = Path(args.github_output)
        with gh_path.open("a", encoding="utf-8") as fh:
            fh.write(f"shards={json.dumps(plan['shards'])}\n")
            fh.write(f"has_shards={'true' if plan['shards'] else 'false'}\n")
            fh.write(f"counts={json.dumps(plan['counts'])}\n")

    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


def _scrape_one_store_offline(
    store_key: str,
    vertical: ScrapeVertical,
    *,
    mode: ScrapeMode,
    delay: float,
    limit_override: Optional[int] = None,
) -> tuple[str, list[RawProductSnapshot], dict[str, Any]]:
    scraper_cls = SCRAPER_REGISTRY.get(store_key)
    if scraper_cls is None:
        return store_key, [], {"store": store_key, "vertical": vertical, "status": "MISSING", "scraped": 0}

    supported = getattr(scraper_cls, "supported_verticals", ("core",))
    eff_vertical: ScrapeVertical = vertical if vertical in supported else supported[0]
    started = time.monotonic()
    try:
        with PoliteHttpClient(min_delay_seconds=delay) as http_client:
            scraper = scraper_cls(
                http_client,
                mode=mode,
                vertical=eff_vertical,
                tracked_external_ids=set(),
            )
            eff_limit = scraper.get_target_limit(mode, eff_vertical) if limit_override is None else limit_override
            recs = scraper.scrape(limit=eff_limit)
            meta = {
                "store": store_key,
                "vertical": eff_vertical,
                "status": "OK" if recs else "EMPTY",
                "scraped": len(recs),
                "skipped_oos": scraper.skipped_oos_count,
                "skipped_invalid": scraper.skipped_count,
                "pages": scraper.pages_fetched,
                "elapsed_s": round(time.monotonic() - started, 1),
            }
            return store_key, recs, meta
    except Exception as exc:
        return (
            store_key,
            [],
            {
                "store": store_key,
                "vertical": eff_vertical,
                "status": "FAILED",
                "scraped": 0,
                "error": f"{type(exc).__name__}: {str(exc)[:140]}",
                "elapsed_s": round(time.monotonic() - started, 1),
            },
        )


def _cmd_scrape_shard(args: argparse.Namespace) -> int:
    # Enforce ZERO Neon connections during offline HTTP scraping
    for env_key in ("DATABASE_URL", "DATABASE_URL_ADMIN", "DATABASE_URL_READONLY"):
        os.environ[env_key] = ""

    raw_stores = [s.strip().lower() for s in args.stores.split(",") if s.strip()]
    reg_entries = {e.store_key: e for e in load_stores_registry(enabled_only=True)}
    targets: list[tuple[str, ScrapeVertical]] = []
    for skey in raw_stores:
        entry = reg_entries.get(skey)
        if entry is None:
            if skey in SCRAPER_REGISTRY:
                targets.append((skey, SCRAPER_REGISTRY[skey].supported_verticals[0]))
            continue
        for vert in entry.all_verticals:
            targets.append((skey, vert))

    mode: ScrapeMode = "discover" if args.mode == "discovery" else args.mode
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    store_stats: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(targets) or 1))) as pool:
        futs = [
            pool.submit(
                _scrape_one_store_offline,
                skey,
                vert,
                mode=mode,
                delay=args.delay,
                limit_override=args.limit,
            )
            for skey, vert in targets
        ]
        for fut in as_completed(futs):
            _, recs, meta = fut.result()
            store_stats.append(meta)
            print(
                f"OFFLINE_SCRAPE | store={meta['store']} | vertical={meta['vertical']} "
                f"| status={meta['status']} | kept={meta['scraped']} "
                f"| skipped_oos={meta.get('skipped_oos', 0)} | {meta.get('elapsed_s', 0)}s",
                flush=True,
            )
            for rec in recs:
                # Extra safety: never stage brand-new OOS from offline scraper
                if not rec.in_stock:
                    continue
                row = rec.to_json_dict()
                k = (row["store_name"], row["external_id"], row["snapshot_date"])
                deduped[k] = row

    tmp_path = out_path.with_suffix(".tmp.gz")
    with gzip.open(tmp_path, "wt", encoding="utf-8", compresslevel=6) as gz:
        for row in deduped.values():
            gz.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp_path.replace(out_path)

    meta_path = out_path.with_suffix(".meta.json")
    summary = {
        "shard": args.shard,
        "priority": args.priority,
        "mode": mode,
        "records_written": len(deduped),
        "stores": store_stats,
    }
    meta_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"SHARD_DONE | shard={args.shard} | priority={args.priority} "
        f"| unique_in_stock_records={len(deduped):,} | out={out_path}"
    )
    return 0


def _load_jsonl_artifacts(artifacts_dir: Path) -> list[RawProductSnapshot]:
    files = sorted(artifacts_dir.rglob("*.jsonl.gz")) + sorted(artifacts_dir.rglob("*.jsonl"))
    deduped: dict[tuple[str, str, str], RawProductSnapshot] = {}
    for fp in files:
        opener = gzip.open if fp.suffix == ".gz" else open
        with opener(fp, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = RawProductSnapshot.model_validate(json.loads(line))
                except Exception:
                    continue
                key = (rec.store_name, rec.external_id, rec.snapshot_date.isoformat())
                prev = deduped.get(key)
                if prev is None or rec.scraped_at >= prev.scraped_at:
                    deduped[key] = rec
    return list(deduped.values())


def _partition_by_priority(
    records: list[RawProductSnapshot],
    tier_map: dict[str, tuple[int, str]],
) -> list[tuple[str, list[RawProductSnapshot]]]:
    """Partition snapshots into strict Priority 1 -> Priority 2 -> Priority 3A -> Priority 3B waves."""
    buckets: dict[str, list[RawProductSnapshot]] = {
        "P1_MAJOR_BRANDS": [],
        "P2_MAJOR_STORES": [],
        "P3_TIER2_MID": [],
        "P3_TIER3_LONG_TAIL": [],
    }
    for rec in records:
        tier, pgroup = tier_map.get(rec.store_name.lower(), (3, "long_tail"))
        if tier == 1 and pgroup == "major_brands":
            buckets["P1_MAJOR_BRANDS"].append(rec)
        elif tier == 1:
            buckets["P2_MAJOR_STORES"].append(rec)
        elif tier == 2:
            buckets["P3_TIER2_MID"].append(rec)
        else:
            buckets["P3_TIER3_LONG_TAIL"].append(rec)
    return [(name, rows) for name, rows in buckets.items() if rows]


def _cmd_load_and_transform(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")
    artifacts_dir = Path(args.artifacts_dir)
    records = _load_jsonl_artifacts(artifacts_dir)
    print(f"Loaded {len(records):,} deduplicated offline records from {artifacts_dir}")

    if not records and not args.force_dbt:
        print("No offline records found; skipping Neon wake cleanly (0 CU).")
        return 0

    import psycopg2

    db_url = os.getenv("DATABASE_URL_ADMIN")
    if not db_url:
        raise RuntimeError("DATABASE_URL_ADMIN is required for load-and-transform.")

    tier_map = get_store_tier_map(enabled_only=False)
    waves = _partition_by_priority(records, tier_map)
    total_copied = 0
    tracked_sks: Optional[set[str]] = None
    notified_modes: set[str] = set()

    conn = psycopg2.connect(db_url)
    try:
        # Step 1: Check Neon storage circuit-breaker BEFORE any write
        snap_before = inspect_neon_storage(conn=conn)
        decision = evaluate_storage_mode(
            snap_before.db_size_mb,
            warn_mb=args.warn_mb,
            stop_mb=args.stop_mb,
        )
        print(f"CIRCUIT_BREAKER | mode={decision.mode} | db={snap_before.db_size_mb:.2f} MB | {decision.reason}")

        if decision.should_notify and decision.mode not in notified_modes:
            send_storage_telegram_alert(decision, snap_before, context="pre-load check")
            notified_modes.add(decision.mode)

        if not decision.allow_writes:
            print("HARD_STOP active (> 950 MB) — aborting new writes cleanly.")
            return 0 if args.soft_exit_on_stop else 42

        # Step 2: Load strictly Priority 1 -> Priority 2 -> Priority 3A -> Priority 3B via PostgreSQL COPY
        for wave_name, wave_rows in waves:
            snap_wave = inspect_neon_storage(conn=conn)
            wave_dec = evaluate_storage_mode(
                snap_wave.db_size_mb,
                warn_mb=args.warn_mb,
                stop_mb=args.stop_mb,
            )
            if wave_dec.should_notify and wave_dec.mode not in notified_modes:
                send_storage_telegram_alert(wave_dec, snap_wave, context=wave_name)
                notified_modes.add(wave_dec.mode)

            if not wave_dec.allow_writes:
                print(f"WAVE_STOPPED | wave={wave_name} | db={snap_wave.db_size_mb:.2f} MB > {args.stop_mb:.0f} MB")
                break

            to_load = wave_rows
            dropped_new = 0
            if not wave_dec.allow_new_inserts:
                if tracked_sks is None:
                    tracked_sks = fetch_tracked_product_sks(conn=conn)
                to_load, dropped_new = filter_for_price_update_only(wave_rows, tracked_sks)

            if args.dry_run:
                print(
                    f"WAVE_COPY (DRY-RUN) | wave={wave_name} | mode={wave_dec.mode} "
                    f"| would_copy={len(to_load):,} | skipped_new={dropped_new:,}"
                )
                continue

            if to_load:
                t_cp = time.perf_counter()
                n_copied = bulk_copy_snapshots_to_neon(to_load, conn=conn)
                total_copied += n_copied
                print(
                    f"WAVE_COPY | wave={wave_name} | mode={wave_dec.mode} "
                    f"| copied={n_copied:,} | skipped_new={dropped_new:,} | {time.perf_counter() - t_cp:.2f}s"
                )
    finally:
        conn.close()

    if args.dry_run:
        print("Dry-run complete; skipped dbt, matching, and raw truncation.")
        return 0

    # Step 3: Run incremental dbt -> gold --match-db -> mart_cross_store_matches -> dbt test
    dbt_runner = REPO_ROOT / "data_platform" / "run_dbt.py"
    scrapers_runner = REPO_ROOT / "data_platform" / "ingestion" / "scrapers" / "run_scrapers.py"

    for cmd in (
        [sys.executable, str(dbt_runner), "run"],
        [sys.executable, str(scrapers_runner), "--match-db"],
        [sys.executable, str(dbt_runner), "run", "--select", "mart_cross_store_matches"],
        [sys.executable, str(dbt_runner), "test"],
    ):
        rc = subprocess.call(cmd)
        if rc != 0:
            print(f"PIPELINE_ABORTED | step={' '.join(cmd)} exited with code {rc}; raw preserved for debugging.")
            return rc

    # Step 4: Zero-rest raw staging cleanup ONLY AFTER dbt run & dbt test succeed
    cleared = truncate_raw_snapshots_after_dbt(dry_run=False)
    snap_after = inspect_neon_storage()
    print(
        f"ZERO_REST_RAW | truncated={cleared:,} rows from raw.raw_product_snapshots "
        f"| total_copied={total_copied:,} | final_db={snap_after.db_size_mb:.2f} MB"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Offline Tiered Catalog Expansion & Ultra-Low-Compute Neon Loader.")
    sub = p.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Emit deterministic Priority 1 -> 2 -> 3 shard plan (zero DB).")
    p_plan.add_argument("--day-of-year", type=int, default=0)
    p_plan.add_argument("--tier2-cadence", type=int, default=3)
    p_plan.add_argument("--tier3-cadence", type=int, default=5)
    p_plan.add_argument("--all-tiers", action="store_true")
    p_plan.add_argument("--include-local", action="store_true")
    p_plan.add_argument("--filter", type=str, default="all")
    p_plan.add_argument("--github-output", type=str, default="")

    p_scrape = sub.add_parser("scrape-shard", help="Scrape assigned stores offline to .jsonl.gz (zero DB).")
    p_scrape.add_argument("--shard", required=True)
    p_scrape.add_argument("--priority", default="p1_major_brands")
    p_scrape.add_argument("--stores", required=True, help="Comma-separated store keys.")
    p_scrape.add_argument("--mode", choices=["daily", "discover", "discovery", "expand"], default="daily")
    p_scrape.add_argument("--limit", type=int, default=None)
    p_scrape.add_argument("--delay", type=float, default=1.0)
    p_scrape.add_argument("--workers", type=int, default=4)
    p_scrape.add_argument("--out", required=True)

    p_load = sub.add_parser("load-and-transform", help="Single Neon session: circuit-breaker -> COPY -> dbt -> match -> TRUNCATE raw.")
    p_load.add_argument("--artifacts-dir", required=True)
    p_load.add_argument("--warn-mb", type=float, default=EXPANSION_CEILING_MB)
    p_load.add_argument("--stop-mb", type=float, default=HARD_STOP_CEILING_MB)
    p_load.add_argument("--dry-run", action="store_true")
    p_load.add_argument("--force-dbt", action="store_true")
    p_load.add_argument("--soft-exit-on-stop", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    if args.command == "plan":
        return _cmd_plan(args)
    if args.command == "scrape-shard":
        return _cmd_scrape_shard(args)
    if args.command == "load-and-transform":
        return _cmd_load_and_transform(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
