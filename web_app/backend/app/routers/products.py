"""Product search, direct link checker, and product detail + history + alternatives."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse

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


TRACKING_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "gbraid",
        "wbraid",
        "dclid",
        "msclkid",
        "yclid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ttclid",
        "si",
        "_ga",
        "_gl",
        "srsltid",
        "gad_source",
        "gad_campaignid",
        "trk",
        "spm",
        "scid",
    }
)


def _is_tracking_param(name: str) -> bool:
    low = name.strip().lower()
    return low.startswith("utm_") or low in TRACKING_QUERY_PARAMS


_NOON_SKU_RE = re.compile(r"/([a-z0-9_-]+)/p(?:/|$)", re.I)
_AMAZON_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([a-z0-9]{10})(?:/|$)", re.I)


def _parse_url_parts(raw_url: str) -> dict[str, Optional[str]]:
    """Parse and normalize a pasted URL while stripping ad/analytics tracking params.

    Preserves meaningful query params (e.g. Sigma `id`, B.TECH `offering_id`,
    `q`, `s`, `k`, `ref`) while stripping `utm_*`, `fbclid`, `gclid`, etc.
    Also extracts deterministic store identifiers for Noon (`/SKU/p/`) and
    Amazon Egypt (`/dp/ASIN`).
    """
    cleaned = raw_url.strip()
    if not cleaned:
        return {
            "full_key": "",
            "host": "",
            "path": "",
            "ref": None,
            "sigma_id": None,
            "btech_slug": None,
            "offering_id": None,
            "noon_sku": None,
            "amazon_asin": None,
        }
    if not cleaned.lower().startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")

    kept_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not _is_tracking_param(k)
    ]
    clean_query = urlencode(kept_pairs, doseq=True)
    full_key = f"{netloc}{path}?{clean_query}".lower() if clean_query else f"{netloc}{path}".lower()

    params_ci = {k.lower(): v.strip().lower() for k, v in kept_pairs if v.strip()}
    ref_param = params_ci.get("ref")
    sigma_id = params_ci.get("id") if (netloc == "sigma-computer.com" and path.lower() == "/en/item") else None
    offering_id = params_ci.get("offering_id") if netloc == "btech.com" else None
    btech_slug = None
    if netloc == "btech.com" and path.lower().startswith("/en/p/") and len(path) > len("/en/p/"):
        btech_slug = path.lower()

    noon_sku = None
    if netloc == "noon.com":
        if m := _NOON_SKU_RE.search(path):
            noon_sku = m.group(1).lower()

    amazon_asin = None
    if netloc == "amazon.eg":
        if m := _AMAZON_ASIN_RE.search(path):
            amazon_asin = m.group(1).lower()

    return {
        "full_key": full_key,
        "host": netloc,
        "path": path.lower(),
        "ref": ref_param,
        "sigma_id": sigma_id,
        "btech_slug": btech_slug,
        "offering_id": offering_id,
        "noon_sku": noon_sku,
        "amazon_asin": amazon_asin,
    }


@router.get("/search", response_model=SearchResponse)
def search_products(
    q: Optional[str] = Query(default=None),
    url: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    db: Connection = Depends(get_db),
) -> SearchResponse:
    # 1. If url is provided, match deterministically (exact normalized URL after
    #    stripping tracking params first, then deterministic store-specific key
    #    matching; never loose path-only fallback on search pages).
    if url is not None and url.strip():
        parts = _parse_url_parts(url)
        exact_key = parts["full_key"] or ""
        netloc = parts["host"] or ""
        ref_param = parts["ref"]
        sigma_id = parts["sigma_id"]
        btech_slug = parts["btech_slug"]
        noon_sku = parts["noon_sku"]
        amazon_asin = parts["amazon_asin"]

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

        # Deterministic fallback 1: Sigma `/en/item?id=<slug>` (handles query reordering)
        if not rows and sigma_id:
            id_pattern = rf"(^|[?&])id={re.escape(sigma_id)}(&|$)"
            sigma_sql = text(
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
                ) = 'sigma-computer.com'
                  AND LOWER(product_url) ~ :id_pattern
                ORDER BY product_sk ASC
                LIMIT :limit
                """
            )
            rows = (
                db.execute(sigma_sql, {"id_pattern": id_pattern, "limit": limit})
                .mappings()
                .all()
            )

        # Deterministic fallback 2: B.TECH product page `/en/p/<slug>` (when offering_id omitted/changed)
        if not rows and btech_slug:
            btech_path_key = f"btech.com{btech_slug}"
            btech_sql = text(
                f"""
                SELECT {PRODUCT_SELECT_COLS}
                FROM gold.mart_product_verdicts
                WHERE LOWER(
                    REGEXP_REPLACE(
                        RTRIM(SPLIT_PART(product_url, '?', 1), '/'),
                        '^https?://(www\\.)?',
                        '',
                        'i'
                    )
                ) = :btech_path_key
                ORDER BY product_sk ASC
                LIMIT :limit
                """
            )
            rows = (
                db.execute(btech_sql, {"btech_path_key": btech_path_key, "limit": limit})
                .mappings()
                .all()
            )

        # Deterministic fallback 3: Noon Egypt `/{SKU}/p/` (ignores locale/slug/query differences)
        if not rows and noon_sku:
            noon_pattern = rf"/{re.escape(noon_sku)}/p(/|\?|$)"
            noon_sql = text(
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
                ) = 'noon.com'
                  AND LOWER(product_url) ~ :noon_pattern
                ORDER BY product_sk ASC
                LIMIT :limit
                """
            )
            rows = (
                db.execute(noon_sql, {"noon_pattern": noon_pattern, "limit": limit})
                .mappings()
                .all()
            )

        # Deterministic fallback 4: Amazon Egypt `/dp/{ASIN}` (ignores locale slug & tracking params)
        if not rows and amazon_asin:
            asin_pattern = rf"/(dp|gp/product)/{re.escape(amazon_asin)}(/|\?|$)"
            amz_sql = text(
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
                ) = 'amazon.eg'
                  AND LOWER(product_url) ~ :asin_pattern
                ORDER BY product_sk ASC
                LIMIT :limit
                """
            )
            rows = (
                db.execute(amz_sql, {"asin_pattern": asin_pattern, "limit": limit})
                .mappings()
                .all()
            )

        # Deterministic fallback 5: `(host, ref)` when `ref` query param is present
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
