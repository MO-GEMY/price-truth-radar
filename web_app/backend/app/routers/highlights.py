"""Launch Radar Highlights endpoint: Biggest Scandals vs Best Real Deals."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cache import api_cache, set_cache_headers
from app.database import get_db
from app.schemas import (
    CategoryFilter,
    HighlightBasis,
    HighlightVerdict,
    HistoryMaturity,
    RadarHighlightItem,
    RadarHighlightsResponse,
)

router = APIRouter(tags=["highlights"])

_MAJOR_APPLIANCE_SUBS: frozenset[str] = frozenset(
    {
        "cookers",
        "refrigerators",
        "washing_machines",
        "air_conditioners",
        "tvs",
        "dishwashers",
        "freezers",
    }
)

_ACCESSORY_SQL_REGEX = (
    r"(\m(cover|hose|stand|remote|filter|cable|bracket|cleaner|mount|adapter|adaptor|"
    r"lnb|receiver|reciever|dish|tray|shelf|knob|thermostat|valve|gasket|pipe|cap|kit|"
    r"plug|switch|sensor|spare|part|parts|accessory|accessories|protector|stabilizer|"
    r"regulator|drain|detergent|tablet|salt|brush|base|extension|connector|splitter|"
    r"antenna|aerial|dongle|stick)\M|"
    r"غطاء|كفر|ريموت|حامل|ستاند|فلتر|كابل|سلك|خرطوم|منظف|غيار|اكسسوار|إكسسوار|محول|رسيفر|عدسة|مفتاح|صمام|رف|درج)"
)

_ACCESSORY_PY_RE = re.compile(
    r"(?:\b(?:"
    r"cover|hose|stand|remote|filter|cable|bracket|cleaner|mount|adapter|adaptor|"
    r"lnb|receiver|reciever|dish|tray|shelf|knob|thermostat|valve|gasket|pipe|cap|kit|"
    r"plug|switch|sensor|spare|part|parts|accessor(?:y|ies)|protector|stabilizer|"
    r"regulator|drain|detergent|tablet|salt|brush|base|extension|connector|splitter|"
    r"antenna|aerial|dongle|stick"
    r")\b|"
    r"غطاء|كفر|ريموت|حامل|ستاند|فلتر|كابل|سلك|خرطوم|منظف|غيار|اكسسوار|إكسسوار|محول|رسيفر|عدسة|مفتاح|صمام|رف|درج)",
    re.I,
)

_PRICE_FLOOR_SQL_GUARD = f"""
    AND current_price >= 10
    AND NOT (
        sub_category IN (
            'cookers',
            'refrigerators',
            'washing_machines',
            'air_conditioners',
            'tvs',
            'dishwashers',
            'freezers'
        )
        AND current_price < 2500
        AND product_title !~* '{_ACCESSORY_SQL_REGEX}'
    )
"""

_HIGHLIGHT_COLS = """
    v.product_sk,
    v.canonical_product_key,
    v.store_name,
    v.category,
    v.sub_category,
    v.product_title,
    v.product_url,
    v.image_url,
    v.current_price,
    v.claimed_original_price,
    v.rolling_60d_median,
    v.min_historical_price,
    v.max_historical_price,
    v.claimed_discount_pct,
    v.real_discount_pct,
    v.discount_verdict,
    v.last_updated_at,
    v.parent_product_key,
    v.variant_label,
    v.variant_count,
    v.has_multiple_variants,
    v.min_variant_price,
    v.max_variant_price,
    v.tracked_days_count,
    v.history_maturity,
    v.verified_historical_median,
    m.lowest_price AS market_cheapest_price,
    m.lowest_price_store AS market_cheapest_store,
    m.highest_price AS market_highest_price,
    COALESCE(m.stores_count, 0)::INTEGER AS market_stores_count,
    COALESCE(m.price_spread_pct, 0.0)::FLOAT AS market_spread_pct
