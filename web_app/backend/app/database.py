"""Database engines for Price Truth Radar FastAPI backend.

- `get_engine()` / `get_db()`: Read-only engine via `DATABASE_URL_READONLY`
  for all gold-layer serving queries.
- `get_write_engine()` / `get_write_db()`: Bounded write engine via
  `DATABASE_URL_ALERTS` or `DATABASE_URL_ADMIN` (fallback `DATABASE_URL_READONLY`
  for local dev/tests) exclusively for `public.price_alerts`.

Both engines enforce Neon + Render safe connection pooling (`pool_pre_ping=True`,
bounded pool sizes, short recycle, connect timeout, and per-connection PostgreSQL
`statement_timeout` via connect event so both Neon direct and PgBouncer pooled
endpoints work cleanly).
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

def _resolve_repo_root() -> Path:
    env_root = os.getenv("REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    parents = Path(__file__).resolve().parents
    return parents[min(3, len(parents) - 1)] if parents else Path(".")


# Load root .env for local development (ignored in production when env vars are set)
_REPO_ROOT = _resolve_repo_root()
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "10000"))

_engine: Engine | None = None
_write_engine: Engine | None = None
_alerts_table_ready = False
_alerts_table_lock = threading.Lock()

PRICE_ALERTS_DDL = text(
    """
    CREATE TABLE IF NOT EXISTS public.price_alerts (
        id            SERIAL PRIMARY KEY,
        product_key   TEXT NOT NULL,
        product_title TEXT,
        store_name    TEXT,
        target_price  NUMERIC(12,2) NOT NULL CHECK (target_price > 0),
        channel       TEXT NOT NULL CHECK (channel IN ('telegram', 'email')),
        destination   TEXT NOT NULL,
        is_active     BOOLEAN NOT NULL DEFAULT TRUE,
        triggered_at  TIMESTAMPTZ,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
)


def _normalize_pg_url(db_url: str) -> str:
    if db_url.startswith("postgres://"):
        return db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return db_url


def _build_pooled_engine(db_url: str, *, pool_size: int, max_overflow: int) -> Engine:
    engine = create_engine(
        _normalize_pg_url(db_url),
        pool_pre_ping=True,
        pool_recycle=240,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=15,
        connect_args={"connect_timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_connection: object, _connection_record: object) -> None:
        # Applying statement_timeout via session SET works cleanly across both
        # direct PostgreSQL connections and Neon PgBouncer pooled endpoints.
        try:
            cur = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cur.execute(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}")
            finally:
                cur.close()
        except Exception as exc:
            logger.debug("Could not apply statement_timeout on DB connection: %s", exc)

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        db_url = os.getenv("DATABASE_URL_READONLY")
        if not db_url:
            raise RuntimeError("DATABASE_URL_READONLY environment variable is not set")
        _engine = _build_pooled_engine(
            db_url,
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
        )
    return _engine


def get_write_engine() -> Engine:
    global _write_engine
    if _write_engine is None:
        db_url = (
            os.getenv("DATABASE_URL_ALERTS")
            or os.getenv("DATABASE_URL_ADMIN")
            or os.getenv("DATABASE_URL_READONLY")
        )
        if not db_url:
            raise RuntimeError(
                "DATABASE_URL_ALERTS / DATABASE_URL_ADMIN environment variable is not set"
            )
        _write_engine = _build_pooled_engine(
            db_url,
            pool_size=int(os.getenv("DB_WRITE_POOL_SIZE", "3")),
            max_overflow=int(os.getenv("DB_WRITE_MAX_OVERFLOW", "3")),
        )
    return _write_engine


def ensure_price_alerts_table(conn: Connection) -> None:
    """Idempotently ensure `public.price_alerts` exists once per worker process."""
    global _alerts_table_ready
    if _alerts_table_ready:
        return
    with _alerts_table_lock:
        if _alerts_table_ready:
            return
        conn.execute(PRICE_ALERTS_DDL)
        _alerts_table_ready = True


def get_db() -> Generator[Connection, None, None]:
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


def get_write_db() -> Generator[Connection, None, None]:
    engine = get_write_engine()
    with engine.begin() as conn:
        yield conn
