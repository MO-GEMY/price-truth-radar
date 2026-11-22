"""
Live scraper for HyperOne Egypt (`https://www.hyperone.com.eg`).

Uses `curl_cffi` TLS impersonation (`ImpersonatedHttpClient`, `impersonate="chrome"`)
against HyperOne's on-origin Magento Cloud GraphQL endpoint (`/graphql`) — which
exposes full product pricing, stock, categories, images, and 13-digit Egypt GS1
EAN barcodes (`sku`) — plus an SSR Nuxt payload helper (`parse_nuxt_product_html`)
matching `scripts/supermarket_probe_report.md`.

Includes graceful 403/WAF detection so datacenter blocks log clearly and return
without crashing the rest of the groceries pipeline.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Optional

from .base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    ThrottledResponseError,
    parse_egp_price,
    utc_now_naive,
)
from .groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)

logger = logging.getLogger(__name__)

# 7 high-frequency Egyptian household sub-categories (interleaved for balanced caps)
HYPERONE_GROCERY_QUERIES: list[tuple[str, str]] = [
    ("oils_ghee", "crystal oil"),
    ("rice_pasta", "pasta"),
    ("dairy_cheese", "juhayna milk"),
    ("tea_coffee", "lipton tea"),
    ("canned_sauces", "tomato paste"),
    ("beverages", "juhayna juice"),
    ("detergents", "ariel"),
    ("oils_ghee", "ghee"),
    ("rice_pasta", "rice"),
    ("dairy_cheese", "cheese"),
    ("tea_coffee", "nescafe"),
    ("canned_sauces", "tuna"),
    ("beverages", "pepsi"),
    ("detergents", "persil"),
    ("detergents", "fairy"),
]

_HYPERONE_GQL_QUERY = """
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

_EAN_RE = re.compile(r"\b(\d{8}(?:\d{4,6})?)\b")
_NUXT_DATA_RE = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)


def parse_nuxt_product_html(html: str) -> Optional[dict[str, Any]]:
    """
    Parse HyperOne's SSR `__NUXT_DATA__` script payload on a product detail page
    for `price`, `priceBefore`, `stock`, `sku`, `thumbnail`, etc.
    """
    m = _NUXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        arr = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list):
        return None

    def _resolve(val: Any, depth: int = 0) -> Any:
        if depth > 4:
            return val
        if isinstance(val, int) and 0 <= val < len(arr):
            return _resolve(arr[val], depth + 1)
        return val

    for entry in arr:
        if isinstance(entry, dict) and "price" in entry and "sku" in entry:
            return {
                "name": _resolve(entry.get("name")),
                "sku": _resolve(entry.get("sku")),
                "price": _resolve(entry.get("price")),
                "priceBefore": _resolve(entry.get("priceBefore")),
                "stock": _resolve(entry.get("stock")),
                "thumbnail": _resolve(entry.get("thumbnail")),
            }
    return None


def _extract_hyperone_ean(sku: str, url_key: str) -> Optional[str]:
    """Extract 8–14 digit GS1/EAN barcode from HyperOne `sku` or `url_key` tail."""
    digits = re.sub(r"\D", "", sku or "")
    if re.fullmatch(r"\d{8}(?:\d{4,6})?", digits):
        return digits
    if m := re.search(r"-(\d{8}(?:\d{4,6})?)$", url_key or ""):
        return m.group(1)
    if m := _EAN_RE.search(url_key or ""):
        return m.group(1)
    return None


class HyperOneScraper(BaseScraper):
    """Live Egyptian supermarket scraper for HyperOne (`curl_cffi` impersonation)."""

    store_name = "hyperone"
    category: Category = "groceries"
    base_url = "https://www.hyperone.com.eg"
    graphql_url = "https://www.hyperone.com.eg/graphql"
    default_limit = 350
    groceries_limit = 350
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    min_delay_seconds = 2.0
    request_timeout = 30.0
    page_size = 24

    def _parse_item(
        self,
        item: dict[str, Any],
        default_sub: str,
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        sku = str(item.get("sku") or "").strip()
        url_key = str(item.get("url_key") or "").strip().lstrip("/")
        title = re.sub(r"\s+", " ", str(item.get("name") or "")).strip()
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
        img_obj = item.get("small_image")
        if isinstance(img_obj, dict) and img_obj.get("url"):
            cand = str(img_obj["url"]).strip()
            if cand.startswith("http") and "placeholder" not in cand.lower():
                image_url = cand

        cat_names = [
            str(c.get("name")).strip()
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        # Skip non-grocery kitchenware/glassware that can show up on "crystal" searches
        cat_low = " ".join(cat_names).lower()
        if any(bad in cat_low for bad in ("glassware", "dinnerware", "cookware", "homeware", "appliances")):
            return None

        brand = extract_grocery_brand(title)
        sub_category = refine_grocery_sub_category(f"{title} {' '.join(cat_names)}", default_sub)

        ean = _extract_hyperone_ean(sku, url_key)
        external_id = (ean or sku)[:120]

        attrs: dict[str, Any] = {"hyperone_category": cat_names[0] if cat_names else sub_category}
        attrs.update(parse_grocery_packaging(title, raw_payload={"ean": ean} if ean else None))
        if ean:
            attrs["ean"] = ean

        stock_status = str(item.get("stock_status") or "IN_STOCK").upper()
        in_stock = stock_status == "IN_STOCK"

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": "groceries",
                "sub_category": sub_category,
                "brand": brand,
                "product_title": title,
                "product_url": f"{self.base_url}/en/product/{url_key}",
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
        per_query_cap = max(2, math.ceil(target_limit / len(HYPERONE_GROCERY_QUERIES)))
        max_pages = 2 if target_limit <= 100 else 3
        blocked = False

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 30.0,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 1.0),
            headers={"Accept": "application/json, text/plain, */*"},
        ) as client:
            for default_sub, query in HYPERONE_GROCERY_QUERIES:
                if len(snapshots) >= target_limit or blocked:
                    break
                query_collected = 0

                for page in range(1, max_pages + 1):
                    if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                        break

                    logger.info("[hyperone] Fetching query=%r (%s) page %d", query, default_sub, page)
                    variables_json = (
                        f'{{"search": "{query}", "pageSize": {self.page_size}, "currentPage": {page}}}'
                    )
                    try:
                        resp = client.get(
                            self.graphql_url,
                            params={"query": _HYPERONE_GQL_QUERY, "variables": variables_json},
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=False,
                        )
                    except ThrottledResponseError as exc:
                        logger.warning(
                            "[hyperone] WAF/403 or throttle block detected on query=%r page %d (%s); "
                            "exiting gracefully with %d collected snapshots.",
                            query,
                            page,
                            exc,
                            len(snapshots),
                        )
                        blocked = True
                        break
                    except Exception as exc:
                        logger.warning("[hyperone] Request error for query=%r page %d: %s", query, page, exc)
                        break

                    self.pages_fetched += 1
                    try:
                        payload = resp.json()
                    except Exception:
                        body_snippet = (resp.text or "")[:160].replace("\n", " ")
                        logger.warning(
                            "[hyperone] Non-JSON response (HTTP %s, snippet=%r); treating as WAF block and exiting gracefully.",
                            resp.status_code,
                            body_snippet,
                        )
                        blocked = True
                        break

                    if payload.get("errors"):
                        logger.warning("[hyperone] GraphQL errors for query=%r: %s", query, payload["errors"])
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

        logger.info("[hyperone] Per-subcategory counts: %s", self.category_counts)
        return snapshots
