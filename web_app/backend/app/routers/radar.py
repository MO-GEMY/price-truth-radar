"""Paginated and filterable radar feed endpoint querying gold.mart_product_verdicts."""

from __future__ import annotations

import math
from statistics import median as _stats_median
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.cache import api_cache, set_cache_headers
from app.database import get_db
from app.schemas import (
    CategoryFilter,
    DiscountVerdict,
    MarketBenchmark,
    MarketBenchmarkStatus,
    ProductVerdictItem,
    RadarFeedResponse,
)
from app.subcategories import build_subcategory_sql_filter, normalize_subcategory_slug

router = APIRouter(prefix="/api/v1/radar", tags=["radar"])

SORT_EXPRESSIONS: dict[str, str] = {
    # Prioritize verified mature verdicts -> live verified cross-store comparisons ->
    # recent observed price moves -> remaining catalog (rich & honest during White Friday cold-start).
    "claimed_vs_real_gap_desc": (
        "CASE "
        "WHEN tracked_days_count >= 7 AND discount_verdict IN ('FAKE_DISCOUNT', 'PRESALE_HIKE', 'ALL_TIME_LOW', 'GENUINE_DEAL') THEN 0 "
        "WHEN canonical_product_key IS NOT NULL AND in_stock = TRUE THEN 1 "
        "WHEN discount_verdict IN ('RECENT_DROP', 'RECENT_HIKE') AND in_stock = TRUE THEN 2 "
        "ELSE 3 END ASC, "
        "(claimed_discount_pct - real_discount_pct) DESC, "
        "product_sk ASC"
    ),
    "real_discount_pct_desc": (
        "CASE "
        "WHEN tracked_days_count >= 7 AND discount_verdict IN ('ALL_TIME_LOW', 'GENUINE_DEAL') THEN 0 "
        "WHEN discount_verdict = 'RECENT_DROP' AND in_stock = TRUE THEN 1 "
        "WHEN canonical_product_key IS NOT NULL AND in_stock = TRUE THEN 2 "
        "ELSE 3 END ASC, "
        "real_discount_pct DESC, "
        "CASE WHEN max_historical_price > 0 THEN ((max_historical_price - current_price) / max_historical_price) ELSE 0 END DESC, "
        "product_sk ASC"
    ),
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
    max_variant_price,
    first_seen_date,
    tracked_days_count,
    history_maturity,
    verified_historical_median
"""


def compute_market_benchmark(
    product: ProductVerdictItem,
    listings_json: list[dict[str, Any]] | None,
) -> Optional[MarketBenchmark]:
    """Compute live verified cross-store market benchmark from exact `mart_cross_store_matches` offers."""
    if not listings_json:
        return None
    by_store: dict[str, tuple[float, bool]] = {}
    for entry in listings_json:
        st = str(entry.get("store_name") or "").strip()
        try:
            pr = float(entry.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
        if not st or pr <= 0:
            continue
        ins = bool(entry.get("in_stock"))
        prev = by_store.get(st)
        if prev is None or (not ins, pr) < (not prev[1], prev[0]):
            by_store[st] = (pr, ins)

    # Ensure current listing is represented at its latest price/stock
    if product.store_name and product.current_price > 0:
        prev = by_store.get(product.store_name)
        if prev is None or (not product.in_stock, product.current_price) <= (not prev[1], prev[0]):
            by_store[product.store_name] = (float(product.current_price), bool(product.in_stock))

    in_stock_offers = [(st, pr) for st, (pr, ins) in by_store.items() if ins and pr > 0]
    if len(by_store) < 2 or not in_stock_offers:
        return None
    # Require at least one OTHER store to exist in the exact match cluster
    if not any(st != product.store_name for st in by_store):
        return None

    in_stock_offers.sort(key=lambda pair: (pair[1], pair[0]))
    cheapest_store, cheapest_price = in_stock_offers[0]
    prices = [pr for _, pr in in_stock_offers]
    highest_price = prices[-1]
    median_price = round(float(_stats_median(prices)), 2)

    cur_price = float(product.current_price)
    diff_egp = round(cur_price - cheapest_price, 2)
    diff_pct = round((diff_egp / cheapest_price) * 100.0, 2) if cheapest_price > 0 else 0.0

    other_in_stock_prices = sorted(pr for st, pr in in_stock_offers if st != product.store_name)
    savings_vs_next = 0.0
    status: MarketBenchmarkStatus
    if not product.in_stock:
        status = "OUT_OF_STOCK"
    elif other_in_stock_prices and cur_price < other_in_stock_prices[0] - 0.5:
        status = "CHEAPEST_IN_MARKET"
        savings_vs_next = round(other_in_stock_prices[0] - cur_price, 2)
    elif cur_price <= cheapest_price + 0.5:
        status = "TIED_CHEAPEST" if (other_in_stock_prices and abs(other_in_stock_prices[0] - cur_price) <= 0.5) else "CHEAPEST_IN_MARKET"
        if other_in_stock_prices and other_in_stock_prices[0] > cur_price:
            savings_vs_next = round(other_in_stock_prices[0] - cur_price, 2)
    else:
        status = "ABOVE_MARKET"

    return MarketBenchmark(
        stores_count=len(by_store),
        cheapest_price=round(cheapest_price, 2),
        cheapest_store=cheapest_store,
        median_market_price=median_price,
        highest_price=round(highest_price, 2),
        price_diff_vs_cheapest_egp=diff_egp,
        price_diff_vs_cheapest_pct=diff_pct,
        savings_vs_next_cheapest_egp=savings_vs_next,
        status=status,
    )


def attach_market_benchmarks(
    db: Connection,
    items: list[ProductVerdictItem],
) -> list[ProductVerdictItem]:
    """Batch-enrich matched items (<= 50) with Live Market Benchmarks in one <1ms PK lookup."""
    keys = list(dict.fromkeys(item.canonical_product_key for item in items if item.canonical_product_key))
    if not keys:
        return items
    try:
        rows = (
            db.execute(
                text(
                    """
                    SELECT canonical_product_key, listings_json
                    FROM gold.mart_cross_store_matches
                    WHERE canonical_product_key = ANY(:keys)
                    """
                ),
                {"keys": keys},
            )
            .mappings()
            .all()
        )
    except DBAPIError:
        db.rollback()
        return items

    listings_by_key = {
        str(r["canonical_product_key"]): r.get("listings_json")
        for r in rows
        if r.get("canonical_product_key") and r.get("listings_json")
    }
    if not listings_by_key:
        return items

    enriched: list[ProductVerdictItem] = []
    for item in items:
        if item.canonical_product_key and item.canonical_product_key in listings_by_key:
            bm = compute_market_benchmark(item, listings_by_key[item.canonical_product_key])
            if bm is not None:
                enriched.append(item.model_copy(update={"market_benchmark": bm}))
                continue
        enriched.append(item)
    return enriched


@router.get("/feed", response_model=RadarFeedResponse)
def get_radar_feed(
    response: Response,
    category: CategoryFilter = Query(default="all"),
    subcategory: Optional[str] = Query(default=None),
    brand: Optional[str] = Query(default=None),
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
    norm_sub = normalize_subcategory_slug(subcategory)
    norm_brand = brand.strip().lower() if (brand and brand.strip()) else ""
    if verdict is None and not norm_store and not norm_sub and not norm_brand and page == 1:
        set_cache_headers(response, s_maxage=86400, stale_while_revalidate=604800)
    else:
        set_cache_headers(response, s_maxage=3600, stale_while_revalidate=86400)
    cache_key = (
        f"radar:feed:v4:{category}:{norm_sub}:{norm_brand}:{verdict or ''}:{norm_store}:{sort}:{page}:{limit}"
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    conditions: list[str] = []
    params: dict[str, object] = {}

    if category != "all":
        conditions.append("category = :category")
        params["category"] = category

    if norm_sub:
        sub_pred, sub_params = build_subcategory_sql_filter(category, norm_sub, param_prefix="rsub")
        if sub_pred:
            conditions.append(sub_pred)
            params.update(sub_params)

    if norm_brand:
        conditions.append("LOWER(TRIM(COALESCE(brand, ''))) = :brand")
        params["brand"] = norm_brand

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

    items = attach_market_benchmarks(db, [ProductVerdictItem.model_validate(dict(r)) for r in rows])
    total_pages = math.ceil(total / limit) if total > 0 else 0

    result = RadarFeedResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )
    api_cache.set(cache_key, result, ttl=21600.0)
    return result
