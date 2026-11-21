"""Cross-store arbitrage comparison endpoint querying gold.mart_cross_store_matches."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app.schemas import CompareResponse, CrossStoreMatchItem

router = APIRouter(prefix="/api/v1", tags=["compare"])


@router.get("/compare", response_model=CompareResponse)
def get_cross_store_comparison(
    category: Literal["all", "electronics", "fashion", "home_appliances"] = Query(default="all"),
    min_spread_pct: float = Query(default=0.0, ge=0.0),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Connection = Depends(get_db),
) -> CompareResponse:
    conditions: list[str] = ["price_spread_pct >= :min_spread_pct"]
    params: dict[str, object] = {"min_spread_pct": min_spread_pct}

    if category != "all":
        conditions.append("category = :category")
        params["category"] = category

    where_clause = f"WHERE {' AND '.join(conditions)}"

    count_sql = text(
        f"SELECT COUNT(*)::INTEGER FROM gold.mart_cross_store_matches {where_clause}"
    )
    total = int(db.execute(count_sql, params).scalar_one())

    offset = (page - 1) * limit
    query_params = {**params, "limit": limit, "offset": offset}
    items_sql = text(
        f"""
        SELECT
            canonical_product_key,
            product_title_clean,
            category,
            brand,
            stores_count,
            lowest_price,
            lowest_price_store,
            highest_price,
            price_spread_egp,
            price_spread_pct,
            listings_json
        FROM gold.mart_cross_store_matches
        {where_clause}
        ORDER BY price_spread_pct DESC, canonical_product_key ASC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = db.execute(items_sql, query_params).mappings().all()
    items = [CrossStoreMatchItem.model_validate(dict(r)) for r in rows]

    return CompareResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )
