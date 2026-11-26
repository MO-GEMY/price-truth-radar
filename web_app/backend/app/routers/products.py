"""Product search, direct link checker, and product detail + history + alternatives."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cache import api_cache, product_detail_cache, search_cache, set_cache_headers
from app.catalog_search import build_catalog_query, search_catalog
from app.coupons_service import coupon_store
from app.database import get_db
from app.routers.radar import (
    PRODUCT_SELECT_COLS,
    attach_market_benchmarks,
    compute_market_benchmark,
)
from app.schemas import (
    AlternativeListing,
    CategoryFilter,
    MarketBenchmark,
    PriceHistoryPoint,
    ProductDetailResponse,
    ProductPriceSnapshot,
    ProductPricesBatchResponse,
    ProductVariantItem,
    ProductVerdictItem,
    SearchResponse,
    SimilarAlternativeItem,
)
from app.similar_alternatives import find_similar_alternatives
from app.subcategories import build_subcategory_sql_filter, normalize_subcategory_slug

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

# Known domain -> store_name map so URL lookups narrow via `idx_mart_verdicts_store_name`
# instead of scanning all 100k+ rows with REGEXP_REPLACE.
_HOST_TO_STORE: dict[str, str] = {
    "amazon.eg": "amazon_eg",
    "noon.com": "noon",
    "btech.com": "btech",
    "2b.com.eg": "2b",
    "sigma-computer.com": "sigma",
    "dream2000.com": "dream2000",
    "rayashop.com": "rayashop",
    "raneen.com": "raneen",
    "elarabygroup.com": "elaraby",
    "tradelineegypt.com": "tradeline",
    "tradelinestores.com": "tradeline",
    "jumia.com.eg": "jumia_eg",
    "seoudisupermarket.com": "seoudi",
    "spinneys-egypt.com": "spinneys",
    "gourmetegypt.com": "gourmet",
    "hyperone.com.eg": "hyperone",
    "metro-markets.com": "metro_market",
    "compumarts.com": "compumarts",
    "elbadrgroupeg.store": "elbadr",
    "egyptlaptop.com": "egyptlaptop",
    "cairosales.com": "cairosales",
    "ehabcenter.com": "ehab_center",
    "kimostore.net": "kimostore",
    "kabbanifurniture.com": "kabbani",
    "ariika.com": "ariika",
    "chichomz.com": "chichomz",
    "happet.net": "happet",
    "sourcebeauty.com": "source_beauty",
    "bloompharmacy.com": "bloom_pharmacy",
}


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
    category: Optional[CategoryFilter] = Query(default=None),
    subcategory: Optional[str] = Query(default=None),
    store: Optional[str] = Query(default=None),
    brand: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    db: Connection = Depends(get_db),
) -> SearchResponse:
    set_cache_headers(response, s_maxage=3600, stale_while_revalidate=86400)
    norm_cat = category if (category and category != "all") else ""
    norm_sub = normalize_subcategory_slug(subcategory)
    norm_store = store.strip().lower() if (store and store.strip()) else ""
    norm_brand = brand.strip().lower() if (brand and brand.strip()) else ""
    cache_key = (
        f"products:search:v5:{(q or '').strip().lower()}:{(url or '').strip().lower()}:"
        f"{norm_cat}:{norm_sub}:{norm_store}:{norm_brand}:{limit}"
    )
    cached = search_cache.get(cache_key)
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

        inferred_store = _HOST_TO_STORE.get(netloc)
        store_scope_sql = "store_name = :inferred_store AND " if inferred_store else ""
        exact_params: dict[str, object] = {"exact_key": exact_key, "limit": limit}
        if inferred_store:
            exact_params["inferred_store"] = inferred_store

        exact_sql = text(
            f"""
            SELECT {PRODUCT_SELECT_COLS}
            FROM gold.mart_product_verdicts
            WHERE {store_scope_sql}LOWER(
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
        rows = db.execute(exact_sql, exact_params).mappings().all()

        # Deterministic fallback 1: Sigma `/en/item?id=<slug>` (handles query reordering)
        if not rows and sigma_id:
            id_pattern = rf"(^|[?&])id={re.escape(sigma_id)}(&|$)"
            sigma_sql = text(
                f"""
                SELECT {PRODUCT_SELECT_COLS}
                FROM gold.mart_product_verdicts
                WHERE store_name = 'sigma'
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
                WHERE store_name = 'btech'
                  AND LOWER(
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
                WHERE store_name = 'noon'
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
                WHERE store_name = 'amazon_eg'
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
                WHERE store_name = 'jumia_eg'
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
            ref_params: dict[str, object] = {
                "netloc": netloc,
                "ref_pattern": ref_pattern,
                "limit": limit,
            }
            if inferred_store:
                ref_params["inferred_store"] = inferred_store
            ref_sql = text(
                f"""
                SELECT {PRODUCT_SELECT_COLS}
                FROM gold.mart_product_verdicts
                WHERE {store_scope_sql}SPLIT_PART(
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
            rows = db.execute(ref_sql, ref_params).mappings().all()
        if rows:
            items = attach_market_benchmarks(db, [ProductVerdictItem.model_validate(dict(r)) for r in rows])
            res = SearchResponse(match_type="url_exact", items=items, total=len(items))
            search_cache.set(cache_key, res, ttl=3600.0)
            return res

        if not (q and q.strip()):
            res = SearchResponse(match_type="url_not_found", items=[], total=0)
            search_cache.set(cache_key, res, ttl=300.0)
            return res

    query = build_catalog_query(q or "", db=db)
    if not query.terms:
        return SearchResponse(match_type="none", items=[], total=0)

    filter_clauses: list[str] = []
    filter_params: dict[str, object] = {}
    if norm_cat:
        filter_clauses.append("p.category = :search_cat")
        filter_params["search_cat"] = norm_cat
    if norm_sub:
        sub_pred, sub_params = build_subcategory_sql_filter(
            norm_cat or "all",
            norm_sub,
            alias="p",
            param_prefix="ssub",
        )
        if sub_pred:
            filter_clauses.append(sub_pred)
            filter_params.update(sub_params)
    if norm_store:
        filter_clauses.append("p.store_name = :search_store")
        filter_params["search_store"] = norm_store
    if norm_brand:
        filter_clauses.append("LOWER(TRIM(COALESCE(p.brand, ''))) = :search_brand")
        filter_params["search_brand"] = norm_brand

    rows, total, match_type = search_catalog(
        db,
        query,
        limit,
        filters_sql=" AND ".join(filter_clauses),
        filters_params=filter_params,
    )
    items = attach_market_benchmarks(db, [ProductVerdictItem.model_validate(row) for row in rows])
    res = SearchResponse(match_type=match_type, items=items, total=total)
    search_cache.set(cache_key, res, ttl=3600.0)
    return res


def _attach_coupons_to_detail(detail: ProductDetailResponse) -> ProductDetailResponse:
    """Attach in-memory matching coupons to product & alternatives (zero Neon queries)."""
    prod = detail.product
    prod_coupons, prod_est = coupon_store.match_for_offer(
        store_id=prod.store_name,
        price=prod.current_price,
        category=prod.category,
    )
    enriched_product = prod.model_copy(
        update={
            "applicable_coupons": prod_coupons,
            "estimated_price_after_coupon": prod_est,
        }
    )
    enriched_alts: list[AlternativeListing] = []
    for alt in detail.alternatives:
        alt_coupons, alt_est = coupon_store.match_for_offer(
            store_id=alt.store_name,
            price=alt.price,
            category=prod.category,
        )
        enriched_alts.append(
            alt.model_copy(
                update={
                    "applicable_coupons": alt_coupons,
                    "estimated_price_after_coupon": alt_est,
                }
            )
        )
    return detail.model_copy(
        update={
            "product": enriched_product,
            "alternatives": enriched_alts,
        }
    )


MAX_BATCH_PRICE_SKS = 25


@router.get("/prices", response_model=ProductPricesBatchResponse)
def get_product_prices_batch(
    response: Response,
    sks: str = Query(default="", description="Comma-separated list of up to 25 product_sk values"),
    db: Connection = Depends(get_db),
) -> ProductPricesBatchResponse:
    """Lightweight, RAM-cached batch price lookup for `/my-alerts` (1 query, zero history/alt overhead)."""
    set_cache_headers(response, s_maxage=1800, stale_while_revalidate=86400)
    raw_list = [part.strip() for part in sks.split(",") if part.strip()]
    unique_sks = list(dict.fromkeys(raw_list))
    if not unique_sks:
        return ProductPricesBatchResponse(items=[])
    if len(unique_sks) > MAX_BATCH_PRICE_SKS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_BATCH_PRICE_SKS} product_sk values may be queried per request.",
        )

    cache_key = f"products:prices:v1:{','.join(sorted(unique_sks))}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    batch_sql = text(
        """
        SELECT
            product_sk,
            current_price,
            in_stock,
            last_updated_at
        FROM gold.mart_product_verdicts
        WHERE product_sk = ANY(:sks)
        """
    )
    rows = db.execute(batch_sql, {"sks": unique_sks}).mappings().all()
    by_sk = {
        str(r["product_sk"]): ProductPriceSnapshot.model_validate(dict(r))
        for r in rows
    }
    ordered_items = [by_sk[sk] for sk in unique_sks if sk in by_sk]
    result = ProductPricesBatchResponse(items=ordered_items)
    api_cache.set(cache_key, result, ttl=3600.0)
    return result


