"""
Sanctioned offline ingestion adapter for Talabat Egypt (`talabat_eg`, `region_mode: local_only`).

NOTE: `www.talabat.com` enforces Cloudflare WAF (`HTTP 403`) against automated HTTP clients.
This adapter NEVER attempts to bypass Cloudflare or solve anti-bot challenges. Instead,
it operates strictly via two sanctioned ingestion paths (0 CU during scraping):

1. Authorized Partner / Configured API Mode (optional `.env` config):
   - `TALABAT_API_BASE`   : Authorized Talabat Partner / catalog JSON API base URL
   - `TALABAT_AUTH_TOKEN` : Optional OAuth2 Bearer token
   - `TALABAT_VENDOR_ID`  : Optional Talabat Mart / branch vendor ID
   - `TALABAT_LAT` / `TALABAT_LNG`: Deterministic Cairo coordinates (default `30.0561`, `31.3301` — Nasr City)

2. Local Captured Feed / HAR Ingestion Mode (automatic):
   - Scans `data/manual_feeds/talabat_eg/` (or `TALABAT_FEED_DIR`) for `.har`, `.json`, and `.jsonl` files
     exported from a user's own browser or authorized partner catalog export.
   - Normalizes every item into `RawProductSnapshot` records compatible with
     `silver.stg_products`, `gold.fct_price_history`, and `gold.mart_product_verdicts`,
     with direct `https://www.talabat.com/egypt/...` product URLs.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from .base import (
    BaseScraper,
    Category,
    REPO_ROOT,
    RawProductSnapshot,
    ScrapeVertical,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)
from .breadfast import (
    DEFAULT_CAIRO_LAT,
    DEFAULT_CAIRO_LNG,
    _extract_image_url,
    _extract_in_stock,
    _extract_prices,
    _first_non_empty,
    extract_product_dicts,
    iter_json_payloads_from_feed_dir,
    map_retail_department_to_category,
)
from .currency_guard import is_valid_egp_currency
from .groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
)

logger = logging.getLogger(__name__)

DEFAULT_TALABAT_FEED_DIR = REPO_ROOT / "data" / "manual_feeds" / "talabat_eg"
_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")


class TalabatEgScraper(BaseScraper):
    """Sanctioned Authorized-API & HAR/JSON Feed adapter for Talabat Egypt (`local_only`)."""

    store_name = "talabat_eg"
    category: Category = "groceries"
    base_url = "https://www.talabat.com/egypt"
    default_limit = 5000
    discover_limit = 15000
    groceries_limit = 5000
    discover_groceries_limit = 15000
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries", "core")
    min_delay_seconds = 1.5
    request_timeout = 20.0

    def __init__(
        self,
        *args: Any,
        feed_dir: Optional[Path] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        env_dir = (os.getenv("TALABAT_FEED_DIR") or "").strip()
        self.feed_dir = feed_dir or (Path(env_dir) if env_dir else DEFAULT_TALABAT_FEED_DIR)
        self.api_base = (os.getenv("TALABAT_API_BASE") or "").strip().rstrip("/")
        self.auth_token = (os.getenv("TALABAT_AUTH_TOKEN") or "").strip()
        self.vendor_id = (os.getenv("TALABAT_VENDOR_ID") or "").strip()
        self.cairo_lat = float(os.getenv("TALABAT_LAT") or DEFAULT_CAIRO_LAT)
        self.cairo_lng = float(os.getenv("TALABAT_LNG") or DEFAULT_CAIRO_LNG)

    def _build_product_url(self, sku: str, item: dict[str, Any]) -> str:
        raw_url = str(item.get("product_url") or item.get("productUrl") or item.get("url") or "").strip()
        if raw_url.startswith("https://www.talabat.com/egypt/"):
            return raw_url
        if raw_url.startswith("/egypt/"):
            return f"https://www.talabat.com{raw_url}"
        slug = str(item.get("slug") or "").strip().strip("/")
        vendor = str(item.get("vendor_id") or item.get("vendorId") or self.vendor_id or "talabat-mart").strip()
        if slug:
            return f"https://www.talabat.com/egypt/grocery/{quote(vendor, safe='-_.')}/{quote(slug, safe='-_.')}"
        return f"https://www.talabat.com/egypt/grocery/{quote(vendor, safe='-_.')}?item={quote(sku, safe='-_.')}"

    def _parse_product_dict(
        self,
        item: dict[str, Any],
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        raw_id = _first_non_empty(item, ("sku", "id", "item_id", "itemId", "product_id", "productId", "remoteId", "code"))
        raw_title = _first_non_empty(item, ("name_en", "en_name", "name", "title", "product_name", "productName"))
        if raw_id is None or raw_title is None:
            return None

        sku = str(raw_id).strip()[:120]
        title = re.sub(r"\s+", " ", str(raw_title)).strip()
        if not sku or len(title) < 3:
            return None

        cur_raw, orig_raw, currency = _extract_prices(item)
        if not is_valid_egp_currency(currency, allow_missing=True):
            logger.error("CURRENCY_MISMATCH_ABORT | store=talabat_eg | sku=%s currency=%r", sku, currency)
            return None

        current_price = parse_egp_price(cur_raw)
        if current_price is None:
            return None

        orig_price = parse_egp_price(orig_raw) if orig_raw is not None else None
        claimed_original = orig_price if (orig_price is not None and orig_price > current_price) else None

        dept_parts: list[str] = []
        for k in ("department", "category", "category_name", "categoryName", "sectionName", "sub_category", "subcategory"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                dept_parts.append(v.strip())
            elif isinstance(v, dict) and v.get("name"):
                dept_parts.append(str(v["name"]).strip())
        dept_text = " ".join(dept_parts)

        category, sub_category = map_retail_department_to_category(title, dept_text)
        raw_brand_val = _first_non_empty(item, ("brand", "brand_name", "brandName", "vendor", "manufacturer"))
        if isinstance(raw_brand_val, dict):
            raw_brand_val = raw_brand_val.get("name")
        raw_brand = str(raw_brand_val).strip() if raw_brand_val else None
        brand = extract_grocery_brand(title, raw_brand) if category == "groceries" else (raw_brand or "Unknown")

        attrs: dict[str, Any] = {
            "cairo_coords": f"{self.cairo_lat:.4f},{self.cairo_lng:.4f}",
        }
        if self.vendor_id:
            attrs["talabat_vendor_id"] = self.vendor_id
        if dept_parts:
            attrs["talabat_category"] = dept_parts[0][:80]
        if category == "groceries":
            attrs.update(parse_grocery_packaging(title, raw_payload=item))
        barcode = _first_non_empty(item, ("barcode", "ean", "gtin"))
        if barcode and _EAN_RE.match(str(barcode).strip()):
            attrs["ean"] = str(barcode).strip()

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": sku,
                "canonical_product_key": None,
                "category": category,
                "sub_category": normalize_snake_slug(sub_category, fallback="other"),
                "brand": brand,
                "product_title": title,
                "product_url": self._build_product_url(sku, item),
                "image_url": _extract_image_url(item),
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": _extract_in_stock(item),
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _fetch_from_authorized_api(self, limit: int) -> list[dict[str, Any]]:
        """Mode A: Fetch catalog items from configured `TALABAT_API_BASE` (graceful stop on 403/429)."""
        if not self.api_base:
            return []

        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = (
                self.auth_token if self.auth_token.lower().startswith("bearer ") else f"Bearer {self.auth_token}"
            )

        collected_raw: list[dict[str, Any]] = []
        base_params: dict[str, Any] = {
            "lat": self.cairo_lat,
            "lon": self.cairo_lng,
            "countrySlug": "egypt",
        }
        if self.vendor_id:
            base_params["vendorId"] = self.vendor_id

        page = 1
        max_pages = max(1, min(100, (limit // 50) + 2))
        while len(collected_raw) < limit and page <= max_pages:
            params = {**base_params, "page": page, "limit": 50}
            try:
                resp = self.http.get(self.api_base, params=params, headers=headers)
                if resp.status_code in (401, 403, 404, 429):
                    logger.warning("[talabat_eg] API returned HTTP %d on page %d; stopping gracefully.", resp.status_code, page)
                    break
                payload = resp.json()
            except Exception as exc:
                logger.warning("[talabat_eg] API request failed on page %d: %s", page, exc)
                break

            self.pages_fetched += 1
            batch = extract_product_dicts(payload)
            if not batch:
                break
            collected_raw.extend(batch)
            if len(batch) < 20:
                break
            page += 1

        return collected_raw

    def _load_from_manual_feeds(self) -> list[dict[str, Any]]:
        """Mode B: Parse all `.har`, `.json`, and `.jsonl` files placed in `data/manual_feeds/talabat_eg/`."""
        items: list[dict[str, Any]] = []
        for source_name, payload in iter_json_payloads_from_feed_dir(self.feed_dir):
            batch = extract_product_dicts(payload)
            if batch:
                logger.info("[talabat_eg] Parsed %d candidate items from %s", len(batch), source_name)
                items.extend(batch)
        return items

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()

        raw_items: list[dict[str, Any]] = []
        raw_items.extend(self._fetch_from_authorized_api(target_limit))
        raw_items.extend(self._load_from_manual_feeds())

        if not raw_items:
            logger.info(
                "[talabat_eg] No authorized API (TALABAT_API_BASE) or feed files found in %s; returning 0 records.",
                self.feed_dir,
            )
            return []

        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        for item in raw_items:
            if len(snapshots) >= target_limit:
                break
            rec = self._parse_product_dict(item, today, now)
            if rec is None or rec.external_id in seen_ids:
                continue
            seen_ids.add(rec.external_id)
            snapshots.append(rec)

        return snapshots
