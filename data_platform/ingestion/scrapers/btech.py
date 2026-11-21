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
    RawProductSnapshot,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)

logger = logging.getLogger(__name__)

# Diverse live B.TECH electronics category pages (20 SSR items per page)
BTECH_CATEGORIES: list[tuple[str, str]] = [
    ("smartphones", "https://btech.com/en/c/mobiles-tablets"),
    ("laptops", "https://btech.com/en/c/laptop-pc"),
    ("wearables", "https://btech.com/en/c/wearables"),
    ("headphones", "https://btech.com/en/c/audio-recording"),
    ("gaming", "https://btech.com/en/c/gaming-area"),
    ("tvs", "https://btech.com/en/c/tvs-projectors"),
    ("electronics", "https://btech.com/en/c/electronics"),
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
    """Live catalog scraper for B.TECH Egypt (page-1 SSR across electronics categories)."""

    store_name = "btech"
    category = "electronics"
    base_url = "https://btech.com"
    min_delay_seconds = 2.5

    def _build_record(
        self,
        raw_item: dict[str, Any],
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
                "category": self.category,
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

    def scrape(self, limit: int = 30) -> list[RawProductSnapshot]:
        if limit <= 0:
            return []

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()

        for default_subcat, category_url in BTECH_CATEGORIES:
            if len(collected) >= limit:
                break

            logger.info("[btech] Fetching category page (%s)", category_url)
            resp = self.http.get(
                category_url,
                min_delay_seconds=self.min_delay_seconds,
            )
            self.pages_fetched += 1

            raw_items = _extract_flight_items(resp.text)
            if not raw_items:
                logger.warning("[btech] No flight items extracted from %s; skipping.", category_url)
                continue

            for raw_item in raw_items:
                record = self._build_record(
                    raw_item=raw_item,
                    default_subcat=default_subcat,
                    snapshot_date=snapshot_date,
                    scraped_at=scraped_at,
                )
                if record is None or record.external_id in seen_ids:
                    continue

                seen_ids.add(record.external_id)
                collected.append(record)
                if len(collected) >= limit:
                    break

        return collected
