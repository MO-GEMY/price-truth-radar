"""
CLI entry point for running Price Truth Radar store scrapers.

Examples:
    python data_platform/ingestion/scrapers/run_scrapers.py --store sigma --limit 30 --dry-run
    python -m data_platform.ingestion.scrapers.run_scrapers --store sigma --limit 30 --dry-run
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
    PoliteHttpClient,
    RawProductSnapshot,
    SCRAPER_REGISTRY,
    upsert_snapshots_to_neon,
)


def _build_parser() -> argparse.ArgumentParser:
    store_choices = sorted(SCRAPER_REGISTRY.keys()) + ["all"]
    parser = argparse.ArgumentParser(
        description="Run live Egyptian store scrapers for Price Truth Radar.",
    )
    parser.add_argument(
        "--store",
        required=True,
        choices=store_choices,
        help="Store slug to scrape (or 'all' for every registered scraper).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum number of products to collect per store (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, validate, and print summary + 3 sample JSON records without writing to Neon.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Minimum polite delay in seconds between HTTP requests (default: 1.0).",
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
    if subcats:
        breakdown = ", ".join(f"{k}={v}" for k, v in subcats.most_common())
        print(f"  Sub-categories       : {breakdown}")

    print("\n--- SAMPLE VALIDATED RECORDS (3) ---")
    for idx, rec in enumerate(records[:3], start=1):
        print(f"\n[Sample {idx}]")
        print(json.dumps(rec.to_json_dict(), indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.limit <= 0:
        parser.error("--limit must be a positive integer")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stores = sorted(SCRAPER_REGISTRY.keys()) if args.store == "all" else [args.store]
    all_records: list[RawProductSnapshot] = []

    with PoliteHttpClient(min_delay_seconds=args.delay) as http_client:
        for store_slug in stores:
            scraper_cls = SCRAPER_REGISTRY[store_slug]
            scraper = scraper_cls(http_client)
            records = scraper.scrape(limit=args.limit)
            all_records.extend(records)
            _print_summary(
                store_slug,
                records,
                pages_fetched=scraper.pages_fetched,
                skipped_count=scraper.skipped_count,
                dry_run=args.dry_run,
            )

    if args.dry_run:
        print("\nDry-run complete. Zero writes made to Neon.")
        return 0

    upserted = upsert_snapshots_to_neon(all_records)
    print(f"\nUpserted {upserted} live rows into raw.raw_product_snapshots (existing rows preserved).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