@router.get("/{product_sk}", response_model=ProductDetailResponse)
def get_product_detail(
    product_sk: str,
    response: Response,
    db: Connection = Depends(get_db),
) -> ProductDetailResponse:
    set_cache_headers(response, s_maxage=86400, stale_while_revalidate=604800)
    cache_key = f"products:detail:v5:{product_sk}"
    cached = product_detail_cache.get(cache_key)
    if cached is not None:
        return _attach_coupons_to_detail(cached)
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
            available_sizes_count,
            tracked_days_count,
            history_maturity,
            verified_historical_median
        FROM gold.fct_price_history
        WHERE product_sk = :product_sk
        ORDER BY snapshot_date ASC
        """
    )
    history_rows = db.execute(history_sql, {"product_sk": product_sk}).mappings().all()
    history = [PriceHistoryPoint.model_validate(dict(r)) for r in history_rows]
    # For change-only deduplicated history that already has verified multi-point evidence,
    # project the latest unchanged anchor to `product.last_updated_at.date()` so charts
    # extend cleanly to the latest observation without storing flat duplicate rows.
    if (
        len(history) >= 2
        and (
            len(history) >= 3
            or abs(product.max_historical_price - product.min_historical_price) > 0.005
        )
        and product.last_updated_at is not None
    ):
        latest_obs_date = product.last_updated_at.date()
        last_pt = history[-1]
        if latest_obs_date > last_pt.snapshot_date:
            history.append(
                PriceHistoryPoint(
                    snapshot_date=latest_obs_date,
                    price=product.current_price,
                    claimed_original_price=product.claimed_original_price,
                    rolling_60d_median=product.rolling_60d_median,
                    in_stock=product.in_stock,
                    available_sizes_count=last_pt.available_sizes_count,
                    tracked_days_count=product.tracked_days_count,
                    history_maturity=product.history_maturity,
                    verified_historical_median=product.verified_historical_median,
                )
            )

    # Exact cross-store offers MUST ONLY be read from verified `gold.mart_cross_store_matches`.
    alternatives: list[AlternativeListing] = []
    market_benchmark: Optional[MarketBenchmark] = None
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
            market_benchmark = compute_market_benchmark(product, alt_row["listings_json"])
            if market_benchmark is not None:
                product = product.model_copy(update={"market_benchmark": market_benchmark})
            best_by_store: dict[str, AlternativeListing] = {}
            for entry in alt_row["listings_json"]:
                if entry.get("product_sk") == product_sk:
                    continue
                alt = AlternativeListing.model_validate(entry)
                if alt.store_name == product.store_name:
                    continue
                prev = best_by_store.get(alt.store_name)
                if prev is None or (not alt.in_stock, alt.price) < (not prev.in_stock, prev.price):
                    best_by_store[alt.store_name] = alt
            alternatives = sorted(
                best_by_store.values(),
                key=lambda a: (not a.in_stock, a.price, a.store_name),
            )

    variants: list[ProductVariantItem] = []
    if product.parent_product_key:
        if not product.has_multiple_variants and product.variant_count <= 1:
            # Skip redundant DB round-trip for single-variant products (~79% of catalog)
            variants = [
                ProductVariantItem(
                    product_sk=product.product_sk,
                    variant_label=product.variant_label,
                    title=product.product_title,
                    current_price=product.current_price,
                    claimed_original_price=product.claimed_original_price,
                    verdict=product.discount_verdict,
                    in_stock=product.in_stock,
                    product_url=product.product_url,
                )
            ]
        else:
            variants_sql = text(
                """
                SELECT
                    product_sk,
                    variant_label,
                    product_title AS title,
                    current_price,
                    claimed_original_price,
                    discount_verdict AS verdict,
                    in_stock,
                    product_url
                FROM gold.mart_product_verdicts
                WHERE parent_product_key = :parent_key
                  AND has_multiple_variants = TRUE
                ORDER BY current_price ASC, in_stock DESC, product_sk ASC
                LIMIT 50
                """
            )
            variant_rows = (
                db.execute(variants_sql, {"parent_key": product.parent_product_key})
                .mappings()
                .all()
            )
            variants = [ProductVariantItem.model_validate(dict(r)) for r in variant_rows]

    similar_alternatives: list[SimilarAlternativeItem] = find_similar_alternatives(
        db,
        product,
        max_results=6,
    )

    res = ProductDetailResponse(
        product=product,
        history=history,
        alternatives=alternatives,
        market_benchmark=market_benchmark,
        similar_alternatives=similar_alternatives,
        similar_products=similar_alternatives,
        variants=variants,
    )
    product_detail_cache.set(cache_key, res, ttl=43200.0)
    return _attach_coupons_to_detail(res)
