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
from app.schemas import HighlightVerdict, RadarHighlightItem, RadarHighlightsResponse

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
    claimed_discount_pct,
    real_discount_pct,
    discount_verdict,
    last_updated_at
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
    baseline_price = float(row["rolling_60d_median"] or current_price)
    claimed_old = (
        float(row["claimed_original_price"])
        if row["claimed_original_price"] is not None
        else None
    )
    claimed_pct = float(row["claimed_discount_pct"] or 0.0)
    real_pct = float(row["real_discount_pct"] or 0.0)
    raw_verdict = str(row["discount_verdict"] or "NORMAL_PRICE")

    if raw_verdict == "PRESALE_HIKE":
        verdict: HighlightVerdict = "inflated_before_sale"
        if baseline_price > 0 and current_price > baseline_price:
            inflation_pct = round(((current_price - baseline_price) / baseline_price) * 100.0, 1)
        else:
            inflation_pct = round(max(0.0, claimed_pct - real_pct), 1)
    elif bucket == "scandal" or raw_verdict == "FAKE_DISCOUNT":
        verdict = "fake_discount"
        inflation_pct = round(max(0.0, claimed_pct - real_pct), 1)
    else:
        verdict = "real_deal"
        inflation_pct = 0.0

    real_drop_pct = round(max(0.0, real_pct), 1)
    if bucket == "deal" and real_drop_pct == 0.0 and claimed_old and claimed_old > current_price:
        real_drop_pct = round(((claimed_old - current_price) / claimed_old) * 100.0, 1)

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
    )


@router.get("/api/radar/highlights", response_model=RadarHighlightsResponse)
@router.get("/api/v1/radar/highlights", response_model=RadarHighlightsResponse, include_in_schema=True)
def get_radar_highlights(
    response: Response,
    limit: int = Query(default=24, ge=1, le=60),
    category: Literal["all", "electronics", "fashion", "home_appliances", "groceries"] = Query(
        default="all"
    ),
    db: Connection = Depends(get_db),
) -> RadarHighlightsResponse:
    set_cache_headers(response, s_maxage=300, stale_while_revalidate=600)
    cache_key = f"radar:highlights:{category}:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params: dict[str, object] = {"limit": limit}
    cat_filter = ""
    if category != "all":
        cat_filter = "AND category = :category"
        params["category"] = category

    scandals_sql = text(
        f"""
        SELECT {_HIGHLIGHT_COLS}
        FROM gold.mart_product_verdicts
        WHERE in_stock = TRUE
          {_PRICE_FLOOR_SQL_GUARD}
          AND (
              discount_verdict IN ('PRESALE_HIKE', 'FAKE_DISCOUNT')
              OR (claimed_discount_pct - real_discount_pct) >= 10.0
          )
          {cat_filter}
        ORDER BY
            CASE WHEN discount_verdict = 'PRESALE_HIKE' THEN 0 ELSE 1 END ASC,
            GREATEST(
                claimed_discount_pct - real_discount_pct,
                CASE
                    WHEN rolling_60d_median > 0
                    THEN ((current_price - rolling_60d_median) / rolling_60d_median) * 100.0
                    ELSE 0.0
                END
            ) DESC,
            product_sk ASC
        LIMIT :limit
        """
    )

    deals_sql = text(
        f"""
        SELECT {_HIGHLIGHT_COLS}
        FROM gold.mart_product_verdicts
        WHERE in_stock = TRUE
          {_PRICE_FLOOR_SQL_GUARD}
          AND discount_verdict NOT IN ('FAKE_DISCOUNT', 'PRESALE_HIKE')
          AND (
              discount_verdict IN ('ALL_TIME_LOW', 'GENUINE_DEAL')
              OR real_discount_pct > 0.0
              OR (
                  claimed_original_price IS NOT NULL
                  AND claimed_original_price > current_price
                  AND current_price <= min_historical_price
              )
          )
          {cat_filter}
        ORDER BY
            CASE
                WHEN discount_verdict = 'ALL_TIME_LOW' THEN 0
                WHEN discount_verdict = 'GENUINE_DEAL' THEN 1
                ELSE 2
            END ASC,
            real_discount_pct DESC,
            claimed_discount_pct DESC,
            product_sk ASC
        LIMIT :limit
        """
    )

    scandal_rows = [
        dict(r)
        for r in db.execute(scandals_sql, params).mappings().all()
        if _passes_highlight_price_floor(dict(r))
    ]
    deal_rows = [
        dict(r)
        for r in db.execute(deals_sql, params).mappings().all()
        if _passes_highlight_price_floor(dict(r))
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
    api_cache.set(cache_key, result, ttl=300.0)
    return result
