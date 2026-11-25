"""
Live scraper for B.TECH Egypt (`https://btech.com`).

Uses plain HTTP via `PoliteHttpClient` with a polite delay (`>= 2.5s`),
fetching page 1 across diverse public electronics category pages (20 items/page
each) because `?page=2` does not advance SSR payloads and client pagination hits
a WAF-gated API.

Extracts products from the dehydrated React Query state inside Next.js flight
rows (`self.__next_f.push([1,"..."])`).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .base import (
    BaseScraper,
    Category,
    RawProductSnapshot,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)

logger = logging.getLogger(__name__)

# Interleaved electronics + home_appliances SSR pages (20 items/page each -> ~400+ live items)
BTECH_CATEGORIES: list[tuple[str, Category, str]] = [
    ("smartphones", "electronics", "https://btech.com/en/c/mobiles-tablets/mobile-phones"),
    ("tvs", "home_appliances", "https://btech.com/en/c/tvs-projectors/televisions"),
    ("laptops", "electronics", "https://btech.com/en/c/laptop-pc/laptops"),
    ("air_conditioners", "home_appliances", "https://btech.com/en/c/large-home-appliances/air-conditioners"),
    ("refrigerators", "home_appliances", "https://btech.com/en/c/large-home-appliances"),
    ("monitors", "electronics", "https://btech.com/en/c/laptop-pc/monitors"),
    ("washing_machines", "home_appliances", "https://btech.com/en/c/large-home-appliances/washing-machines-dryers"),
    ("headphones", "electronics", "https://btech.com/en/c/audio-recording"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/c/small-home-appliances/kettles-coffee-makers"),
    ("tablets", "electronics", "https://btech.com/en/c/mobiles-tablets/tablets"),
    ("microwaves", "home_appliances", "https://btech.com/en/c/small-home-appliances/microwaves-ovens"),
    ("wearables", "electronics", "https://btech.com/en/c/wearables"),
    ("freezers", "home_appliances", "https://btech.com/en/c/large-home-appliances/deep-freezers"),
    ("gaming", "electronics", "https://btech.com/en/c/gaming-area"),
    ("dishwashers", "home_appliances", "https://btech.com/en/c/large-home-appliances/dishwashers"),
    ("storage", "electronics", "https://btech.com/en/c/laptop-pc/external-storage-flash-drives"),
    ("cookers", "home_appliances", "https://btech.com/en/c/large-home-appliances/cookers"),
    ("vacuums", "home_appliances", "https://btech.com/en/c/small-home-appliances/vacuum-cleaners"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/c/small-home-appliances/blenders-mixers"),
    ("ovens", "home_appliances", "https://btech.com/en/c/large-home-appliances/built-in-ovens"),
    ("water_heaters", "home_appliances", "https://btech.com/en/c/small-home-appliances/water-heaters"),
    ("fans", "home_appliances", "https://btech.com/en/c/small-home-appliances/fans"),
    ("accessories", "electronics", "https://btech.com/en/c/mobiles-tablets/mobile-accessories"),
    ("accessories", "electronics", "https://btech.com/en/c/laptop-pc/laptop-pc-accessories"),
    ("personal_care", "beauty", "https://btech.com/en/c/personal-care"),
    ("cameras", "electronics", "https://btech.com/en/c/cameras"),
    ("printers", "electronics", "https://btech.com/en/c/laptop-pc/printers-scanners"),
    ("networking", "electronics", "https://btech.com/en/c/laptop-pc/networking"),
    ("speakers", "electronics", "https://btech.com/en/c/audio-recording/speakers"),
    ("irons", "home_appliances", "https://btech.com/en/c/small-home-appliances/irons-garment-steamers"),
    ("air_purifiers", "home_appliances", "https://btech.com/en/c/small-home-appliances/air-purifiers"),
    ("cookware", "home_furniture", "https://btech.com/en/c/kitchenware"),
]

# Deep brand/subcategory/sort SSR URLs used ONLY in `mode="expand"` (keeps daily runs lean)
BTECH_EXPAND_EXTRA_URLS: list[tuple[str, Category, str]] = [
    ("refrigerators", "home_appliances", "https://btech.com/en/c/large-home-appliances/refrigerators"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/c/small-home-appliances/air-fryers"),
    ("smartphones", "electronics", "https://btech.com/en/c/mobiles-tablets/mobile-phones?sort=price_asc"),
    ("smartphones", "electronics", "https://btech.com/en/c/mobiles-tablets/mobile-phones?sort=price_desc"),
    ("laptops", "electronics", "https://btech.com/en/c/laptop-pc/laptops?sort=price_asc"),
    ("laptops", "electronics", "https://btech.com/en/c/laptop-pc/laptops?sort=price_desc"),
    ("tvs", "home_appliances", "https://btech.com/en/c/tvs-projectors/televisions?sort=price_asc"),
    ("tvs", "home_appliances", "https://btech.com/en/c/tvs-projectors/televisions?sort=price_desc"),
    ("air_conditioners", "home_appliances", "https://btech.com/en/c/large-home-appliances/air-conditioners?sort=price_asc"),
    ("air_conditioners", "home_appliances", "https://btech.com/en/c/large-home-appliances/air-conditioners?sort=price_desc"),
    ("washing_machines", "home_appliances", "https://btech.com/en/c/large-home-appliances/washing-machines-dryers?sort=price_asc"),
    ("washing_machines", "home_appliances", "https://btech.com/en/c/large-home-appliances/washing-machines-dryers?sort=price_desc"),
    ("refrigerators", "home_appliances", "https://btech.com/en/c/large-home-appliances/refrigerators?sort=price_asc"),
    ("refrigerators", "home_appliances", "https://btech.com/en/c/large-home-appliances/refrigerators?sort=price_desc"),
    ("cookers", "home_appliances", "https://btech.com/en/c/large-home-appliances/cookers?sort=price_asc"),
    ("cookers", "home_appliances", "https://btech.com/en/c/large-home-appliances/cookers?sort=price_desc"),
    ("dishwashers", "home_appliances", "https://btech.com/en/c/large-home-appliances/dishwashers?sort=price_asc"),
    ("microwaves", "home_appliances", "https://btech.com/en/c/small-home-appliances/microwaves-ovens?sort=price_asc"),
    ("vacuums", "home_appliances", "https://btech.com/en/c/small-home-appliances/vacuum-cleaners?sort=price_asc"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/c/small-home-appliances/kettles-coffee-makers?sort=price_asc"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/c/small-home-appliances/blenders-mixers?sort=price_asc"),
    ("headphones", "electronics", "https://btech.com/en/c/audio-recording?sort=price_asc"),
    ("monitors", "electronics", "https://btech.com/en/c/laptop-pc/monitors?sort=price_asc"),
    ("tablets", "electronics", "https://btech.com/en/c/mobiles-tablets/tablets?sort=price_asc"),
    ("wearables", "electronics", "https://btech.com/en/c/wearables?sort=price_asc"),
    ("gaming", "electronics", "https://btech.com/en/c/gaming-area?sort=price_asc"),
    # Brand-sharded SSR search pages on B.TECH
    ("smartphones", "electronics", "https://btech.com/en/s?q=samsung"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=apple"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=iphone"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=xiaomi"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=oppo"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=realme"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=honor"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=infinix"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=vivo"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=huawei"),
    ("smartphones", "electronics", "https://btech.com/en/s?q=nokia"),
    ("laptops", "electronics", "https://btech.com/en/s?q=lenovo"),
    ("laptops", "electronics", "https://btech.com/en/s?q=hp"),
    ("laptops", "electronics", "https://btech.com/en/s?q=dell"),
    ("laptops", "electronics", "https://btech.com/en/s?q=asus"),
    ("laptops", "electronics", "https://btech.com/en/s?q=acer"),
    ("laptops", "electronics", "https://btech.com/en/s?q=msi"),
    ("tvs", "home_appliances", "https://btech.com/en/s?q=lg"),
    ("tvs", "home_appliances", "https://btech.com/en/s?q=sharp"),
    ("tvs", "home_appliances", "https://btech.com/en/s?q=toshiba"),
    ("tvs", "home_appliances", "https://btech.com/en/s?q=tornado"),
    ("tvs", "home_appliances", "https://btech.com/en/s?q=tcl"),
    ("tvs", "home_appliances", "https://btech.com/en/s?q=haier"),
    ("tvs", "home_appliances", "https://btech.com/en/s?q=hisense"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=fresh"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=beko"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=zanussi"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=hoover"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=bosch"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=ariston"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=carrier"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=midea"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=unionaire"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=kiriazi"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=white+whale"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=white+point"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=indesit"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=electrolux"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=la+germania"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=elba"),
    ("large_appliances", "home_appliances", "https://btech.com/en/s?q=olympic"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=philips"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=braun"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=tefal"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=kenwood"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=moulinex"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=delonghi"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=black+decker"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=mienta"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=ninja"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=nespresso"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=air+fryer"),
    ("kitchen_appliances", "home_appliances", "https://btech.com/en/s?q=coffee+maker"),
    ("headphones", "electronics", "https://btech.com/en/s?q=sony"),
    ("headphones", "electronics", "https://btech.com/en/s?q=jbl"),
    ("headphones", "electronics", "https://btech.com/en/s?q=anker"),
    ("headphones", "electronics", "https://btech.com/en/s?q=oraimo"),
    ("headphones", "electronics", "https://btech.com/en/s?q=soundcore"),
    ("gaming", "electronics", "https://btech.com/en/s?q=playstation"),
    ("gaming", "electronics", "https://btech.com/en/s?q=logitech"),
    ("gaming", "electronics", "https://btech.com/en/s?q=hyperx"),
    ("networking", "electronics", "https://btech.com/en/s?q=tp-link"),
    ("printers", "electronics", "https://btech.com/en/s?q=canon"),
    ("printers", "electronics", "https://btech.com/en/s?q=epson"),
]

_MEDIA_BASE_URL = "https://media.btech.com/catalogs/"
_RSC_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)

_BRAND_ACRONYMS: dict[str, str] = {
    "hp": "HP",
    "lg": "LG",
    "asus": "ASUS",
    "msi": "MSI",
    "aoc": "AOC",
    "jbl": "JBL",
    "oppo": "OPPO",
    "tcl": "TCL",
    "tp-link": "TP-Link",
    "hyperx": "HyperX",
    "hmd": "HMD",
    "realme": "Realme",
    "xiaomi": "Xiaomi",
    "samsung": "Samsung",
    "apple": "Apple",
}

_SUBCATEGORY_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("refrigerator", "fridge"), "refrigerators"),
    (("deep freezer", "freezer"), "freezers"),
    (("washing machine", "washer", "dryer"), "washing_machines"),
    (("dishwasher",), "dishwashers"),
    (("air conditioner", "split ac", "1.5 hp", "2.25 hp", "3 hp"), "air_conditioners"),
    (("microwave",), "microwaves"),
    (("cooker", "gas stove", "hob"), "cookers"),
    (("built-in oven", "electric oven", "oven"), "ovens"),
    (("vacuum",), "vacuums"),
    (("water heater",), "water_heaters"),
    (("stand fan", "ceiling fan", "wall fan", "box fan", "air cooler"), "fans"),
    (("air fryer", "blender", "mixer", "kettle", "coffee", "espresso", "toaster", "juicer", "food processor"), "kitchen_appliances"),
    (("flash drive", "usb flash", "ssd", "hdd", "hard drive", "memory card", "storage"), "storage"),
    (("monitor", "curved gaming monitor"), "monitors"),
    (("headphone", "headset", "earbud", "airpods", "buds", "earphone"), "headphones"),
    (("smartwatch", "smart watch", "watch", "band", "wearable"), "wearables"),
    (("tablet", "ipad", "tab "), "tablets"),
    (("smartphone", "mobile phone", "iphone", "galaxy a", "galaxy s", "galaxy z", "redmi", "poco", "reno", "infinix", "tecno", "honor x", "realme"), "smartphones"),
    (("laptop", "notebook", "macbook", "ideapad", "thinkpad", "victus", "loq", "vivobook", "omnibook", "rog strix", "tuf gaming"), "laptops"),
    (("tv", "television", "qled", "oled", "uhd", "projector"), "tvs"),
    (("playstation", "ps5", "xbox", "nintendo", "console"), "gaming"),
    (("speaker", "soundbar", "subwoofer"), "speakers"),
    (("printer", "scanner"), "printers"),
    (("router", "extender", "modem", "switch"), "networking"),
    (("power bank", "charger", "cable", "adapter", "mouse", "keyboard"), "accessories"),
]

_RAM_RE = re.compile(r"\b(\d{1,3})\s*GB\s*(?:RAM|DDR[345])?\b", re.I)
_STORAGE_TB_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*TB\b", re.I)
_STORAGE_GB_RE = re.compile(r"\b(64|128|256|512|1000|1024)\s*GB\s*(?:SSD|NVMe|M\.2|ROM|Storage)?\b", re.I)
_REFRESH_HZ_RE = re.compile(r"\b(60|75|90|100|120|144|165|170|180|240)\s*Hz\b", re.I)
_SCREEN_INCH_RE = re.compile(r"\b(6\.\d|10\.\d|11(?:\.\d)?|13\.3|14(?:\.\d)?|15\.\d|16(?:\.\d)?|17\.3|23\.8|24|27|32|43|50|55|65|75)\s*(?:\"|-?\s*inch)\b", re.I)


def _normalize_brand(raw_brand: Optional[str], title: str) -> str:
    candidate = (raw_brand or "").strip()
    if not candidate:
        first_token = title.strip().split(" ", 1)[0] if title.strip() else "Unknown"
        candidate = re.sub(r"[^A-Za-z0-9.\-+']", "", first_token) or "Unknown"

    lower = candidate.lower()
    if lower in _BRAND_ACRONYMS:
        return _BRAND_ACRONYMS[lower]
    if candidate.isupper() and len(candidate) > 3:
        return candidate.title()
    return candidate[:100]


def _resolve_sub_category(raw_item: dict[str, Any], default_subcat: str, title: str) -> str:
    # Check specific leaf category (l3/l2) and product title BEFORE broad parent_category
    # (e.g., monitors & USB drives sit under "Laptops, PCs & Accessories").
    leaf_parts: list[str] = []
    cats = raw_item.get("categories")
    if isinstance(cats, dict):
        for level in ("l3", "l2"):
            lvl = cats.get(level)
            if isinstance(lvl, dict) and lvl.get("name"):
                leaf_parts.append(str(lvl["name"]))

    leaf_haystack = " ".join(leaf_parts).lower()
    if leaf_haystack:
        for keywords, mapped in _SUBCATEGORY_KEYWORDS:
            if any(kw in leaf_haystack for kw in keywords):
                return mapped

    title_lower = title.lower()
    for keywords, mapped in _SUBCATEGORY_KEYWORDS:
        if any(kw in title_lower for kw in keywords):
            return mapped

    parent_haystack = str(raw_item.get("parent_category") or "").lower()
    if parent_haystack:
        for keywords, mapped in _SUBCATEGORY_KEYWORDS:
            if any(kw in parent_haystack for kw in keywords):
                return mapped

    return normalize_snake_slug(default_subcat, fallback="electronics", max_len=80)


def _extract_attributes(raw_item: dict[str, Any], title: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {}

    for key in ("sku", "product_id", "variant_id", "offer_id"):
        val = str(raw_item.get(key) or "").strip()
        if val:
            attrs[key] = val

    if raw_item.get("parent_category"):
        attrs["btech_category"] = str(raw_item["parent_category"]).strip()

    fulfillment = raw_item.get("fulfillment")
    if isinstance(fulfillment, list) and fulfillment:
        attrs["fulfillment"] = [str(f) for f in fulfillment]

    if raw_item.get("is_best_seller") is True:
        attrs["is_best_seller"] = True

    ram_matches = [int(m) for m in _RAM_RE.findall(title) if 2 <= int(m) <= 64]
    if ram_matches:
        attrs["ram_gb"] = ram_matches[0]

    if m := _STORAGE_TB_RE.search(title):
        tb_val = float(m.group(1))
        if 0.5 <= tb_val <= 16:
            attrs["storage_gb"] = int(round(tb_val * 1024))
    else:
        for val in [int(m) for m in _STORAGE_GB_RE.findall(title)]:
            if val != attrs.get("ram_gb") or val >= 128:
                attrs["storage_gb"] = val
                break

    if m := _REFRESH_HZ_RE.search(title):
        attrs["refresh_hz"] = int(m.group(1))

    if m := _SCREEN_INCH_RE.search(title):
        inch = float(m.group(1))
        attrs["screen_size_inch"] = int(inch) if inch.is_integer() else inch

    return attrs


def _extract_flight_items(html: str) -> list[dict[str, Any]]:
    """Extract product items from dehydrated React Query state inside Next.js flight chunks."""
    chunks = _RSC_PUSH_RE.findall(html)
    if not chunks:
        return []

    parts: list[str] = []
    for chunk in chunks:
        try:
            parts.append(json.loads(f'"{chunk}"'))
        except json.JSONDecodeError:
            continue
    joined = "".join(parts)

    decoder = json.JSONDecoder()
    marker = '"items":['
    search_pos = 0
    found: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    while True:
        idx = joined.find(marker, search_pos)
        if idx == -1:
            break
        try:
            arr, end_pos = decoder.raw_decode(joined, idx + len('"items":'))
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                sample = arr[0]
                if "slug" in sample and "price" in sample and (
                    "sku" in sample or "variant_id" in sample or "product_id" in sample
                ):
                    for item in arr:
                        if not isinstance(item, dict):
                            continue
                        dedup_key = str(
                            item.get("sku")
                            or item.get("variant_id")
                            or item.get("product_id")
                            or item.get("slug")
                            or ""
                        ).strip()
                        if dedup_key and dedup_key not in seen_keys:
                            seen_keys.add(dedup_key)
                            found.append(item)
            search_pos = end_pos
        except json.JSONDecodeError:
            search_pos = idx + len(marker)

    return found


class BTechScraper(BaseScraper):
    """Live catalog scraper for B.TECH Egypt (page-1 SSR across electronics & home appliances)."""

    store_name = "btech"
    category: Category = "electronics"
    base_url = "https://btech.com"
    default_limit = 500
    discover_limit = 1500
    expand_limit = 6000
    min_delay_seconds = 2.0

    def _build_record(
        self,
        raw_item: dict[str, Any],
        category: Category,
        default_subcat: str,
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        slug = str(raw_item.get("slug") or "").strip().lstrip("/")
        if not slug:
            return None

        external_id = str(
            raw_item.get("sku")
            or raw_item.get("variant_id")
            or raw_item.get("product_id")
            or slug
        ).strip()[:120]
        if not external_id:
            return None

        title = str(raw_item.get("name") or "").strip()
        if not title:
            return None

        price_obj = raw_item.get("price") if isinstance(raw_item.get("price"), dict) else {}
        current_price = parse_egp_price(price_obj.get("final_price"))
        if current_price is None:
            return None

        base_price = parse_egp_price(price_obj.get("base_price"))
        claimed_original_price = (
            base_price if (base_price is not None and base_price > current_price) else None
        )

        offer_id = str(raw_item.get("offer_id") or "").strip()
        product_url = (
            f"{self.base_url}/en/p/{slug}?offering_id={offer_id}"
            if offer_id
            else f"{self.base_url}/en/p/{slug}"
        )

        thumb_raw = str(raw_item.get("thumbnail_url") or "").strip()
        if not thumb_raw:
            image_url = None
        elif thumb_raw.lower().startswith(("http://", "https://")):
            image_url = thumb_raw
        else:
            image_url = f"{_MEDIA_BASE_URL}{thumb_raw.lstrip('/')}"

        brand = _normalize_brand(
            str(raw_item.get("brand")) if raw_item.get("brand") is not None else None,
            title,
        )
        sub_category = _resolve_sub_category(raw_item, default_subcat, title)
        attributes_json = _extract_attributes(raw_item, title)

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": category,
                "sub_category": sub_category,
                "brand": brand,
                "product_title": title,
                "product_url": product_url,
                "image_url": image_url,
                "attributes_json": attributes_json,
                "current_price": current_price,
                "claimed_original_price": claimed_original_price,
                "in_stock": bool(raw_item.get("is_in_stock", True)),
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

        cats = (
            BTECH_CATEGORIES + BTECH_EXPAND_EXTRA_URLS
            if self.mode == "expand"
            else BTECH_CATEGORIES
        )
        for default_subcat, cat_name, category_url in cats:
            if len(collected) >= target_limit:
                break

            logger.info("[btech] Fetching %s/%s (%s)", cat_name, default_subcat, category_url)
            try:
                resp = self.http.get(
                    category_url,
                    min_delay_seconds=self.min_delay_seconds,
                    timeout=self.request_timeout,
                )
            except Exception as exc:
                logger.warning("[btech] Error fetching %s: %s; skipping category.", category_url, exc)
                continue
            self.pages_fetched += 1

            raw_items = _extract_flight_items(resp.text)
            if not raw_items:
                logger.warning("[btech] No flight items extracted from %s; skipping.", category_url)
                continue

            for raw_item in raw_items:
                record = self._build_record(
                    raw_item=raw_item,
                    category=cat_name,
                    default_subcat=default_subcat,
                    snapshot_date=snapshot_date,
                    scraped_at=scraped_at,
                )
                if record is None or record.external_id in seen_ids:
                    continue

                seen_ids.add(record.external_id)
                collected.append(record)
                if len(collected) >= target_limit:
                    break

        return collected
