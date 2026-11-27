"""
Live scraper for Mi Store Egypt (`https://mistore-eg.com`, `store_name = "mi_egypt"`).

Mi Store Egypt runs an Angular SPA backed by a public Laravel JSON API at
`https://api.mistore-eg.com/api/customer/products/search?page={P}` (plain HTTP,
no Cloudflare WAF, `region_mode: cloud`).

Extracts all Xiaomi / Redmi / POCO Egypt catalog items:
- `external_id`            : product `id` (string)
- `current_price`          : `discount_price` when strictly `< price`, else `price` (EGP)
- `claimed_original_price` : `price` when discounted, else `None`
- `in_stock`               : `active and in_stock and not available_soon and stock > 0`
- `product_url`            : `share_link` (or `https://mistore-eg.com/en/{slug}`)
- `ean`                    : 13-digit GS1 barcode extracted from `barcode` or `sku` suffix (e.g. `17773-6941812791240`)
"""

from __future__ import annotations

import logging
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
from .noon import _extract_specs, _refine_sub_category

logger = logging.getLogger(__name__)

_EAN_SUFFIX_RE = re.compile(r"(?:^|[-_\s])(\d{13})$")
_APPLIANCE_TITLE_RE = re.compile(
    r"\b(?:tv|television|air\s*fryer|vacuum|robot\s*vacuum|kettle|blender|heater|fan|"
    r"air\s*purifier|humidifier|dehumidifier|induction|rice\s*cooker|microwave|dispenser|iron|steamer)\b",
    re.I,
)
_PERSONAL_CARE_RE = re.compile(
    r"\b(?:shaver|trimmer|grooming|hair\s*dryer|toothbrush|water\s*flosser|scale|massage|clipper)\b",
    re.I,
)


def _classify_mi_category(title: str, cat_name: str, sub_cat_name: str) -> tuple[Category, str]:
    cat_low = f"{cat_name} {sub_cat_name}".lower()
    title_low = title.lower()

    if "personal care" in cat_low or _PERSONAL_CARE_RE.search(title_low):
        return "beauty", "personal_care"
    if "screen" in cat_low or re.search(r"\b(?:tv|a\s*pro\s*\d{2}|s\s*mini\s*led)\b", title_low):
        if "monitor" in title_low or "gaming monitor" in title_low:
            return "electronics", "monitors"
        return "home_appliances", "tvs"
    if "smart home" in cat_low and _APPLIANCE_TITLE_RE.search(title_low):
        sub = _refine_sub_category(title, "home_appliances", "small_appliances")
        return "home_appliances", sub

    default_sub = "accessories"
    if "mobile" in cat_low or "phone" in cat_low:
        default_sub = "smartphones"
    elif "tablet" in cat_low or "pad" in title_low:
        default_sub = "tablets"
    elif "laptop" in cat_low:
        default_sub = "laptops"

    sub = _refine_sub_category(title, "electronics", default_sub)
    return "electronics", sub


