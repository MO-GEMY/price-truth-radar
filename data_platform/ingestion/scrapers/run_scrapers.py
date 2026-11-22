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
import sys
from collections import Counter
from pathlib import Path

# Support direct script invocation without requiring PYTHONPATH=.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_platform.ingestion.scrapers import (  # noqa: E402
    MatchSummary,
    PoliteHttpClient,
    RawProductSnapshot,
    SCRAPER_REGISTRY,
    ScrapeMode,
    ScrapeVertical,
    assign_canonical_keys,
    fetch_latest_snapshots_from_neon,
    fetch_tracked_store_ids_from_neon,
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
        "--vertical",
        choices=["core", "groceries"],
        default="core",
        help="Product vertical: 'core' (electronics/home_appliances/fashion, default) or 'groceries' (Egyptian Supermarket Wave 1).",
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "discover"],
        default="daily",
        help="Scrape mode: 'daily' (balanced refresh prioritizing tracked SKUs) or 'discover' (deeper catalog sweep with higher limits).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum products to collect per store (defaults to each scraper's target for the selected --mode).",
    )
    parser.add_argument(
        "--match-db",
        action="store_true",
        help="Read latest snapshot_date rows across all stores from Neon, run cross-store matching, and update canonical_product_key.",
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
        f"| matched_products={summary.matched_products}"
    )
    print("=" * 72)
    if not summary.group_details:
        print("  No cross-store matches detected in this batch.")
        return

    for key, entries in summary.group_details.items():
        stores_str = ", ".join(f"{store}={price:,.0f} EGP" for store, price, _ in entries)
        prices = [price for _, price, _ in entries]
        spread = max(prices) - min(prices)
        spread_pct = (spread / min(prices) * 100.0) if min(prices) > 0 else 0.0
        print(f"  * {key} (spread {spread:,.0f} EGP / +{spread_pct:.1f}%): {stores_str}")


def _run_match_db(dry_run: bool) -> int:
    snap_date, records = fetch_latest_snapshots_from_neon()
    if not records or snap_date is None:
        print("No rows found in raw.raw_product_snapshots to match.")
        return 0

    stores_counter = Counter(r.store_name for r in records)
    print(
        f"Loaded {len(records)} rows for snapshot_date={snap_date.isoformat()} "
        f"across {len(stores_counter)} stores: {dict(sorted(stores_counter.items()))}"
    )
    match_summary = assign_canonical_keys(records)
    _print_match_summary(match_summary)

    if dry_run:
        print("\nDry-run complete (--match-db). Zero writes made to Neon.")
        return 0

    updated = update_canonical_keys_in_neon(records)
    print(f"\nUpdated canonical_product_key across {updated} rows for {snap_date.isoformat()} in Neon.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.store and not args.match_db:
        parser.error("Provide --store <slug|all> and/or --match-db")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.match_db and not args.store:
        return _run_match_db(dry_run=args.dry_run)

    vertical: ScrapeVertical = args.vertical
    if args.store == "all":
        stores = [
            slug
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
        stores = [args.store]

    all_records: list[RawProductSnapshot] = []
    per_store_meta: list[tuple[str, list[RawProductSnapshot], int, int, int, int, dict[str, int]]] = []
    scrape_mode: ScrapeMode = args.mode

    with PoliteHttpClient(min_delay_seconds=args.delay) as http_client:
        for store_slug in stores:
            scraper_cls = SCRAPER_REGISTRY[store_slug]
            tracked_ids = (
                fetch_tracked_store_ids_from_neon(
                    store_slug,
                    category="groceries" if vertical == "groceries" else None,
                )
                if scrape_mode == "daily"
                else set()
            )
            scraper = scraper_cls(
                http_client,
                mode=scrape_mode,
                vertical=vertical,
                tracked_external_ids=tracked_ids,
            )
            effective_limit = (
                scraper.get_target_limit(scrape_mode, vertical)
                if args.limit is None
                else args.limit
            )
            logging.info(
                "[%s] Starting scrape (vertical=%s, mode=%s, target_limit=%d, tracked_watchlist=%d)",
                store_slug,
                vertical,
                scrape_mode,
                effective_limit,
                len(tracked_ids),
            )
            records = scraper.scrape(limit=effective_limit)
            tracked_hits = sum(1 for r in records if r.external_id in tracked_ids) if tracked_ids else 0
            all_records.extend(records)
            per_store_meta.append(
                (
                    store_slug,
                    records,
                    scraper.pages_fetched,
                    scraper.skipped_count,
                    tracked_hits,
                    len(tracked_ids),
                    dict(scraper.category_counts),
                )
            )

    match_summary = assign_canonical_keys(all_records)

    for (
        store_slug,
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
            vertical=vertical,
            tracked_hits=tracked_hits,
            tracked_total=tracked_total,
            category_counts=category_counts or None,
        )

    if len(stores) > 1 or match_summary.matched_groups > 0:
        _print_match_summary(match_summary)

    if len(stores) == 1 and len(all_records) == 0:
        logging.error(
            "[%s] Collected 0 valid records (mode=%s); failing run so silent blocks are surfaced.",
            stores[0],
            scrape_mode,
        )
        return 2

    if args.dry_run:
        if args.match_db:
            return _run_match_db(dry_run=True)
        print("\nDry-run complete. Zero writes made to Neon.")
        return 0

    upserted = upsert_snapshots_to_neon(all_records)
    print(f"\nUpserted {upserted} live rows into raw.raw_product_snapshots (existing rows preserved).")

    if args.match_db:
        return _run_match_db(dry_run=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
