"""Pydantic response schemas strictly adhering to CONTRACTS.md."""

from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from app.coupons_service import ApplicableCoupon, CouponRecord
from app.sanitize import http_url, normalize_email, normalize_whatsapp

CANONICAL_CATEGORIES: tuple[str, ...] = (
    "electronics",
    "home_appliances",
    "home_furniture",
    "fashion",
    "beauty",
    "groceries",
    "health",
    "sports",
    "pet_care",
    "baby_kids",
)

Category = Literal[
    "electronics",
    "home_appliances",
    "home_furniture",
    "fashion",
    "beauty",
    "groceries",
    "health",
    "sports",
    "pet_care",
    "baby_kids",
]
CategoryFilter = Literal[
    "all",
    "electronics",
    "home_appliances",
    "home_furniture",
    "fashion",
    "beauty",
    "groceries",
    "health",
    "sports",
    "pet_care",
    "baby_kids",
]
UnitPriceUnit = Literal["kg", "L"]


def compute_unit_pricing(
    price: float,
    attributes_json: Optional[dict[str, Any]],
) -> tuple[Optional[float], Optional[UnitPriceUnit]]:
    """Derive normalized EGP/kg or EGP/L unit price from packaging attributes."""
    if not isinstance(attributes_json, dict) or price <= 0:
        return None, None

    raw_weight = attributes_json.get("net_weight_g")
    if isinstance(raw_weight, (int, float)) and raw_weight > 0:
        return round((float(price) * 1000.0) / float(raw_weight), 2), "kg"

    raw_vol = attributes_json.get("net_volume_ml")
    if isinstance(raw_vol, (int, float)) and raw_vol > 0:
        return round((float(price) * 1000.0) / float(raw_vol), 2), "L"

    return None, None

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
    available_stores: list[str] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    cross_store_matches_count: int = 0

    @field_serializer("last_pipeline_run_at")
    def serialize_last_run(self, v: Optional[datetime]) -> Optional[str]:
        return _format_utc_z(v)


class CategoryFacetItem(BaseModel):
    slug: Category
    label_en: str
    label_ar: str
    product_count: int
    compare_count: int = 0


class CategoriesResponse(BaseModel):
    items: list[CategoryFacetItem]
    total_products: int


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
    attributes_json: dict[str, Any] = Field(default_factory=dict)
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
    unit_price_egp: Optional[float] = None
    unit_price_unit: Optional[UnitPriceUnit] = None
    parent_product_key: Optional[str] = None
    variant_label: Optional[str] = None
    variant_count: int = 1
    has_multiple_variants: bool = False
    min_variant_price: Optional[float] = None
    max_variant_price: Optional[float] = None
    applicable_coupons: list[ApplicableCoupon] = Field(default_factory=list)
    estimated_price_after_coupon: Optional[float] = None

    @field_validator("attributes_json", mode="before")
    @classmethod
    def _coerce_null_attributes(cls, v: Any) -> dict[str, Any]:
        return v if isinstance(v, dict) else {}

    @model_validator(mode="after")
    def _populate_unit_pricing(self) -> "ProductVerdictItem":
        derived_price, derived_unit = compute_unit_pricing(self.current_price, self.attributes_json)
        if self.unit_price_egp is None and derived_price is not None:
            self.unit_price_egp = derived_price
        if self.unit_price_unit is None and derived_unit is not None:
            self.unit_price_unit = derived_unit
        if self.variant_count < 1:
            self.variant_count = 1
        if self.variant_count > 1:
            self.has_multiple_variants = True
        if self.min_variant_price is None:
            self.min_variant_price = self.current_price
        if self.max_variant_price is None:
            self.max_variant_price = self.current_price
        return self

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
    unit_price_egp: Optional[float] = None
    unit_price_unit: Optional[UnitPriceUnit] = None
    applicable_coupons: list[ApplicableCoupon] = Field(default_factory=list)
    estimated_price_after_coupon: Optional[float] = None


class ProductVariantItem(BaseModel):
    product_sk: str
    variant_label: Optional[str] = None
    title: str
    current_price: float
    claimed_original_price: Optional[float] = None
    verdict: DiscountVerdict
    in_stock: bool
    product_url: str


class SimilarAlternativeItem(BaseModel):
    product_sk: str
    title: str
    store_name: str
    current_price: float
    price_diff_egp: float
    price_diff_pct: float
    verdict: DiscountVerdict
    in_stock: bool
    image_url: Optional[str] = None
    product_url: str
    similarity_reason: str
    is_exact_match: Literal[False] = False


