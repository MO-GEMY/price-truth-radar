"""Overview statistics endpoint querying gold.mart_product_verdicts."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app.schemas import OverviewStatsResponse

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

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
        MAX(last_updated_at) AS last_pipeline_run_at
    FROM gold.mart_product_verdicts
    """
)


@router.get("/overview", response_model=OverviewStatsResponse)
def get_overview_stats(db: Connection = Depends(get_db)) -> OverviewStatsResponse:
    row = db.execute(OVERVIEW_SQL).mappings().one()
    return OverviewStatsResponse(
        total_tracked=int(row["total_tracked"]),
        fake_discounts_today=int(row["fake_discounts_today"]),
        genuine_deals_today=int(row["genuine_deals_today"]),
        all_time_lows_today=int(row["all_time_lows_today"]),
        presale_hikes_today=int(row["presale_hikes_today"]),
        avg_fake_inflation_pct=float(row["avg_fake_inflation_pct"]),
        last_pipeline_run_at=row["last_pipeline_run_at"],
    )
