"""Overview statistics endpoint querying gold.mart_product_verdicts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cache import api_cache, set_cache_headers
from app.database import get_db
from app.schemas import OverviewStatsResponse

router = APIRouter(tags=["stats"])

OVERVIEW_SQL = text(
    """
    SELECT
        COUNT(*)::INTEGER AS total_tracked,
        COUNT(*) FILTER (WHERE discount_verdict = 'FAKE_DISCOUNT')::INTEGER AS fake_discounts_today,
        COUNT(*) FILTER (WHERE discount_verdict = 'GENUINE_DEAL')::INTEGER AS genuine_deals_today,
        COUNT(*) FILTER (WHERE discount_verdict = 'ALL_TIME_LOW')::INTEGER AS all_time_lows_today,
        COUNT(*) FILTER (WHERE discount_verdict = 'PRESALE_HIKE')::INTEGER AS presale_hikes_today,
        COALESCE(
            ROUND(
                AVG(claimed_discount_pct - real_discount_pct)
                FILTER (WHERE discount_verdict = 'FAKE_DISCOUNT'),
                1
            ),
            0.0
        )::FLOAT AS avg_fake_inflation_pct,
        MAX(last_updated_at) AS last_pipeline_run_at,
        COALESCE(
            ARRAY_AGG(DISTINCT store_name ORDER BY store_name) FILTER (WHERE store_name IS NOT NULL),
            ARRAY[]::TEXT[]
        ) AS available_stores
    FROM gold.mart_product_verdicts
    """
)


@router.get("/api/v1/stats/overview", response_model=OverviewStatsResponse)
@router.get("/api/stats", response_model=OverviewStatsResponse, include_in_schema=True)
def get_overview_stats(
    response: Response,
    db: Connection = Depends(get_db),
) -> OverviewStatsResponse:
    set_cache_headers(response, s_maxage=300, stale_while_revalidate=600)
    cache_key = "stats:overview"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    row = db.execute(OVERVIEW_SQL).mappings().one()
    result = OverviewStatsResponse(
        total_tracked=int(row["total_tracked"]),
        fake_discounts_today=int(row["fake_discounts_today"]),
        genuine_deals_today=int(row["genuine_deals_today"]),
        all_time_lows_today=int(row["all_time_lows_today"]),
        presale_hikes_today=int(row["presale_hikes_today"]),
        avg_fake_inflation_pct=float(row["avg_fake_inflation_pct"]),
        last_pipeline_run_at=row["last_pipeline_run_at"],
        available_stores=list(row["available_stores"] or []),
    )
    api_cache.set(cache_key, result, ttl=300.0)
    return result
