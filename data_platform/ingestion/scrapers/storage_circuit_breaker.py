"""Automatic Neon storage circuit-breaker (900 MB / 970 MB) with Telegram alerting.

Thresholds:
  - `< 900 MB`      : FULL_EXPANSION    (ingest net-new in-stock products P1 -> P2 -> P3 + price updates)
  - `900 - 970 MB`  : PRICE_UPDATE_ONLY (update prices/stock for already-tracked SKUs + active alerts only;
                                         skip net-new inserts; send Telegram warning)
  - `> 970 MB`      : HARD_STOP         (abort new writes cleanly; send critical Telegram alert)
  - `> 700 MB`      : VACUUM FULL forbidden (`can_run_vacuum_full(size_mb) == False`)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx
import psycopg2

from .base import RawProductSnapshot, compute_product_sk

logger = logging.getLogger(__name__)

EXPANSION_CEILING_MB = 900.0
HARD_STOP_CEILING_MB = 970.0
VACUUM_FULL_MAX_MB = 700.0
TELEGRAM_API_BASE = "https://api.telegram.org"

StorageMode = Literal["FULL_EXPANSION", "PRICE_UPDATE_ONLY", "HARD_STOP"]


@dataclass(frozen=True)
class TableSizeStat:
    relation: str
    total_mb: float
    heap_mb: float
    index_mb: float
    live_rows: int


@dataclass(frozen=True)
class StorageSnapshot:
    db_size_mb: float
    db_size_bytes: int
    tables: tuple[TableSizeStat, ...] = ()


@dataclass(frozen=True)
class StorageDecision:
    mode: StorageMode
    db_size_mb: float
    warn_mb: float = EXPANSION_CEILING_MB
    stop_mb: float = HARD_STOP_CEILING_MB
    allow_new_inserts: bool = True
    allow_writes: bool = True
    should_notify: bool = False
    reason: str = ""


def can_run_vacuum_full(db_size_mb: float, *, max_mb: float = VACUUM_FULL_MAX_MB) -> bool:
    """Guardrail: NEVER allow `VACUUM FULL` when DB size exceeds 700 MB."""
    return float(db_size_mb) <= float(max_mb)


def evaluate_storage_mode(
    db_size_mb: float,
    *,
    warn_mb: float = EXPANSION_CEILING_MB,
    stop_mb: float = HARD_STOP_CEILING_MB,
) -> StorageDecision:
    """Evaluate Neon DB size against the 900 MB / 950 MB storage circuit-breaker."""
    size = round(float(db_size_mb), 2)
    if size > stop_mb:
        return StorageDecision(
            mode="HARD_STOP",
            db_size_mb=size,
            warn_mb=warn_mb,
            stop_mb=stop_mb,
            allow_new_inserts=False,
            allow_writes=False,
            should_notify=True,
            reason=f"Neon DB {size:.2f} MB > {stop_mb:.0f} MB hard ceiling — aborting new writes.",
        )
    if size >= warn_mb:
        return StorageDecision(
            mode="PRICE_UPDATE_ONLY",
            db_size_mb=size,
            warn_mb=warn_mb,
            stop_mb=stop_mb,
            allow_new_inserts=False,
            allow_writes=True,
            should_notify=True,
            reason=(
                f"Neon DB {size:.2f} MB >= {warn_mb:.0f} MB circuit-breaker — "
                f"switching to Price-Update-Only Mode (tracked SKUs & active alerts only)."
            ),
        )
    return StorageDecision(
        mode="FULL_EXPANSION",
        db_size_mb=size,
        warn_mb=warn_mb,
        stop_mb=stop_mb,
        allow_new_inserts=True,
        allow_writes=True,
        should_notify=False,
        reason=f"Neon DB {size:.2f} MB < {warn_mb:.0f} MB — full expansion mode active.",
    )


def inspect_neon_storage(*, conn: Any = None) -> StorageSnapshot:
    """Query exact Neon DB size + top table breakdown in one brief query."""
    own_conn = conn is None
    if own_conn:
        db_url = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL_READONLY") or os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL_ADMIN / DATABASE_URL not set.")
        conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())::BIGINT;")
            db_bytes = int(cur.fetchone()[0] or 0)
            cur.execute(
                """
                SELECT
                    schemaname || '.' || relname AS rel,
                    pg_total_relation_size(relid)::BIGINT AS total_b,
                    pg_relation_size(relid)::BIGINT AS heap_b,
                    pg_indexes_size(relid)::BIGINT AS idx_b,
                    COALESCE(n_live_tup, 0)::BIGINT AS live_rows
                FROM pg_stat_user_tables
                WHERE schemaname IN ('raw', 'gold', 'public')
                ORDER BY pg_total_relation_size(relid) DESC
                LIMIT 8;
                """
            )
            stats = tuple(
                TableSizeStat(
                    relation=str(r[0]),
                    total_mb=round(int(r[1]) / (1024.0 * 1024.0), 2),
                    heap_mb=round(int(r[2]) / (1024.0 * 1024.0), 2),
                    index_mb=round(int(r[3]) / (1024.0 * 1024.0), 2),
                    live_rows=int(r[4]),
                )
                for r in cur.fetchall()
            )
        return StorageSnapshot(
            db_size_mb=round(db_bytes / (1024.0 * 1024.0), 2),
            db_size_bytes=db_bytes,
            tables=stats,
        )
    finally:
        if own_conn:
            conn.close()


def fetch_tracked_product_sks(*, conn: Any = None) -> set[str]:
    """Load tracked `product_sk` set from `gold.mart_product_verdicts` + active `public.price_alerts`."""
    own_conn = conn is None
    if own_conn:
        db_url = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL_READONLY") or os.getenv("DATABASE_URL")
        if not db_url:
            return set()
        conn = psycopg2.connect(db_url)
    try:
        tracked: set[str] = set()
        with conn.cursor() as cur:
            cur.execute("SELECT product_sk FROM gold.mart_product_verdicts;")
            tracked.update(str(r[0]) for r in cur.fetchall() if r and r[0])
            try:
                cur.execute("SELECT product_key FROM public.price_alerts WHERE is_active = TRUE;")
                tracked.update(str(r[0]) for r in cur.fetchall() if r and r[0])
            except Exception:
                conn.rollback()
        return tracked
    finally:
        if own_conn:
            conn.close()


def filter_for_price_update_only(
    snapshots: list[RawProductSnapshot],
    tracked_sks: set[str],
) -> tuple[list[RawProductSnapshot], int]:
    """Keep ONLY snapshots whose deterministic `product_sk` already exists in Neon or active alerts."""
    kept: list[RawProductSnapshot] = []
    dropped = 0
    for s in snapshots:
        sk = compute_product_sk(s.store_name, s.external_id)
        if sk in tracked_sks:
            kept.append(s)
        else:
            dropped += 1
    return kept, dropped


def format_telegram_storage_alert(
    decision: StorageDecision,
    snapshot: StorageSnapshot,
    *,
    context: str = "",
) -> str:
    """Format a concise operational Telegram alert with exact Neon DB size & table breakdown."""
    icon = "🚨 CRITICAL" if decision.mode == "HARD_STOP" else "⚠️ WARNING"
    lines = [
        f"{icon} — Asarak Neon Storage Circuit-Breaker ({decision.mode})",
        f"DB Size: {snapshot.db_size_mb:.2f} MB / 1024 MB ({100.0 * snapshot.db_size_mb / 1024.0:.1f}%)",
        f"Reason: {decision.reason}",
    ]
    if context:
        lines.append(f"Wave: {context}")
    if snapshot.tables:
        lines.append("")
        lines.append("Table breakdown:")
        for t in snapshot.tables[:6]:
            lines.append(
                f"• {t.relation}: {t.total_mb:.1f} MB "
                f"(heap {t.heap_mb:.1f} / idx {t.index_mb:.1f}, ~{t.live_rows:,} rows)"
            )
    return "\n".join(lines)[:4000]


def send_storage_telegram_alert(
    decision: StorageDecision,
    snapshot: StorageSnapshot,
    *,
    context: str = "",
    http_post: Any = None,
) -> bool:
    """Send Telegram circuit-breaker alert via `TELEGRAM_BOT_TOKEN` + `TELEGRAM_NOTIFY_CHAT_ID`."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = (os.getenv("TELEGRAM_NOTIFY_CHAT_ID", "") or os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")).strip()
    if not token or not chat_id:
        logger.warning(
            "[circuit-breaker] %s triggered at %.2f MB (Telegram not configured; skipping push).",
            decision.mode,
            snapshot.db_size_mb,
        )
        return False

    text = format_telegram_storage_alert(decision, snapshot, context=context)
    poster = http_post or httpx.post
    try:
        resp = poster(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=12.0,
        )
        if getattr(resp, "status_code", 500) >= 400:
            logger.warning("[circuit-breaker] Telegram API rejected alert (HTTP %s).", getattr(resp, "status_code", "?"))
            return False
        return True
    except Exception as exc:
        logger.warning("[circuit-breaker] Failed sending Telegram alert (%s).", type(exc).__name__)
        return False
