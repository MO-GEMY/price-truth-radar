"""Reusable scraper foundation and store scrapers for Price Truth Radar."""

from __future__ import annotations

from .base import (
    BaseScraper,
    PoliteHttpClient,
    RawProductSnapshot,
    parse_egp_price,
    upsert_snapshots_to_neon,
)
from .btech import BTechScraper
from .sigma import SigmaScraper
from .two_b import TwoBScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    BTechScraper.store_name: BTechScraper,
    SigmaScraper.store_name: SigmaScraper,
    TwoBScraper.store_name: TwoBScraper,
}

__all__ = [
    "BaseScraper",
    "BTechScraper",
    "PoliteHttpClient",
    "RawProductSnapshot",
    "SCRAPER_REGISTRY",
    "SigmaScraper",
    "TwoBScraper",
    "parse_egp_price",
    "upsert_snapshots_to_neon",
]
