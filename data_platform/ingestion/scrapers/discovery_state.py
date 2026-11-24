"""
Checkpointed catalog-expansion state management (`raw.scraper_discovery_state`).

Provides an idempotent DDL initializer plus safe load/save helpers so
`run_scrapers.py --mode expand` can resume each store across daily runs
from its saved `(last_page, last_cursor)` without re-fetching page 1.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import psycopg2

logger = logging.getLogger(__name__)

DISCOVERY_STATE_DDL_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.scraper_discovery_state (
    store_id                  VARCHAR(120) PRIMARY KEY,
    last_cursor               TEXT,
    last_page                 INTEGER NOT NULL DEFAULT 0,
    products_discovered_total INTEGER NOT NULL DEFAULT 0,
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

UPSERT_DISCOVERY_STATE_SQL = """
INSERT INTO raw.scraper_discovery_state (
    store_id,
    last_cursor,
    last_page,
    products_discovered_total,
    updated_at
) VALUES (%s, %s, %s, %s, NOW())
ON CONFLICT (store_id) DO UPDATE SET
    last_cursor               = EXCLUDED.last_cursor,
    last_page                 = EXCLUDED.last_page,
    products_discovered_total = raw.scraper_discovery_state.products_discovered_total
                                + EXCLUDED.products_discovered_total,
    updated_at                = NOW()
RETURNING store_id, last_cursor, last_page, products_discovered_total, updated_at;
"""


@dataclass
class DiscoveryCheckpoint:
    store_id: str
    last_cursor: Optional[str] = None
    last_page: int = 0
    products_discovered_total: int = 0
    updated_at: Optional[datetime] = None


def ensure_discovery_state_table(db_url: Optional[str] = None) -> bool:
    """Idempotently create `raw.scraper_discovery_state` in Neon."""
    url = db_url or os.getenv("DATABASE_URL_ADMIN")
    if not url:
        logger.warning("DATABASE_URL_ADMIN not set; skipping scraper_discovery_state DDL init.")
        return False

    conn = psycopg2.connect(url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DISCOVERY_STATE_DDL_SQL)
        return True
    finally:
        conn.close()


def load_discovery_state(
    store_id: str,
    *,
    db_url: Optional[str] = None,
) -> DiscoveryCheckpoint:
    """Load the saved expansion checkpoint for `store_id`, or return a fresh zeroed checkpoint."""
    url = db_url or os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL_READONLY")
    if not url:
        return DiscoveryCheckpoint(store_id=store_id)

    try:
        conn = psycopg2.connect(url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT store_id, last_cursor, last_page, products_discovered_total, updated_at
                    FROM raw.scraper_discovery_state
                    WHERE store_id = %s;
                    """,
                    (store_id,),
                )
                row = cur.fetchone()
                if not row:
                    return DiscoveryCheckpoint(store_id=store_id)
                return DiscoveryCheckpoint(
                    store_id=str(row[0]),
                    last_cursor=str(row[1]) if row[1] is not None else None,
                    last_page=max(0, int(row[2] or 0)),
                    products_discovered_total=max(0, int(row[3] or 0)),
                    updated_at=row[4],
                )
        finally:
            conn.close()
    except psycopg2.Error as exc:
        # Table may not exist yet on first dry-run; degrade gracefully to page 0
        logger.info(
            "[%s] Discovery state not yet initialized (%s); starting fresh from page 0.",
            store_id,
            getattr(exc, "pgcode", None) or type(exc).__name__,
        )
        return DiscoveryCheckpoint(store_id=store_id)
    except Exception as exc:
        logger.warning("[%s] Could not load discovery state (%s); starting from page 0.", store_id, exc)
        return DiscoveryCheckpoint(store_id=store_id)


def save_discovery_state(
    store_id: str,
    *,
    last_cursor: Optional[str],
    last_page: int,
    newly_discovered: int,
    db_url: Optional[str] = None,
) -> DiscoveryCheckpoint:
    """Idempotently ensure table exists and persist updated expansion checkpoint."""
    url = db_url or os.getenv("DATABASE_URL_ADMIN")
    if not url:
        raise RuntimeError("DATABASE_URL_ADMIN is not set; cannot save scraper_discovery_state.")

    safe_page = max(0, int(last_page or 0))
    safe_new = max(0, int(newly_discovered or 0))

    conn = psycopg2.connect(url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DISCOVERY_STATE_DDL_SQL)
                cur.execute(
                    UPSERT_DISCOVERY_STATE_SQL,
                    (store_id, last_cursor, safe_page, safe_new),
                )
                row: Any = cur.fetchone()
                if row:
                    return DiscoveryCheckpoint(
                        store_id=str(row[0]),
                        last_cursor=str(row[1]) if row[1] is not None else None,
                        last_page=int(row[2] or 0),
                        products_discovered_total=int(row[3] or 0),
                        updated_at=row[4],
                    )
        return DiscoveryCheckpoint(
            store_id=store_id,
            last_cursor=last_cursor,
            last_page=safe_page,
            products_discovered_total=safe_new,
        )
    finally:
        conn.close()