class MiEgyptScraper(BaseScraper):
    """Official Mi Store Egypt scraper via public Laravel JSON API (`api.mistore-eg.com`)."""

    store_name = "mi_egypt"
    category: Category = "electronics"
    base_url = "https://mistore-eg.com"
    api_url = "https://api.mistore-eg.com/api/customer/products/search"
    default_limit = 5000
    discover_limit = 10000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 0.8
    request_timeout = 20.0

    def _parse_product(
        self,
        item: dict[str, Any],
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        raw_id = item.get("id")
        if raw_id is None:
            return None
        external_id = str(raw_id).strip()[:120]
        if not external_id:
            return None

        raw_title = str(item.get("name_en") or item.get("name") or item.get("name_ar") or "").strip()
        title = re.sub(r"\s+", " ", raw_title).strip()
        if len(title) < 3:
            return None

        regular_price = parse_egp_price(item.get("price"))
        discount_price = parse_egp_price(item.get("discount_price"))
        if discount_price is not None and (regular_price is None or discount_price < regular_price):
            current_price = discount_price
            claimed_original = regular_price if (regular_price is not None and regular_price > discount_price) else None
        else:
            current_price = regular_price
            claimed_original = None

        if current_price is None:
            return None

        is_active = bool(item.get("active", True)) and not bool(item.get("soft_deleted", False))
        avail_soon = bool(item.get("available_soon", False))
        stock_flag = bool(item.get("in_stock", False))
        stock_qty = item.get("stock")
        qty_ok = True if stock_qty is None else (isinstance(stock_qty, (int, float)) and stock_qty > 0)
        in_stock = is_active and not avail_soon and stock_flag and qty_ok

        share_link = str(item.get("share_link") or "").strip()
        slug = str(item.get("slug") or "").strip().strip("/")
        if share_link.startswith("https://mistore-eg.com/"):
            product_url = share_link
        elif slug:
            product_url = f"{self.base_url}/en/{slug}"
        else:
            return None

        image_url: Optional[str] = None
        raw_img = str(item.get("image") or "").strip()
        if raw_img.startswith("http"):
            image_url = raw_img
        else:
            imgs = item.get("images")
            if isinstance(imgs, list):
                for im in imgs:
                    if isinstance(im, dict) and str(im.get("url") or "").startswith("http"):
                        image_url = str(im["url"]).strip()
                        break

        cat_obj = item.get("category") if isinstance(item.get("category"), dict) else {}
        cat_name = str(cat_obj.get("name") or "").strip()
        sub_list = cat_obj.get("sub_categories") if isinstance(cat_obj.get("sub_categories"), list) else []
        sub_name = str(sub_list[0].get("name") or "").strip() if sub_list and isinstance(sub_list[0], dict) else ""

        top_category, sub_category = _classify_mi_category(title, cat_name, sub_name)
        attrs = _extract_specs(title, top_category, sub_category)
        attrs.pop("noon_category", None)
        if cat_name:
            attrs["mi_category"] = cat_name[:80]

        sku = str(item.get("sku") or "").strip()
        barcode = str(item.get("barcode") or "").strip()
        if re.fullmatch(r"\d{8}(?:\d{4,6})?", barcode):
            attrs["ean"] = barcode
        elif sku:
            m_ean = _EAN_SUFFIX_RE.search(sku)
            if m_ean:
                attrs["ean"] = m_ean.group(1)

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": top_category,
                "sub_category": sub_category,
                "brand": "Xiaomi",
                "product_title": title,
                "product_url": product_url,
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
        headers = {"Accept": "application/json", "Accept-Language": "en"}

        page = 1
        max_pages = 50
        while len(snapshots) < target_limit and page <= max_pages:
            try:
                resp = self.http.get(self.api_url, params={"page": page}, headers=headers)
                if resp.status_code != 200:
                    logger.warning("[mi_egypt] API HTTP %d on page %d", resp.status_code, page)
                    break
                payload = resp.json()
            except Exception as exc:
                logger.warning("[mi_egypt] API request failed on page %d: %s", page, exc)
                break

            if not isinstance(payload, dict) or payload.get("code") != 200:
                break

            self.pages_fetched += 1
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            products = data.get("products") if isinstance(data.get("products"), list) else []
            if not products:
                break

            total_pages = data.get("total")
            if isinstance(total_pages, int) and total_pages > 0:
                max_pages = min(max_pages, total_pages)

            page_new = 0
            for item in products:
                if not isinstance(item, dict):
                    continue
                raw_id = str(item.get("id") or "").strip()
                if not raw_id or raw_id in seen_ids:
                    continue
                seen_ids.add(raw_id)
                page_new += 1
                rec = self._parse_product(item, today, now)
                if rec is not None:
                    snapshots.append(rec)
                    if len(snapshots) >= target_limit:
                        break

            if page_new == 0:
                break
            page += 1

        return snapshots
