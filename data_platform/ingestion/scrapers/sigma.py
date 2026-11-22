"""
Live scraper for Sigma Computer Egypt (`https://www.sigma-computer.com`).

Scrapes public server-rendered catalog pages (`/en/search?page={n}`), respecting
`robots.txt` (never calls `/api/`). Parses the embedded Next.js SSR product
payload as primary source and falls back to BeautifulSoup DOM extraction if
needed.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import (
    BaseScraper,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ThrottledResponseError,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)

logger = logging.getLogger(__name__)

_RSC_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_BRAND_ACRONYMS: dict[str, str] = {
    "hp": "HP",
    "lg": "LG",
    "asus": "ASUS",
    "msi": "MSI",
    "aoc": "AOC",
    "amd": "AMD",
    "wd": "WD",
    "xpg": "XPG",
    "pny": "PNY",
    "nzxt": "NZXT",
    "evga": "EVGA",
    "jbl": "JBL",
    "oppo": "OPPO",
    "tp-link": "TP-Link",
    "t-dagger": "T-Dagger",
    "hyperx": "HyperX",
    "g.skill": "G.Skill",
    "teamgroup": "TeamGroup",
    "lian li": "Lian Li",
    "cooler master": "Cooler Master",
    "western digital": "Western Digital",
}

_SUBCATEGORY_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("laptop", "notebook", "macbook"), "laptops"),
    (("monitor", "display", "screen"), "monitors"),
    (("headset", "headphone", "earphone", "earbud", "airpods"), "headphones"),
    (
        ("mouse", "keyboard", "controller", "gamepad", "game pad", "joystick", "webcam", "microphone", "speaker", "mousepad", "mouse pad"),
        "peripherals",
    ),
    (("smartphone", "mobile phone", "iphone", "galaxy a", "galaxy s", "redmi", "poco"), "smartphones"),
    (("tablet", "ipad"), "tablets"),
    (("ssd", "hdd", "hard drive", "storage", "nvme", "flash"), "storage"),
    (("ram", "memory", "ddr4", "ddr5"), "memory"),
    (("vga", "graphics", "gpu", "geforce", "rtx", "gtx", "radeon"), "gpus"),
    (("motherboard", "mainboard"), "motherboards"),
    (("processor", "cpu", "ryzen", "core i"), "cpus"),
    (("power supply", "psu"), "power_supplies"),
    (("case", "chassis"), "cases"),
    (("cooler", "cooling", "fan", "thermal"), "cooling"),
    (("router", "switch", "network", "wifi", "wi-fi"), "networking"),
    (("printer", "scanner"), "printers"),
    (("cable", "adapter", "hub", "charger", "bag", "stand", "chair", "accessory", "accessories"), "accessories"),
]

_RAM_RE = re.compile(r"\b(\d{1,3})\s*GB?\s*(?:DDR[345]|RAM)\b", re.I)
_STORAGE_TB_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*TB\b(?:\s*(?:SSD|NVMe|M\.2|HDD|PCIe))?", re.I)
_STORAGE_GB_RE = re.compile(r"\b(128|256|512|1000|1024|2000|2048)\s*GB\s*(?:SSD|NVMe|M\.2|SATA|PCIe|HDD)\b", re.I)
_REFRESH_HZ_RE = re.compile(r"\b(60|75|100|120|144|165|170|180|200|240|280|300|360)\s*Hz\b", re.I)
_SCREEN_INCH_RE = re.compile(r"\b(13\.3|14(?:\.\d)?|15\.3|15\.6|16(?:\.\d)?|17\.3|21\.5|23\.8|24(?:\.\d)?|27(?:\.\d)?|31\.5|32|34)\s*(?:\"|-?\s*inch)\b", re.I)
_GPU_RE = re.compile(r"\b((?:RTX|GTX|RX)\s*\d{3,4}(?:\s*(?:Ti|SUPER|XT))?)\b", re.I)


def _normalize_brand(raw_brand: Optional[str], title: str) -> str:
    candidate = (raw_brand or "").strip()
    if not candidate:
        first_token = title.strip().split(" ", 1)[0] if title.strip() else "Unknown"
        candidate = re.sub(r"[^A-Za-z0-9.\-+]", "", first_token) or "Unknown"

    lower = candidate.lower()
    if lower in _BRAND_ACRONYMS:
        return _BRAND_ACRONYMS[lower]
    if candidate.isupper() and len(candidate) > 3:
        return candidate.title()
    return candidate[:100]


def _normalize_sub_category(category_obj: Any, title: str) -> str:
    parts: list[str] = []
    if isinstance(category_obj, dict):
        if category_obj.get("name"):
            parts.append(str(category_obj["name"]))
        parent = category_obj.get("parent_category")
        if isinstance(parent, dict) and parent.get("name"):
            parts.append(str(parent["name"]))

    cat_haystack = " ".join(parts).lower()
    if cat_haystack:
        for keywords, mapped in _SUBCATEGORY_KEYWORDS:
            if any(kw in cat_haystack for kw in keywords):
                return mapped

    title_haystack = title.lower()
    for keywords, mapped in _SUBCATEGORY_KEYWORDS:
        if any(kw in title_haystack for kw in keywords):
            return mapped

    if parts:
        return normalize_snake_slug(parts[0], fallback="components", max_len=80)
    return "electronics"


def _extract_attributes(raw_product: dict[str, Any], title: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {}

    sku = str(raw_product.get("sku") or "").strip()
    if sku:
        attrs["sku"] = sku

    cat = raw_product.get("category")
    if isinstance(cat, dict) and cat.get("name"):
        attrs["sigma_category"] = str(cat["name"]).strip()

    if raw_product.get("is_free_shipping") is True:
        attrs["free_shipping"] = True

    offers = raw_product.get("offers")
    if isinstance(offers, list) and offers:
        offer_titles = [str(o.get("title")).strip() for o in offers if isinstance(o, dict) and o.get("title")]
        if offer_titles:
            attrs["offers"] = offer_titles

    # Parse lightweight hardware specs from product title when present
    if m := _RAM_RE.search(title):
        ram_gb = int(m.group(1))
        if 2 <= ram_gb <= 256:
            attrs["ram_gb"] = ram_gb

    if m := _STORAGE_TB_RE.search(title):
        tb_val = float(m.group(1))
        if 0.5 <= tb_val <= 24:
            attrs["storage_gb"] = int(round(tb_val * 1024))
    elif m := _STORAGE_GB_RE.search(title):
        attrs["storage_gb"] = int(m.group(1))

    if m := _REFRESH_HZ_RE.search(title):
        attrs["refresh_hz"] = int(m.group(1))

    if m := _SCREEN_INCH_RE.search(title):
        inch = float(m.group(1))
        attrs["screen_size_inch"] = int(inch) if inch.is_integer() else inch

    if m := _GPU_RE.search(title):
        attrs["gpu"] = re.sub(r"\s+", " ", m.group(1).strip().upper())

    return attrs


def _extract_rsc_products(html: str) -> tuple[list[dict[str, Any]], bool]:
    """Decode embedded Next.js SSR RSC chunks and return (products, has_next)."""
    chunks = _RSC_PUSH_RE.findall(html)
    if not chunks:
        return [], False

    parts: list[str] = []
    for chunk in chunks:
        try:
            parts.append(json.loads(f'"{chunk}"'))
        except json.JSONDecodeError:
            continue
    joined = "".join(parts)

    decoder = json.JSONDecoder()
    products: list[dict[str, Any]] = []
    marker = '"products":['
    search_pos = 0
    while True:
        idx = joined.find(marker, search_pos)
        if idx == -1:
            break
        try:
            arr, end_pos = decoder.raw_decode(joined, idx + len('"products":'))
            if isinstance(arr, list) and arr and isinstance(arr[0], dict) and "slug" in arr[0]:
                products = arr
                break
            search_pos = end_pos
        except json.JSONDecodeError:
            search_pos = idx + len(marker)

    has_next = '"isNext":true' in joined
    return products, has_next


class SigmaScraper(BaseScraper):
    """Live catalog scraper for Sigma Computer Egypt."""

    store_name = "sigma"
    category = "electronics"
    base_url = "https://www.sigma-computer.com"
    catalog_path = "/en/search"
    default_limit = 400
    discover_limit = 1200
    min_delay_seconds = 1.5
    request_timeout = 30.0
    per_page = 16

    def _parse_rsc_item(
        self,
        raw: dict[str, Any],
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        slug = str(raw.get("slug") or "").strip()
        if not slug:
            return None

        external_id = str(raw.get("id") or slug).strip()[:120]
        title = str(raw.get("name") or "").strip()
        if not title:
            return None

        price_obj = raw.get("price") if isinstance(raw.get("price"), dict) else {}
        current_price = parse_egp_price(price_obj.get("current"))
        if current_price is None:
            return None

        # Sigma sometimes stores an outdated lower `base` on non-discounted items;
        # only treat `base` as `claimed_original_price` when discounted and > current.
        is_discount = bool(raw.get("is_discount")) or (
            isinstance(price_obj.get("discount_percentage"), (int, float))
            and price_obj["discount_percentage"] > 0
        )
        base_price = parse_egp_price(price_obj.get("base"))
        claimed_original_price = (
            base_price if (is_discount and base_price is not None and base_price > current_price) else None
        )

        # Primary image from thumbnail, falling back to first media entry
        image_url: Optional[str] = None
        thumb = raw.get("thumbnail")
        if isinstance(thumb, dict) and thumb.get("url"):
            image_url = str(thumb["url"]).strip()
        else:
            media = raw.get("media")
            if isinstance(media, list):
                for entry in media:
                    if isinstance(entry, dict) and entry.get("url"):
                        image_url = str(entry["url"]).strip()
                        break

        brand_obj = raw.get("brand")
        brand_raw = brand_obj.get("name") if isinstance(brand_obj, dict) else None
        brand = _normalize_brand(brand_raw, title)
        sub_category = _normalize_sub_category(raw.get("category"), title)
        attributes_json = _extract_attributes(raw, title)

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": self.category,
                "sub_category": sub_category,
                "brand": brand,
                "product_title": title,
                "product_url": f"{self.base_url}/en/item?id={slug}",
                "image_url": image_url,
                "attributes_json": attributes_json,
                "current_price": current_price,
                "claimed_original_price": claimed_original_price,
                "in_stock": bool(raw.get("is_stock", True)),
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _parse_dom_fallback(
        self,
        html: str,
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> list[RawProductSnapshot]:
        """Fallback BeautifulSoup parser if Next.js RSC payload structure changes."""
        soup = BeautifulSoup(html, "html.parser")
        results: list[RawProductSnapshot] = []
        seen_hrefs: set[str] = set()

        for anchor in soup.find_all("a", href=re.compile(r"/en/item\?id=")):
            href = str(anchor.get("href") or "").strip()
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            slug = href.split("id=", 1)[-1].split("&", 1)[0].strip()
            if not slug:
                continue

            card = anchor
            for _ in range(5):
                txt = card.get_text(" ", strip=True)
                if re.search(r"\d[\d,]+\s*EGP", txt, re.I):
                    break
                if card.parent:
                    card = card.parent

            card_text = card.get_text(" ", strip=True)
            prices = [parse_egp_price(m) for m in re.findall(r"(\d[\d,]*(?:\.\d{1,2})?)\s*EGP", card_text, re.I)]
            valid_prices = [p for p in prices if p is not None]
            if not valid_prices:
                continue

            current_price = valid_prices[0]
            claimed_original = (
                valid_prices[1] if len(valid_prices) > 1 and valid_prices[1] > current_price else None
            )

            title = anchor.get_text(" ", strip=True)
            if not title or len(title) < 4:
                heading = card.find(["h2", "h3", "h4", "p"])
                title = heading.get_text(" ", strip=True) if heading else slug.replace("-", " ").title()

            img = card.find("img")
            img_src = (img.get("src") or img.get("data-src")) if img else None
            image_url = urljoin(self.base_url, str(img_src)) if img_src else None

            out_of_stock = "out of stock" in card_text.lower()
            snap = self.validate_record(
                {
                    "store_name": self.store_name,
                    "external_id": slug[:120],
                    "canonical_product_key": None,
                    "category": self.category,
                    "sub_category": _normalize_sub_category(None, title),
                    "brand": _normalize_brand(None, title),
                    "product_title": title,
                    "product_url": urljoin(self.base_url, href),
                    "image_url": image_url,
                    "attributes_json": _extract_attributes({}, title),
                    "current_price": current_price,
                    "claimed_original_price": claimed_original,
                    "in_stock": not out_of_stock,
                    "snapshot_date": snapshot_date,
                    "scraped_at": scraped_at,
                }
            )
            if snap is not None:
                results.append(snap)

        return results

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()

        # Estimate pages needed with a small buffer in case any item is skipped
        max_pages = max(1, math.ceil(target_limit / self.per_page) + 4)
        catalog_url = f"{self.base_url}{self.catalog_path}"
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 30.0,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.25, 0.8),
        ) as client:
            for page in range(1, max_pages + 1):
                if len(collected) >= target_limit:
                    break

                logger.info("[sigma] Fetching catalog page %d (%s?page=%d)", page, catalog_url, page)
                try:
                    resp = client.get(
                        catalog_url,
                        params={"page": page},
                        min_delay_seconds=effective_delay,
                        timeout=self.request_timeout,
                        check_throttle=True,
                        min_html_bytes=5120,
                    )
                except ThrottledResponseError as exc:
                    logger.warning(
                        "[sigma] Throttled/blocked on page %d (%s); stopping gracefully with %d snapshots.",
                        page,
                        exc,
                        len(collected),
                    )
                    break
                except Exception as exc:
                    logger.warning("[sigma] Failed to fetch page %d: %s; stopping gracefully.", page, exc)
                    break

                self.pages_fetched += 1

                raw_items, has_next = _extract_rsc_products(resp.text)
                page_records: list[RawProductSnapshot] = []

                if raw_items:
                    for raw in raw_items:
                        record = self._parse_rsc_item(raw, snapshot_date, scraped_at)
                        if record is not None:
                            page_records.append(record)
                else:
                    logger.warning("[sigma] RSC payload not found on page %d; using DOM fallback.", page)
                    page_records = self._parse_dom_fallback(resp.text, snapshot_date, scraped_at)

                if not page_records:
                    logger.info("[sigma] No products found on page %d; stopping pagination.", page)
                    break

                page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                added_this_page = 0
                for record in page_records:
                    if record.external_id in seen_ids:
                        continue
                    seen_ids.add(record.external_id)
                    collected.append(record)
                    added_this_page += 1
                    if len(collected) >= target_limit:
                        break

                if not has_next or added_this_page == 0:
                    break

        return collected
