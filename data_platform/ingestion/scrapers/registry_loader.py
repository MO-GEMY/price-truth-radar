"""Config-driven multi-store registry loader backed by `stores_registry.yaml`.

Dynamically synthesizes generic `ShopifyBaseScraper`, `WooCommerceBaseScraper`,
and `MagentoGraphQLBaseScraper` subclasses for any enabled platform store in
`stores_registry.yaml` that is not already implemented in Python, while also
providing batch discovery helpers for GitHub Actions matrix workflows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

import yaml

from .adapters import (
    MagentoGraphQLBaseScraper,
    ShopifyBaseScraper,
    WooCommerceBaseScraper,
)
from .base import BaseScraper, Category, ScrapeVertical

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "stores_registry.yaml"

PlatformType = Literal["shopify", "woocommerce", "magento_graphql", "custom"]
RegionMode = Literal["cloud", "local_only"]

# Map registry categories (and legacy aliases) onto canonical top-level categories
_CATEGORY_CONTRACT_MAP: dict[str, Category] = {
    "electronics": "electronics",
    "home_appliances": "home_appliances",
    "home_furniture": "home_furniture",
    "kitchen": "home_furniture",
    "fashion": "fashion",
    "optics": "fashion",
    "watches": "fashion",
    "lifestyle": "fashion",
    "beauty": "beauty",
    "groceries": "groceries",
    "health": "health",
    "pharmacy": "health",
    "sports": "sports",
    "pet_care": "pet_care",
    "baby_kids": "baby_kids",
    "books": "baby_kids",
}

DEFAULT_REGISTRY_MAX_PRODUCTS = 5000

# Amazon Egypt runs as #1 Priority-1 store split into 5 parallel department shards
# so every canonical category refreshes daily without GitHub Actions runner timeouts.
AMAZON_EG_P1_SHARD_SPECS: tuple[tuple[str, str], ...] = (
    ("p1_amazon_eg_electronics", "amazon_eg:electronics"),
    ("p1_amazon_eg_home_appliances", "amazon_eg:home_appliances"),
    ("p1_amazon_eg_fashion_beauty", "amazon_eg:fashion_beauty"),
    ("p1_amazon_eg_groceries_health", "amazon_eg:groceries_health"),
    ("p1_amazon_eg_home_sports_baby_pet", "amazon_eg:home_sports_baby_pet"),
)


@dataclass(frozen=True)
class StoreRegistryEntry:
    store_key: str
    display_name: str
    platform: PlatformType
    base_url: str
    category: str
    vertical: ScrapeVertical
    region_mode: RegionMode = "cloud"
    enabled: bool = False
    verified: bool = False
    batch: str = "default"
    tier: int = 3
    priority_group: str = "long_tail"
    extra_verticals: tuple[ScrapeVertical, ...] = ()
    default_limit: Optional[int] = None
    discover_limit: Optional[int] = None
    max_products: Optional[int] = None
    config: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    @property
    def contract_category(self) -> Category:
        return _CATEGORY_CONTRACT_MAP.get(self.category.lower(), "electronics")

    @property
    def all_verticals(self) -> tuple[ScrapeVertical, ...]:
        seen: list[ScrapeVertical] = [self.vertical]
        for v in self.extra_verticals:
            if v not in seen:
                seen.append(v)
        return tuple(seen)

    @property
    def priority_rank(self) -> tuple[int, int, str]:
        """Strict wave ordering: Amazon EG (#1 P1) -> Priority 1 (major_brands) -> Priority 2 (major_stores) -> Tier 2 -> Tier 3."""
        if self.store_key == "amazon_eg":
            return (0, 0, self.store_key)
        if self.tier == 1:
            sub = 0 if self.priority_group == "major_brands" else 1
            return (1, sub, self.store_key)
        if self.tier == 2:
            return (2, 0, self.store_key)
        return (3, 0, self.store_key)


def load_stores_registry(
    path: Optional[Path] = None,
    *,
    enabled_only: bool = False,
    region_mode: Optional[RegionMode] = None,
) -> list[StoreRegistryEntry]:
    """Load and validate store entries from `stores_registry.yaml`."""
    reg_path = path or DEFAULT_REGISTRY_PATH
    if not reg_path.exists():
        logger.warning("Store registry YAML not found at %s", reg_path)
        return []

    raw = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    raw_stores = raw.get("stores") or []
    entries: list[StoreRegistryEntry] = []
    seen_keys: set[str] = set()

    for item in raw_stores:
        if not isinstance(item, dict):
            continue
        key = str(item.get("store_key") or "").strip().lower()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        raw_tier = item.get("tier")
        tier = int(raw_tier) if raw_tier in (1, 2, 3, "1", "2", "3") else 3
        raw_pg = str(item.get("priority_group") or "").strip().lower()
        if not raw_pg:
            raw_pg = "major_stores" if tier == 1 else ("mid_specialty" if tier == 2 else "long_tail")

        entry = StoreRegistryEntry(
            store_key=key,
            display_name=str(item.get("display_name") or key).strip(),
            platform=str(item.get("platform") or "custom").strip().lower(),  # type: ignore[arg-type]
            base_url=str(item.get("base_url") or "").strip().rstrip("/"),
            category=str(item.get("category") or "electronics").strip().lower(),
            vertical=str(item.get("vertical") or "core").strip().lower(),  # type: ignore[arg-type]
            region_mode=str(item.get("region_mode") or "cloud").strip().lower(),  # type: ignore[arg-type]
            enabled=bool(item.get("enabled", False)),
            verified=bool(item.get("verified", False)),
            batch=str(item.get("batch") or "default").strip(),
            tier=tier,
            priority_group=raw_pg,
            extra_verticals=tuple(
                str(v).strip().lower() for v in (item.get("extra_verticals") or [])  # type: ignore[misc]
            ),
            default_limit=int(item["default_limit"]) if item.get("default_limit") else None,
            discover_limit=int(item["discover_limit"]) if item.get("discover_limit") else None,
            max_products=int(item["max_products"]) if item.get("max_products") else None,
            config=dict(item.get("config") or {}),
            notes=str(item.get("notes") or "").strip(),
        )
        if enabled_only and not entry.enabled:
            continue
        if region_mode is not None and entry.region_mode != region_mode:
            continue
        entries.append(entry)

    return entries


def build_platform_scraper_class(entry: StoreRegistryEntry) -> Optional[type[BaseScraper]]:
    """Synthesize a generic scraper subclass from a `stores_registry.yaml` entry."""
    cfg = entry.config or {}
    common_attrs: dict[str, Any] = {
        "store_name": entry.store_key,
        "category": entry.contract_category,
        "base_url": entry.base_url,
        "supported_verticals": entry.all_verticals,
    }
    tier_default_max = 15000 if entry.tier == 1 else (8000 if entry.tier == 2 else DEFAULT_REGISTRY_MAX_PRODUCTS)
    tier_default_daily = 5000 if entry.tier == 1 else (2500 if entry.tier == 2 else 1500)
    effective_max = entry.max_products or entry.discover_limit or tier_default_max
    eff_daily = min(entry.default_limit, effective_max) if entry.default_limit else min(tier_default_daily, effective_max)
    common_attrs["default_limit"] = eff_daily
    if entry.vertical == "groceries":
        common_attrs["groceries_limit"] = eff_daily
    if effective_max:
        common_attrs["discover_limit"] = effective_max
        if entry.vertical == "groceries":
            common_attrs["discover_groceries_limit"] = effective_max

    if cfg.get("default_brand"):
        common_attrs["default_brand"] = str(cfg["default_brand"])
    if "override_brand" in cfg:
        common_attrs["override_brand"] = bool(cfg["override_brand"])
    if "use_impersonation" in cfg:
        common_attrs["use_impersonation"] = bool(cfg["use_impersonation"])
    if "min_delay_seconds" in cfg:
        common_attrs["min_delay_seconds"] = float(cfg["min_delay_seconds"])

    cls_name = f"Registry_{entry.store_key}_Scraper"

    if entry.platform == "shopify":
        if cfg.get("collections"):
            common_attrs["collections"] = tuple(cfg["collections"])
        return type(cls_name, (ShopifyBaseScraper,), common_attrs)

    if entry.platform == "woocommerce":
        if cfg.get("api_path"):
            common_attrs["api_path"] = str(cfg["api_path"])
        if "per_page" in cfg:
            common_attrs["per_page"] = int(cfg["per_page"])
        if "min_price_egp" in cfg:
            common_attrs["min_price_egp"] = float(cfg["min_price_egp"])
        return type(cls_name, (WooCommerceBaseScraper,), common_attrs)

    if entry.platform == "magento_graphql":
        common_attrs["graphql_url"] = str(cfg.get("graphql_url") or f"{entry.base_url}/graphql")
        if cfg.get("store_header"):
            common_attrs["store_header"] = str(cfg["store_header"])
        if "use_post" in cfg:
            common_attrs["use_post"] = bool(cfg["use_post"])
        if cfg.get("search_queries"):
            common_attrs["search_queries"] = tuple(tuple(q) for q in cfg["search_queries"])
        return type(cls_name, (MagentoGraphQLBaseScraper,), common_attrs)

    return None


def get_registry_scraper_classes(
    existing_registry: dict[str, type[BaseScraper]],
    *,
    path: Optional[Path] = None,
) -> dict[str, type[BaseScraper]]:
    """Build scraper classes for enabled platform stores not already in `existing_registry`."""
    dynamic: dict[str, type[BaseScraper]] = {}
    for entry in load_stores_registry(path=path, enabled_only=True):
        if entry.store_key in existing_registry:
            continue
        cls = build_platform_scraper_class(entry)
        if cls is not None:
            dynamic[entry.store_key] = cls
    return dynamic


def get_batch_targets(
    batch_name: str,
    *,
    region_mode: Optional[RegionMode] = "cloud",
    enabled_only: bool = True,
    path: Optional[Path] = None,
) -> list[tuple[str, ScrapeVertical]]:
    """Return `(store_key, vertical)` targets belonging to `batch_name`."""
    targets: list[tuple[str, ScrapeVertical]] = []
    for entry in load_stores_registry(path=path, enabled_only=enabled_only, region_mode=region_mode):
        if entry.batch == batch_name:
            targets.append((entry.store_key, entry.vertical))
        # Also include multi-vertical stores (e.g. amazon_eg/noon groceries) in groceries_1 batch
        elif batch_name == "groceries_1" and "groceries" in entry.extra_verticals:
            targets.append((entry.store_key, "groceries"))
    return targets


def list_active_batches(
    *,
    region_mode: Optional[RegionMode] = "cloud",
    path: Optional[Path] = None,
) -> list[str]:
    """Return sorted distinct batch names that have >= 1 enabled store for `region_mode`."""
    batches: set[str] = set()
    for entry in load_stores_registry(path=path, enabled_only=True, region_mode=region_mode):
        batches.add(entry.batch)
    return sorted(batches)


def get_store_tier_map(
    *,
    enabled_only: bool = True,
    path: Optional[Path] = None,
) -> dict[str, tuple[int, str]]:
    """Return `{store_key: (tier, priority_group)}` for registry stores."""
    return {
        e.store_key: (e.tier, e.priority_group)
        for e in load_stores_registry(path=path, enabled_only=enabled_only)
    }


def plan_tiered_waves_for_day(
    day_of_year: int,
    *,
    region_mode: Optional[RegionMode] = "cloud",
    tier2_cadence_days: int = 3,
    tier3_cadence_days: int = 5,
    include_all_tiers: bool = False,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """Build deterministic Priority 1 -> Priority 2 -> Priority 3 wave schedule for `day_of_year`.

    Cadence:
      - Priority 1 (`tier=1, priority_group='major_brands'`): EVERY day.
      - Priority 2 (`tier=1, priority_group='major_stores'`): EVERY day.
      - Priority 3A (`tier=2`, mid-specialty): rotated every `tier2_cadence_days` (default: 3 days).
      - Priority 3B (`tier=3`, long-tail): rotated every `tier3_cadence_days` (default: 5 days).
    """
    entries = sorted(
        load_stores_registry(path=path, enabled_only=True, region_mode=region_mode),
        key=lambda e: e.priority_rank,
    )
    p1_stores: list[str] = []
    p2_stores: list[str] = []
    t2_all: list[str] = []
    t3_all: list[str] = []

    for e in entries:
        if e.tier == 1 and e.priority_group == "major_brands":
            p1_stores.append(e.store_key)
        elif e.tier == 1:
            p2_stores.append(e.store_key)
        elif e.tier == 2:
            t2_all.append(e.store_key)
        else:
            t3_all.append(e.store_key)

    t2_cad = max(1, int(tier2_cadence_days))
    t3_cad = max(1, int(tier3_cadence_days))
    if include_all_tiers:
        t2_today = list(t2_all)
        t3_today = list(t3_all)
    else:
        t2_slot = day_of_year % t2_cad
        t3_slot = day_of_year % t3_cad
        t2_today = [s for idx, s in enumerate(t2_all) if idx % t2_cad == t2_slot]
        t3_today = [s for idx, s in enumerate(t3_all) if idx % t3_cad == t3_slot]

    # Chunk each priority group into balanced offline worker shards (<= 14 stores/shard)
    def _chunk(items: list[str], prefix: str, size: int = 14) -> list[dict[str, Any]]:
        shards: list[dict[str, Any]] = []
        for i in range(0, len(items), size):
            shards.append(
                {
                    "shard": f"{prefix}_{i // size + 1}",
                    "priority": prefix,
                    "stores": items[i : i + size],
                }
            )
        return shards

    amazon_shards: list[dict[str, Any]] = []
    other_p1_stores = [s for s in p1_stores if s != "amazon_eg"]
    if "amazon_eg" in p1_stores:
        for shard_name, store_spec in AMAZON_EG_P1_SHARD_SPECS:
            amazon_shards.append(
                {
                    "shard": shard_name,
                    "priority": "p1_major_brands",
                    "stores": [store_spec],
                }
            )

    p1_shards = amazon_shards + _chunk(other_p1_stores, "p1_major_brands", size=12)
    p2_shards = _chunk(p2_stores, "p2_major_stores", size=10)
    p3_shards = _chunk(t2_today, "p3_tier2", size=14) + _chunk(t3_today, "p3_tier3", size=14)

    return {
        "day_of_year": day_of_year,
        "counts": {
            "p1_major_brands": len(p1_stores),
            "p2_major_stores": len(p2_stores),
            "tier2_total": len(t2_all),
            "tier2_today": len(t2_today),
            "tier3_total": len(t3_all),
            "tier3_today": len(t3_today),
        },
        "priority_1_stores": p1_stores,
        "priority_2_stores": p2_stores,
        "tier2_today_stores": t2_today,
        "tier3_today_stores": t3_today,
        "shards": p1_shards + p2_shards + p3_shards,
    }
