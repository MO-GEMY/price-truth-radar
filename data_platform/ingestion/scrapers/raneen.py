"""
Live scraper for Raneen Egypt (`https://www.raneen.com`).

Uses plain HTTP (`PoliteHttpClient` / `httpx`) to parse Raneen's server-rendered
Magento Hyva category pages (`/en/appliances`, `/en/electronics`, `/en/kitchen`,
`/en/deals/daily-deals`) with `?p={N}` pagination — avoiding the stale sitemap.
Extracts `.product-item` cards with `Special Price` / `Regular Price` EGP prices,
strikethroughs, images, and product URLs.
"""

from __future__ import annotations

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
    RawProductSnapshot,
    ScrapeVertical,
    parse_egp_price,
    utc_now_naive,
)
from .two_b import _extract_specs, _normalize_brand, _refine_sub_category

logger = logging.getLogger(__name__)

RANEEN_CATEGORIES: tuple[tuple[str, Category, str], ...] = (
    ("large_appliances", "home_appliances", "https://www.raneen.com/en/appliances"),
    ("smartphones", "electronics", "https://www.raneen.com/en/electronics"),
    ("kitchen_appliances", "home_appliances", "https://www.raneen.com/en/kitchen"),
    ("small_appliances", "home_appliances", "https://www.raneen.com/en/deals/daily-deals"),
)

_EGP_PRICE_RE = re.compile(r"EGP\s*(\d[\d,]*(?:\.\d{1,2})?)", re.I)


class RaneenScraper(BaseScraper):
    """Live SSR scraper for Raneen Egypt (home_appliances & electronics)."""

    store_name = "raneen"
    category: Category = "home_appliances"
    base_url = "https://www.raneen.com"
    default_limit = 200
    discover_limit = 900
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 1.5
    request_timeout = 30.0

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
        per_cat_cap = max(2, math.ceil(target_limit / len(RANEEN_CATEGORIES)))
        max_pages = 8 if self.mode == "discover" else (3 if target_limit > 40 else 1)

        for default_sub, cat_name, cat_url in RANEEN_CATEGORIES:
            if len(collected) >= target_limit:
                break
            cat_collected = 0

            for page in range(1, max_pages + 1):
                if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                    break
                logger.info("[raneen] Fetching %s/%s page %d (%s)", cat_name, default_sub, page, cat_url)
                try:
                    resp = self.http.get(
                        cat_url,
                        params={"p": page} if page > 1 else None,
                        min_delay_seconds=effective_delay,
                        timeout=self.request_timeout,
                    )
                except Exception as exc:
                    logger.warning("[raneen] Error fetching %s page %d: %s", cat_url, page, exc)
                    break

                self.pages_fetched += 1
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select(".product-item")
                if not cards:
                    break

                page_records: list[RawProductSnapshot] = []
                for card in cards:
                    link = (
                        card.select_one("a.product-item-link[href]")
                        or card.select_one("a.product-item-photo[href]")
                        or card.select_one("a[href*='/en/']")
                    )
                    if not link:
                        continue
                    href = str(link.get("href") or "").strip()
                    if not href or href.startswith("#") or "/customer/" in href:
                        continue
                    product_url = urljoin(self.base_url, href)
                    slug = urlparse(product_url).path.rstrip("/").rsplit("/", 1)[-1]
                    if not slug:
                        continue

                    # Title
                    title_el = (
                        card.select_one("a.product-item-link")
                        or card.select_one("h2, h3, h4")
                    )
                    title = re.sub(r"\s+", " ", (title_el.get_text(" ", strip=True) if title_el else "")).strip()
                    if len(title) < 4:
                        img_alt = card.select_one("img[alt]")
                        title = str(img_alt.get("alt") or "").strip() if img_alt else ""
                    if len(title) < 4:
                        continue

                    # Prices (Magento data-price-amount or EGP text)
                    current_price: Optional[Decimal] = None
                    claimed_price: Optional[Decimal] = None

                    fin_el = card.select_one('[data-price-type="finalPrice"]')
                    old_el = card.select_one('[data-price-type="oldPrice"]')
                    if fin_el:
                        current_price = parse_egp_price(fin_el.get("data-price-amount") or fin_el.get_text(" ", strip=True))
                    if old_el:
                        claimed_price = parse_egp_price(old_el.get("data-price-amount") or old_el.get_text(" ", strip=True))

                    if current_price is None:
                        card_txt = card.get_text(" ", strip=True)
                        nums = [parse_egp_price(m) for m in _EGP_PRICE_RE.findall(card_txt)]
                        nums = [n for n in nums if n is not None and n >= Decimal("10")]
                        if nums:
                            current_price = nums[0]
                            if len(nums) >= 2 and nums[1] > current_price:
                                claimed_price = nums[1]

                    if current_price is None:
                        continue
                    if claimed_price is not None and claimed_price <= current_price:
                        claimed_price = None

                    img = card.select_one("img")
                    img_src = None
                    if img:
                        for attr in ("data-src", "src"):
                            val = str(img.get(attr) or "").strip()
                            if val.startswith("http") and "placeholder" not in val.lower() and not val.endswith(".svg"):
                                img_src = val
                                break

                    pid_el = card.select_one("[data-product-id]")
                    ext_id = str(pid_el.get("data-product-id") or slug).strip()[:120]
                    if ext_id in seen_ids:
                        continue

                    brand = _normalize_brand(None, title)
                    sub_cat = _refine_sub_category(default_sub, cat_name, title)
                    attrs: dict[str, Any] = _extract_specs(title, sub_cat)
                    attrs.pop("two_b_category", None)
                    attrs["raneen_category"] = sub_cat
                    card_low = card.get_text(" ", strip=True).lower()
                    in_stock = "out of stock" not in card_low

                    rec = self.validate_record(
                        {
                            "store_name": self.store_name,
                            "external_id": ext_id,
                            "canonical_product_key": None,
                            "category": cat_name,
                            "sub_category": sub_cat,
                            "brand": brand,
                            "product_title": title,
                            "product_url": product_url,
                            "image_url": img_src,
                            "attributes_json": attrs,
                            "current_price": current_price,
                            "claimed_original_price": claimed_price,
                            "in_stock": in_stock,
                            "snapshot_date": snapshot_date,
                            "scraped_at": scraped_at,
                        }
                    )
                    if rec is not None:
                        page_records.append(rec)

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

        logger.info("[raneen] Per-category counts: %s", self.category_counts)
        return collected
