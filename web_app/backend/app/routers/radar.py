"""Paginated and filterable radar feed endpoint querying gold.mart_product_verdicts."""

from __future__ import annotations

import math
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.cache import api_cache, set_cache_headers
from app.database import get_db
from app.schemas import CategoryFilter, DiscountVerdict, ProductVerdictItem, RadarFeedResponse

router = APIRouter(prefix="/api/v1/radar", tags=["radar"])

SORT_EXPRESSIONS: dict[str, str] = {
    "claimed_vs_real_gap_desc": "(claimed_discount_pct - real_discount_pct) DESC, product_sk ASC",
    "real_discount_pct_desc": "real_discount_pct DESC, product_sk ASC",
    "price_asc": "current_price ASC, product_sk ASC",
    "price_desc": "current_price DESC, product_sk ASC",
}

PRODUCT_SELECT_COLS = """
    product_sk,
    canonical_product_key,
    store_name,
    category,
    sub_category,
    brand,
    product_title,
    product_url,
    image_url,
    attributes_json,
    current_price,
    claimed_original_price,
    rolling_60d_median,
    min_historical_price,
    max_historical_price,
    claimed_discount_pct,
    real_discount_pct,
    discount_verdict,
    scarcity_flag,
    in_stock,
    last_updated_at,
    parent_product_key,
    variant_label,
    variant_count,
    has_multiple_variants,
    min_variant_price,
    max_variant_price
"""


@router.get("/feed", response_model=RadarFeedResponse)
def get_radar_feed(
    response: Response,
    category: CategoryFilter = Query(default="all"),
    verdict: Optional[DiscountVerdict] = Query(default=None),
    store: Optional[str] = Query(default=None),
    sort: Literal[
        "real_discount_pct_desc",
        "claimed_vs_real_gap_desc",
        "price_asc",
        "price_desc",
    ] = Query(default="claimed_vs_real_gap_desc"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Connection = Depends(get_db),
) -> RadarFeedResponse:
    norm_store = store.strip().lower() if (store and store.strip()) else ""
    if verdict is None and not norm_store and page == 1:
        set_cache_headers(response, s_maxage=86400, stale_while_revalidate=604800)
    else:
        set_cache_headers(response, s_maxage=3600, stale_while_revalidate=86400)
    cache_key = f"radar:feed:v2:{category}:{verdict or ''}:{norm_store}:{sort}:{page}:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    conditions: list[str] = []
    params: dict[str, object] = {}

    if category != "all":
        conditions.append("category = :category")
        params["category"] = category

    if verdict is not None:
        conditions.append("discount_verdict = :verdict")
        params["verdict"] = verdict

    if norm_store:
        conditions.append("store_name = :store")
        params["store"] = norm_store

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_clause = SORT_EXPRESSIONS[sort]
    offset = (page - 1) * limit
    query_params = {**params, "limit": limit, "offset": offset}

    # Fast path (no verdict filter): `is_primary_variant = TRUE` is precomputed in dbt
    # with the exact same tie-breaking (`in_stock DESC, current_price ASC, product_sk ASC`
    # per `parent_product_key`), eliminating the 101k-row DISTINCT ON external disk sort
    # and the redundant second full-table COUNT(DISTINCT ...) scan.
    rows = None
    if verdict is None:
        primary_conditions = ["is_primary_variant = TRUE", *conditions]
        primary_where = f"WHERE {' AND '.join(primary_conditions)}"
        fast_sql = text(
            f"""
            SELECT
                {PRODUCT_SELECT_COLS},
                COUNT(*) OVER()::INTEGER AS total_count
            FROM gold.mart_product_verdicts
            {primary_where}
            ORDER BY {order_clause}
            LIMIT :limit OFFSET :offset
            """
        )
        try:
            rows = db.execute(fast_sql, query_params).mappings().all()
        except DBAPIError as exc:
            # Rolling-deploy compatibility if `is_primary_variant` is not yet materialized
            if "is_primary_variant" not in str(exc):
                raise
            db.rollback()
            rows = None

    if rows is None:
        dedup_sql = text(
            f"""
            WITH deduped AS (
                SELECT DISTINCT ON (parent_product_key)
                    {PRODUCT_SELECT_COLS}
                FROM gold.mart_product_verdicts
                {where_clause}
                ORDER BY
                    parent_product_key,
                    in_stock DESC,
                    current_price ASC,
                    product_sk ASC
            )
            SELECT
                {PRODUCT_SELECT_COLS},
                COUNT(*) OVER()::INTEGER AS total_count
            FROM deduped
            ORDER BY {order_clause}
            LIMIT :limit OFFSET :offset
            """
        )
        rows = db.execute(dedup_sql, query_params).mappings().all()

    if rows and "total_count" in rows[0] and rows[0]["total_count"] is not None:
        total = int(rows[0]["total_count"])
    elif rows:
        total = len(rows)
    elif page > 1:
        count_where = (
            f"WHERE {' AND '.join(['is_primary_variant = TRUE', *conditions])}"
            if verdict is None
            else where_clause
        )
        count_expr = "COUNT(*)::INTEGER" if verdict is None else "COUNT(DISTINCT parent_product_key)::INTEGER"
        try:
            total = int(
                db.execute(
                    text(f"SELECT {count_expr} FROM gold.mart_product_verdicts {count_where}"),
                    params,
                ).scalar_one()
            )
        except DBAPIError:
            db.rollback()
            total = int(
                db.execute(
                    text(f"SELECT COUNT(DISTINCT parent_product_key)::INTEGER FROM gold.mart_product_verdicts {where_clause}"),
                    params,
                ).scalar_one()
            )
    else:
        total = 0

    items = [ProductVerdictItem.model_validate(dict(r)) for r in rows]
    total_pages = math.ceil(total / limit) if total > 0 else 0

    result = RadarFeedResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )
    api_cache.set(cache_key, result, ttl=3600.0)
    return result
