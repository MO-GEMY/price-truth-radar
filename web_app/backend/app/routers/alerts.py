"""Price drop alerts creation (`POST /api/alerts`) & token-verified cancellation (`POST /api/alerts/{id}/cancel`)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.database import _is_insufficient_privilege, ensure_price_alerts_table, get_write_db
from app.schemas import (
    AlertCancelRequest,
    AlertCancelResponse,
    AlertCreateRequest,
    AlertCreateResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["alerts"])

MAX_ACTIVE_ALERTS_PER_DESTINATION = 25
_WARNED_FALLBACK_SECRET = False


def _resolve_cancel_secret() -> bytes:
    """Resolve the HMAC signing key for stateless alert cancel tokens.

    Prefers explicit `ALERT_CANCEL_SECRET`. If not yet configured on Railway,
    derives a domain-separated key from an existing server-only secret so cancel
    tokens stay cryptographically unforgeable without requiring a DB migration.
    """
    global _WARNED_FALLBACK_SECRET
    explicit = os.getenv("ALERT_CANCEL_SECRET", "").strip()
    if explicit:
        return explicit.encode("utf-8")

    for env_name in (
        "DATABASE_URL_ALERTS",
        "DATABASE_URL_ADMIN",
        "RESEND_API_KEY",
        "TELEGRAM_BOT_TOKEN",
    ):
        val = os.getenv(env_name, "").strip()
        if val:
            if not _WARNED_FALLBACK_SECRET:
                logger.info(
                    "ALERT_CANCEL_SECRET not set; deriving stateless cancel-token key from %s.",
                    env_name,
                )
                _WARNED_FALLBACK_SECRET = True
            return hmac.new(
                b"asarak-alert-cancel-secret-v1",
                val.encode("utf-8"),
                hashlib.sha256,
            ).digest()

    # Local dev / unit tests with no external secrets configured
    return b"asarak-dev-alert-cancel-fallback-v1"


def compute_cancel_token(*, alert_id: int, product_key: str, destination: str) -> str:
    """Derive a stateless 64-char HMAC-SHA256 cancellation token for a specific alert row."""
    secret = _resolve_cancel_secret()
    payload = f"v1:{int(alert_id)}:{product_key.strip()}:{destination.strip().lower()}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify_cancel_token(
    *,
    token: str,
    alert_id: int,
    product_key: str,
    destination: str,
) -> bool:
    expected = compute_cancel_token(
        alert_id=alert_id,
        product_key=product_key,
        destination=destination,
    )
    return hmac.compare_digest(expected, token.strip())


@router.post(
    "/api/alerts",
    response_model=AlertCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/api/v1/alerts",
    response_model=AlertCreateResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=True,
)
def create_price_alert(
    payload: AlertCreateRequest,
    response: Response,
    db: Connection = Depends(get_write_db),
) -> AlertCreateResponse:
    response.headers["Cache-Control"] = "no-store"
    if not ensure_price_alerts_table(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price alerts are temporarily unavailable. Please try again later.",
        )

    # 1. Deduplicate active alert for same destination + product_key
    dup_sql = text(
        """
        SELECT id
        FROM public.price_alerts
        WHERE is_active = TRUE
          AND LOWER(destination) = LOWER(:destination)
          AND product_key = :product_key
        LIMIT 1
        """
    )
    existing = db.execute(
        dup_sql,
        {"destination": payload.destination, "product_key": payload.product_key},
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active price alert already exists for this product and destination.",
        )

    # 2. Cap active alerts per destination to protect against spam/abuse
    cap_sql = text(
        """
        SELECT COUNT(*)::INTEGER
        FROM public.price_alerts
        WHERE is_active = TRUE
          AND LOWER(destination) = LOWER(:destination)
        """
    )
    active_count = int(db.execute(cap_sql, {"destination": payload.destination}).scalar_one())
    if active_count >= MAX_ACTIVE_ALERTS_PER_DESTINATION:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Active alert limit reached ({MAX_ACTIVE_ALERTS_PER_DESTINATION} alerts per destination)."
            ),
        )

    # 3. Insert new active alert
    insert_sql = text(
        """
        INSERT INTO public.price_alerts (
            product_key,
            product_title,
            store_name,
            target_price,
            channel,
            destination,
            is_active
        )
        VALUES (
            :product_key,
            :product_title,
            :store_name,
            :target_price,
            :channel,
            :destination,
            TRUE
        )
        RETURNING id
        """
    )
    alert_id = int(
        db.execute(
            insert_sql,
            {
                "product_key": payload.product_key,
                "product_title": payload.product_title or None,
                "store_name": payload.store_name.lower() if payload.store_name else None,
                "target_price": payload.target_price,
                "channel": payload.channel,
                "destination": payload.destination,
            },
        ).scalar_one()
    )

    cancel_token = compute_cancel_token(
        alert_id=alert_id,
        product_key=payload.product_key,
        destination=payload.destination,
    )

    return AlertCreateResponse(
        id=alert_id,
        status="active",
        message="Price drop alert created and monitoring daily price snapshots.",
        cancel_token=cancel_token,
    )


@router.post(
    "/api/alerts/{alert_id}/cancel",
    response_model=AlertCancelResponse,
    status_code=status.HTTP_200_OK,
)
@router.post(
    "/api/v1/alerts/{alert_id}/cancel",
    response_model=AlertCancelResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=True,
)
def cancel_price_alert(
    payload: AlertCancelRequest,
    response: Response,
    alert_id: int = Path(..., ge=1),
    db: Connection = Depends(get_write_db),
) -> AlertCancelResponse:
    response.headers["Cache-Control"] = "no-store"
    if not ensure_price_alerts_table(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price alerts are temporarily unavailable. Please try again later.",
        )

    fetch_sql = text(
        """
        SELECT id, product_key, destination, is_active
        FROM public.price_alerts
        WHERE id = :alert_id
        LIMIT 1
        """
    )
    row = db.execute(fetch_sql, {"alert_id": alert_id}).mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Price alert not found.",
        )

    if not verify_cancel_token(
        token=payload.cancel_token,
        alert_id=int(row["id"]),
        product_key=str(row["product_key"]),
        destination=str(row["destination"]),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid alert cancellation token.",
        )

    if not bool(row["is_active"]):
        return AlertCancelResponse(
            id=alert_id,
            status="already_inactive",
            message="Price alert was already inactive.",
        )

    deactivate_sql = text(
        """
        UPDATE public.price_alerts
        SET is_active = FALSE
        WHERE id = :alert_id
          AND is_active = TRUE
        """
    )
    try:
        db.execute(deactivate_sql, {"alert_id": alert_id})
    except DBAPIError as exc:
        if _is_insufficient_privilege(exc):
            logger.error(
                "App DB role lacks UPDATE privilege on public.price_alerts (%s).",
                exc.orig,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Alert cancellation is temporarily unavailable.",
            ) from exc
        raise

    return AlertCancelResponse(
        id=alert_id,
        status="cancelled",
        message="Price alert cancelled.",
    )
