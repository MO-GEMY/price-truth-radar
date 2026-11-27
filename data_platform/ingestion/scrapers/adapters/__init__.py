"""Reusable platform scraper adapters for Shopify, Magento 2 GraphQL, WooCommerce, and Sllr."""

from .magento_graphql_base import MagentoGraphQLBaseScraper
from .shopify_base import ShopifyBaseScraper
from .sllr_base import SllrBaseScraper
from .woocommerce_base import WooCommerceBaseScraper

__all__ = [
    "MagentoGraphQLBaseScraper",
    "ShopifyBaseScraper",
    "SllrBaseScraper",
    "WooCommerceBaseScraper",
]
