"""
Live scraper for 2B Egypt (`https://2b.com.eg`).

Uses plain HTTP via `PoliteHttpClient` with a polite delay (`>= 2.5s`) across
key electronics category pages (`?p={N}&product_list_limit=48`), stopping
pagination per category when `<link rel="next">` is absent.

Extracts structured product data from embedded `<script type="application/ld+json">`
(`schema.org/Product` array) and pairs each item with its Magento category tile
DOM element for `data-product-id` (`external_id`) and `[data-price-type="oldPrice"]`
(`claimed_original_price`, kept only when strictly `> current_price`).
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ThrottledResponseError,
    parse_egp_price,
    utc_now_naive,
)

logger = logging.getLogger(__name__)

# Interleaved electronics + home_appliances categories on 2B Egypt (verified live URLs)
TWO_B_CATEGORIES: list[tuple[str, Category, str]] = [
    ("smartphones", "electronics", "https://2b.com.eg/en/mobile-and-tablet/mobiles.html"),
    ("tvs", "home_appliances", "https://2b.com.eg/en/televisions/tvs.html"),
    ("laptops", "electronics", "https://2b.com.eg/en/computers/laptops.html"),
    ("air_conditioners", "home_appliances", "https://2b.com.eg/en/home-appliances/air-conditioners.html"),
    ("large_appliances", "home_appliances", "https://2b.com.eg/en/home-appliances/large-home-appliances.html"),
    ("headphones", "electronics", "https://2b.com.eg/en/audio/headphones.html"),
    ("kitchen_appliances", "home_appliances", "https://2b.com.eg/en/home-appliances/kitchen-appliances.html"),
    ("monitors", "electronics", "https://2b.com.eg/en/computers/monitor-projector.html"),
    ("small_appliances", "home_appliances", "https://2b.com.eg/en/home-appliances/small-home-appliances.html"),
    ("tablets", "electronics", "https://2b.com.eg/en/mobile-and-tablet/mobile-tablet.html"),
    ("wearables", "electronics", "https://2b.com.eg/en/mobile-and-tablet/wearables.html"),
    ("gaming", "electronics", "https://2b.com.eg/en/gaming.html"),
]

_APPLIANCE_SUBCAT_REFINERS: list[tuple[tuple[str, ...], str]] = [
    (("refrigerator", "fridge"), "refrigerators"),
    (("freezer",), "freezers"),
    (("washing machine", "washer", "dryer"), "washing_machines"),
    (("dishwasher",), "dishwashers"),
    (("air conditioner", "split ac", "1.5 hp", "2.25 hp", "3 hp"), "air_conditioners"),
    (("microwave",), "microwaves"),
    (("cooker", "gas stove", "hob"), "cookers"),
    (("oven",), "ovens"),
    (("vacuum",), "vacuums"),
    (("water heater",), "water_heaters"),
    (("fan", "air cooler"), "fans"),
    (("air fryer", "blender", "mixer", "kettle", "coffee", "espresso", "toaster", "juicer", "food processor"), "kitchen_appliances"),
]

_BRAND_ACRONYMS: dict[str, str] = {
    "hp": "HP",
    "lg": "LG",
    "asus": "ASUS",
    "msi": "MSI",
    "aoc": "AOC",
    "amd": "AMD",
    "jbl": "JBL",
    "oppo": "OPPO",
    "tcl": "TCL",
    "tp-link": "TP-Link",
    "hyperx": "HyperX",
    "redmi": "Xiaomi",
    "playstation": "Sony",
}

_RAM_RE = re.compile(r"\b(\d{1,3})\s*GB\s*(?:RAM|DDR[345])?\b", re.I)
_STORAGE_TB_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*TB\b", re.I)
_STORAGE_GB_RE = re.compile(r"\b(64|128|256|512|1000|1024)\s*GB\s*(?:SSD|NVMe|M\.2|ROM|Storage|Internal)?\b", re.I)
_REFRESH_HZ_RE = re.compile(r"\b(60|75|90|100|120|144|165|170|180|240)\s*Hz\b", re.I)
_SCREEN_INCH_RE = re.compile(r"\b(6\.\d|10\.\d|11(?:\.\d)?|13\.3|14(?:\.\d)?|15\.\d|16(?:\.\d)?|17\.3|23\.8|24|27|32|43|50|55|65|75)\s*(?:\"|-?\s*inch)\b", re.I)


def _normalize_url_key(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}"


def _normalize_brand(raw_brand: Optional[str], title: str) -> str:
    candidate = (raw_brand or "").strip()
    if not candidate or candidate.lower() in {"generic", "other", "none", "null"}:
        first_token = title.strip().split(" ", 1)[0] if title.strip() else "Unknown"
        candidate = re.sub(r"[^A-Za-z0-9.\-+']", "", first_token) or "Unknown"

    lower = candidate.lower()
    if lower in _BRAND_ACRONYMS:
        return _BRAND_ACRONYMS[lower]
    if candidate.isupper() and len(candidate) > 3:
        return candidate.title()
    return candidate[:100]


def _extract_specs(title: str, sub_category: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {"two_b_category": sub_category}

    ram_matches = [int(m) for m in _RAM_RE.findall(title) if 2 <= int(m) <= 64]
    if ram_matches:
        attrs["ram_gb"] = ram_matches[0]

    if m := _STORAGE_TB_RE.search(title):
        tb_val = float(m.group(1))
        if 0.5 <= tb_val <= 16:
            attrs["storage_gb"] = int(round(tb_val * 1024))
    else:
        storage_matches = [int(m) for m in _STORAGE_GB_RE.findall(title)]
        # Avoid mistaking RAM (e.g. 64GB RAM) when storage is also present
        for val in storage_matches:
            if val != attrs.get("ram_gb") or val >= 128:
                attrs["storage_gb"] = val
                break

    if m := _REFRESH_HZ_RE.search(title):
        attrs["refresh_hz"] = int(m.group(1))

    if m := _SCREEN_INCH_RE.search(title):
        inch = float(m.group(1))
        attrs["screen_size_inch"] = int(inch) if inch.is_integer() else inch

    return attrs


def _extract_jsonld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw_text = (script.string or script.get_text() or "").strip()
        if not raw_text:
            continue
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            continue

        candidates: list[Any]
        if isinstance(parsed, list):
            candidates = parsed
        elif isinstance(parsed, dict):
            if parsed.get("@type") == "Product":
                candidates = [parsed]
            elif isinstance(parsed.get("@graph"), list):
                candidates = parsed["@graph"]
            else:
                candidates = []
        else:
            candidates = []

        for obj in candidates:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                products.append(obj)

    return products


def _extract_dom_tiles(soup: BeautifulSoup, base_url: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Index Magento category tiles by normalized URL (plus ordered fallback list)."""
    by_url: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []

    for li in soup.select("li.product-item"):
        pid_el = li.select_one("[data-product-id]")
        product_id = str(pid_el.get("data-product-id") or "").strip() if pid_el else ""

        link_el = li.select_one("a.product-item-link") or li.select_one("a.product-item-photo")
        href = str(link_el.get("href") or "").strip() if link_el else ""
        full_href = urljoin(base_url, href) if href and href != "#" else ""

        old_el = li.select_one('[data-price-type="oldPrice"]')
        old_raw = (
            old_el.get("data-price-amount") or old_el.get_text(" ", strip=True)
            if old_el
            else None
        )
        old_price: Optional[Decimal] = parse_egp_price(old_raw)

        final_el = li.select_one('[data-price-type="finalPrice"]')
        final_raw = (
            final_el.get("data-price-amount") or final_el.get_text(" ", strip=True)
            if final_el
            else None
        )
        final_price: Optional[Decimal] = parse_egp_price(final_raw)

        tile_info = {
            "product_id": product_id or None,
            "href": full_href or None,
            "old_price": old_price,
            "final_price": final_price,
        }
        ordered.append(tile_info)
        if full_href:
            by_url[_normalize_url_key(full_href)] = tile_info

    return by_url, ordered


