"""Reusable platform scraper adapters for Shopify, Magento 2 GraphQL, and WooCommerce."""

from .magento_graphql_base import MagentoGraphQLBaseScraper
from .shopify_base import ShopifyBaseScraper
from .woocommerce_base import WooCommerceBaseScraper

__all__ = [
    "MagentoGraphQLBaseScraper",
    "ShopifyBaseScraper",
    "WooCommerceBaseScraper",
]
