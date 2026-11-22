"""
Config-driven Magento 2 GraphQL adapter (`MagentoGraphQLBaseScraper`).

Supports both plain HTTP (`PoliteHttpClient`) and optional TLS impersonation
(`ImpersonatedHttpClient` via `curl_cffi`, `impersonate="chrome"`) with graceful
403/WAF handling. Parses `sku`/EAN, `final_price`, `regular_price`, `stock_status`,
`small_image`/`image`, `categories`, and pagination across search queries.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Optional

from ..base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    ThrottledResponseError,
    parse_egp_price,
    utc_now_naive,
)
from ..groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)
from ..two_b import _normalize_brand

logger = logging.getLogger(__name__)

_DEFAULT_GQL_QUERY = """
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
      thumbnail { url }
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

_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")


class MagentoGraphQLBaseScraper(BaseScraper):
    """Config-driven Magento 2 `/graphql` scraper (plain HTTP or `curl_cffi`)."""

    store_name: str = ""
    category: Category = "groceries"
    base_url: str = ""
    graphql_url: str = ""
    product_url_prefix: str = "/en/"  # joined with url_key
    product_url_suffix: str = ""  # e.g. ".html"
    use_impersonation: bool = False
    use_post: bool = False
    store_header: Optional[str] = None
    default_brand: str = ""
    override_brand: bool = False
    gql_query: str = _DEFAULT_GQL_QUERY
    search_queries: tuple[tuple[str, Category, str], ...] = ()  # (sub_category, category, query)
    exclude_category_terms: tuple[str, ...] = ()
    default_limit: int = 200
    discover_limit: int = 320
    groceries_limit: int = 250
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    min_delay_seconds: float = 1.5
    request_timeout: float = 25.0
    page_size: int = 24

    def _clean_title(self, raw_title: str) -> str:
        cleaned = re.sub(r"^\s*[-–—]+\s*", "", raw_title or "")
        return re.sub(r"\s+", " ", cleaned).strip()

    def _build_product_url(self, url_key: str) -> str:
        clean_key = url_key.strip().lstrip("/")
        prefix = self.product_url_prefix
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        if not prefix.endswith("/"):
            prefix += "/"
        return f"{self.base_url.rstrip('/')}{prefix}{clean_key}{self.product_url_suffix}"

    def _extract_ean(self, sku: str, url_key: str) -> Optional[str]:
        digits = re.sub(r"\D", "", sku or "")
        if _EAN_RE.match(digits):
            return digits
        if m := re.search(r"-(\d{8}(?:\d{4,6})?)$", url_key or ""):
            return m.group(1)
        return None

    def _parse_item(
        self,
        item: dict[str, Any],
        default_sub: str,
        cat: Category,
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        sku = str(item.get("sku") or "").strip()
        url_key = str(item.get("url_key") or "").strip()
        title = self._clean_title(str(item.get("name") or ""))
        if not sku or not url_key or len(title) < 3:
            return None

        price_range = item.get("price_range") if isinstance(item.get("price_range"), dict) else {}
        min_price = price_range.get("minimum_price") if isinstance(price_range.get("minimum_price"), dict) else {}
        final_obj = min_price.get("final_price") if isinstance(min_price.get("final_price"), dict) else {}
        regular_obj = min_price.get("regular_price") if isinstance(min_price.get("regular_price"), dict) else {}

        current_price = parse_egp_price(final_obj.get("value"))
        if current_price is None:
            return None
        regular_price = parse_egp_price(regular_obj.get("value"))
        claimed_original = (
            regular_price if (regular_price is not None and regular_price > current_price) else None
        )

        image_url: Optional[str] = None
        for img_key in ("small_image", "image", "thumbnail"):
            img_obj = item.get(img_key)
            if isinstance(img_obj, dict) and img_obj.get("url"):
                cand = str(img_obj["url"]).strip()
                if cand.startswith("http") and "placeholder" not in cand.lower():
                    image_url = cand
                    break

        cat_names = [
            str(c.get("name")).strip()
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        cat_low = " ".join(cat_names).lower()
        if self.exclude_category_terms and any(term in cat_low for term in self.exclude_category_terms):
            return None

        ean = self._extract_ean(sku, url_key)
        external_id = (ean or sku)[:120]

        raw_brand: Optional[str] = None
        brand_field = item.get("brand")
        if isinstance(brand_field, dict) and brand_field.get("name"):
            raw_brand = str(brand_field["name"]).strip()
        elif isinstance(brand_field, str) and brand_field.strip():
            raw_brand = brand_field.strip()

        if cat == "groceries":
            brand = self.default_brand if self.override_brand and self.default_brand else extract_grocery_brand(title, raw_brand or self.default_brand)
            sub_category = refine_grocery_sub_category(f"{title} {' '.join(cat_names)}", default_sub)
        elif self.override_brand and self.default_brand:
            brand = self.default_brand
            sub_category = default_sub
        else:
            brand = _normalize_brand(raw_brand or self.default_brand or None, title)
            sub_category = default_sub

        attrs: dict[str, Any] = {f"{self.store_name}_category": cat_names[0] if cat_names else sub_category}
        if ean:
            attrs["ean"] = ean
        if cat == "groceries":
            attrs.update(parse_grocery_packaging(title, raw_payload={"ean": ean} if ean else None))

        stock_status = str(item.get("stock_status") or "IN_STOCK").upper()
        in_stock = stock_status == "IN_STOCK"

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": cat,
                "sub_category": sub_category,
                "brand": brand[:100],
                "product_title": title,
                "product_url": self._build_product_url(url_key),
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": in_stock,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _run_queries(self, fetcher: Any, target_limit: int) -> list[RawProductSnapshot]:
        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        queries = self.search_queries or ((self.category, self.category, "a"),)
        per_query_cap = max(2, math.ceil(target_limit / len(queries)))
        max_pages = 2 if target_limit <= 100 else 3
        blocked = False

        extra_headers = {"Accept": "application/json, text/plain, */*"}
        if self.store_header:
            extra_headers["Store"] = self.store_header

        for default_sub, cat, query in queries:
            if len(snapshots) >= target_limit or blocked:
                break
            query_collected = 0

            for page in range(1, max_pages + 1):
                if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                    break

                logger.info("[%s] Fetching GraphQL query=%r (%s) page %d", self.store_name, query, default_sub, page)
                variables_dict = {"search": query, "pageSize": self.page_size, "currentPage": page}
                variables_json = (
                    f'{{"search": "{query}", "pageSize": {self.page_size}, "currentPage": {page}}}'
                )
                try:
                    if self.use_post:
                        post_headers = {"Content-Type": "application/json", **extra_headers}
                        post_body = {"query": self.gql_query, "variables": variables_dict}
                        if self.use_impersonation:
                            resp = fetcher.post(
                                self.graphql_url,
                                json=post_body,
                                headers=post_headers,
                                min_delay_seconds=effective_delay,
                                timeout=self.request_timeout,
                                check_throttle=False,
                            )
                        else:
                            resp = fetcher.post(
                                self.graphql_url,
                                json=post_body,
                                headers=post_headers,
                                min_delay_seconds=effective_delay,
                                timeout=self.request_timeout,
                            )
                    elif self.use_impersonation:
                        resp = fetcher.get(
                            self.graphql_url,
                            params={"query": self.gql_query, "variables": variables_json},
                            headers=extra_headers,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=False,
                        )
                    else:
                        resp = fetcher.get(
                            self.graphql_url,
                            params={"query": self.gql_query, "variables": variables_json},
                            headers=extra_headers,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                        )
                except ThrottledResponseError as exc:
                    logger.warning("[%s] WAF/403 block on query=%r (%s); exiting gracefully.", self.store_name, query, exc)
                    blocked = True
                    break
                except Exception as exc:
                    logger.warning("[%s] GraphQL error on query=%r page %d: %s", self.store_name, query, page, exc)
                    break

                self.pages_fetched += 1
                try:
                    payload = resp.json()
                except Exception:
                    logger.warning("[%s] Non-JSON GraphQL response (HTTP %s); exiting gracefully.", self.store_name, resp.status_code)
                    blocked = True
                    break

                if payload.get("errors"):
                    logger.warning("[%s] GraphQL errors for query=%r: %s", self.store_name, query, payload["errors"])
                    break

                products_block = (payload.get("data") or {}).get("products") or {}
                raw_items = products_block.get("items") or []
                if not raw_items:
                    break

                page_records: list[RawProductSnapshot] = []
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    rec = self._parse_item(raw, default_sub, cat, today, now)
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

        logger.info("[%s] Per-subcategory counts: %s", self.store_name, self.category_counts)
        return snapshots

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        if self.use_impersonation:
            with ImpersonatedHttpClient(
                impersonate="chrome",
                timeout=self.request_timeout or 30.0,
                max_retries=3,
                backoff_base=2.0,
                min_delay_seconds=max(self.min_delay_seconds, self.http.min_delay_seconds),
                jitter_range=(0.3, 1.0),
            ) as client:
                return self._run_queries(client, target_limit)

        return self._run_queries(self.http, target_limit)
