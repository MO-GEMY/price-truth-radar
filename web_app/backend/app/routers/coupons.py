"""Zero-Neon coupon directory and flash-sale cache refresh endpoints."""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Response, status

from app.coupons_service import CouponScope, coupon_store
from app.schemas import CouponsListResponse, CouponsRefreshResponse

router = APIRouter(tags=["coupons"])

COUPONS_CACHE_HEADER = "public, s-maxage=1800, stale-while-revalidate=3600"


@router.get("/api/v1/coupons", response_model=CouponsListResponse)
@router.get("/api/coupons", response_model=CouponsListResponse, include_in_schema=True)
def list_coupons(
    response: Response,
    store_id: Optional[str] = Query(default=None, max_length=80),
    scope: Optional[CouponScope] = Query(default=None),
    category: Optional[str] = Query(default=None, max_length=60),
) -> CouponsListResponse:
    """Return verified, active, non-expired coupons from RAM (zero Neon queries)."""
    response.headers["Cache-Control"] = COUPONS_CACHE_HEADER
    response.headers["CDN-Cache-Control"] = COUPONS_CACHE_HEADER

    items, source, refreshed_at = coupon_store.get_coupons(
        store_id=store_id,
        scope=scope,
        category=category,
    )
    available_stores = sorted({c.store_id for c in items})
    return CouponsListResponse(
        items=items,
        total=len(items),
        source=source,
        refreshed_at=refreshed_at,
        available_stores=available_stores,
    )


@router.post("/api/v1/coupons/refresh", response_model=CouponsRefreshResponse)
@router.post("/api/coupons/refresh", response_model=CouponsRefreshResponse, include_in_schema=True)
def refresh_coupons(
    response: Response,
    x_admin_secret: Optional[str] = Header(default=None, alias="X-Admin-Secret"),
) -> CouponsRefreshResponse:
    """Force an immediate in-memory refresh from `COUPONS_SHEET_CSV_URL` (admin-only)."""
    response.headers["Cache-Control"] = "no-store"
    expected = os.getenv("ADMIN_REFRESH_SECRET", "").strip()
    provided = (x_admin_secret or "").strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-Secret header.",
            headers={"Cache-Control": "no-store"},
        )

    result = coupon_store.refresh(force=True)
    return CouponsRefreshResponse(
        ok=bool(result.get("ok")),
        source=str(result.get("source") or "unknown"),
        count=int(result.get("count") or 0),
        refreshed_at=result.get("refreshed_at"),
        error=result.get("error"),
        skipped=[str(item) for item in result.get("skipped") or []],
    )
