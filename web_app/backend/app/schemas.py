"""Pydantic response schemas strictly adhering to CONTRACTS.md."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, field_serializer

Category = Literal["electronics", "fashion", "home_appliances"]

DiscountVerdict = Literal[
    "ALL_TIME_LOW",
    "GENUINE_DEAL",
    "FAKE_DISCOUNT",
    "PRESALE_HIKE",
    "NORMAL_PRICE",
]


def _format_utc_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class HealthResponse(BaseModel):
    status: str
    database: str


class OverviewStatsResponse(BaseModel):
    total_tracked: int
    fake_discounts_today: int
    genuine_deals_today: int
    all_time_lows_today: int
    presale_hikes_today: int
    avg_fake_inflation_pct: float
    last_pipeline_run_at: Optional[datetime]

    @field_serializer("last_pipeline_run_at")
    def serialize_last_run(self, v: Optional[datetime]) -> Optional[str]:
        return _format_utc_z(v)


class ProductVerdictItem(BaseModel):
    product_sk: str
    canonical_product_key: Optional[str] = None
    store_name: str
    category: Category
    sub_category: str
    brand: str
    product_title: str
    product_url: str
    image_url: Optional[str] = None
    attributes_json: dict[str, Any]
    current_price: float
    claimed_original_price: Optional[float] = None
    rolling_60d_median: float
    min_historical_price: float
    max_historical_price: float
    claimed_discount_pct: float
    real_discount_pct: float
    discount_verdict: DiscountVerdict
    scarcity_flag: bool
    in_stock: bool
    last_updated_at: datetime

    @field_serializer("last_updated_at")
    def serialize_last_updated(self, v: datetime) -> str:
        return _format_utc_z(v) or ""


class RadarFeedResponse(BaseModel):
    items: list[ProductVerdictItem]
    total: int
    page: int
    limit: int
    total_pages: int


class SearchResponse(BaseModel):
    match_type: str
    items: list[ProductVerdictItem]
    total: int


class PriceHistoryPoint(BaseModel):
    snapshot_date: date
    price: float
    claimed_original_price: Optional[float] = None
    rolling_60d_median: float
    in_stock: bool
    available_sizes_count: Optional[int] = None


class AlternativeListing(BaseModel):
    product_sk: str
    store_name: str
    price: float
    in_stock: bool
    product_url: str
    discount_verdict: DiscountVerdict


class ProductDetailResponse(BaseModel):
    product: ProductVerdictItem
    history: list[PriceHistoryPoint]
    alternatives: list[AlternativeListing]


class CrossStoreMatchItem(BaseModel):
    canonical_product_key: str
    product_title_clean: str
    category: Category
    brand: str
    stores_count: int
    lowest_price: float
    lowest_price_store: str
    highest_price: float
    price_spread_egp: float
    price_spread_pct: float
    listings_json: list[AlternativeListing]


class CompareResponse(BaseModel):
    items: list[CrossStoreMatchItem]
    total: int
    page: int
    limit: int
