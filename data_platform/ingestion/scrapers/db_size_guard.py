"""CLI helper for Neon DB storage guardrails & registry batch/store inspection.

Used by `run_all_batches.ps1` to:
  - Query exact Neon database size in MB (`--check-size --max-mb 380`)
  - List active enabled batches from `stores_registry.yaml` (`--list-batches`)
  - Resolve store verticals from `stores_registry.yaml` (`--resolve-store <slug>`)
  - Print live store/product summary counts (`--summary`)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_platform.ingestion.scrapers.registry_loader import (  # noqa: E402
    list_active_batches,
    load_stores_registry,
)


def _get_db_url() -> str:
    load_dotenv(_REPO_ROOT / ".env")
    url = os.getenv("DATABASE_URL_READONLY") or os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_ADMIN")
    if not url:
        raise RuntimeError("No DATABASE_URL* found in .env or environment.")
    return url


def get_neon_db_size_mb() -> float:
    conn = psycopg2.connect(_get_db_url())
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())::BIGINT;")
            size_bytes = int(cur.fetchone()[0])
    finally:
        conn.close()
    return round(size_bytes / (1024.0 * 1024.0), 2)


def get_catalog_summary() -> dict[str, object]:
    conn = psycopg2.connect(_get_db_url())
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())::BIGINT;")
            size_mb = round(int(cur.fetchone()[0]) / (1024.0 * 1024.0), 2)
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT store_name) FROM gold.mart_product_verdicts;")
            gold_products, gold_stores = cur.fetchone()
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT store_name) FROM raw.raw_product_snapshots;")
            raw_rows, raw_stores = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM gold.mart_cross_store_matches;")
            matches = cur.fetchone()[0]
    finally:
        conn.close()
    return {
        "db_size_mb": size_mb,
        "gold_products": int(gold_products),
        "gold_stores": int(gold_stores),
        "raw_rows": int(raw_rows),
        "raw_stores": int(raw_stores),
        "cross_store_matches": int(matches),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Neon DB storage guardrail & registry helper.")
    parser.add_argument("--check-size", action="store_true", help="Print DB size in MB; exit 42 if >= --max-mb.")
    parser.add_argument("--max-mb", type=float, default=380.0, help="Hard stop threshold in MB (default: 380).")
    parser.add_argument("--list-batches", action="store_true", help="Print active enabled batches (one per line).")
    parser.add_argument("--include-local", action="store_true", help="Include local_only batches in --list-batches.")
    parser.add_argument("--resolve-store", type=str, default=None, help="Print vertical for a store_key.")
    parser.add_argument("--summary", action="store_true", help="Print JSON catalog + DB size summary.")
    args = parser.parse_args(argv)

    if args.check_size:
        size_mb = get_neon_db_size_mb()
        print(f"{size_mb:.2f}")
        if size_mb >= args.max_mb:
            print(
                f"NEON_GUARDRAIL_TRIGGERED: {size_mb:.2f} MB >= {args.max_mb:.2f} MB hard cap (512 MB limit).",
                file=sys.stderr,
            )
            return 42
        return 0

    if args.list_batches:
        region = None if args.include_local else "cloud"
        for batch in list_active_batches(region_mode=region):
            print(batch)
        return 0

    if args.resolve_store:
        key = args.resolve_store.strip().lower()
        for entry in load_stores_registry(enabled_only=False):
            if entry.store_key == key:
                print(entry.vertical)
                return 0
        print("core")
        return 0

    if args.summary:
        print(json.dumps(get_catalog_summary(), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
