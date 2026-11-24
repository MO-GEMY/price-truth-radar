"""
Zero-DB single-store scraper worker for the autonomous overnight 1M fill runner.

Runs ONE store in `--mode expand` with ZERO Neon database connections
(callers unset DATABASE_URL_ADMIN / DATABASE_URL_READONLY in subprocess env),
writing validated `RawProductSnapshot` records as JSONL to disk plus a small
checkpoint metadata sidecar JSON file so the orchestrator can bulk-flush an
entire category tier in one short Neon connection.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scrape a single store offline to JSONL with zero DB access.")
    p.add_argument("--store", required=True)
    p.add_argument("--vertical", default="core", choices=["core", "fashion", "groceries"])
    p.add_argument("--limit", type=int, default=2500)
    p.add_argument("--max-pages", type=int, default=30)
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--start-page", type=int, default=0)
    p.add_argument("--start-cursor", default="")
    p.add_argument("--out-jsonl", required=True)
    p.add_argument("--out-meta", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Guarantee zero DB calls from any scraper helper during HTTP scraping
    os.environ["DATABASE_URL_ADMIN"] = ""
    os.environ["DATABASE_URL_READONLY"] = ""

    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from data_platform.ingestion.scrapers import PoliteHttpClient, SCRAPER_REGISTRY, ThrottledResponseError

    started = time.monotonic()
    out_jsonl = Path(args.out_jsonl)
    out_meta = Path(args.out_meta)
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_meta.parent.mkdir(parents=True, exist_ok=True)

    scraper_cls = SCRAPER_REGISTRY.get(args.store)
    if scraper_cls is None:
        meta = {
            "store_id": args.store,
            "status": "FAILED",
            "scraped": 0,
            "pages_fetched": 0,
            "next_page": args.start_page,
            "next_cursor": args.start_cursor or None,
            "exhausted_catalog": False,
            "checkpoint_updated": False,
            "elapsed_s": round(time.monotonic() - started, 1),
            "note": "unknown store",
        }
        out_meta.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return 2

    supported = getattr(scraper_cls, "supported_verticals", ("core",))
    vertical = args.vertical if args.vertical in supported else supported[0]
    start_cursor = args.start_cursor if args.start_cursor else None

    status = "OK"
    note = ""
    records = []
    pages_fetched = 0
    next_page = args.start_page
    next_cursor = start_cursor
    exhausted = False
    checkpoint_updated = False

    try:
        with PoliteHttpClient(min_delay_seconds=args.delay) as http_client:
            scraper = scraper_cls(
                http_client,
                mode="expand",
                vertical=vertical,
                tracked_external_ids=set(),
                start_page=args.start_page,
                start_cursor=start_cursor,
                expand_max_pages=args.max_pages,
            )
            records = scraper.scrape(limit=args.limit)
            pages_fetched = scraper.pages_fetched
            if scraper._checkpoint_updated:
                checkpoint_updated = True
                next_page = scraper.next_page
                next_cursor = scraper.next_cursor
                exhausted = scraper.exhausted_catalog
            elif pages_fetched > 0:
                checkpoint_updated = True
                exhausted = len(records) == 0
                next_page = 0 if exhausted else (args.start_page + pages_fetched)
                next_cursor = None
    except ThrottledResponseError as exc:
        status = "THROTTLED"
        note = str(exc)[:140]
    except Exception as exc:
        low = str(exc).lower()
        status = "THROTTLED" if ("429" in low or "403" in low or "throttle" in low) else "FAILED"
        note = f"{type(exc).__name__}: {str(exc)[:120]}"

    # Write staged JSONL atomically
    written = 0
    if records:
        tmp_path = out_jsonl.with_suffix(".jsonl.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec.to_json_dict(), ensure_ascii=False) + "\n")
                written += 1
        tmp_path.replace(out_jsonl)

    if status == "OK":
        if exhausted:
            status = "WRAPPED"
        elif written == 0:
            status = "FAILED"
            note = note or "0 valid records"

    meta = {
        "store_id": args.store,
        "status": status,
        "scraped": written,
        "pages_fetched": pages_fetched,
        "next_page": next_page,
        "next_cursor": next_cursor,
        "exhausted_catalog": exhausted,
        "checkpoint_updated": checkpoint_updated,
        "elapsed_s": round(time.monotonic() - started, 1),
        "note": note,
    }
    out_meta.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return 0 if status in ("OK", "WRAPPED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
