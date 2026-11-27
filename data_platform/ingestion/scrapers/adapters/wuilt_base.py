"""
Reusable config-driven Wuilt (`wuilt.com`) storefront adapter (`WuiltBaseScraper`).

Queries public Wuilt GraphQL (`https://graphql.wuilt.com`) or storefront `__NEXT_DATA__` /
JSON-LD product catalogs with strict EGP currency guards and in-stock filtering.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urljoin

from ..base import (
    BaseScraper,
    Category,
    RawProductSnapshot,
    ScrapeVertical,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)
from ..currency_guard import is_valid_egp_currency

logger = logging.getLogger(__name__)

WUILT_GRAPHQL_URL = "https://graphql.wuilt.com"
_NEXT_DATA_RE = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

_WUILT_PRODUCTS_QUERY = """
query StoreProducts($storeId: ID!, $first: Int!, $after: String) {
  storeProducts(storeId: $storeId, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      handle
      images { src }
      variants(first: 20) {
        nodes {
          id
          title
          quantity
          price { amount currencyCode }
          compareAtPrice { amount currencyCode }
        }
      }
    }
  }
}
""".strip()


class WuiltBaseScraper(BaseScraper):
    """Config-driven scraper for Egyptian Wuilt (`wuilt.com`) stores."""

    store_name: str = ""
    category: Category = "fashion"
    base_url: str = ""
    wuilt_store_id: str = ""
    default_brand: str = ""
    override_brand: bool = False
    default_limit: int = 2500
    discover_limit: int = 8000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "fashion")
    min_delay_seconds: float = 1.2
    request_timeout: float = 20.0

    def _parse_wuilt_node(
        self,
        node: dict[str, Any],
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        pid = str(node.get("id") or "").strip()
        handle = str(node.get("handle") or "").strip().strip("/")
        title = re.sub(r"\s+", " ", str(node.get("title") or "")).strip()
        if not pid or not handle or len(title) < 2:
            return None

        var_nodes = ((node.get("variants") or {}).get("nodes") or []) if isinstance(node.get("variants"), dict) else []
        if not var_nodes:
            return None

        chosen = None
        any_in_stock = False
        for v in var_nodes:
            if not isinstance(v, dict):
                continue
            qty = v.get("quantity")
            v_ok = qty is None or (isinstance(qty, (int, float)) and qty > 0)
            if v_ok:
                any_in_stock = True
                if chosen is None:
                    chosen = v
        chosen = chosen or var_nodes[0]

        price_obj = chosen.get("price") if isinstance(chosen.get("price"), dict) else {}
        if not is_valid_egp_currency(price_obj.get("currencyCode"), allow_missing=True):
            return None
        current_price = parse_egp_price(price_obj.get("amount"))
        if current_price is None:
            return None

        cmp_obj = chosen.get("compareAtPrice") if isinstance(chosen.get("compareAtPrice"), dict) else {}
        cmp_price = parse_egp_price(cmp_obj.get("amount"))
        claimed_original = cmp_price if (cmp_price is not None and cmp_price > current_price) else None

        imgs = node.get("images") or []
        image_url = imgs[0].get("src") if imgs and isinstance(imgs[0], dict) else None

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": pid[:120],
                "canonical_product_key": None,
                "category": self.category,
                "sub_category": normalize_snake_slug(self.category, fallback="other"),
                "brand": self.default_brand or self.store_name,
                "product_title": title,
                "product_url": urljoin(self.base_url.rstrip("/") + "/", f"products/{handle}"),
                "image_url": image_url,
                "attributes_json": {},
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": any_in_stock,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0 or not self.wuilt_store_id:
            return []

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        cursor: Optional[str] = None

        for _ in range(50):
            if len(snapshots) >= target_limit:
                break
            try:
                resp = self.http.post(
                    WUILT_GRAPHQL_URL,
                    json={
                        "query": _WUILT_PRODUCTS_QUERY,
                        "variables": {"storeId": self.wuilt_store_id, "first": 50, "after": cursor},
                    },
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                if resp.status_code != 200:
                    break
                sp = ((resp.json() or {}).get("data") or {}).get("storeProducts") or {}
            except Exception as exc:
                logger.warning("[%s] Wuilt GraphQL failed: %s", self.store_name, exc)
                break

            nodes = sp.get("nodes") or []
            if not nodes:
                break
            self.pages_fetched += 1
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                rec = self._parse_wuilt_node(node, today, now)
                if rec and rec.external_id not in seen_ids:
                    seen_ids.add(rec.external_id)
                    snapshots.append(rec)
                    if len(snapshots) >= target_limit:
                        break

            page_info = sp.get("pageInfo") or {}
            if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
                break
            cursor = str(page_info["endCursor"])

        return snapshots
