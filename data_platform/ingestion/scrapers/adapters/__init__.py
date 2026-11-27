"""Reusable platform scraper adapters for Shopify, Magento 2 GraphQL, WooCommerce, Sllr, EasyOrders, and Wuilt."""

from .easyorders_base import EasyOrdersBaseScraper
from .magento_graphql_base import MagentoGraphQLBaseScraper
from .shopify_base import ShopifyBaseScraper
from .sllr_base import SllrBaseScraper
from .woocommerce_base import WooCommerceBaseScraper
from .wuilt_base import WuiltBaseScraper

__all__ = [
    "EasyOrdersBaseScraper",
    "MagentoGraphQLBaseScraper",
    "ShopifyBaseScraper",
    "SllrBaseScraper",
    "WooCommerceBaseScraper",
    "WuiltBaseScraper",
]
