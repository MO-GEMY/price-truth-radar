"""
Live scraper for Raya Shop Egypt (`https://www.rayashop.com`).

Uses `curl_cffi` TLS impersonation (`ImpersonatedHttpClient`, `impersonate="chrome"`)
across Raya Shop's SSR category pages (`/en/mobiles-and-tablets`,
`/en/televisions-and-receivers`, `/en/large-appliances`, `/en/laptops-pcs`,
`/en/small-appliances`). Parses embedded `JSON-LD Product` blocks when present
and falls back cleanly to SSR product card DOM extraction. Includes graceful
403/WAF detection so datacenter blocks exit cleanly without breaking other stores.
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
    ScrapeVertical,
    ThrottledResponseError,
    parse_egp_price,
    utc_now_naive,
)
from .two_b import _extract_specs, _normalize_brand, _refine_sub_category

logger = logging.getLogger(__name__)

RAYASHOP_CATEGORIES: tuple[tuple[str, Category, str], ...] = (
    ("smartphones", "electronics", "https://www.rayashop.com/en/mobiles-and-tablets"),
    ("tvs", "home_appliances", "https://www.rayashop.com/en/televisions-and-receivers"),
    ("laptops", "electronics", "https://www.rayashop.com/en/laptops-pcs"),
    ("large_appliances", "home_appliances", "https://www.rayashop.com/en/large-appliances"),
    ("small_appliances", "home_appliances", "https://www.rayashop.com/en/small-appliances"),
)

_PRICE_NUM_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,7}(?:\.\d{1,2})?)\s*EGP", re.I)


def _extract_jsonld_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = parsed if isinstance(parsed, list) else [parsed]
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if node.get("@type") == "Product" and node.get("name"):
                    found.append(node)
                for key in ("@graph", "itemListElement", "mainEntity", "hasPart"):
                    child = node.get(key)
                    if isinstance(child, (list, dict)):
                        stack.append(child)
                if isinstance(node.get("item"), dict):
                    stack.append(node["item"])
    return found


class RayaShopScraper(BaseScraper):
    """Live scraper for Raya Shop Egypt (`curl_cffi` chrome + JSON-LD / SSR DOM)."""

    store_name = "rayashop"
    category: Category = "electronics"
    base_url = "https://www.rayashop.com"
    default_limit = 200
    discover_limit = 800
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 2.0
    request_timeout = 30.0

    def _parse_dom_cards(
        self,
        soup: BeautifulSoup,
        cat_name: Category,
        default_sub: str,
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> list[RawProductSnapshot]:
        results: list[RawProductSnapshot] = []
        seen_urls: set[str] = set()

        # RayaShop Nuxt product links sit inside cards containing an EGP price + img
        for anchor in soup.select('a[href^="/en/"], a[href^="https://www.rayashop.com/en/"]'):
            href = str(anchor.get("href") or "").strip()
            path = urlparse(urljoin(self.base_url, href)).path.rstrip("/")
            if not path or path.count("/") < 2:
                continue
            if any(
                skip in path.lower()
                for skip in ("/login", "/cart", "/account", "/checkout", "/black-friday", "/brands", "/stores", "/category")
            ):
                continue
            full_url = urljoin(self.base_url, path)
            if full_url in seen_urls:
                continue

            # Walk up up to 3 parents to find card containing price + image
            card = anchor
            for _ in range(3):
                txt = card.get_text(" ", strip=True)
                if _PRICE_NUM_RE.search(txt) and card.select_one("img"):
                    break
                if card.parent:
                    card = card.parent

            card_txt = card.get_text(" ", strip=True)
            price_matches = [parse_egp_price(m) for m in _PRICE_NUM_RE.findall(card_txt)]
            valid_prices = [p for p in price_matches if p is not None and p >= Decimal("50")]
            if not valid_prices:
                continue

            # Skip if card is actually an entire container with > 4 prices
            if len(valid_prices) > 4:
                continue

            current_price = min(valid_prices)
            max_price = max(valid_prices)
            claimed_price = max_price if max_price > current_price else None

            title = ""
            for sel in ("h2", "h3", "h4", "[class*='title']", "[class*='name']"):
                el = card.select_one(sel)
                if el:
                    cand = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
                    if len(cand) >= 8 and "EGP" not in cand:
                        title = cand
                        break
            if not title:
                img = card.select_one("img[alt]")
                if img:
                    title = re.sub(r"\s+", " ", str(img.get("alt") or "")).strip()
            if len(title) < 6:
                continue

            img_url: Optional[str] = None
            for img in card.select("img"):
                for attr in ("data-src", "src"):
                    val = str(img.get(attr) or "").strip()
                    if val.startswith("http") and not val.endswith(".svg") and "logo" not in val.lower():
                        img_url = val
                        break
                if img_url:
                    break

            slug = path.rsplit("/", 1)[-1]
            seen_urls.add(full_url)
            brand = _normalize_brand(None, title)
            sub_cat = _refine_sub_category(default_sub, cat_name, title)
            attrs: dict[str, Any] = _extract_specs(title, sub_cat)
            attrs.pop("two_b_category", None)
            attrs["rayashop_category"] = sub_cat

            rec = self.validate_record(
                {
                    "store_name": self.store_name,
                    "external_id": slug[:120],
                    "canonical_product_key": None,
                    "category": cat_name,
                    "sub_category": sub_cat,
                    "brand": brand,
                    "product_title": title,
                    "product_url": full_url,
                    "image_url": img_url,
                    "attributes_json": attrs,
                    "current_price": current_price,
                    "claimed_original_price": claimed_price,
                    "in_stock": "out of stock" not in card_txt.lower(),
                    "snapshot_date": snapshot_date,
                    "scraped_at": scraped_at,
                }
            )
            if rec is not None:
                results.append(rec)

        return results

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
        per_cat_cap = max(2, math.ceil(target_limit / len(RAYASHOP_CATEGORIES)))
        max_pages = 6 if self.mode == "discover" else (2 if target_limit > 40 else 1)
        blocked = False

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 30.0,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 1.0),
        ) as client:
            for default_sub, cat_name, cat_url in RAYASHOP_CATEGORIES:
                if len(collected) >= target_limit or blocked:
                    break
                cat_collected = 0

                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                        break
                    logger.info("[rayashop] Fetching %s/%s page %d (%s)", cat_name, default_sub, page, cat_url)
                    try:
                        resp = client.get(
                            cat_url,
                            params={"page": page} if page > 1 else None,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=True,
                            min_html_bytes=5120,
                        )
                    except ThrottledResponseError as exc:
                        logger.warning("[rayashop] WAF/403 block on %s (%s); exiting gracefully with %d snapshots.", cat_url, exc, len(collected))
                        blocked = True
                        break
                    except Exception as exc:
                        logger.warning("[rayashop] Fetch error on %s page %d: %s", cat_url, page, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    page_records: list[RawProductSnapshot] = []

                    # Primary: JSON-LD Product items when present
                    for ld in _extract_jsonld_items(soup):
                        title = re.sub(r"\s+", " ", str(ld.get("name") or "")).strip()
                        raw_url = str(ld.get("url") or "").strip()
                        offers = ld.get("offers")
                        offer = offers[0] if isinstance(offers, list) and offers else (offers if isinstance(offers, dict) else {})
                        price = parse_egp_price(offer.get("price"))
                        if not title or not raw_url or price is None:
                            continue
                        full_url = urljoin(self.base_url, raw_url)
                        slug = urlparse(full_url).path.rstrip("/").rsplit("/", 1)[-1]
                        img_raw = ld.get("image")
                        img_url = img_raw[0] if isinstance(img_raw, list) and img_raw else (img_raw if isinstance(img_raw, str) else None)
                        brand_obj = ld.get("brand")
                        raw_brand = brand_obj.get("name") if isinstance(brand_obj, dict) else (brand_obj if isinstance(brand_obj, str) else None)
                        sub_cat = _refine_sub_category(default_sub, cat_name, title)
                        attrs: dict[str, Any] = _extract_specs(title, sub_cat)
                        attrs.pop("two_b_category", None)
                        attrs["rayashop_category"] = sub_cat
                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": str(ld.get("sku") or slug)[:120],
                                "canonical_product_key": None,
                                "category": cat_name,
                                "sub_category": sub_cat,
                                "brand": _normalize_brand(raw_brand, title),
                                "product_title": title,
                                "product_url": full_url,
                                "image_url": img_url,
                                "attributes_json": attrs,
                                "current_price": price,
                                "claimed_original_price": None,
                                "in_stock": "outofstock" not in str(offer.get("availability") or "").lower(),
                                "snapshot_date": snapshot_date,
                                "scraped_at": scraped_at,
                            }
                        )
                        if rec is not None:
                            page_records.append(rec)

                    if not page_records:
                        page_records = self._parse_dom_cards(soup, cat_name, default_sub, snapshot_date, scraped_at)

                    page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                    added = 0
                    for rec in page_records:
                        if rec.external_id in seen_ids:
                            continue
                        seen_ids.add(rec.external_id)
                        collected.append(rec)
                        cat_collected += 1
                        added += 1
                        if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                            break

                    if added == 0:
                        break

                self.category_counts[f"{cat_name}/{default_sub}"] = cat_collected

        logger.info("[rayashop] Per-category counts: %s", self.category_counts)
        return collected
