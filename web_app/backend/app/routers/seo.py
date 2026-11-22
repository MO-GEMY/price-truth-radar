"""Lightweight SEO sitemap entries endpoint (cached 1 hour)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cache import set_cache_headers, sitemap_cache
from app.database import get_db
from app.schemas import (
    SitemapComparisonEntry,
    SitemapEntriesResponse,
    SitemapProductEntry,
)

router = APIRouter(tags=["seo"])


@router.get("/api/seo/sitemap-entries", response_model=SitemapEntriesResponse)
@router.get("/api/v1/seo/sitemap-entries", response_model=SitemapEntriesResponse, include_in_schema=True)
def get_sitemap_entries(
    response: Response,
    limit: int = Query(default=2000, ge=1, le=10000),
    db: Connection = Depends(get_db),
) -> SitemapEntriesResponse:
    set_cache_headers(response, s_maxage=3600, stale_while_revalidate=7200)
    cache_key = f"seo:sitemap:{limit}"
    cached = sitemap_cache.get(cache_key)
    if cached is not None:
        return cached

    products_sql = text(
        """
        SELECT
            product_sk,
            COALESCE(canonical_product_key, product_sk) AS product_key,
            category,
            store_name,
            last_updated_at
        FROM gold.mart_product_verdicts
        ORDER BY
            CASE
                WHEN discount_verdict IN ('ALL_TIME_LOW', 'GENUINE_DEAL', 'FAKE_DISCOUNT', 'PRESALE_HIKE') THEN 0
                ELSE 1
            END ASC,
            last_updated_at DESC,
            product_sk ASC
        LIMIT :limit
        """
    )

    comparisons_sql = text(
        """
        SELECT
            canonical_product_key,
            category,
            stores_count
        FROM gold.mart_cross_store_matches
        ORDER BY stores_count DESC, price_spread_pct DESC, canonical_product_key ASC
        LIMIT :comp_limit
        """
    )

    comp_limit = min(limit, 2000)
    prod_rows = db.execute(products_sql, {"limit": limit}).mappings().all()
    comp_rows = db.execute(comparisons_sql, {"comp_limit": comp_limit}).mappings().all()

    products = [
        SitemapProductEntry(
            product_sk=str(r["product_sk"]),
            product_key=str(r["product_key"]),
            category=str(r["category"]),
            store_name=str(r["store_name"]),
            last_updated=r["last_updated_at"],
        )
        for r in prod_rows
    ]
    comparisons = [
        SitemapComparisonEntry(
            canonical_product_key=str(r["canonical_product_key"]),
            category=str(r["category"]),
            stores_count=int(r["stores_count"]),
        )
        for r in comp_rows
    ]

    timestamps = [r["last_updated_at"] for r in prod_rows if r.get("last_updated_at") is not None]
    last_updated = max(timestamps) if timestamps else datetime.now(timezone.utc)

    result = SitemapEntriesResponse(
        last_updated=last_updated,
        products=products,
        comparisons=comparisons,
    )
    sitemap_cache.set(cache_key, result, ttl=3600.0)
    return result
