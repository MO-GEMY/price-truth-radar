"""Price drop alerts creation endpoint (`POST /api/alerts`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import ensure_price_alerts_table, get_write_db
from app.schemas import AlertCreateRequest, AlertCreateResponse

router = APIRouter(tags=["alerts"])

MAX_ACTIVE_ALERTS_PER_DESTINATION = 25


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

    return AlertCreateResponse(
        id=alert_id,
        status="active",
        message="Price drop alert created and monitoring daily price snapshots.",
    )
