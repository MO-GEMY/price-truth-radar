"""Reusable scraper foundation and store scrapers for Price Truth Radar."""

from __future__ import annotations

from .adapters import (
    MagentoGraphQLBaseScraper,
    ShopifyBaseScraper,
    SllrBaseScraper,
    WooCommerceBaseScraper,
)
from .amazon_eg import AmazonEgScraper
from .aswaq_mozhela import AswaqMozhelaScraper
from .base import (
    BaseScraper,
    Category,
    DeltaStats,
    ImpersonatedHttpClient,
    PoliteHttpClient,
    RawProductSnapshot,
    ScrapeMode,
    ScrapeVertical,
    ThrottledResponseError,
    bulk_copy_snapshots_to_neon,
    compute_delta_snapshots,
    compute_product_sk,
    fetch_gold_catalog_for_matching,
    fetch_latest_snapshots_from_neon,
    fetch_tracked_store_ids_from_neon,
    parse_egp_price,
    preview_delta_savings,
    prune_old_raw_snapshots,
    truncate_raw_snapshots_after_dbt,
    update_canonical_keys_in_neon,
    update_gold_canonical_keys_in_neon,
    upsert_snapshots_to_neon,
)
from .brand_normalizer import (
    is_placeholder_brand,
    normalize_product_brand,
)
from .breadfast import BreadfastScraper
from .btech import BTechScraper
from .currency_guard import (
    ALLOWED_COUNTRY,
    ALLOWED_CURRENCY,
    CurrencyFlipAlert,
    ShopifyLocalizationResult,
    detect_store_currency_flips,
    enforce_shopify_egypt_context,
    filter_currency_flip_batches,
    is_same_store_host,
    is_valid_egp_currency,
    normalize_currency_code,
)
from .discovery_state import (
    DiscoveryCheckpoint,
    ensure_discovery_state_table,
    load_discovery_state,
    save_discovery_state,
)
from .expansion_stores import EXPANSION_SCRAPER_CLASSES
from .expansion_stores_wave2 import WAVE2_EXPANSION_SCRAPER_CLASSES
from .groceries import (
    GROCERY_SUB_CATEGORIES,
    compute_grocery_barcode_key,
    compute_grocery_candidate_key,
    compute_grocery_size_key,
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)
from .hyperone import HyperOneScraper
from .matcher import MatchSummary, assign_canonical_keys, compute_candidate_key
from .mi_egypt import MiEgyptScraper
from .noon import NoonScraper
from .platform_stores import (
    PLATFORM_SCRAPER_CLASSES,
    AbuAufScraper,
    ActivScraper,
    CairoSalesScraper,
    CarinaScraper,
    CompuMartsScraper,
    CompuScienceScraper,
    ConcreteScraper,
    DubaiPhoneScraper,
    EgyptLaptopScraper,
    ElArabyScraper,
    ElBadrScraper,
    GourmetScraper,
    ImtenanScraper,
    KhotwhScraper,
    MetroMarketScraper,
    MobacoScraper,
    TradeLineScraper,
)
from .raneen import RaneenScraper
from .rayashop import RayaShopScraper
from .registry_loader import (
    StoreRegistryEntry,
    get_batch_targets,
    get_registry_scraper_classes,
    get_store_tier_map,
    list_active_batches,
    load_stores_registry,
    plan_tiered_waves_for_day,
)
from .seoudi import SeoudiScraper
from .shopify import DalydressScraper, DejavuScraper, ShopifyScraper, TownTeamScraper
from .sigma import SigmaScraper
from .spinneys import SpinneysScraper
from .talabat_eg import TalabatEgScraper
from .two_b import TwoBScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    AmazonEgScraper.store_name: AmazonEgScraper,
    AswaqMozhelaScraper.store_name: AswaqMozhelaScraper,
    BreadfastScraper.store_name: BreadfastScraper,
    BTechScraper.store_name: BTechScraper,
    DalydressScraper.store_name: DalydressScraper,
    DejavuScraper.store_name: DejavuScraper,
    HyperOneScraper.store_name: HyperOneScraper,
    MiEgyptScraper.store_name: MiEgyptScraper,
    NoonScraper.store_name: NoonScraper,
    RaneenScraper.store_name: RaneenScraper,
    RayaShopScraper.store_name: RayaShopScraper,
    SeoudiScraper.store_name: SeoudiScraper,
    SigmaScraper.store_name: SigmaScraper,
    SpinneysScraper.store_name: SpinneysScraper,
    TalabatEgScraper.store_name: TalabatEgScraper,
    TownTeamScraper.store_name: TownTeamScraper,
    TwoBScraper.store_name: TwoBScraper,
    **{cls.store_name: cls for cls in PLATFORM_SCRAPER_CLASSES},
    **{cls.store_name: cls for cls in EXPANSION_SCRAPER_CLASSES},
    **{cls.store_name: cls for cls in WAVE2_EXPANSION_SCRAPER_CLASSES},
}

# Dynamically register any enabled platform stores declared in `stores_registry.yaml`
SCRAPER_REGISTRY.update(get_registry_scraper_classes(SCRAPER_REGISTRY))

__all__ = [
    "AbuAufScraper",
    "ActivScraper",
    "AmazonEgScraper",
    "AswaqMozhelaScraper",
    "BaseScraper",
    "BTechScraper",
    "CairoSalesScraper",
    "CarinaScraper",
    "Category",
    "CompuMartsScraper",
    "CompuScienceScraper",
    "ConcreteScraper",
    "DalydressScraper",
    "DejavuScraper",
    "DiscoveryCheckpoint",
    "DubaiPhoneScraper",
    "EgyptLaptopScraper",
    "ElArabyScraper",
    "ElBadrScraper",
    "GROCERY_SUB_CATEGORIES",
    "GourmetScraper",
    "HyperOneScraper",
    "ImpersonatedHttpClient",
    "ImtenanScraper",
    "KhotwhScraper",
    "MagentoGraphQLBaseScraper",
    "MatchSummary",
    "MetroMarketScraper",
    "MobacoScraper",
    "NoonScraper",
    "PLATFORM_SCRAPER_CLASSES",
    "PoliteHttpClient",
    "RaneenScraper",
    "RawProductSnapshot",
    "RayaShopScraper",
    "SCRAPER_REGISTRY",
    "ScrapeMode",
    "ScrapeVertical",
    "SeoudiScraper",
    "ShopifyBaseScraper",
    "ShopifyScraper",
    "SigmaScraper",
    "SpinneysScraper",
    "ThrottledResponseError",
    "TownTeamScraper",
    "TradeLineScraper",
    "TwoBScraper",
    "WooCommerceBaseScraper",
    "assign_canonical_keys",
    "compute_candidate_key",
    "compute_grocery_barcode_key",
    "compute_grocery_candidate_key",
    "compute_grocery_size_key",
    "ensure_discovery_state_table",
    "extract_grocery_brand",
    "fetch_latest_snapshots_from_neon",
    "fetch_tracked_store_ids_from_neon",
    "load_discovery_state",
    "parse_egp_price",
    "parse_grocery_packaging",
    "prune_old_raw_snapshots",
    "refine_grocery_sub_category",
    "save_discovery_state",
    "update_canonical_keys_in_neon",
    "upsert_snapshots_to_neon",
]
