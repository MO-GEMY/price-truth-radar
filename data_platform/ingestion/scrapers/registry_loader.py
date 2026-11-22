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

DEFAULT_REGISTRY_MAX_PRODUCTS = 650


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
    effective_max = entry.max_products or entry.discover_limit or DEFAULT_REGISTRY_MAX_PRODUCTS
    if entry.default_limit:
        common_attrs["default_limit"] = min(entry.default_limit, effective_max)
        if entry.vertical == "groceries":
            common_attrs["groceries_limit"] = min(entry.default_limit, effective_max)
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

    cls_name = f"Registry_{entry.store_key}_Scraper"

    if entry.platform == "shopify":
        if cfg.get("collections"):
            common_attrs["collections"] = tuple(cfg["collections"])
        return type(cls_name, (ShopifyBaseScraper,), common_attrs)

    if entry.platform == "woocommerce":
        if cfg.get("api_path"):
            common_attrs["api_path"] = str(cfg["api_path"])
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
