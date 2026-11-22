"""Overview statistics endpoint querying gold.mart_product_verdicts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cache import api_cache, set_cache_headers
from app.database import get_db
from app.schemas import (
    CANONICAL_CATEGORIES,
    CategoriesResponse,
    Category,
    CategoryFacetItem,
    OverviewStatsResponse,
)

router = APIRouter(tags=["stats"])

CATEGORY_METADATA: dict[str, tuple[str, str]] = {
    "electronics": ("Electronics", "إلكترونيات"),
    "home_appliances": ("Home Appliances", "أجهزة منزلية"),
    "home_furniture": ("Home & Furniture", "أثاث ومنزل"),
    "fashion": ("Fashion", "أزياء"),
    "beauty": ("Beauty & Perfumes", "عطور وتجميل"),
    "groceries": ("Groceries", "منتجات غذائية"),
    "health": ("Health & Pharmacy", "صيدليات وصحة"),
    "sports": ("Sports & Fitness", "رياضة ولياقة"),
    "pet_care": ("Pet Care", "مستلزمات الحيوانات"),
    "baby_kids": ("Baby & Kids", "أطفال وألعاب"),
}

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
        ) AS available_stores,
        COALESCE(
            (
                SELECT JSONB_OBJECT_AGG(cat_row.category, cat_row.cnt)
                FROM (
                    SELECT category, COUNT(*)::INTEGER AS cnt
                    FROM gold.mart_product_verdicts
                    WHERE category IS NOT NULL
                    GROUP BY category
                    HAVING COUNT(*) > 0
                ) cat_row
            ),
            '{}'::JSONB
        ) AS category_counts
    FROM gold.mart_product_verdicts
    """
)

CATEGORY_FACETS_SQL = text(
    """
    WITH product_counts AS (
        SELECT category, COUNT(*)::INTEGER AS product_count
        FROM gold.mart_product_verdicts
        WHERE category IS NOT NULL
        GROUP BY category
    ),
    compare_counts AS (
        SELECT category, COUNT(*)::INTEGER AS compare_count
        FROM gold.mart_cross_store_matches
        WHERE category IS NOT NULL
        GROUP BY category
    )
    SELECT
        COALESCE(p.category, c.category) AS category,
        COALESCE(p.product_count, 0)::INTEGER AS product_count,
        COALESCE(c.compare_count, 0)::INTEGER AS compare_count
    FROM product_counts p
    FULL OUTER JOIN compare_counts c
        ON p.category = c.category
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
    raw_cat_counts = row.get("category_counts") or {}
    cat_counts = {
        str(k): int(v)
        for k, v in (raw_cat_counts.items() if isinstance(raw_cat_counts, dict) else [])
        if str(k) in CATEGORY_METADATA and int(v) > 0
    }
    result = OverviewStatsResponse(
        total_tracked=int(row["total_tracked"]),
        fake_discounts_today=int(row["fake_discounts_today"]),
        genuine_deals_today=int(row["genuine_deals_today"]),
        all_time_lows_today=int(row["all_time_lows_today"]),
        presale_hikes_today=int(row["presale_hikes_today"]),
        avg_fake_inflation_pct=float(row["avg_fake_inflation_pct"]),
        last_pipeline_run_at=row["last_pipeline_run_at"],
        available_stores=list(row["available_stores"] or []),
        category_counts=cat_counts,
    )
    api_cache.set(cache_key, result, ttl=300.0)
    return result


@router.get("/api/v1/categories", response_model=CategoriesResponse)
@router.get("/api/categories", response_model=CategoriesResponse, include_in_schema=True)
def get_categories(
    response: Response,
    include_empty: bool = False,
    db: Connection = Depends(get_db),
) -> CategoriesResponse:
    set_cache_headers(response, s_maxage=300, stale_while_revalidate=600)
    cache_key = f"stats:categories:{int(include_empty)}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    rows = db.execute(CATEGORY_FACETS_SQL).mappings().all()
    by_slug: dict[str, tuple[int, int]] = {
        str(r["category"]): (int(r["product_count"]), int(r["compare_count"]))
        for r in rows
        if r.get("category") is not None
    }
    items: list[CategoryFacetItem] = []
    total_products = 0
    for slug in CANONICAL_CATEGORIES:
        p_cnt, c_cnt = by_slug.get(slug, (0, 0))
        total_products += p_cnt
        if not include_empty and p_cnt <= 0 and c_cnt <= 0:
            continue
        label_en, label_ar = CATEGORY_METADATA[slug]
        items.append(
            CategoryFacetItem(
                slug=slug,  # type: ignore[arg-type]
                label_en=label_en,
                label_ar=label_ar,
                product_count=p_cnt,
                compare_count=c_cnt,
            )
        )

    result = CategoriesResponse(items=items, total_products=total_products)
    api_cache.set(cache_key, result, ttl=300.0)
    return result
