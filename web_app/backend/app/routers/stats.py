"""Overview statistics endpoint querying gold.mart_product_verdicts."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cache import api_cache, set_cache_headers
from app.database import get_db
from app.schemas import (
    BrandFacetItem,
    CANONICAL_CATEGORIES,
    CategoriesResponse,
    Category,
    CategoryFacetItem,
    CategoryFacetsResponse,
    OverviewStatsResponse,
    StoreFacetItem,
    SubcategoryFacetItem,
)
from app.subcategories import (
    build_subcategory_sql_filter,
    get_category_subcategories,
    normalize_subcategory_slug,
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
    WITH base AS (
        SELECT
            category,
            store_name,
            COUNT(*)::INTEGER AS cnt,
            COUNT(*) FILTER (WHERE discount_verdict = 'FAKE_DISCOUNT')::INTEGER AS fake_cnt,
            COUNT(*) FILTER (WHERE discount_verdict = 'GENUINE_DEAL')::INTEGER AS genuine_cnt,
            COUNT(*) FILTER (WHERE discount_verdict = 'ALL_TIME_LOW')::INTEGER AS atl_cnt,
            COUNT(*) FILTER (WHERE discount_verdict = 'PRESALE_HIKE')::INTEGER AS hike_cnt,
            SUM(claimed_discount_pct - real_discount_pct)
                FILTER (WHERE discount_verdict = 'FAKE_DISCOUNT') AS fake_infl_sum,
            MAX(last_updated_at) AS max_updated_at
        FROM gold.mart_product_verdicts
        GROUP BY category, store_name
    ),
    cat_totals AS (
        SELECT category, SUM(cnt)::INTEGER AS cnt
        FROM base
        WHERE category IS NOT NULL
        GROUP BY category
        HAVING SUM(cnt) > 0
    )
    SELECT
        COALESCE(SUM(cnt), 0)::INTEGER AS total_tracked,
        COALESCE(SUM(fake_cnt), 0)::INTEGER AS fake_discounts_today,
        COALESCE(SUM(genuine_cnt), 0)::INTEGER AS genuine_deals_today,
        COALESCE(SUM(atl_cnt), 0)::INTEGER AS all_time_lows_today,
        COALESCE(SUM(hike_cnt), 0)::INTEGER AS presale_hikes_today,
        COALESCE(
            ROUND(
                (SUM(fake_infl_sum) / NULLIF(SUM(fake_cnt), 0))::NUMERIC,
                1
            ),
            0.0
        )::FLOAT AS avg_fake_inflation_pct,
        MAX(max_updated_at) AS last_pipeline_run_at,
        COALESCE(
            ARRAY_AGG(DISTINCT store_name ORDER BY store_name) FILTER (WHERE store_name IS NOT NULL),
            ARRAY[]::TEXT[]
        ) AS available_stores,
        COALESCE(
            (SELECT JSONB_OBJECT_AGG(category, cnt) FROM cat_totals),
            '{}'::JSONB
        ) AS category_counts,
        COALESCE(
            (SELECT COUNT(*)::INTEGER FROM gold.mart_cross_store_matches),
            0
        ) AS cross_store_matches_count
    FROM base
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
    set_cache_headers(response, s_maxage=3600, stale_while_revalidate=86400)
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
        cross_store_matches_count=int(row.get("cross_store_matches_count") or 0),
    )
    api_cache.set(cache_key, result, ttl=21600.0)
    return result


@router.get("/api/v1/categories", response_model=CategoriesResponse)
@router.get("/api/categories", response_model=CategoriesResponse, include_in_schema=True)
def get_categories(
    response: Response,
    include_empty: bool = False,
    db: Connection = Depends(get_db),
) -> CategoriesResponse:
    set_cache_headers(response, s_maxage=86400, stale_while_revalidate=604800)
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
    api_cache.set(cache_key, result, ttl=43200.0)
    return result


_IGNORED_BRANDS_SQL = (
    "('unknown', 'generic', 'unbranded', 'other', 'n/a', 'none', 'no brand', 'null', '-', 'na')"
)


def _compute_subcategory_counts(
    db: Connection,
    category: Category,
) -> tuple[int, list[SubcategoryFacetItem]]:
    """Compute live in-stock counts for all canonical subcategories in a category (cached 6h)."""
    sub_cache_key = f"stats:cat_subcounts:v1:{category}"
    cached = api_cache.get(sub_cache_key)
    if cached is not None:
        return cached

    specs = get_category_subcategories(category)
    select_parts = ["COUNT(*)::INTEGER AS total_in_stock"]
    params: dict[str, Any] = {"category": category}

    for idx, spec in enumerate(specs):
        pred, pred_params = build_subcategory_sql_filter(
            category,
            spec.slug,
            param_prefix=f"sc{idx}",
        )
        if pred:
            select_parts.append(f"COUNT(*) FILTER (WHERE {pred})::INTEGER AS cnt_{idx}")
            params.update(pred_params)

    sql = text(
        f"""
        SELECT {", ".join(select_parts)}
        FROM gold.mart_product_verdicts
        WHERE category = :category
          AND in_stock = TRUE
        """
    )
    row = db.execute(sql, params).mappings().one()
    total_in_stock = int(row.get("total_in_stock") or 0)

    items: list[SubcategoryFacetItem] = []
    for idx, spec in enumerate(specs):
        cnt = int(row.get(f"cnt_{idx}") or 0)
        if cnt <= 0:
            continue
        items.append(
            SubcategoryFacetItem(
                slug=spec.slug,
                label_en=spec.label_en,
                label_ar=spec.label_ar,
                count=cnt,
            )
        )
    items.sort(key=lambda item: (-item.count, item.label_en))
    result = (total_in_stock, items)
    api_cache.set(sub_cache_key, result, ttl=21600.0)
    return result


def _load_category_facets(
    response: Response,
    category: Category,
    subcategory: Optional[str],
    db: Connection,
) -> CategoryFacetsResponse:
    set_cache_headers(response, s_maxage=21600, stale_while_revalidate=86400)
    norm_sub = normalize_subcategory_slug(subcategory)
    cache_key = f"stats:cat_facets:v1:{category}:{norm_sub}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    total_in_stock, subcategories = _compute_subcategory_counts(db, category)

    params: dict[str, Any] = {"category": category}
    sub_clause = ""
    if norm_sub:
        pred, pred_params = build_subcategory_sql_filter(category, norm_sub, param_prefix="fsub")
        if pred:
            sub_clause = f"AND {pred}"
            params.update(pred_params)

    facets_sql = text(
        f"""
        WITH scoped AS (
            SELECT store_name, brand
            FROM gold.mart_product_verdicts
            WHERE category = :category
              AND in_stock = TRUE
              {sub_clause}
        ),
        store_agg AS (
            SELECT store_name AS slug, COUNT(*)::INTEGER AS cnt
            FROM scoped
            WHERE store_name IS NOT NULL AND store_name <> ''
            GROUP BY store_name
        ),
        brand_agg AS (
            SELECT MIN(TRIM(brand)) AS name, COUNT(*)::INTEGER AS cnt
            FROM scoped
            WHERE brand IS NOT NULL
              AND TRIM(brand) <> ''
              AND LOWER(TRIM(brand)) NOT IN {_IGNORED_BRANDS_SQL}
            GROUP BY LOWER(TRIM(brand))
            ORDER BY COUNT(*) DESC, MIN(TRIM(brand)) ASC
            LIMIT 40
        )
        SELECT
            (SELECT COUNT(*)::INTEGER FROM scoped) AS scoped_total,
            COALESCE(
                (SELECT JSONB_AGG(JSONB_BUILD_OBJECT('slug', slug, 'count', cnt) ORDER BY cnt DESC, slug ASC) FROM store_agg),
                '[]'::JSONB
            ) AS stores,
            COALESCE(
                (SELECT JSONB_AGG(JSONB_BUILD_OBJECT('name', name, 'count', cnt) ORDER BY cnt DESC, name ASC) FROM brand_agg),
                '[]'::JSONB
            ) AS brands
        """
    )
    row = db.execute(facets_sql, params).mappings().one()
    raw_stores = row.get("stores") or []
    raw_brands = row.get("brands") or []

    stores = [
        StoreFacetItem(slug=str(item["slug"]), count=int(item["count"]))
        for item in raw_stores
        if isinstance(item, dict) and item.get("slug") and int(item.get("count") or 0) > 0
    ]
    brands = [
        BrandFacetItem(name=str(item["name"]), count=int(item["count"]))
        for item in raw_brands
        if isinstance(item, dict) and item.get("name") and int(item.get("count") or 0) > 0
    ]

    result = CategoryFacetsResponse(
        category=category,
        subcategory=norm_sub or None,
        total_in_stock=int(row.get("scoped_total") or 0) if norm_sub else total_in_stock,
        subcategories=subcategories,
        stores=stores,
        brands=brands,
    )
    api_cache.set(cache_key, result, ttl=21600.0)
    return result


@router.get("/api/v1/categories/facets", response_model=CategoryFacetsResponse)
@router.get("/api/facets", response_model=CategoryFacetsResponse, include_in_schema=True)
def get_facets_by_query(
    response: Response,
    category: Category = Query(...),
    subcategory: Optional[str] = Query(default=None),
    db: Connection = Depends(get_db),
) -> CategoryFacetsResponse:
    return _load_category_facets(response, category, subcategory, db)


@router.get("/api/v1/categories/{category}/facets", response_model=CategoryFacetsResponse)
@router.get("/api/categories/{category}/facets", response_model=CategoryFacetsResponse, include_in_schema=True)
def get_category_facets(
    category: Category,
    response: Response,
    subcategory: Optional[str] = Query(default=None),
    db: Connection = Depends(get_db),
) -> CategoryFacetsResponse:
    return _load_category_facets(response, category, subcategory, db)
