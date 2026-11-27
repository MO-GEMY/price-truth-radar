"""
Reusable config-driven EasyOrders (`easy-orders.net`) storefront adapter (`EasyOrdersBaseScraper`).

Supports:
  1. Public EasyOrders storefront JSON-LD / `__NEXT_DATA__` product catalogs (0 API key required).
  2. Optional authenticated EasyOrders External Apps API (`https://api.easy-orders.net/api/v1/external-apps/products`)
     when `api_key_env` is configured.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

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

EASYORDERS_API_URL = "https://api.easy-orders.net/api/v1/external-apps/products"
_NEXT_DATA_RE = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class EasyOrdersBaseScraper(BaseScraper):
    """Config-driven scraper for Egyptian EasyOrders (`easy-orders.net`) stores."""

    store_name: str = ""
    category: Category = "fashion"
    base_url: str = ""
    default_brand: str = ""
    override_brand: bool = False
    api_key_env: str = ""
    collection_paths: tuple[str, ...] = ("/", "/products")
    default_limit: int = 2500
    discover_limit: int = 8000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "fashion")
    min_delay_seconds: float = 1.2
    request_timeout: float = 20.0

    def _parse_product_obj(
        self,
        item: dict[str, Any],
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        raw_id = item.get("id") or item.get("_id") or item.get("slug") or item.get("sku")
        title = re.sub(r"\s+", " ", str(item.get("name") or item.get("title") or "")).strip()
        if not raw_id or len(title) < 2:
            return None

        currency = item.get("currency") or item.get("currencyCode")
        if not is_valid_egp_currency(currency, allow_missing=True):
            return None

        sale_p = parse_egp_price(item.get("sale_price") or item.get("salePrice"))
        reg_p = parse_egp_price(item.get("price"))
        if sale_p is not None and (reg_p is None or sale_p < reg_p):
            current_price = sale_p
            claimed_original = reg_p if (reg_p is not None and reg_p > sale_p) else None
        else:
            current_price = reg_p
            claimed_original = None
        if current_price is None:
            return None

        slug = str(item.get("slug") or raw_id).strip().strip("/")
        raw_url = str(item.get("url") or "").strip()
        product_url = raw_url if raw_url.startswith("http") else f"{self.base_url.rstrip('/')}/products/{slug}"

        image_url: Optional[str] = None
        for cand in [item.get("thumb"), item.get("image"), item.get("image_url")]:
            if isinstance(cand, str) and cand.startswith("http"):
                image_url = cand
                break
        if not image_url and isinstance(item.get("images"), list) and item["images"]:
            first = item["images"][0]
            if isinstance(first, str) and first.startswith("http"):
                image_url = first
            elif isinstance(first, dict) and str(first.get("url") or "").startswith("http"):
                image_url = str(first["url"])

        qty = item.get("quantity")
        hidden = bool(item.get("hidden", False))
        in_stock = (not hidden) and (qty is None or not isinstance(qty, (int, float)) or qty > 0)

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": str(raw_id).strip()[:120],
                "canonical_product_key": None,
                "category": self.category,
                "sub_category": normalize_snake_slug(str(item.get("category_name") or self.category), fallback="other"),
                "brand": self.default_brand or self.store_name,
                "product_title": title,
                "product_url": product_url,
                "image_url": image_url,
                "attributes_json": {},
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": in_stock,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _extract_from_next_data(self, html: str) -> list[dict[str, Any]]:
        m = _NEXT_DATA_RE.search(html)
        if not m:
            return []
        try:
            doc = json.loads(m.group(1))
        except Exception:
            return []
        found: list[dict[str, Any]] = []

        def _walk(node: Any, depth: int = 0) -> None:
            if depth > 7 or node is None:
                return
            if isinstance(node, list):
                for el in node:
                    _walk(el, depth + 1)
            elif isinstance(node, dict):
                if node.get("name") and node.get("price") is not None and (node.get("id") or node.get("slug")):
                    found.append(node)
                    return
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        _walk(v, depth + 1)

        _walk(doc)
        return found

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()

        api_key = os.getenv(self.api_key_env, "").strip() if self.api_key_env else ""
        if api_key:
            for page in range(1, 50):
                if len(snapshots) >= target_limit:
                    break
                try:
                    resp = self.http.get(
                        EASYORDERS_API_URL,
                        params={"page": page, "limit": 100},
                        headers={"Api-Key": api_key, "Accept": "application/json"},
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    items = data if isinstance(data, list) else (data.get("data") or [])
                except Exception:
                    break
                if not items:
                    break
                self.pages_fetched += 1
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    rec = self._parse_product_obj(item, today, now)
                    if rec and rec.external_id not in seen_ids:
                        seen_ids.add(rec.external_id)
                        snapshots.append(rec)
                        if len(snapshots) >= target_limit:
                            break
                if len(items) < 100:
                    break
            return snapshots

        for path in self.collection_paths:
            if len(snapshots) >= target_limit:
                break
            url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
            try:
                resp = self.http.get(url)
                if resp.status_code != 200:
                    continue
            except Exception:
                continue
            self.pages_fetched += 1
            for item in self._extract_from_next_data(resp.text):
                rec = self._parse_product_obj(item, today, now)
                if rec and rec.external_id not in seen_ids:
                    seen_ids.add(rec.external_id)
                    snapshots.append(rec)
                    if len(snapshots) >= target_limit:
                        break

        return snapshots
