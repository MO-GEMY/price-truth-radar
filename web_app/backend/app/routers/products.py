"""Product search, direct link checker, and product detail + history + alternatives."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app.routers.radar import PRODUCT_SELECT_COLS
from app.schemas import (
    AlternativeListing,
    PriceHistoryPoint,
    ProductDetailResponse,
    ProductVerdictItem,
    SearchResponse,
)

router = APIRouter(prefix="/api/v1/products", tags=["products"])


def _parse_url_parts(raw_url: str) -> tuple[str, str, Optional[str]]:
    """Return (normalized_full_key, normalized_host, ref_param).

    Normalizes scheme, strips optional `www.` prefix, strips trailing `/`
    before `?` or end-of-path, drops `#fragment`, and preserves query params.
    """
    cleaned = raw_url.strip()
    if not cleaned:
        return "", "", None
    if not cleaned.lower().startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    query = parsed.query
    full_key = f"{netloc}{path}?{query}".lower() if query else f"{netloc}{path}".lower()
    ref_values = parse_qs(query, keep_blank_values=False).get("ref")
    ref_param = ref_values[0].strip().lower() if ref_values and ref_values[0].strip() else None
    return full_key, netloc, ref_param


@router.get("/search", response_model=SearchResponse)
def search_products(
    q: Optional[str] = Query(default=None),
    url: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    db: Connection = Depends(get_db),
) -> SearchResponse:
    # 1. If url is provided, match deterministically (exact normalized URL first,
    #    then optional deterministic (host + ref) match; never loose path-only fallback).
    if url is not None and url.strip():
        exact_key, netloc, ref_param = _parse_url_parts(url)

        exact_sql = text(
            f"""
            SELECT {PRODUCT_SELECT_COLS}
            FROM gold.mart_product_verdicts
            WHERE LOWER(
                REGEXP_REPLACE(
                    RTRIM(REPLACE(product_url, '/?', '?'), '/'),
                    '^https?://(www\\.)?',
                    '',
                    'i'
                )
            ) = :exact_key
            ORDER BY product_sk ASC
            LIMIT :limit
            """
        )
        rows = (
            db.execute(
                exact_sql,
                {
                    "exact_key": exact_key,
                    "limit": limit,
                },
            )
            .mappings()
            .all()
        )
        if not rows and netloc and ref_param:
            ref_pattern = rf"(^|[?&])ref={re.escape(ref_param)}(&|$)"
            ref_sql = text(
                f"""
                SELECT {PRODUCT_SELECT_COLS}
                FROM gold.mart_product_verdicts
                WHERE SPLIT_PART(
                    SPLIT_PART(
                        REGEXP_REPLACE(LOWER(product_url), '^https?://(www\\.)?', ''),
                        '?',
                        1
                    ),
                    '/',
                    1
                ) = :netloc
                  AND LOWER(product_url) ~ :ref_pattern
                ORDER BY product_sk ASC
                LIMIT :limit
                """
            )
            rows = (
                db.execute(
                    ref_sql,
                    {
                        "netloc": netloc,
                        "ref_pattern": ref_pattern,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
        if rows:
            items = [ProductVerdictItem.model_validate(dict(r)) for r in rows]
            return SearchResponse(match_type="url_exact", items=items, total=len(items))

        if not (q and q.strip()):
            return SearchResponse(match_type="url_not_found", items=[], total=0)

    # 2. Case-insensitive search on product_title and brand (plus store / canonical key)
    query_str = (q or "").strip()
    if not query_str:
        return SearchResponse(match_type="none", items=[], total=0)

    like_pattern = f"%{query_str}%"
    prefix_pattern = f"{query_str}%"

    count_sql = text(
        """
        SELECT COUNT(*)::INTEGER
        FROM gold.mart_product_verdicts
        WHERE product_title ILIKE :pattern
           OR brand ILIKE :pattern
        """
    )
    total = int(db.execute(count_sql, {"pattern": like_pattern}).scalar_one())

    search_sql = text(
        f"""
        SELECT {PRODUCT_SELECT_COLS}
        FROM gold.mart_product_verdicts
        WHERE product_title ILIKE :pattern
           OR brand ILIKE :pattern
        ORDER BY
            CASE
                WHEN brand ILIKE :prefix THEN 0
                WHEN product_title ILIKE :prefix THEN 1
                ELSE 2
            END ASC,
            real_discount_pct DESC,
            product_sk ASC
        LIMIT :limit
        """
    )
    rows = (
        db.execute(
            search_sql,
            {"pattern": like_pattern, "prefix": prefix_pattern, "limit": limit},
        )
        .mappings()
        .all()
    )
    items = [ProductVerdictItem.model_validate(dict(r)) for r in rows]
    return SearchResponse(match_type="text_search", items=items, total=total)


@router.get("/{product_sk}", response_model=ProductDetailResponse)
def get_product_detail(
    product_sk: str,
    db: Connection = Depends(get_db),
) -> ProductDetailResponse:
    product_sql = text(
        f"""
        SELECT {PRODUCT_SELECT_COLS}
        FROM gold.mart_product_verdicts
        WHERE product_sk = :product_sk
        LIMIT 1
        """
    )
    product_row = db.execute(product_sql, {"product_sk": product_sk}).mappings().first()
    if product_row is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product = ProductVerdictItem.model_validate(dict(product_row))

    history_sql = text(
        """
        SELECT
            snapshot_date,
            price,
            claimed_original_price,
            rolling_60d_median,
            in_stock,
            available_sizes_count
        FROM gold.fct_price_history
        WHERE product_sk = :product_sk
        ORDER BY snapshot_date ASC
        """
    )
    history_rows = db.execute(history_sql, {"product_sk": product_sk}).mappings().all()
    history = [PriceHistoryPoint.model_validate(dict(r)) for r in history_rows]

    alternatives: list[AlternativeListing] = []
    if product.canonical_product_key:
        alt_sql = text(
            """
            SELECT listings_json
            FROM gold.mart_cross_store_matches
            WHERE canonical_product_key = :canonical_key
            LIMIT 1
            """
        )
        alt_row = (
            db.execute(alt_sql, {"canonical_key": product.canonical_product_key})
            .mappings()
            .first()
        )
        if alt_row and alt_row["listings_json"]:
            for entry in alt_row["listings_json"]:
                if entry.get("product_sk") != product_sk:
                    alternatives.append(AlternativeListing.model_validate(entry))

    return ProductDetailResponse(
        product=product,
        history=history,
        alternatives=alternatives,
    )
