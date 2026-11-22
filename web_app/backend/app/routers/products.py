"""Product search, direct link checker, and product detail + history + alternatives."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.bilingual import expand_search_query, normalize_arabic
from app.cache import api_cache, set_cache_headers
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
_JUMIA_SKU_RE = re.compile(r"-(\d{5,15})\.html$", re.I)


def _parse_url_parts(raw_url: str) -> dict[str, Optional[str]]:
    """Parse and normalize a pasted URL while stripping ad/analytics tracking params.

    Preserves meaningful query params (e.g. Sigma `id`, B.TECH `offering_id`,
    `q`, `s`, `k`, `ref`) while stripping `utm_*`, `fbclid`, `gclid`, etc.
    Also extracts deterministic store identifiers for Noon (`/SKU/p/`),
    Amazon Egypt (`/dp/ASIN`), and Jumia Egypt (`-<SKU>.html`).
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
            "jumia_sku": None,
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

    jumia_sku = None
    if netloc == "jumia.com.eg":
        if m := _JUMIA_SKU_RE.search(path):
            jumia_sku = m.group(1).lower()

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
        "jumia_sku": jumia_sku,
    }


@router.get("/search", response_model=SearchResponse)
def search_products(
    response: Response,
    q: Optional[str] = Query(default=None),
    url: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    db: Connection = Depends(get_db),
) -> SearchResponse:
    set_cache_headers(response, s_maxage=300, stale_while_revalidate=600)
    cache_key = f"products:search:{(q or '').strip().lower()}:{(url or '').strip().lower()}:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached
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
        jumia_sku = parts["jumia_sku"]

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

        # Deterministic fallback 5: Jumia Egypt trailing numeric SKU `-<SKU>.html`
        if not rows and jumia_sku:
            jumia_pattern = rf"-{re.escape(jumia_sku)}\.html(\?|$)"
            jumia_sql = text(
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
                ) = 'jumia.com.eg'
                  AND LOWER(product_url) ~ :jumia_pattern
                ORDER BY product_sk ASC
                LIMIT :limit
                """
            )
            rows = (
                db.execute(jumia_sql, {"jumia_pattern": jumia_pattern, "limit": limit})
                .mappings()
                .all()
            )

        # Deterministic fallback 6: `(host, ref)` when `ref` query param is present
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
            res = SearchResponse(match_type="url_exact", items=items, total=len(items))
            api_cache.set(cache_key, res, ttl=300.0)
            return res

        if not (q and q.strip()):
            res = SearchResponse(match_type="url_not_found", items=[], total=0)
            api_cache.set(cache_key, res, ttl=120.0)
            return res

    # 2. Bilingual AR <-> EN search on normalized title, brand, sub_category & canonical key
    #    with multi-term AND matching + graceful pg_trgm typo-tolerant fallback.
    query_str = (q or "").strip()
    if not query_str:
        return SearchResponse(match_type="none", items=[], total=0)

    variants = expand_search_query(query_str)
    norm_q = normalize_arabic(query_str).lower()
    prefix_pattern = f"{norm_q}%"

    haystack_expr = (
        "TRANSLATE("
        "LOWER(COALESCE(product_title, '') || ' ' || COALESCE(brand, '') || ' ' || "
        "REPLACE(COALESCE(sub_category, ''), '_', ' ') || ' ' || COALESCE(canonical_product_key, '')), "
        "'أإآٱةىؤئ٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', "
        "'ااااهيوي01234567890123456789'"
        ")"
    )

    or_clauses: list[str] = []
    params: dict[str, object] = {"prefix": prefix_pattern, "limit": limit}

    for idx, variant in enumerate(variants):
        v_key = f"var_{idx}"
        or_clauses.append(f"{haystack_expr} LIKE :{v_key}")
        params[v_key] = f"%{variant}%"

        # Multi-word AND clause so e.g. "تلاجة سامسونج" -> "refrigerator samsung" matches
        # "Samsung 450L No Frost Refrigerator" regardless of word order.
        tokens = [tok for tok in variant.split() if len(tok) >= 2]
        if len(tokens) >= 2:
            and_parts: list[str] = []
            for t_idx, tok in enumerate(tokens[:6]):
                t_key = f"v{idx}_t{t_idx}"
                and_parts.append(f"{haystack_expr} LIKE :{t_key}")
                params[t_key] = f"%{tok}%"
            or_clauses.append(f"({' AND '.join(and_parts)})")

    where_clause = " OR ".join(or_clauses)
    count_sql = text(
        f"""
        SELECT COUNT(*)::INTEGER
        FROM gold.mart_product_verdicts
        WHERE {where_clause}
        """
    )
    total = int(db.execute(count_sql, params).scalar_one())

    search_sql = text(
        f"""
        SELECT {PRODUCT_SELECT_COLS}
        FROM gold.mart_product_verdicts
        WHERE {where_clause}
        ORDER BY
            CASE
                WHEN LOWER(brand) LIKE :prefix THEN 0
                WHEN LOWER(product_title) LIKE :prefix THEN 1
                ELSE 2
            END ASC,
            real_discount_pct DESC,
            product_sk ASC
        LIMIT :limit
        """
    )
    rows = db.execute(search_sql, params).mappings().all()

    # Typo-tolerant pg_trgm fallback when exact/bilingual LIKE returns 0 hits
    match_type = "text_search"
    if not rows and len(norm_q) >= 3:
        primary_trgm = variants[1] if len(variants) > 1 else norm_q
        trgm_sql = text(
            f"""
            SELECT {PRODUCT_SELECT_COLS}
            FROM gold.mart_product_verdicts
            WHERE similarity({haystack_expr}, :trgm_q) >= 0.22
               OR similarity(LOWER(product_title), :trgm_q) >= 0.22
            ORDER BY
                GREATEST(
                    similarity({haystack_expr}, :trgm_q),
                    similarity(LOWER(product_title), :trgm_q)
                ) DESC,
                real_discount_pct DESC,
                product_sk ASC
            LIMIT :limit
            """
        )
        try:
            rows = (
                db.execute(trgm_sql, {"trgm_q": primary_trgm, "limit": limit})
                .mappings()
                .all()
            )
            if rows:
                total = len(rows)
                match_type = "fuzzy_trgm"
        except Exception:
            # pg_trgm extension not yet installed on this DB — stay graceful
            try:
                db.rollback()
            except Exception:
                pass

    items = [ProductVerdictItem.model_validate(dict(r)) for r in rows]
    res = SearchResponse(match_type=match_type, items=items, total=total)
    api_cache.set(cache_key, res, ttl=300.0)
    return res


@router.get("/{product_sk}", response_model=ProductDetailResponse)
def get_product_detail(
    product_sk: str,
    response: Response,
    db: Connection = Depends(get_db),
) -> ProductDetailResponse:
    set_cache_headers(response, s_maxage=300, stale_while_revalidate=600)
    cache_key = f"products:detail:{product_sk}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached
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

    res = ProductDetailResponse(
        product=product,
        history=history,
        alternatives=alternatives,
    )
    api_cache.set(cache_key, res, ttl=300.0)
    return res