class ProductDetailResponse(BaseModel):
    product: ProductVerdictItem
    history: list[PriceHistoryPoint]
    alternatives: list[AlternativeListing]
    similar_alternatives: list[SimilarAlternativeItem] = Field(default_factory=list)
    similar_products: list[SimilarAlternativeItem] = Field(default_factory=list)
    variants: list[ProductVariantItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_similar_aliases(self) -> "ProductDetailResponse":
        if self.similar_alternatives and not self.similar_products:
            self.similar_products = list(self.similar_alternatives)
        elif self.similar_products and not self.similar_alternatives:
            self.similar_alternatives = list(self.similar_products)
        return self


class CrossStoreMatchItem(BaseModel):
    canonical_product_key: str
    product_title_clean: str
    category: Category
    brand: str
    image_url: Optional[str] = None
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


# ---------------------------------------------------------------------------
# Launch Feature Schemas: Radar Highlights, Price Drop Alerts, SEO Sitemap
# ---------------------------------------------------------------------------

HighlightVerdict = Literal["fake_discount", "inflated_before_sale", "real_deal"]
AlertChannel = Literal["telegram", "email"]

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_TELEGRAM_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_TELEGRAM_CHAT_ID_RE = re.compile(r"^-?\d{5,20}$")


class RadarHighlightItem(BaseModel):
    id: str
    product_key: str
    title: str
    store_name: str
    category: str
    image_url: Optional[str] = None
    product_url: str
    current_price: float
    claimed_old_price: Optional[float] = None
    baseline_price: float
    inflation_pct: float
    real_drop_pct: float
    verdict: HighlightVerdict
    parent_product_key: Optional[str] = None
    variant_label: Optional[str] = None
    variant_count: int = 1
    has_multiple_variants: bool = False
    min_variant_price: Optional[float] = None
    max_variant_price: Optional[float] = None


class RadarHighlightsResponse(BaseModel):
    updated_at: Optional[datetime]
    biggest_scandals: list[RadarHighlightItem]
    best_real_deals: list[RadarHighlightItem]

    @field_serializer("updated_at")
    def serialize_updated_at(self, v: Optional[datetime]) -> str:
        return _format_utc_z(v or datetime.now(timezone.utc)) or ""


class AlertCreateRequest(BaseModel):
    product_key: str = Field(..., min_length=1, max_length=200)
    product_title: str = Field(default="", max_length=300)
    store_name: str = Field(default="", max_length=100)
    target_price: float = Field(..., gt=0, le=50_000_000)
    channel: AlertChannel
    destination: str = Field(..., min_length=3, max_length=254)

    @field_validator("product_key", "product_title", "store_name", "destination", mode="before")
    @classmethod
    def _strip_strings(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_channel_destination(self) -> "AlertCreateRequest":
        dest = self.destination.strip()
        if self.channel == "email":
            if not _EMAIL_RE.match(dest):
                raise ValueError("Invalid email address format for email alert destination.")
            self.destination = dest.lower()
        elif self.channel == "telegram":
            if not _TELEGRAM_CHAT_ID_RE.match(dest):
                raise ValueError(
                    "رقم محادثة تليجرام (Chat ID) يجب أن يكون أرقاماً فقط (5 إلى 20 رقماً) وليس اسم مستخدم مثل @username. افتح بوت أسعارك واضغط Start للحصول على رقم المحادثة الخاص بك."
                )
            self.destination = dest
        self.target_price = round(float(self.target_price), 2)
        return self


class AlertCreateResponse(BaseModel):
    id: int
    status: Literal["active"] = "active"
    message: str


class SitemapProductEntry(BaseModel):
    product_sk: str
    product_key: str
    category: str
    store_name: str
    last_updated: Optional[datetime] = None

    @field_serializer("last_updated")
    def serialize_last_updated(self, v: Optional[datetime]) -> Optional[str]:
        return _format_utc_z(v)


class SitemapComparisonEntry(BaseModel):
    canonical_product_key: str
    category: str
    stores_count: int


class SitemapEntriesResponse(BaseModel):
    last_updated: Optional[datetime]
    products: list[SitemapProductEntry]
    comparisons: list[SitemapComparisonEntry]

    @field_serializer("last_updated")
    def serialize_last_updated(self, v: Optional[datetime]) -> str:
        return _format_utc_z(v or datetime.now(timezone.utc)) or ""


# ---------------------------------------------------------------------------
# Public Inbound Forms: Contact Messages & Store Suggestions
# (zero DB — validated in memory, forwarded to the team, never stored)
# ---------------------------------------------------------------------------

ContactCategory = Literal["price_error", "general", "partnership"]
StoreSuggestKind = Literal["suggest", "owner"]
StorePlatform = Literal["shopify", "woocommerce", "salla_zid", "custom"]

_TURNSTILE_TOKEN_MAX_LENGTH = 4096


class ContactCreateRequest(BaseModel):
    category: ContactCategory
    name: str = Field(default="", max_length=80)
    email: str = Field(..., max_length=254)
    message: str = Field(..., min_length=10, max_length=3000)
    product_url: str = Field(default="", max_length=2048)
    # Anti-spam: `website` is a honeypot — hidden from humans, filled by bots.
    website: str = Field(default="", max_length=200)
    turnstile_token: str = Field(default="", max_length=_TURNSTILE_TOKEN_MAX_LENGTH)

    @field_validator(
        "name", "email", "message", "product_url", "website", "turnstile_token", mode="before"
    )
    @classmethod
    def _strip_strings(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_fields(self) -> "ContactCreateRequest":
        email = normalize_email(self.email)
        if email is None:
            raise ValueError("Invalid email address format.")
        self.email = email
        product_url = http_url(self.product_url) if self.product_url else ""
        if self.product_url and not product_url:
            raise ValueError("Enter a complete http(s) product URL.")
        if self.category == "price_error" and not product_url:
            raise ValueError("A product URL is required to report a wrong price.")
        self.product_url = product_url
        return self


class StoreSuggestCreateRequest(BaseModel):
    kind: StoreSuggestKind
    store_name: str = Field(..., min_length=2, max_length=120)
    store_url: str = Field(..., max_length=2048)
    notes: str = Field(default="", max_length=2000)
    platform: Optional[StorePlatform] = None
    contact_email: Optional[str] = Field(default=None, max_length=254)
    contact_whatsapp: Optional[str] = Field(default=None, max_length=32)
    website: str = Field(default="", max_length=200)
    turnstile_token: str = Field(default="", max_length=_TURNSTILE_TOKEN_MAX_LENGTH)

    @field_validator(
        "store_name", "store_url", "notes", "contact_email", "contact_whatsapp",
        "website", "turnstile_token", mode="before",
    )
    @classmethod
    def _strip_strings(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_fields(self) -> "StoreSuggestCreateRequest":
        # Syntax only: the URL is never requested, resolved, or scraped.
        store_url = http_url(self.store_url)
        if not store_url:
            raise ValueError("Enter a complete http(s) store URL.")
        self.store_url = store_url

        if self.kind != "owner":
            # Owner-only details never travel with a plain suggestion.
            self.platform = None
            self.contact_email = None
            self.contact_whatsapp = None
            return self

        if self.platform is None:
            raise ValueError("Store owners must choose the store platform.")
        email = normalize_email(self.contact_email) if self.contact_email else None
        if self.contact_email and email is None:
            raise ValueError("Invalid contact email address format.")
        whatsapp = normalize_whatsapp(self.contact_whatsapp) if self.contact_whatsapp else None
        if self.contact_whatsapp and whatsapp is None:
            raise ValueError("Invalid WhatsApp number.")
        if not email and not whatsapp:
            raise ValueError("Provide a contact email or a WhatsApp number.")
        self.contact_email = email
        self.contact_whatsapp = whatsapp
        return self


class SubmissionsConfigResponse(BaseModel):
    form_enabled: bool
    turnstile_site_key: str = ""
    telegram_bot_username: str = ""


class SubmissionAcceptedResponse(BaseModel):
    status: Literal["received"] = "received"
    message: str


class CouponsListResponse(BaseModel):
    items: list[CouponRecord]
    total: int
    source: str
    refreshed_at: Optional[str] = None
    available_stores: list[str] = Field(default_factory=list)


class CouponsRefreshResponse(BaseModel):
    ok: bool
    source: str
    count: int
    refreshed_at: Optional[str] = None
    error: Optional[str] = None
    # Why each source row was not published, e.g. "noon/CODE10: expired"
    skipped: list[str] = Field(default_factory=list)