def _refine_sub_category(default_subcat: str, category: Category, title: str) -> str:
    if category == "home_appliances" and default_subcat in ("large_appliances", "small_appliances", "kitchen_appliances"):
        low = title.lower()
        for keywords, mapped in _APPLIANCE_SUBCAT_REFINERS:
            if any(kw in low for kw in keywords):
                return mapped
    return default_subcat


class TwoBScraper(BaseScraper):
    """Live catalog scraper for 2B Egypt (electronics & home appliances)."""

    store_name = "2b"
    category: Category = "electronics"
    base_url = "https://2b.com.eg"
    default_limit = 400
    discover_limit = 1200
    min_delay_seconds = 2.5
    request_timeout = 45.0
    page_limit = 48

    def _build_record(
        self,
        ld_item: dict[str, Any],
        tile: Optional[dict[str, Any]],
        category: Category,
        sub_category: str,
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        title = str(ld_item.get("name") or "").strip()
        if not title:
            return None

        offers_raw = ld_item.get("offers")
        offer: dict[str, Any] = {}
        if isinstance(offers_raw, list) and offers_raw and isinstance(offers_raw[0], dict):
            offer = offers_raw[0]
        elif isinstance(offers_raw, dict):
            offer = offers_raw

        raw_url = str(ld_item.get("url") or offer.get("url") or (tile or {}).get("href") or "").strip()
        if not raw_url:
            return None
        product_url = urljoin(self.base_url, raw_url)

        current_price = parse_egp_price(offer.get("price")) or (tile or {}).get("final_price")
        if current_price is None:
            return None

        old_price = (tile or {}).get("old_price")
        claimed_original_price = (
            old_price if (old_price is not None and old_price > current_price) else None
        )

        availability = str(offer.get("availability") or "").lower()
        in_stock = "outofstock" not in availability if availability else True

        img_raw = ld_item.get("image")
        image_url: Optional[str] = None
        if isinstance(img_raw, list) and img_raw:
            image_url = str(img_raw[0]).strip()
        elif isinstance(img_raw, str) and img_raw.strip():
            image_url = img_raw.strip()
        if image_url:
            image_url = urljoin(self.base_url, image_url)

        brand_raw = ld_item.get("brand")
        brand_name = brand_raw.get("name") if isinstance(brand_raw, dict) else (
            str(brand_raw) if isinstance(brand_raw, str) else None
        )
        brand = _normalize_brand(brand_name, title)

        # Prefer Magento `data-product-id`; fall back to URL slug stem
        dom_pid = (tile or {}).get("product_id")
        if dom_pid:
            external_id = str(dom_pid).strip()[:120]
        else:
            slug_stem = urlparse(product_url).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
            external_id = slug_stem[:120]

        refined_subcat = _refine_sub_category(sub_category, category, title)
        attrs = _extract_specs(title, refined_subcat)
        if dom_pid:
            attrs["magento_product_id"] = str(dom_pid)

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": category,
                "sub_category": refined_subcat,
                "brand": brand,
                "product_title": title,
                "product_url": product_url,
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original_price,
                "in_stock": in_stock,
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
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_cat_cap = max(5, math.ceil(target_limit / len(TWO_B_CATEGORIES)))
        max_pages = 8 if self.mode == "discover" else 2
        self.category_counts = {}
        failed_categories: list[str] = []

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 45.0,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.4, 1.2),
        ) as client:
            for sub_category, cat_name, category_url in TWO_B_CATEGORIES:
                if len(collected) >= target_limit:
                    break

                cat_key = f"{cat_name}/{sub_category}"
                cat_collected = 0
                page = 1
                while len(collected) < target_limit and cat_collected < per_cat_cap and page <= max_pages:
                    logger.info(
                        "[2b] Fetching %s page %d (%s?p=%d&product_list_limit=%d)",
                        cat_key,
                        page,
                        category_url,
                        page,
                        self.page_limit,
                    )
                    try:
                        resp = client.get(
                            category_url,
                            params={"p": page, "product_list_limit": self.page_limit},
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=True,
                            min_html_bytes=5120,
                        )
                    except ThrottledResponseError as exc:
                        logger.warning(
                            "[2b] Throttled/blocked on %s page %d (%s); moving to next category.",
                            cat_key,
                            page,
                            exc,
                        )
                        failed_categories.append(f"{cat_key}(throttled)")
                        break
                    except Exception as exc:
                        logger.warning("[2b] Error fetching %s page %d: %s; moving to next category.", cat_key, page, exc)
                        failed_categories.append(f"{cat_key}(error)")
                        break
                    self.pages_fetched += 1

                    soup = BeautifulSoup(resp.text, "html.parser")
                    ld_products = _extract_jsonld_products(soup)
                    tiles_by_url, tiles_ordered = _extract_dom_tiles(soup, self.base_url)

                    if not ld_products:
                        logger.warning("[2b] No JSON-LD products on %s page %d; moving to next category.", cat_key, page)
                        if page == 1:
                            failed_categories.append(f"{cat_key}(empty)")
                        break

                    page_records: list[RawProductSnapshot] = []
                    for idx, ld_item in enumerate(ld_products):
                        raw_url = str(ld_item.get("url") or "").strip()
                        tile = (
                            tiles_by_url.get(_normalize_url_key(urljoin(self.base_url, raw_url)))
                            if raw_url
                            else None
                        )
                        if tile is None and idx < len(tiles_ordered) and len(tiles_ordered) == len(ld_products):
                            tile = tiles_ordered[idx]

                        record = self._build_record(
                            ld_item=ld_item,
                            tile=tile,
                            category=cat_name,
                            sub_category=sub_category,
                            snapshot_date=snapshot_date,
                            scraped_at=scraped_at,
                        )
                        if record is not None and record.external_id not in seen_ids:
                            page_records.append(record)

                    # Prioritize previously tracked SKUs first in `daily` mode
                    page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)

                    added_this_page = 0
                    for record in page_records:
                        if record.external_id in seen_ids:
                            continue
                        seen_ids.add(record.external_id)
                        collected.append(record)
                        cat_collected += 1
                        added_this_page += 1
                        if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                            break

                    has_next = soup.find("link", rel="next") is not None
                    if not has_next or added_this_page == 0:
                        break
                    page += 1

                self.category_counts[cat_key] = cat_collected

        logger.info("[2b] Per-category scraped counts: %s", self.category_counts)
        if failed_categories:
            logger.warning("[2b] Categories with fetch/parse issues: %s", ", ".join(failed_categories))

        return collected
