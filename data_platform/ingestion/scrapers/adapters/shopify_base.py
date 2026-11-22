"""
Config-driven Shopify storefront adapter (`ShopifyBaseScraper`).

Uses plain HTTP (`PoliteHttpClient` / `httpx`) against public Shopify JSON endpoints:
  - `/collections/{handle}/products.json?limit=250&page={N}` (when `collection_handles` is set)
  - `/products.json?limit=250&page={N}` (default full catalog)

Supports all 4 verticals (`fashion`, `groceries`, `electronics`, `home_appliances`):
  - Parses EGP `price`, `compare_at_price` (kept only when strictly `> price`),
    `in_stock` (True if any variant is available), `image_url`, canonical `product_url`,
    `brand`/`vendor`, `sku` & `barcode` (EAN/GTIN when valid 8–14 digits).
  - For `category == "fashion"`: extracts `available_sizes` & `total_sizes` for scarcity tracking.
  - For `category == "groceries"`: runs `groceries.py` packaging, brand, and 7-subcategory normalization.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from ..base import (
    BaseScraper,
    Category,
    RawProductSnapshot,
    ScrapeVertical,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)
from ..groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)

logger = logging.getLogger(__name__)

_SIZE_OPTION_NAMES = {"size", "sizes", "shoe size", "uk", "eu", "us", "المقاس", "مقاس"}
_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")

_FASHION_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("sneaker", "trainer", "running", "loafers", "loafer", "boot", "sandal", "slipper", "mule", "heel", "flat", "shoe", "footwear"), "footwear"),
    (("bag", "handbag", "backpack", "tote", "crossbody", "clutch", "wallet", "belt", "cap", "hat", "scarf", "sock", "tie", "cravat", "accessory", "accessories"), "accessories"),
    (("dress", "abaya", "kaftan", "jumpsuit", "skirt", "gown"), "dresses"),
    (("jacket", "coat", "blazer", "vest", "gilet", "trench", "puffer", "bomber", "suit", "overcoat"), "jackets"),
    (("hoodie", "sweatshirt", "pullover", "cardigan", "sweater", "knit", "turtleneck"), "knitwear"),
    (("jean", "denim", "trouser", "pant", "chino", "jogger", "short", "legging", "cargo", "sweatpant"), "pants"),
    (("polo",), "polos"),
    (("t-shirt", "tshirt", "tee"), "tees"),
    (("shirt", "blouse", "top", "tunic", "chemise"), "shirts"),
)

_ELECTRONICS_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("iphone", "galaxy", "smartphone", "mobile", "redmi", "xiaomi", "oppo", "realme"), "smartphones"),
    (("laptop", "macbook", "notebook", "thinkpad", "ideapad", "vivobook", "zenbook"), "laptops"),
    (("ipad", "tablet", "tab"), "tablets"),
    (("monitor", "screen"), "monitors"),
    (("headphone", "earbud", "airpods", "headset", "speaker", "audio"), "headphones"),
    (("watch", "band", "wearable"), "wearables"),
    (("rtx", "gtx", "gpu", "vga", "graphics"), "gpus"),
    (("cpu", "processor", "ryzen", "core i"), "cpus"),
    (("motherboard", "mainboard"), "motherboards"),
    (("ssd", "hdd", "nvme", "hard drive", "flash"), "storage"),
    (("ram", "ddr4", "ddr5", "memory"), "memory"),
    (("mouse", "keyboard", "gaming", "controller", "chair", "pad"), "peripherals"),
    (("tv", "television", "qled", "oled", "smart tv"), "tvs"),
    (("air conditioner", "split ac", "inverter ac"), "air_conditioners"),
    (("refrigerator", "fridge", "freezer"), "refrigerators"),
    (("washing machine", "washer", "dryer", "dishwasher"), "washing_machines"),
    (("microwave", "oven", "cooker", "air fryer", "blender", "kettle", "coffee", "vacuum", "heater", "fan"), "kitchen_appliances"),
)


def _normalize_size(raw: str) -> str:
    val = re.sub(r"\s+", " ", raw.strip())
    if not val:
        return ""
    low = val.lower()
    if low in {"default title", "default", "one size", "os", "free size", "free"}:
        return "One Size"
    if len(val) <= 5 and re.fullmatch(r"[0-9a-zA-Z./+-]+", val):
        return val.upper()
    return val[:20]


def _extract_fashion_sizes(raw_product: dict[str, Any]) -> tuple[list[str], int]:
    variants = raw_product.get("variants") or []
    options = raw_product.get("options") or []
    size_pos: Optional[int] = None
    for idx, opt in enumerate(options, start=1):
        if isinstance(opt, dict) and str(opt.get("name") or "").strip().lower() in _SIZE_OPTION_NAMES:
            size_pos = idx
            break

    all_sizes: list[str] = []
    avail_sizes: list[str] = []
    seen_all: set[str] = set()
    seen_avail: set[str] = set()

    for v in variants:
        if not isinstance(v, dict):
            continue
        raw_size = ""
        if size_pos is not None:
            raw_size = str(v.get(f"option{size_pos}") or "")
        else:
            for pos in (1, 2, 3):
                cand = str(v.get(f"option{pos}") or "").strip()
                if cand and re.fullmatch(r"(?:[2-5]?\d(?:\.5)?|XXS|XS|S|M|L|XL|2XL|3XL|4XL|5XL|XXL|XXXL)", cand, re.I):
                    raw_size = cand
                    break
            if not raw_size:
                raw_size = str(v.get("option1") or v.get("title") or "")

        norm = _normalize_size(raw_size)
        if not norm:
            continue
        if norm not in seen_all:
            seen_all.add(norm)
            all_sizes.append(norm)
        if bool(v.get("available")) and norm not in seen_avail:
            seen_avail.add(norm)
            avail_sizes.append(norm)

    if not all_sizes:
        any_avail = any(isinstance(v, dict) and bool(v.get("available")) for v in variants)
        return (["One Size"] if any_avail else []), 1
    return avail_sizes, len(all_sizes)


class ShopifyBaseScraper(BaseScraper):
    """Config-driven Shopify `/products.json` & `/collections/{handle}/products.json` scraper."""

    store_name: str = ""
    category: Category = "fashion"
    base_url: str = ""
    default_brand: str = ""
    override_brand: bool = False
    default_limit: int = 180
    discover_limit: int = 950
    groceries_limit: int = 180
    discover_groceries_limit: int = 750
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)
    collection_handles: tuple[tuple[str, Category, str], ...] = ()  # (sub_category, category, handle)
    min_delay_seconds: float = 1.2
    request_timeout: float = 25.0
    per_page: int = 250

    def _resolve_sub_category(self, title: str, product_type: str, default_sub: Optional[str], cat: Category) -> str:
        if cat == "groceries":
            return refine_grocery_sub_category(f"{title} {product_type}", default_sub or "canned_sauces")
        hay = f"{product_type} {title}".lower()
        if cat == "fashion":
            for kws, mapped in _FASHION_SUBCAT_KEYWORDS:
                if any(k in hay for k in kws):
                    return mapped
            return default_sub or (normalize_snake_slug(product_type, fallback="apparel", max_len=60) if product_type else "apparel")
        for kws, mapped in _ELECTRONICS_SUBCAT_KEYWORDS:
            if any(k in hay for k in kws):
                return mapped
        return default_sub or (normalize_snake_slug(product_type, fallback="accessories", max_len=60) if product_type else "accessories")

    def _parse_product(
        self,
        raw: dict[str, Any],
        cat: Category,
        default_sub: Optional[str],
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        pid = raw.get("id")
        handle = str(raw.get("handle") or "").strip()
        title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
        if not pid or not handle or len(title) < 3:
            return None

        variants = raw.get("variants") if isinstance(raw.get("variants"), list) else []
        if not variants:
            return None

        avail_prices: list[Decimal] = []
        all_prices: list[Decimal] = []
        compare_prices: list[Decimal] = []
        any_available = False
        first_sku = ""
        first_barcode = ""

        for v in variants:
            if not isinstance(v, dict):
                continue
            p = parse_egp_price(v.get("price"))
            if p is None:
                continue
            all_prices.append(p)
            if bool(v.get("available")):
                any_available = True
                avail_prices.append(p)
            cp = parse_egp_price(v.get("compare_at_price"))
            if cp is not None and cp > p:
                compare_prices.append(cp)
            if not first_sku and v.get("sku"):
                first_sku = str(v["sku"]).strip()
            if not first_barcode and v.get("barcode"):
                cand_bc = re.sub(r"\D", "", str(v["barcode"]).strip())
                if _EAN_RE.match(cand_bc):
                    first_barcode = cand_bc

        if not all_prices:
            return None

        current_price = min(avail_prices) if avail_prices else min(all_prices)
        claimed_original = (
            max(compare_prices) if (compare_prices and max(compare_prices) > current_price) else None
        )

        image_url: Optional[str] = None
        images = raw.get("images")
        if isinstance(images, list) and images and isinstance(images[0], dict) and images[0].get("src"):
            image_url = str(images[0]["src"]).strip()

        vendor = str(raw.get("vendor") or "").strip()
        product_type = str(raw.get("product_type") or "").strip()

        if cat == "groceries":
            brand = self.default_brand if self.override_brand and self.default_brand else extract_grocery_brand(title, vendor or self.default_brand)
        elif self.override_brand and self.default_brand:
            brand = self.default_brand
        else:
            brand = vendor or self.default_brand or "Unknown"

        sub_category = self._resolve_sub_category(title, product_type, default_sub, cat)
        attrs: dict[str, Any] = {}
        if product_type:
            attrs["shopify_product_type"] = product_type
        if first_sku:
            attrs["sku"] = first_sku
        if first_barcode:
            attrs["ean"] = first_barcode

        if cat == "fashion":
            avail_sizes, total_sizes = _extract_fashion_sizes(raw)
            attrs["available_sizes"] = avail_sizes
            attrs["total_sizes"] = total_sizes
        elif cat == "groceries":
            attrs.update(parse_grocery_packaging(title, raw_payload={"ean": first_barcode} if first_barcode else None))

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": str(pid)[:120],
                "canonical_product_key": None,
                "category": cat,
                "sub_category": sub_category,
                "brand": brand[:100],
                "product_title": title,
                "product_url": f"{self.base_url.rstrip('/')}/products/{handle}",
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": any_available,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)

        if self.collection_handles:
            endpoints: list[tuple[Optional[str], Category, str]] = [
                (sub, cat, f"{self.base_url.rstrip('/')}/collections/{handle}/products.json")
                for sub, cat, handle in self.collection_handles
            ]
            per_ep_cap = max(3, math.ceil(target_limit / len(endpoints)))
        else:
            endpoints = [(None, self.category, f"{self.base_url.rstrip('/')}/products.json")]
            per_ep_cap = target_limit

        for default_sub, cat, endpoint in endpoints:
            if len(collected) >= target_limit:
                break
            ep_collected = 0
            page = 1
            max_pages = max(1, math.ceil(per_ep_cap / self.per_page) + 2)

            while len(collected) < target_limit and ep_collected < per_ep_cap and page <= max_pages:
                logger.info("[%s] Fetching Shopify JSON page %d (%s)", self.store_name, page, endpoint)
                try:
                    resp = self.http.get(
                        endpoint,
                        params={"limit": min(self.per_page, max(20, per_ep_cap)), "page": page},
                        min_delay_seconds=effective_delay,
                        timeout=self.request_timeout,
                    )
                    payload = resp.json()
                except Exception as exc:
                    logger.warning("[%s] Error fetching %s page %d: %s", self.store_name, endpoint, page, exc)
                    break

                self.pages_fetched += 1
                products = payload.get("products") if isinstance(payload, dict) else None
                if not isinstance(products, list) or not products:
                    break

                page_records: list[RawProductSnapshot] = []
                for raw in products:
                    if not isinstance(raw, dict):
                        continue
                    rec = self._parse_product(raw, cat, default_sub, snapshot_date, scraped_at)
                    if rec is not None and rec.external_id not in seen_ids:
                        page_records.append(rec)

                page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                added = 0
                for rec in page_records:
                    if rec.external_id in seen_ids:
                        continue
                    seen_ids.add(rec.external_id)
                    collected.append(rec)
                    ep_collected += 1
                    added += 1
                    if len(collected) >= target_limit or ep_collected >= per_ep_cap:
                        break

                if len(products) < min(self.per_page, max(20, per_ep_cap)) or added == 0:
                    break
                page += 1

            self.category_counts[default_sub or cat] = self.category_counts.get(default_sub or cat, 0) + ep_collected

        return collected