"""

_HIGHLIGHT_OUTER_COLS = """
    product_sk,
    canonical_product_key,
    store_name,
    category,
    sub_category,
    product_title,
    product_url,
    image_url,
    current_price,
    claimed_original_price,
    rolling_60d_median,
    min_historical_price,
    max_historical_price,
    claimed_discount_pct,
    real_discount_pct,
    discount_verdict,
    last_updated_at,
    parent_product_key,
    variant_label,
    variant_count,
    has_multiple_variants,
    min_variant_price,
    max_variant_price,
    tracked_days_count,
    history_maturity,
    verified_historical_median,
    market_cheapest_price,
    market_cheapest_store,
    market_highest_price,
    market_stores_count,
    market_spread_pct
"""


def _passes_highlight_price_floor(row: dict[str, Any]) -> bool:
    """Defense-in-depth price-floor filter excluding < 10 EGP bait & < 2,500 EGP non-accessory major appliances."""
    price = float(row.get("current_price") or 0.0)
    if price < 10.0:
        return False
    sub_cat = str(row.get("sub_category") or "").strip().lower()
    title = str(row.get("product_title") or "")
    if sub_cat in _MAJOR_APPLIANCE_SUBS and price < 2500.0 and not _ACCESSORY_PY_RE.search(title):
        return False
    return True


def _row_to_highlight(row: dict[str, Any], *, bucket: Literal["scandal", "deal"]) -> RadarHighlightItem:
    current_price = float(row["current_price"])
    raw_verdict = str(row["discount_verdict"] or "NORMAL_PRICE")

    raw_days = row.get("tracked_days_count")
    if raw_days is None:
        tracked_days = (
            14
            if raw_verdict in ("ALL_TIME_LOW", "GENUINE_DEAL", "FAKE_DISCOUNT", "PRESALE_HIKE")
            else 1
        )
    else:
        tracked_days = max(1, int(raw_days))

    raw_mat = row.get("history_maturity")
    if raw_mat in ("EARLY", "GROWING", "MATURE"):
        maturity: HistoryMaturity = raw_mat
    else:
        maturity = "EARLY" if tracked_days < 7 else ("GROWING" if tracked_days < 60 else "MATURE")

    verified_med_raw = row.get("verified_historical_median")
    if verified_med_raw is not None and tracked_days >= 7:
        verified_med: float | None = round(float(verified_med_raw), 2)
    elif tracked_days >= 7 and row.get("rolling_60d_median"):
        verified_med = round(float(row["rolling_60d_median"]), 2)
    else:
        verified_med = None

    claimed_old = (
        float(row["claimed_original_price"])
        if row["claimed_original_price"] is not None
        else None
    )
    claimed_pct = float(row["claimed_discount_pct"] or 0.0)
    real_pct = float(row["real_discount_pct"] or 0.0)
    min_hist = float(row.get("min_historical_price") or current_price)
    max_hist = float(row.get("max_historical_price") or current_price)

    market_cheapest = (
        round(float(row["market_cheapest_price"]), 2)
        if row.get("market_cheapest_price") is not None
        else None
    )
    market_cheapest_store = (
        str(row["market_cheapest_store"])
        if row.get("market_cheapest_store")
        else None
    )
    market_highest = (
        round(float(row["market_highest_price"]), 2)
        if row.get("market_highest_price") is not None
        else None
    )
    market_stores = int(row.get("market_stores_count") or 0)

    basis: HighlightBasis = "historical"
    baseline_price = verified_med if verified_med is not None else current_price
    inflation_pct = 0.0
    real_drop_pct = 0.0

    if bucket == "scandal":
        if tracked_days >= 7 and raw_verdict == "PRESALE_HIKE":
            verdict: HighlightVerdict = "inflated_before_sale"
            basis = "historical"
            if baseline_price > 0 and current_price > baseline_price:
                inflation_pct = round(((current_price - baseline_price) / baseline_price) * 100.0, 1)
            else:
                inflation_pct = round(max(0.0, claimed_pct - real_pct), 1)
        elif tracked_days >= 7 and raw_verdict == "FAKE_DISCOUNT":
            verdict = "fake_discount"
            basis = "historical"
            inflation_pct = round(max(0.0, claimed_pct - real_pct), 1)
        elif raw_verdict == "RECENT_HIKE" and min_hist > 0 and current_price > min_hist:
            verdict = "inflated_before_sale"
            basis = "recent_hike"
            baseline_price = min_hist
            inflation_pct = round(((current_price - min_hist) / min_hist) * 100.0, 1)
        elif market_cheapest is not None and market_cheapest > 0 and current_price > market_cheapest:
            verdict = "fake_discount"
            basis = "above_market"
            baseline_price = market_cheapest
            inflation_pct = round(((current_price - market_cheapest) / market_cheapest) * 100.0, 1)
        else:
            verdict = "fake_discount"
            basis = "historical"
            inflation_pct = round(max(0.0, claimed_pct - real_pct), 1)
    else:
        verdict = "real_deal"
        if tracked_days >= 7 and raw_verdict in ("ALL_TIME_LOW", "GENUINE_DEAL"):
            basis = "historical"
            real_drop_pct = round(max(0.0, real_pct), 1)
        elif raw_verdict == "RECENT_DROP" and max_hist > current_price and max_hist > 0:
            basis = "recent_drop"
            baseline_price = max_hist
            real_drop_pct = round(((max_hist - current_price) / max_hist) * 100.0, 1)
        elif market_highest is not None and market_highest > current_price and market_stores >= 2:
            basis = "cross_store_lowest"
            baseline_price = market_highest
            real_drop_pct = round(((market_highest - current_price) / market_highest) * 100.0, 1)
        else:
            basis = "historical"
            real_drop_pct = round(max(0.0, real_pct), 1)

    variant_count = max(1, int(row.get("variant_count") or 1))
    has_multiple = bool(row.get("has_multiple_variants") or variant_count > 1)
    min_var = (
        round(float(row["min_variant_price"]), 2)
        if row.get("min_variant_price") is not None
        else round(current_price, 2)
    )
    max_var = (
        round(float(row["max_variant_price"]), 2)
        if row.get("max_variant_price") is not None
        else round(current_price, 2)
    )

    return RadarHighlightItem(
        id=str(row["product_sk"]),
        product_key=str(row["canonical_product_key"] or row["product_sk"]),
        title=str(row["product_title"]),
        store_name=str(row["store_name"]),
        category=str(row["category"]),
        image_url=row["image_url"],
        product_url=str(row["product_url"]),
        current_price=round(current_price, 2),
        claimed_old_price=round(claimed_old, 2) if claimed_old is not None else None,
        baseline_price=round(baseline_price, 2),
        inflation_pct=inflation_pct,
        real_drop_pct=real_drop_pct,
        verdict=verdict,
        parent_product_key=row.get("parent_product_key"),
        variant_label=row.get("variant_label"),
        variant_count=variant_count,
        has_multiple_variants=has_multiple,
        min_variant_price=min_var,
        max_variant_price=max_var,
        tracked_days_count=tracked_days,
        history_maturity=maturity,
        verified_historical_median=verified_med,
        highlight_basis=basis,
        market_cheapest_price=market_cheapest,
        market_cheapest_store=market_cheapest_store,
        market_stores_count=market_stores,
    )


@router.get("/api/radar/highlights", response_model=RadarHighlightsResponse)
@router.get("/api/v1/radar/highlights", response_model=RadarHighlightsResponse, include_in_schema=True)
def get_radar_highlights(
    response: Response,
    limit: int = Query(default=24, ge=1, le=60),
    category: CategoryFilter = Query(default="all"),
    db: Connection = Depends(get_db),
) -> RadarHighlightsResponse:
    set_cache_headers(response, s_maxage=3600, stale_while_revalidate=86400)
    cache_key = f"radar:highlights:v3:{category}:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params: dict[str, object] = {"limit": limit}
    cat_filter = ""
    if category != "all":
        cat_filter = "AND v.category = :category"
        params["category"] = category

    price_floor_v = _PRICE_FLOOR_SQL_GUARD.replace("current_price", "v.current_price").replace(
        "sub_category", "v.sub_category"
    ).replace("product_title", "v.product_title")

    scandal_rank_inner = """
        CASE
            WHEN v.tracked_days_count >= 7 AND v.discount_verdict = 'PRESALE_HIKE' THEN 0
            WHEN v.tracked_days_count >= 7 AND v.discount_verdict = 'FAKE_DISCOUNT' THEN 1
            WHEN v.discount_verdict = 'RECENT_HIKE' THEN 2
            ELSE 3
        END ASC,
        GREATEST(
            CASE WHEN v.tracked_days_count >= 7 THEN (v.claimed_discount_pct - v.real_discount_pct) ELSE 0.0 END,
            CASE WHEN v.min_historical_price > 0 AND v.discount_verdict = 'RECENT_HIKE'
                 THEN ((v.current_price - v.min_historical_price) / v.min_historical_price) * 100.0
                 ELSE 0.0 END,
            CASE WHEN m.lowest_price > 0 AND v.current_price > m.lowest_price
                 THEN ((v.current_price - m.lowest_price) / m.lowest_price) * 100.0
                 ELSE 0.0 END
        ) DESC,
        v.current_price ASC,
        v.product_sk ASC
    """
    scandal_rank_outer = """
        CASE
            WHEN tracked_days_count >= 7 AND discount_verdict = 'PRESALE_HIKE' THEN 0
            WHEN tracked_days_count >= 7 AND discount_verdict = 'FAKE_DISCOUNT' THEN 1
            WHEN discount_verdict = 'RECENT_HIKE' THEN 2
            ELSE 3
        END ASC,
        GREATEST(
            CASE WHEN tracked_days_count >= 7 THEN (claimed_discount_pct - real_discount_pct) ELSE 0.0 END,
            CASE WHEN min_historical_price > 0 AND discount_verdict = 'RECENT_HIKE'
                 THEN ((current_price - min_historical_price) / min_historical_price) * 100.0
                 ELSE 0.0 END,
            CASE WHEN market_cheapest_price > 0 AND current_price > market_cheapest_price
                 THEN ((current_price - market_cheapest_price) / market_cheapest_price) * 100.0
                 ELSE 0.0 END
        ) DESC,
        current_price ASC,
        product_sk ASC
    """
    scandals_sql = text(
        f"""
        WITH deduped AS (
            SELECT DISTINCT ON (v.parent_product_key)
                {_HIGHLIGHT_COLS}
            FROM gold.mart_product_verdicts v
            LEFT JOIN gold.mart_cross_store_matches m
                ON m.canonical_product_key = v.canonical_product_key
            WHERE v.in_stock = TRUE
              {price_floor_v}
              AND (
                  (v.tracked_days_count >= 7 AND v.discount_verdict IN ('PRESALE_HIKE', 'FAKE_DISCOUNT'))
                  OR v.discount_verdict = 'RECENT_HIKE'
                  OR (
                      m.canonical_product_key IS NOT NULL
                      AND m.lowest_price > 0
                      AND v.current_price >= m.lowest_price * 1.12
                      AND m.price_spread_pct >= 12.0
                  )
              )
              {cat_filter}
            ORDER BY v.parent_product_key, {scandal_rank_inner}
        )
        SELECT {_HIGHLIGHT_OUTER_COLS}
        FROM deduped
        ORDER BY {scandal_rank_outer}
        LIMIT :limit
        """
    )

    deal_rank_inner = """
        CASE
            WHEN v.tracked_days_count >= 7 AND v.discount_verdict = 'ALL_TIME_LOW' THEN 0
            WHEN v.tracked_days_count >= 7 AND v.discount_verdict = 'GENUINE_DEAL' THEN 1
            WHEN v.discount_verdict = 'RECENT_DROP' THEN 2
            ELSE 3
        END ASC,
        GREATEST(
            CASE WHEN v.tracked_days_count >= 7 THEN v.real_discount_pct ELSE 0.0 END,
            CASE WHEN v.max_historical_price > 0 AND v.discount_verdict = 'RECENT_DROP'
                 THEN ((v.max_historical_price - v.current_price) / v.max_historical_price) * 100.0
                 ELSE 0.0 END,
            CASE WHEN m.highest_price > 0 AND v.store_name = m.lowest_price_store
                 THEN ((m.highest_price - v.current_price) / m.highest_price) * 100.0
                 ELSE 0.0 END
        ) DESC,
        v.current_price ASC,
        v.product_sk ASC
    """
    deal_rank_outer = """
        CASE
            WHEN tracked_days_count >= 7 AND discount_verdict = 'ALL_TIME_LOW' THEN 0
            WHEN tracked_days_count >= 7 AND discount_verdict = 'GENUINE_DEAL' THEN 1
            WHEN discount_verdict = 'RECENT_DROP' THEN 2
            ELSE 3
        END ASC,
        GREATEST(
            CASE WHEN tracked_days_count >= 7 THEN real_discount_pct ELSE 0.0 END,
            CASE WHEN max_historical_price > 0 AND discount_verdict = 'RECENT_DROP'
                 THEN ((max_historical_price - current_price) / max_historical_price) * 100.0
                 ELSE 0.0 END,
            CASE WHEN market_highest_price > 0 AND store_name = market_cheapest_store
                 THEN ((market_highest_price - current_price) / market_highest_price) * 100.0
                 ELSE 0.0 END
        ) DESC,
        current_price ASC,
        product_sk ASC
    """
    deals_sql = text(
        f"""
        WITH deduped AS (
            SELECT DISTINCT ON (v.parent_product_key)
                {_HIGHLIGHT_COLS}
            FROM gold.mart_product_verdicts v
            LEFT JOIN gold.mart_cross_store_matches m
                ON m.canonical_product_key = v.canonical_product_key
            WHERE v.in_stock = TRUE
              {price_floor_v}
              AND v.discount_verdict NOT IN ('FAKE_DISCOUNT', 'PRESALE_HIKE', 'RECENT_HIKE')
              AND (
                  (v.tracked_days_count >= 7 AND v.discount_verdict IN ('ALL_TIME_LOW', 'GENUINE_DEAL'))
                  OR v.discount_verdict = 'RECENT_DROP'
                  OR (
                      m.canonical_product_key IS NOT NULL
                      AND v.store_name = m.lowest_price_store
                      AND m.price_spread_pct >= 8.0
                      AND m.highest_price > v.current_price
                  )
              )
              {cat_filter}
            ORDER BY v.parent_product_key, {deal_rank_inner}
        )
        SELECT {_HIGHLIGHT_OUTER_COLS}
        FROM deduped
        ORDER BY {deal_rank_outer}
        LIMIT :limit
        """
    )

    scandal_rows = [
        row_dict
        for r in db.execute(scandals_sql, params).mappings().all()
        if _passes_highlight_price_floor(row_dict := dict(r))
    ]
    deal_rows = [
        row_dict
        for r in db.execute(deals_sql, params).mappings().all()
        if _passes_highlight_price_floor(row_dict := dict(r))
    ]

    biggest_scandals = [_row_to_highlight(r, bucket="scandal") for r in scandal_rows]
    best_real_deals = [_row_to_highlight(r, bucket="deal") for r in deal_rows]

    timestamps = [
        r["last_updated_at"]
        for r in (*scandal_rows, *deal_rows)
        if r.get("last_updated_at") is not None
    ]
    updated_at = max(timestamps) if timestamps else datetime.now(timezone.utc)

    result = RadarHighlightsResponse(
        updated_at=updated_at,
        biggest_scandals=biggest_scandals,
        best_real_deals=best_real_deals,
    )
    api_cache.set(cache_key, result, ttl=21600.0)
    return result
