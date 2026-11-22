"""
Live scraper for Seoudi Supermarket Egypt (`https://seoudisupermarket.com`).

Uses `MagentoGraphQLBaseScraper` over plain HTTP against Seoudi's wide-open
Magento Cloud GraphQL host (`https://mcprod.seoudisupermarket.com/graphql`)
as verified in `scripts/wave3_probe_report.md`.
Extracts 13-digit Egypt GS1 EAN barcodes directly from `sku`, EGP final &
regular strikethrough prices, stock, images, and packaging via `groceries.py`.
"""

from __future__ import annotations

from .adapters import MagentoGraphQLBaseScraper
from .base import Category, ScrapeVertical

SEOUDI_GROCERY_QUERIES: tuple[tuple[str, Category, str], ...] = (
    ("oils_ghee", "groceries", "sunflower oil"),
    ("rice_pasta", "groceries", "pasta"),
    ("dairy_cheese", "groceries", "milk"),
    ("tea_coffee", "groceries", "tea"),
    ("canned_sauces", "groceries", "tomato paste"),
    ("beverages", "groceries", "juice"),
    ("detergents", "groceries", "ariel"),
    ("oils_ghee", "groceries", "ghee"),
    ("rice_pasta", "groceries", "rice"),
    ("dairy_cheese", "groceries", "cheese"),
    ("tea_coffee", "groceries", "coffee"),
    ("canned_sauces", "groceries", "tuna"),
    ("beverages", "groceries", "water"),
    ("detergents", "groceries", "persil"),
    ("detergents", "groceries", "fairy"),
)


class SeoudiScraper(MagentoGraphQLBaseScraper):
    """Live Egyptian supermarket scraper for Seoudi Supermarket (plain HTTP GraphQL)."""

    store_name = "seoudi"
    category: Category = "groceries"
    base_url = "https://seoudisupermarket.com"
    graphql_url = "https://mcprod.seoudisupermarket.com/graphql"
    product_url_prefix = "/en/"
    use_impersonation = False
    search_queries = SEOUDI_GROCERY_QUERIES
    default_limit = 200
    groceries_limit = 200
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    min_delay_seconds = 1.5
    request_timeout = 25.0
    page_size = 24
