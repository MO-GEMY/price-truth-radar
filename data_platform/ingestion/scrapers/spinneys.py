"""
Live scraper for Spinneys Egypt (`https://spinneys-egypt.com`).

Uses plain HTTP (`PoliteHttpClient` / `httpx`) against Spinneys Egypt's on-origin
Magento GraphQL endpoint (`/graphql`) as documented in `scripts/supermarket_probe_report.md`.
Targets the 7 Egyptian household grocery sub-categories (`category="groceries"`)
with safe pacing and packaging normalization via `groceries.py`.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Optional

from .base import (
    BaseScraper,
    Category,
    RawProductSnapshot,
    ScrapeVertical,
    parse_egp_price,
    utc_now_naive,
)
from .currency_guard import is_valid_egp_currency
from .groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)

logger = logging.getLogger(__name__)

# 7 high-frequency Egyptian household sub-categories (interleaved for balanced caps)
SPINNEYS_GROCERY_QUERIES: list[tuple[str, str]] = [
    ("oils_ghee", "sunflower oil"),
    ("rice_pasta", "pasta"),
    ("dairy_cheese", "milk"),
    ("tea_coffee", "tea"),
    ("canned_sauces", "tomato paste"),
    ("beverages", "juice"),
    ("detergents", "ariel"),
    ("oils_ghee", "ghee"),
    ("rice_pasta", "rice"),
    ("dairy_cheese", "cheese"),
    ("tea_coffee", "coffee"),
    ("canned_sauces", "tuna"),
    ("beverages", "water"),
    ("detergents", "persil"),
    ("detergents", "fairy"),
    ("snacks", "chocolate"),
    ("snacks", "biscuits"),
    ("frozen", "chicken"),
    ("canned_sauces", "honey"),
    ("detergents", "shampoo"),
    ("detergents", "tissue"),
    ("baby_care", "diapers"),
    ("pet_food", "cat food"),
]

_SPINNEYS_GQL_QUERY = """
query SearchProducts($search: String!, $pageSize: Int!, $currentPage: Int!) {
  products(search: $search, pageSize: $pageSize, currentPage: $currentPage) {
    total_count
    page_info {
      current_page
      total_pages
    }
    items {
      name
      sku
      url_key
      stock_status
      small_image { url }
      image { url }
      brand { name }
      categories { name }
      price_range {
        minimum_price {
          final_price { value currency }
          regular_price { value }
        }
      }
    }
  }
}
""".strip()


def _clean_spinneys_title(raw_title: str) -> str:
    """Strip leading/trailing dashes Spinneys occasionally places on SKUs."""
    cleaned = re.sub(r"^\s*[-–—]+\s*", "", raw_title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class SpinneysScraper(BaseScraper):
    """Live Egyptian supermarket scraper for Spinneys Egypt (plain HTTP GraphQL)."""

    store_name = "spinneys"
    category: Category = "groceries"
    base_url = "https://spinneys-egypt.com"
    graphql_url = "https://spinneys-egypt.com/graphql"
    default_limit = 350
    groceries_limit = 350
    discover_groceries_limit = 1000
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    min_delay_seconds = 1.5
    request_timeout = 18.0
    page_size = 24
    max_consecutive_errors = 3

    def _parse_item(
        self,
        item: dict[str, Any],
        default_sub: str,
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        sku = str(item.get("sku") or "").strip()
        url_key = str(item.get("url_key") or "").strip().lstrip("/")
        raw_title = str(item.get("name") or "").strip()
        title = _clean_spinneys_title(raw_title)
        if not sku or not url_key or len(title) < 3:
            return None

        price_range = item.get("price_range") if isinstance(item.get("price_range"), dict) else {}
        min_price = price_range.get("minimum_price") if isinstance(price_range.get("minimum_price"), dict) else {}
        final_obj = min_price.get("final_price") if isinstance(min_price.get("final_price"), dict) else {}
        regular_obj = min_price.get("regular_price") if isinstance(min_price.get("regular_price"), dict) else {}

        if not is_valid_egp_currency(final_obj.get("currency"), allow_missing=True):
            logger.error("CURRENCY_MISMATCH_ABORT | store=spinneys | item=%s returned currency=%r", sku, final_obj.get("currency"))
            return None

        current_price = parse_egp_price(final_obj.get("value"))
        if current_price is None:
            return None

        regular_price = parse_egp_price(regular_obj.get("value"))
        claimed_original = (
            regular_price if (regular_price is not None and regular_price > current_price) else None
        )

        image_url: Optional[str] = None
        for img_key in ("small_image", "image"):
            img_obj = item.get(img_key)
            if isinstance(img_obj, dict) and img_obj.get("url"):
                cand = str(img_obj["url"]).strip()
                if cand.startswith("http") and "placeholder" not in cand.lower():
                    image_url = cand
                    break

        brand_obj = item.get("brand")
        raw_brand = str(brand_obj.get("name")).strip() if isinstance(brand_obj, dict) and brand_obj.get("name") else None
        brand = extract_grocery_brand(title, raw_brand)

        cat_names = [
            str(c.get("name")).strip()
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        sub_category = refine_grocery_sub_category(f"{title} {' '.join(cat_names)}", default_sub)

        attrs: dict[str, Any] = {"spinneys_category": cat_names[0] if cat_names else sub_category}
        attrs.update(parse_grocery_packaging(title, raw_payload={"sku": sku}))
        if re.fullmatch(r"\d{8}(?:\d{4,6})?", sku) and "ean" not in attrs:
            attrs["ean"] = sku

        stock_status = str(item.get("stock_status") or "IN_STOCK").upper()
        in_stock = stock_status == "IN_STOCK"

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": sku[:120],
                "canonical_product_key": None,
                "category": "groceries",
                "sub_category": sub_category,
                "brand": brand,
                "product_title": title,
                "product_url": f"{self.base_url}/en/{url_key}",
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": in_stock,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}

        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_query_cap = max(2, math.ceil(target_limit / len(SPINNEYS_GROCERY_QUERIES)))
        max_pages = 8 if self.mode in ("discover", "expand") else (2 if target_limit <= 100 else 3)
        consecutive_errors = 0

        for default_sub, query in SPINNEYS_GROCERY_QUERIES:
            if len(snapshots) >= target_limit or consecutive_errors >= self.max_consecutive_errors:
                break
            query_collected = 0

            for page in range(1, max_pages + 1):
                if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                    break

                logger.info("[spinneys] Fetching query=%r (%s) page %d", query, default_sub, page)
                variables_json = (
                    f'{{"search": "{query}", "pageSize": {self.page_size}, "currentPage": {page}}}'
                )
                try:
                    resp = self.http.get(
                        self.graphql_url,
                        params={"query": _SPINNEYS_GQL_QUERY, "variables": variables_json},
                        min_delay_seconds=effective_delay,
                        timeout=self.request_timeout,
                    )
                    payload = resp.json()
                    consecutive_errors = 0
                except Exception as exc:
                    consecutive_errors += 1
                    logger.warning(
                        "[spinneys] GraphQL error for query=%r page %d (%d/%d): %s",
                        query,
                        page,
                        consecutive_errors,
                        self.max_consecutive_errors,
                        exc,
                    )
                    if consecutive_errors >= self.max_consecutive_errors:
                        logger.warning("[spinneys] Failing fast after %d consecutive GraphQL errors.", consecutive_errors)
                    break

                self.pages_fetched += 1
                if payload.get("errors"):
                    logger.warning("[spinneys] GraphQL errors for query=%r: %s", query, payload["errors"])
                    break

                products_block = (payload.get("data") or {}).get("products") or {}
                raw_items = products_block.get("items") or []
                if not raw_items:
                    break

                page_records: list[RawProductSnapshot] = []
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    rec = self._parse_item(raw, default_sub, today, now)
                    if rec is not None and rec.external_id not in seen_ids:
                        page_records.append(rec)

                page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                added = 0
                for rec in page_records:
                    if rec.external_id in seen_ids:
                        continue
                    seen_ids.add(rec.external_id)
                    snapshots.append(rec)
                    query_collected += 1
                    added += 1
                    if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                        break

                page_info = products_block.get("page_info") or {}
                total_pages = int(page_info.get("total_pages") or 1)
                if page >= total_pages or added == 0:
                    break

            self.category_counts[default_sub] = self.category_counts.get(default_sub, 0) + query_collected

        logger.info("[spinneys] Per-subcategory counts: %s", self.category_counts)
        return snapshots
