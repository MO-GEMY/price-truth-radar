"""Database engines for Asarak (أسعارك) FastAPI backend.

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
from psycopg2.errors import InsufficientPrivilege
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

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
_IDLE_DISPOSE_DEFAULT = 90


def _idle_dispose_seconds() -> int:
    raw = os.getenv("DB_IDLE_DISPOSE_SECONDS", "").strip()
    try:
        val = int(raw) if raw else _IDLE_DISPOSE_DEFAULT
    except ValueError:
        val = _IDLE_DISPOSE_DEFAULT
    return max(15, min(300, val))


class _IdlePoolReaper:
    """Drops idle SQLAlchemy pooled connections after `idle_seconds` of inactivity.

    Keeps warm connection reuse during short request bursts while guaranteeing
    `min_size=0` idle sockets after `idle_seconds` (default 90s) with ZERO
    background keepalive pings so Neon's Scale-to-Zero suspends promptly.
    """

    def __init__(self, engine: Engine, idle_seconds: float) -> None:
        self._engine = engine
        self._idle_seconds = float(idle_seconds)
        self._lock = threading.Lock()
        self._checked_out = 0
        self._timer: threading.Timer | None = None

    def on_checkout(self) -> None:
        with self._lock:
            self._checked_out += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def on_checkin(self) -> None:
        with self._lock:
            self._checked_out = max(0, self._checked_out - 1)
            if self._checked_out == 0:
                if self._timer is not None:
                    self._timer.cancel()
                timer = threading.Timer(self._idle_seconds, self._dispose_if_idle)
                timer.daemon = True
                self._timer = timer
                timer.start()

    def _dispose_if_idle(self) -> None:
        with self._lock:
            self._timer = None
            if self._checked_out > 0:
                return
        try:
            self._engine.dispose()
            logger.debug("Disposed idle PostgreSQL pool after %.0fs inactivity for Neon Scale-to-Zero.", self._idle_seconds)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Idle pool dispose skipped: %s", exc)


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

# Read-only existence probe: the app DB role has DML grants on price_alerts but
# no CREATE on schema public, so the DDL must never run against an existing table.
PRICE_ALERTS_EXISTS_SQL = text("SELECT to_regclass('public.price_alerts')")

_INSUFFICIENT_PRIVILEGE_SQLSTATE = "42501"


def _normalize_pg_url(db_url: str) -> str:
    if db_url.startswith("postgres://"):
        return db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return db_url


def _build_pooled_engine(db_url: str, *, pool_size: int, max_overflow: int) -> Engine:
    pool_mode = os.getenv("DB_POOL_MODE", "lazy_reap").strip().lower()
    idle_seconds = _idle_dispose_seconds()
    connect_args = {
        "connect_timeout": 10,
        # Disable background TCP keepalives so idle sockets never keep Neon awake
        "keepalives": 0,
    }
    if pool_mode == "null" or pool_size <= 0:
        engine = create_engine(
            _normalize_pg_url(db_url),
            poolclass=NullPool,
            connect_args=connect_args,
        )
    else:
        engine = create_engine(
            _normalize_pg_url(db_url),
            pool_pre_ping=True,
            pool_recycle=idle_seconds,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=15,
            connect_args=connect_args,
        )
        reaper = _IdlePoolReaper(engine, idle_seconds=idle_seconds)

        @event.listens_for(engine, "checkout")
        def _on_checkout(*_args: object) -> None:
            reaper.on_checkout()

        @event.listens_for(engine, "checkin")
        def _on_checkin(*_args: object) -> None:
            reaper.on_checkin()

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
            pool_size=int(os.getenv("DB_POOL_SIZE", "1")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "4")),
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
            pool_size=int(os.getenv("DB_WRITE_POOL_SIZE", "1")),
            max_overflow=int(os.getenv("DB_WRITE_MAX_OVERFLOW", "2")),
        )
    return _write_engine


def _is_insufficient_privilege(exc: DBAPIError) -> bool:
    # SQLAlchemy surfaces the driver's 42501 as a plain ProgrammingError, so
    # match the wrapped driver error instead of a SQLAlchemy exception class.
    orig = getattr(exc, "orig", None)
    return isinstance(orig, InsufficientPrivilege) or (
        getattr(orig, "pgcode", None) == _INSUFFICIENT_PRIVILEGE_SQLSTATE
    )


def ensure_price_alerts_table(conn: Connection) -> bool:
    """Idempotently ensure `public.price_alerts` exists once per worker process.

    Returns False when the table is missing and cannot be created (the app DB
    role lacks CREATE on schema public) so callers fail closed instead of 500.
    """
    global _alerts_table_ready
    if _alerts_table_ready:
        return True
    with _alerts_table_lock:
        if _alerts_table_ready:
            return True
        try:
            if conn.execute(PRICE_ALERTS_EXISTS_SQL).scalar_one_or_none() is not None:
                _alerts_table_ready = True
                return True
            conn.execute(PRICE_ALERTS_DDL)
        except DBAPIError as exc:
            if not _is_insufficient_privilege(exc):
                raise
            logger.error(
                "price_alerts unavailable to the app DB role and CREATE on schema public "
                "is denied (%s); ensure public.price_alerts exists using an owner role.",
                exc.orig,
            )
            return False
        _alerts_table_ready = True
        return True


def get_db() -> Generator[Connection, None, None]:
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


def get_write_db() -> Generator[Connection, None, None]:
    engine = get_write_engine()
    with engine.begin() as conn:
        yield conn
