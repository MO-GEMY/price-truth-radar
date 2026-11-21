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
    assign_canonical_keys,
    fetch_latest_snapshots_from_neon,
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
        help="Store slug to scrape (or 'all' for every registered scraper).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum products to collect per store (defaults to each scraper's scaled target).",
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
    print(f"SCRAPER SUMMARY | store={store} | mode={'DRY-RUN (no DB write)' if dry_run else 'LIVE UPSERT'}")
    print("=" * 72)
    print(f"  Pages fetched        : {pages_fetched}")
    print(f"  Valid records        : {total}")
    print(f"  Skipped invalid      : {skipped_count}")
    print(f"  In stock / OOS       : {in_stock} / {out_of_stock}")
    print(f"  With claimed discount: {discounted}")
    print(f"  With image URL       : {with_images}/{total}")
    if prices:
        print(f"  EGP price range      : {min(prices):,.2f} .. {max(prices):,.2f} EGP")
    if cats:
        print("  Categories           : " + ", ".join(f"{k}={v}" for k, v in cats.most_common()))
    if subcats:
        print("  Sub-categories       : " + ", ".join(f"{k}={v}" for k, v in subcats.most_common()))

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

    stores = sorted(SCRAPER_REGISTRY.keys()) if args.store == "all" else [args.store]
    all_records: list[RawProductSnapshot] = []
    per_store_meta: list[tuple[str, list[RawProductSnapshot], int, int]] = []

    with PoliteHttpClient(min_delay_seconds=args.delay) as http_client:
        for store_slug in stores:
            scraper_cls = SCRAPER_REGISTRY[store_slug]
            scraper = scraper_cls(http_client)
            effective_limit = scraper.default_limit if args.limit is None else args.limit
            records = scraper.scrape(limit=effective_limit)
            all_records.extend(records)
            per_store_meta.append(
                (store_slug, records, scraper.pages_fetched, scraper.skipped_count)
            )

    match_summary = assign_canonical_keys(all_records)

    for store_slug, records, pages_fetched, skipped_count in per_store_meta:
        _print_summary(
            store_slug,
            records,
            pages_fetched=pages_fetched,
            skipped_count=skipped_count,
            dry_run=args.dry_run,
        )

    if len(stores) > 1 or match_summary.matched_groups > 0:
        _print_match_summary(match_summary)

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
