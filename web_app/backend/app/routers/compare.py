"""Cross-store arbitrage comparison endpoint querying gold.mart_cross_store_matches."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cache import api_cache, set_cache_headers
from app.coupons_service import coupon_store
from app.database import get_db
from app.schemas import AlternativeListing, CategoryFilter, CompareResponse, CrossStoreMatchItem

router = APIRouter(tags=["compare"])


def _attach_coupons_to_compare(result: CompareResponse) -> CompareResponse:
    """Attach in-memory matching coupons to every offer in compare rows (zero Neon queries)."""
    enriched_items: list[CrossStoreMatchItem] = []
    for item in result.items:
        enriched_listings: list[AlternativeListing] = []
        for offer in item.listings_json:
            coupons, est = coupon_store.match_for_offer(
                store_id=offer.store_name,
                price=offer.price,
                category=item.category,
            )
            enriched_listings.append(
                offer.model_copy(
                    update={
                        "applicable_coupons": coupons,
                        "estimated_price_after_coupon": est,
                    }
                )
            )
        enriched_items.append(item.model_copy(update={"listings_json": enriched_listings}))
    return result.model_copy(update={"items": enriched_items})


@router.get("/api/v1/compare", response_model=CompareResponse)
@router.get("/api/compare", response_model=CompareResponse, include_in_schema=True)
def get_cross_store_comparison(
    response: Response,
    category: CategoryFilter = Query(default="all"),
    min_spread_pct: float = Query(default=0.0, ge=0.0),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Connection = Depends(get_db),
) -> CompareResponse:
    set_cache_headers(response, s_maxage=600, stale_while_revalidate=300)
    cache_key = f"compare:{category}:{min_spread_pct:.2f}:{page}:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return _attach_coupons_to_compare(cached)

    conditions: list[str] = ["price_spread_pct >= :min_spread_pct"]
    params: dict[str, object] = {"min_spread_pct": min_spread_pct}

    if category != "all":
        conditions.append("category = :category")
        params["category"] = category

    where_clause = f"WHERE {' AND '.join(conditions)}"

    count_sql = text(
        f"SELECT COUNT(*)::INTEGER FROM gold.mart_cross_store_matches {where_clause}"
    )
    total = int(db.execute(count_sql, params).scalar_one())

    offset = (page - 1) * limit
    query_params = {**params, "limit": limit, "offset": offset}
    items_sql = text(
        f"""
        SELECT
            canonical_product_key,
            product_title_clean,
            category,
            brand,
            stores_count,
            lowest_price,
            lowest_price_store,
            highest_price,
            price_spread_egp,
            price_spread_pct,
            listings_json
        FROM gold.mart_cross_store_matches
        {where_clause}
        ORDER BY price_spread_pct DESC, canonical_product_key ASC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = db.execute(items_sql, query_params).mappings().all()
    items = [CrossStoreMatchItem.model_validate(dict(r)) for r in rows]

    # Hydrate representative product image_url in a single batch lookup so compare
    # cards display real product photos without extra frontend round-trips.
    all_sks = [
        listing.product_sk
        for item in items
        for listing in item.listings_json
        if listing.product_sk
    ]
    if all_sks:
        img_rows = db.execute(
            text(
                """
                SELECT product_sk, image_url
                FROM gold.mart_product_verdicts
                WHERE product_sk = ANY(:sks)
                  AND image_url IS NOT NULL
                  AND BTRIM(image_url) <> ''
                """
            ),
            {"sks": list(dict.fromkeys(all_sks))},
        ).mappings().all()
        image_by_sk = {
            str(r["product_sk"]): str(r["image_url"]).strip()
            for r in img_rows
            if r.get("image_url")
        }
        for item in items:
            # Prefer in-stock lowest-priced listing's image, then fall back to any matched listing
            ranked = sorted(
                item.listings_json,
                key=lambda offer: (not offer.in_stock, offer.price),
            )
            for offer in ranked:
                img = image_by_sk.get(offer.product_sk)
                if img:
                    item.image_url = img
                    break

    result = CompareResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )
    api_cache.set(cache_key, result, ttl=300.0)
    return _attach_coupons_to_compare(result)
