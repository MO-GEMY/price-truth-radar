"""Reusable scraper foundation and store scrapers for Price Truth Radar."""

from __future__ import annotations

from .base import (
    BaseScraper,
    Category,
    PoliteHttpClient,
    RawProductSnapshot,
    fetch_latest_snapshots_from_neon,
    parse_egp_price,
    update_canonical_keys_in_neon,
    upsert_snapshots_to_neon,
)
from .btech import BTechScraper
from .matcher import MatchSummary, assign_canonical_keys, compute_candidate_key
from .shopify import DalydressScraper, DejavuScraper, ShopifyScraper, TownTeamScraper
from .sigma import SigmaScraper
from .two_b import TwoBScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    BTechScraper.store_name: BTechScraper,
    DalydressScraper.store_name: DalydressScraper,
    DejavuScraper.store_name: DejavuScraper,
    SigmaScraper.store_name: SigmaScraper,
    TownTeamScraper.store_name: TownTeamScraper,
    TwoBScraper.store_name: TwoBScraper,
}

__all__ = [
    "BaseScraper",
    "BTechScraper",
    "Category",
    "DalydressScraper",
    "DejavuScraper",
    "MatchSummary",
    "PoliteHttpClient",
    "RawProductSnapshot",
    "SCRAPER_REGISTRY",
    "ShopifyScraper",
    "SigmaScraper",
    "TownTeamScraper",
    "TwoBScraper",
    "assign_canonical_keys",
    "compute_candidate_key",
    "fetch_latest_snapshots_from_neon",
    "parse_egp_price",
    "update_canonical_keys_in_neon",
    "upsert_snapshots_to_neon",
]
