"""
CLI entry point for running Price Truth Radar store scrapers & DB cross-store matching.

Examples:
    python data_platform/ingestion/scrapers/run_scrapers.py --store sigma --limit 30 --dry-run
    python data_platform/ingestion/scrapers/run_scrapers.py --store town_team --limit 30 --dry-run
    python data_platform/ingestion/scrapers/run_scrapers.py --store all --limit 100
    python data_platform/ingestion/scrapers/run_scrapers.py --match-db
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Support direct script invocation without requiring PYTHONPATH=.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_platform.ingestion.scrapers import (  # noqa: E402
    DeltaStats,
    DiscoveryCheckpoint,
    MatchSummary,
    PoliteHttpClient,
    RawProductSnapshot,
    SCRAPER_REGISTRY,
    ScrapeMode,
    ScrapeVertical,
    assign_canonical_keys,
    fetch_latest_snapshots_from_neon,
    fetch_tracked_store_ids_from_neon,
    get_batch_targets,
    load_discovery_state,
    preview_delta_savings,
    prune_old_raw_snapshots,
    save_discovery_state,
    update_canonical_keys_in_neon,
    upsert_snapshots_to_neon,
)


def _build_parser() -> argparse.ArgumentParser:
    store_choices = sorted(SCRAPER_REGISTRY.keys()) + ["all"]
    parser = argparse.ArgumentParser(
        description="Run live Egyptian store scrapers & cross-store matching for Price Truth Radar.",
    )
    parser.add_argument(
        "--store",
        required=False,
        choices=store_choices,
        help="Store slug to scrape (or 'all' for every registered scraper supporting the vertical).",
    )
    parser.add_argument(
        "--batch",
        required=False,
        default=None,
        help="Registry batch name from stores_registry.yaml (e.g. 'core_1', 'groceries_1', 'fashion_1').",
    )
    parser.add_argument(
        "--vertical",
        choices=["core", "groceries", "fashion"],
        default="core",
        help="Product vertical: 'core' (electronics/home_appliances, default), 'groceries', or 'fashion'.",
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "discover", "discovery", "expand"],
        default="daily",
        help=(
            "Scrape mode: 'daily' (balanced refresh prioritizing tracked SKUs), "
            "'discover'/'discovery' (deeper catalog sweep), or "
            "'expand' (checkpointed pagination resuming from scraper_discovery_state)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum products to collect per store (defaults to each scraper's target for the selected --mode).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional per-store page budget override for `--mode expand` (defaults to each adapter's expand_max_pages).",
    )
    parser.add_argument(
        "--match-db",
        action="store_true",
        help="Read latest snapshot_date rows across all stores from Neon, run cross-store matching, and update canonical_product_key.",
    )
    parser.add_argument(
        "--prune-raw",
        action="store_true",
        help=(
            "Post-dbt storage guardrail: delete raw.raw_product_snapshots older than --retention-days "
            "and run VACUUM (ANALYZE). Invoke ONLY after dbt run and dbt test succeed."
        ),
    )
    parser.add_argument(
        "--run-dbt-and-prune",
        action="store_true",
        help=(
            "Execute dbt run + dbt test and, ONLY if both succeed, prune raw.raw_product_snapshots "
            "older than --retention-days followed by VACUUM (ANALYZE)."
        ),
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=3,
        help="Rolling retention window in days for raw.raw_product_snapshots cleanup (default: 3).",
    )
    parser.add_argument(
        "--delta",
        dest="delta",
        action="store_true",
        default=True,
        help="Enable Delta Snapshots (skip inserting unchanged rows, only touch last_seen_at; default: enabled).",
    )
    parser.add_argument(
        "--no-delta",
        dest="delta",
        action="store_false",
        help="Disable Delta Snapshots and upsert every scraped row unconditionally.",
    )
    parser.add_argument(
        "--delta-preview",
        action="store_true",
        help="During --dry-run, query Neon read-only to report exact Delta Snapshot row-reduction savings.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch/match and print summary + sample JSON records without writing to Neon.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Minimum polite delay in seconds between HTTP requests (default: 1.0; stores may enforce higher).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    return parser


def _print_summary(
    store: str,
    records: list[RawProductSnapshot],
    *,
    pages_fetched: int,
    skipped_count: int,
    dry_run: bool,
    scrape_mode: ScrapeMode = "daily",
    vertical: ScrapeVertical = "core",
    tracked_hits: int = 0,
    tracked_total: int = 0,
    category_counts: dict[str, int] | None = None,
) -> None:
    total = len(records)
    in_stock = sum(1 for r in records if r.in_stock)
    out_of_stock = total - in_stock
    discounted = sum(1 for r in records if r.claimed_original_price is not None)
    with_images = sum(1 for r in records if r.image_url is not None)
    cats = Counter(r.category for r in records)
    subcats = Counter(r.sub_category for r in records)
    prices = [r.current_price for r in records]

    print("=" * 72)
    print(
        f"SCRAPER SUMMARY | store={store} | vertical={vertical} | scrape_mode={scrape_mode} "
        f"| io={'DRY-RUN (no DB write)' if dry_run else 'LIVE UPSERT'}"
    )
    print("=" * 72)
    print(f"  Pages fetched        : {pages_fetched}")
    print(f"  Valid records        : {total}")
    print(f"  Skipped invalid      : {skipped_count}")
    if tracked_total > 0:
        print(f"  Watchlist refreshed  : {tracked_hits}/{tracked_total} tracked SKUs")
    print(f"  In stock / OOS       : {in_stock} / {out_of_stock}")
    print(f"  With claimed discount: {discounted}")
    print(f"  With image URL       : {with_images}/{total}")
    if prices:
        print(f"  EGP price range      : {min(prices):,.2f} .. {max(prices):,.2f} EGP")
    if cats:
        print("  Categories           : " + ", ".join(f"{k}={v}" for k, v in cats.most_common()))
    if subcats:
        print("  Sub-categories       : " + ", ".join(f"{k}={v}" for k, v in subcats.most_common()))
    if category_counts:
        print("  Per-category grid    : " + ", ".join(f"{k}={v}" for k, v in category_counts.items()))

    print("\n--- SAMPLE VALIDATED RECORDS (3) ---")
    for idx, rec in enumerate(records[:3], start=1):
        print(f"\n[Sample {idx}]")
        print(json.dumps(rec.to_json_dict(), indent=2, ensure_ascii=False))


def _print_match_summary(summary: MatchSummary) -> None:
    print("\n" + "=" * 72)
    print(
        f"CROSS-STORE MATCHING | matched_groups={summary.matched_groups} "
        f"| matched_products={summary.matched_products} "
        f"| tiers=(T1:{summary.tier1_groups}, T2:{summary.tier2_groups}, "
        f"T3:{summary.tier3_groups}, Grocery:{summary.grocery_groups}, "
        f"HealthBeauty:{summary.health_beauty_groups}, Footwear:{summary.footwear_groups})"
    )
    print("=" * 72)
    if not summary.group_details:
        print("  No cross-store matches detected in this batch.")
        return

    for idx, (key, entries) in enumerate(summary.group_details.items()):
        if idx >= 40:
            print(f"  ... ({len(summary.group_details) - 40} more matched groups omitted)")
            break
        stores_str = ", ".join(f"{store}={price:,.0f} EGP" for store, price, _ in entries)
        prices = [price for _, price, _ in entries]
        spread = max(prices) - min(prices)
        spread_pct = (spread / min(prices) * 100.0) if min(prices) > 0 else 0.0
        print(f"  * {key} (spread {spread:,.0f} EGP / +{spread_pct:.1f}%): {stores_str}")


def _print_delta_preview(stats: DeltaStats) -> None:
    print("\n" + "=" * 72)
    print(
        f"DELTA SNAPSHOT PREVIEW | scraped={stats.total_scraped} "
        f"| would_insert={stats.inserted_or_changed} "
        f"| skipped_unchanged={stats.skipped_unchanged} "
        f"| storage_saved={stats.savings_pct:.1f}%"
    )
    print("=" * 72)


def _run_match_db(dry_run: bool) -> int:
    import random
    import time as _time
    from collections import defaultdict as _dd
    from data_platform.ingestion.scrapers.matcher_verticals import effective_category as _eff_cat

    t0 = _time.perf_counter()
    snap_date, records = fetch_latest_snapshots_from_neon(for_matching=True)
    t_load = _time.perf_counter() - t0
    if not records or snap_date is None:
        print("No rows found in raw.raw_product_snapshots to match.")
        return 0

    stores_counter = Counter(r.store_name for r in records)
    old_matched_skus = sum(1 for r in records if r.canonical_product_key)
    old_groups_map: dict[str, set[str]] = _dd(set)
    for r in records:
        if r.canonical_product_key:
            old_groups_map[r.canonical_product_key].add(r.store_name)
    old_multi_clusters = sum(1 for st in old_groups_map.values() if len(st) >= 2)

    print(
        f"Loaded {len(records):,} rows across {len(stores_counter)} stores in {t_load:.1f}s "
        f"(snapshot_date={snap_date.isoformat()})."
    )
    prev_keys = {
        (r.store_name, r.external_id, r.snapshot_date): r.canonical_product_key
        for r in records
    }
    t1 = _time.perf_counter()
    match_summary = assign_canonical_keys(records)
    t_match = _time.perf_counter() - t1

    _print_match_summary(match_summary)
    print(
        f"\nENTITY RESOLUTION SUMMARY ({t_match:.1f}s local RAM):"
        f"\n  * Old matched SKUs: {old_matched_skus:,} ({old_multi_clusters:,} multi-store clusters)"
        f"\n  * New matched SKUs: {match_summary.matched_products:,} ({match_summary.matched_groups:,} multi-store clusters)"
        f"\n  * Pass breakdown:   Pass1(ID)={match_summary.tier1_groups:,} | Pass2(Det+ModelCode)={match_summary.tier2_groups:,} | Pass3(TF-IDF)={match_summary.tier3_groups:,}"
        f"\n  * Brands recovered: {match_summary.brands_inferred:,} titles"
    )
    if match_summary.category_group_counts:
        cat_line = ", ".join(
            f"{cat}={cnt:,}"
            for cat, cnt in sorted(match_summary.category_group_counts.items(), key=lambda kv: -kv[1])
        )
        print(f"  * Clusters by cat:  {cat_line}")

    changed_records = [
        r for r in records
        if prev_keys.get((r.store_name, r.external_id, r.snapshot_date)) != r.canonical_product_key
    ]

    if dry_run:
        # Print 25 random NEWLY matched cross-store pairs stratified across categories for precision audit
        new_clusters: dict[str, list[RawProductSnapshot]] = _dd(list)
        for r in records:
            if r.canonical_product_key:
                new_clusters[r.canonical_product_key].append(r)

        newly_matched_by_cat: dict[str, list[tuple[str, RawProductSnapshot, RawProductSnapshot]]] = _dd(list)
        for k, members in new_clusters.items():
            # Identify clusters containing at least one newly linked cross-store pair
            by_store: dict[str, RawProductSnapshot] = {}
            for m in sorted(members, key=lambda x: float(x.current_price)):
                by_store.setdefault(m.store_name, m)
            if len(by_store) < 2:
                continue
            store_list = list(by_store.values())
            a, b = store_list[0], store_list[1]
            pk_a = prev_keys.get((a.store_name, a.external_id, a.snapshot_date))
            pk_b = prev_keys.get((b.store_name, b.external_id, b.snapshot_date))
            if pk_a and pk_a == pk_b:
                continue  # Already matched previously
            cat = _eff_cat(a)
            newly_matched_by_cat[cat].append((k, a, b))

        rng = random.Random(42)
        audit_cats = ["electronics", "home_appliances", "beauty", "health", "fashion", "sports", "groceries", "home_furniture", "baby_kids", "pet_care"]
        sampled: list[tuple[str, str, RawProductSnapshot, RawProductSnapshot]] = []
        # Round-robin pick across categories up to 25 pairs
        for cat in audit_cats:
            rng.shuffle(newly_matched_by_cat[cat])
        idx_per_cat = {c: 0 for c in audit_cats}
        while len(sampled) < 25:
            added_any = False
            for cat in audit_cats:
                pool = newly_matched_by_cat.get(cat, [])
                pos = idx_per_cat[cat]
                if pos < len(pool):
                    k, a, b = pool[pos]
                    sampled.append((cat, k, a, b))
                    idx_per_cat[cat] = pos + 1
                    added_any = True
                    if len(sampled) >= 25:
                        break
            if not added_any:
                break

        print("\n" + "=" * 72)
        print(f"PRECISION AUDIT — {len(sampled)} RANDOM NEWLY MATCHED CROSS-STORE PAIRS")
        print("=" * 72)
        for i, (cat, k, a, b) in enumerate(sampled, 1):
            ratio = max(float(a.current_price), float(b.current_price)) / max(0.01, min(float(a.current_price), float(b.current_price)))
            print(
                f"[{i:02d}] ({cat}) key={k} (ratio={ratio:.2f}x)\n"
                f"     A: [{a.store_name}] {float(a.current_price):,.0f} EGP | {a.product_title}\n"
                f"     B: [{b.store_name}] {float(b.current_price):,.0f} EGP | {b.product_title}"
            )

        print(
            f"\nDry-run complete (--match-db). Zero writes made to Neon "
            f"({len(changed_records):,}/{len(records):,} rows would change)."
        )
        return 0

    updated = update_canonical_keys_in_neon(changed_records)
    print(
        f"\nUpdated canonical_product_key across {updated:,} changed rows "
        f"(out of {len(records):,} latest snapshots) for {snap_date.isoformat()} in Neon."
    )
    return 0


def run_post_dbt_raw_retention_cleanup(
    retention_days: int = 3,
    *,
    run_dbt_first: bool = False,
    dry_run: bool = False,
) -> int:
    """Prune `raw.raw_product_snapshots` older than `retention_days` and VACUUM (ANALYZE).

    When `run_dbt_first=True`, runs `dbt run` then `dbt test` first and aborts
    without pruning if either step exits non-zero.
    """
    if run_dbt_first:
        dbt_runner = _REPO_ROOT / "data_platform" / "run_dbt.py"
        for subcmd in ("run", "test"):
            rc = subprocess.call([sys.executable, str(dbt_runner), subcmd])
            if rc != 0:
                logging.error(
                    "Post-dbt cleanup aborted: `dbt %s` failed with exit code %d; raw snapshots preserved.",
                    subcmd,
                    rc,
                )
                return rc

    deleted = prune_old_raw_snapshots(
        retention_days=retention_days,
        vacuum=not dry_run,
        dry_run=dry_run,
    )
    if dry_run:
        print(
            f"RAW_RETENTION (DRY-RUN) | retention_days={retention_days} "
            f"| would_delete={deleted:,} rows from raw.raw_product_snapshots"
        )
    else:
        print(
            f"RAW_RETENTION | retention_days={retention_days} "
            f"| deleted={deleted:,} rows from raw.raw_product_snapshots | vacuum_analyze=OK"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = _build_parser()
    args = parser.parse_args(argv)

    if (
        not args.store
        and not args.batch
        and not args.match_db
        and not args.prune_raw
        and not args.run_dbt_and_prune
    ):
        parser.error(
            "Provide --store <slug|all>, --batch <name>, --match-db, --prune-raw, and/or --run-dbt-and-prune"
        )
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")
    if args.max_pages is not None and args.max_pages <= 0:
        parser.error("--max-pages must be a positive integer")
    if args.retention_days <= 0:
        parser.error("--retention-days must be a positive integer")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.store and not args.batch:
        if args.match_db:
            rc = _run_match_db(dry_run=args.dry_run)
            if rc != 0:
                return rc
        if args.run_dbt_and_prune:
            return run_post_dbt_raw_retention_cleanup(
                retention_days=args.retention_days,
                run_dbt_first=True,
                dry_run=args.dry_run,
            )
        if args.prune_raw:
            return run_post_dbt_raw_retention_cleanup(
                retention_days=args.retention_days,
                run_dbt_first=False,
                dry_run=args.dry_run,
            )
        return 0

    run_targets: list[tuple[str, ScrapeVertical]] = []
    if args.batch:
        region_filter = None if args.batch.startswith("local_") else "cloud"
        batch_targets = get_batch_targets(args.batch, region_mode=region_filter, enabled_only=True)
        for slug, vert in batch_targets:
            if slug in SCRAPER_REGISTRY and vert in SCRAPER_REGISTRY[slug].supported_verticals:
                run_targets.append((slug, vert))
        if not run_targets:
            # Distinguish a valid batch with 0 enabled entries (skip cleanly) from an unknown batch typo.
            any_in_batch = get_batch_targets(args.batch, region_mode=None, enabled_only=False)
            if any_in_batch:
                logging.warning(
                    "Batch '%s' has 0 enabled stores (%d disabled/staged); skipping cleanly.",
                    args.batch,
                    len(any_in_batch),
                )
                print(
                    f"BATCH_SKIPPED | batch={args.batch} | reason=no_enabled_stores "
                    f"| staged_disabled={len(any_in_batch)}"
                )
                return 0
            parser.error(f"Batch '{args.batch}' does not exist in stores_registry.yaml.")
    else:
        vertical: ScrapeVertical = args.vertical
        if args.store == "all":
            run_targets = [
                (slug, vertical)
                for slug in sorted(SCRAPER_REGISTRY.keys())
                if vertical in SCRAPER_REGISTRY[slug].supported_verticals
            ]
        else:
            if vertical not in SCRAPER_REGISTRY[args.store].supported_verticals:
                supported = [
                    s
                    for s in sorted(SCRAPER_REGISTRY.keys())
                    if vertical in SCRAPER_REGISTRY[s].supported_verticals
                ]
                parser.error(
                    f"Store '{args.store}' does not support --vertical {vertical}. "
                    f"Supported stores: {', '.join(supported)}"
                )
            run_targets = [(args.store, vertical)]

    all_records: list[RawProductSnapshot] = []
    per_store_meta: list[tuple[str, ScrapeVertical, list[RawProductSnapshot], int, int, int, int, dict[str, int]]] = []
    expand_updates: list[tuple[str, Optional[str], int, bool, int]] = []
    any_expand_exhausted = False
    scrape_mode: ScrapeMode = "discover" if args.mode == "discovery" else args.mode

    with PoliteHttpClient(min_delay_seconds=args.delay) as http_client:
        for store_slug, target_vertical in run_targets:
            scraper_cls = SCRAPER_REGISTRY[store_slug]
            tracked_ids = (
                fetch_tracked_store_ids_from_neon(
                    store_slug,
                    category=target_vertical if target_vertical in ("groceries", "fashion") else None,
                )
                if scrape_mode == "daily"
                else set()
            )
            checkpoint: Optional[DiscoveryCheckpoint] = (
                load_discovery_state(store_slug) if scrape_mode == "expand" else None
            )
            scraper = scraper_cls(
                http_client,
                mode=scrape_mode,
                vertical=target_vertical,
                tracked_external_ids=tracked_ids,
                start_page=checkpoint.last_page if checkpoint else 0,
                start_cursor=checkpoint.last_cursor if checkpoint else None,
                expand_max_pages=args.max_pages,
            )
            effective_limit = (
                scraper.get_target_limit(scrape_mode, target_vertical)
                if args.limit is None
                else args.limit
            )
            if checkpoint is not None:
                logging.info(
                    "[%s] Starting expand scrape (vertical=%s, target_limit=%d, resume_page=%d, resume_cursor=%r, discovered_total=%d)",
                    store_slug,
                    target_vertical,
                    effective_limit,
                    checkpoint.last_page,
                    checkpoint.last_cursor,
                    checkpoint.products_discovered_total,
                )
            else:
                logging.info(
                    "[%s] Starting scrape (vertical=%s, mode=%s, target_limit=%d, tracked_watchlist=%d)",
                    store_slug,
                    target_vertical,
                    scrape_mode,
                    effective_limit,
                    len(tracked_ids),
                )
            try:
                records = scraper.scrape(limit=effective_limit)
            except Exception as exc:
                logging.error("[%s] Scraper failed (%s); continuing batch.", store_slug, exc)
                records = []
            tracked_hits = sum(1 for r in records if r.external_id in tracked_ids) if tracked_ids else 0
            all_records.extend(records)
            per_store_meta.append(
                (
                    store_slug,
                    target_vertical,
                    records,
                    scraper.pages_fetched,
                    scraper.skipped_count,
                    tracked_hits,
                    len(tracked_ids),
                    dict(scraper.category_counts),
                )
            )
            if scrape_mode == "expand":
                if scraper._checkpoint_updated:
                    if scraper.exhausted_catalog:
                        any_expand_exhausted = True
                    expand_updates.append(
                        (
                            store_slug,
                            scraper.next_cursor,
                            scraper.next_page,
                            scraper.exhausted_catalog,
                            len(records),
                        )
                    )
                elif scraper.pages_fetched > 0:
                    # Fallback advancement for custom scrapers without native cursor support
                    wrapped = len(records) == 0
                    if wrapped:
                        any_expand_exhausted = True
                    next_p = 0 if wrapped else (scraper.start_page + scraper.pages_fetched)
                    expand_updates.append((store_slug, None, next_p, wrapped, len(records)))

    match_summary = assign_canonical_keys(all_records)

    for (
        store_slug,
        target_vertical,
        records,
        pages_fetched,
        skipped_count,
        tracked_hits,
        tracked_total,
        category_counts,
    ) in per_store_meta:
        _print_summary(
            store_slug,
            records,
            pages_fetched=pages_fetched,
            skipped_count=skipped_count,
            dry_run=args.dry_run,
            scrape_mode=scrape_mode,
            vertical=target_vertical,
            tracked_hits=tracked_hits,
            tracked_total=tracked_total,
            category_counts=category_counts or None,
        )

    if len(run_targets) > 1 or match_summary.matched_groups > 0:
        _print_match_summary(match_summary)

    if len(run_targets) == 1 and len(all_records) == 0 and not (scrape_mode == "expand" and any_expand_exhausted):
        logging.error(
            "[%s] Collected 0 valid records (mode=%s); failing run so silent blocks are surfaced.",
            run_targets[0][0],
            scrape_mode,
        )
        return 2

    if args.dry_run:
        if args.delta_preview or args.delta:
            preview = preview_delta_savings(all_records)
            if preview is not None:
                _print_delta_preview(preview)
        if scrape_mode == "expand" and expand_updates:
            for store_slug, next_cur, next_p, wrapped, scraped_cnt in expand_updates:
                print(
                    f"EXPAND_CHECKPOINT (DRY-RUN) | store={store_slug} "
                    f"| next_page={next_p} | next_cursor={next_cur!r} "
                    f"| scraped={scraped_cnt} | wrapped={wrapped}"
                )
        if args.match_db:
            return _run_match_db(dry_run=True)
        print("\nDry-run complete. Zero writes made to Neon.")
        return 0

    new_counts_by_store: dict[str, int] = {}
    upserted = (
        upsert_snapshots_to_neon(
            all_records,
            delta_mode=args.delta,
            new_counts_by_store=new_counts_by_store,
        )
        if all_records
        else 0
    )
    mode_tag = "delta" if args.delta else "full"
    print(
        f"\nUpserted {upserted} live rows into raw.raw_product_snapshots "
        f"(mode={mode_tag}, total_scraped={len(all_records)}, existing rows preserved)."
    )

    if scrape_mode == "expand" and expand_updates:
        for store_slug, next_cur, next_p, wrapped, scraped_cnt in expand_updates:
            newly_discovered = new_counts_by_store.get(store_slug, 0) if args.delta else scraped_cnt
            try:
                saved = save_discovery_state(
                    store_slug,
                    last_cursor=next_cur,
                    last_page=next_p,
                    newly_discovered=newly_discovered,
                )
                print(
                    f"EXPAND_CHECKPOINT | store={saved.store_id} "
                    f"| next_page={saved.last_page} | next_cursor={saved.last_cursor!r} "
                    f"| newly_discovered={newly_discovered} "
                    f"| total_discovered={saved.products_discovered_total} | wrapped={wrapped}"
                )
            except Exception as exc:
                logging.warning("[%s] Failed to save scraper_discovery_state (%s).", store_slug, exc)

    if args.match_db:
        rc = _run_match_db(dry_run=False)
        if rc != 0:
            return rc
    if args.run_dbt_and_prune:
        return run_post_dbt_raw_retention_cleanup(
            retention_days=args.retention_days,
            run_dbt_first=True,
            dry_run=False,
        )
    if args.prune_raw:
        return run_post_dbt_raw_retention_cleanup(
            retention_days=args.retention_days,
            run_dbt_first=False,
            dry_run=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
