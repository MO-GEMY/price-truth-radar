"""SEO sitemap entries & chunked 10,000-URL prioritized endpoints (24h RAM + 7d CDN cache).

Designed to minimize Neon PostgreSQL wakeups:
  - Prioritizes the top 10,000 highest-value URLs:
      1. All cross-store matched products (~8,080 unique canonical matches, cheapest in-stock representative).
      2. Top ~2,000 high-demand electronics/home_appliances & verified-discount SKUs.
  - Caches the entire 10,000-URL list in `sitemap_cache` for 24 hours so all sitemap chunks
    and repeat Googlebot fetches execute ZERO Neon queries.
  - Emits 7-day Cloudflare CDN headers (`s-maxage=604800, stale-while-revalidate=604800`).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Query, Response
from pydantic import BaseModel
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

SITEMAP_CDN_MAX_AGE = 604800  # 7 days on Cloudflare edge
SITEMAP_CDN_SWR = 604800  # 7 days stale-while-revalidate
SITEMAP_RAM_TTL = 86400.0  # 24 hours in Railway FastAPI memory

MAX_SITEMAP_PRODUCTS = 250000
SITEMAP_CHUNK_SIZE = 25000
MAX_SITEMAP_CHUNKS = MAX_SITEMAP_PRODUCTS // SITEMAP_CHUNK_SIZE  # 10 chunks x 25,000 = 250,000


class SitemapChunkResponse(BaseModel):
    chunk_id: int
    chunk_size: int
    total_chunks: int
    total_products: int
    last_updated: datetime
    products: list[SitemapProductEntry]


PRIORITIZED_PRODUCTS_SQL = text(
    """
    WITH matched_ranked AS (
        SELECT
            v.product_sk,
            COALESCE(v.canonical_product_key, v.product_sk) AS product_key,
            v.category,
            v.store_name,
            v.last_updated_at,
            0 AS priority_tier,
            m.stores_count,
            m.price_spread_pct,
            ROW_NUMBER() OVER (
                PARTITION BY v.canonical_product_key
                ORDER BY v.in_stock DESC, v.current_price ASC, v.product_sk ASC
            ) AS canon_rn
        FROM gold.mart_product_verdicts v
        INNER JOIN gold.mart_cross_store_matches m
            ON v.canonical_product_key = m.canonical_product_key
    ),
    matched_top AS (
        SELECT
            product_sk,
            product_key,
            category,
            store_name,
            last_updated_at,
            priority_tier,
            stores_count,
            price_spread_pct
        FROM matched_ranked
        WHERE canon_rn = 1
    ),
    secondary_top AS (
        SELECT
            v.product_sk,
            COALESCE(v.canonical_product_key, v.product_sk) AS product_key,
            v.category,
            v.store_name,
            v.last_updated_at,
            CASE
                WHEN v.discount_verdict IN ('ALL_TIME_LOW', 'GENUINE_DEAL', 'FAKE_DISCOUNT', 'PRESALE_HIKE')
                     AND v.category IN ('electronics', 'home_appliances') THEN 1
                WHEN v.discount_verdict IN ('ALL_TIME_LOW', 'GENUINE_DEAL', 'FAKE_DISCOUNT', 'PRESALE_HIKE') THEN 2
                WHEN v.category IN ('electronics', 'home_appliances') THEN 3
                ELSE 4
            END AS priority_tier,
            1 AS stores_count,
            COALESCE(v.real_discount_pct, 0)::NUMERIC AS price_spread_pct
        FROM gold.mart_product_verdicts v
        WHERE v.in_stock = TRUE
          AND COALESCE(v.is_primary_variant, TRUE) = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM matched_top mt WHERE mt.product_sk = v.product_sk
          )
        ORDER BY
            priority_tier ASC,
            v.last_updated_at DESC,
            v.product_sk ASC
        LIMIT :secondary_limit
    ),
    combined AS (
        SELECT * FROM matched_top
        UNION ALL
        SELECT * FROM secondary_top
    )
    SELECT
        product_sk,
        product_key,
        category,
        store_name,
        last_updated_at
    FROM combined
    ORDER BY
        priority_tier ASC,
        stores_count DESC,
        price_spread_pct DESC,
        last_updated_at DESC,
        product_sk ASC
    LIMIT :limit
    """
)

COMPARISONS_SQL = text(
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


def _load_top_sitemap_products(db: Connection, max_limit: int = MAX_SITEMAP_PRODUCTS) -> tuple[list[SitemapProductEntry], datetime]:
    """Load and cache the top 10,000 prioritized sitemap products for 24h in RAM."""
    cache_key = f"seo:top_products:v2:{max_limit}"
    cached = sitemap_cache.get(cache_key)
    if cached is not None:
        return cached

    prod_rows = db.execute(
        PRIORITIZED_PRODUCTS_SQL,
        {"limit": max_limit, "secondary_limit": min(max_limit, 4000)},
    ).mappings().all()

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
    timestamps = [r["last_updated_at"] for r in prod_rows if r.get("last_updated_at") is not None]
    last_updated = max(timestamps) if timestamps else datetime.now(timezone.utc)

    payload = (products, last_updated)
    sitemap_cache.set(cache_key, payload, ttl=SITEMAP_RAM_TTL)
    return payload


@router.get("/api/seo/sitemap-entries", response_model=SitemapEntriesResponse)
@router.get("/api/v1/seo/sitemap-entries", response_model=SitemapEntriesResponse, include_in_schema=True)
def get_sitemap_entries(
    response: Response,
    limit: int = Query(default=2000, ge=1, le=MAX_SITEMAP_PRODUCTS),
    db: Connection = Depends(get_db),
) -> SitemapEntriesResponse:
    set_cache_headers(response, s_maxage=SITEMAP_CDN_MAX_AGE, stale_while_revalidate=SITEMAP_CDN_SWR)
    cache_key = f"seo:sitemap:v2:{limit}"
    cached = sitemap_cache.get(cache_key)
    if cached is not None:
        return cached

    all_products, last_updated = _load_top_sitemap_products(db, MAX_SITEMAP_PRODUCTS)
    products = all_products[:limit]

    comp_limit = min(limit, 2000)
    comp_rows = db.execute(COMPARISONS_SQL, {"comp_limit": comp_limit}).mappings().all()
    comparisons = [
        SitemapComparisonEntry(
            canonical_product_key=str(r["canonical_product_key"]),
            category=str(r["category"]),
            stores_count=int(r["stores_count"]),
        )
        for r in comp_rows
    ]

    result = SitemapEntriesResponse(
        last_updated=last_updated,
        products=products,
        comparisons=comparisons,
    )
    sitemap_cache.set(cache_key, result, ttl=SITEMAP_RAM_TTL)
    return result


@router.get("/api/seo/sitemap-chunk/{chunk_id}", response_model=SitemapChunkResponse)
@router.get("/api/v1/seo/sitemap-chunk/{chunk_id}", response_model=SitemapChunkResponse, include_in_schema=True)
def get_sitemap_chunk(
    response: Response,
    chunk_id: int = ApiPath(..., ge=1, le=MAX_SITEMAP_CHUNKS),
    db: Connection = Depends(get_db),
) -> SitemapChunkResponse:
    """Serve chunk 1..4 (2,500 URLs each = 10,000 total) from a single 24h RAM cache."""
    set_cache_headers(response, s_maxage=SITEMAP_CDN_MAX_AGE, stale_while_revalidate=SITEMAP_CDN_SWR)
    if chunk_id < 1 or chunk_id > MAX_SITEMAP_CHUNKS:
        raise HTTPException(status_code=404, detail="Sitemap chunk out of range")

    all_products, last_updated = _load_top_sitemap_products(db, MAX_SITEMAP_PRODUCTS)
    total_products = len(all_products)
    total_chunks = max(1, min(MAX_SITEMAP_CHUNKS, math.ceil(total_products / SITEMAP_CHUNK_SIZE)))
    start = (chunk_id - 1) * SITEMAP_CHUNK_SIZE
    end = start + SITEMAP_CHUNK_SIZE
    slice_items = all_products[start:end]

    return SitemapChunkResponse(
        chunk_id=chunk_id,
        chunk_size=SITEMAP_CHUNK_SIZE,
        total_chunks=total_chunks,
        total_products=total_products,
        last_updated=last_updated,
        products=slice_items,
    )
