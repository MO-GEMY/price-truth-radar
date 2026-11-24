"""Verified expansion store scrapers for major Egyptian retailers.

Covers high-impact Priority 1-3 Egyptian retailers verified against live
public APIs, Next.js `__NEXT_DATA__`, and SSR catalog grids:
- `jumia`            : Jumia Egypt (multi-vertical SSR + GA4 attributes, local_only)
- `elghazawy`        : El Ghazawy (public Laravel JSON API with EAN/model numbers)
- `homzmart`         : Homzmart Egypt (Next.js `__NEXT_DATA__` furniture & appliances)
- `decathlon_eg`     : Decathlon Egypt (SSR `.product-card` sports superstore)
- `misr_pharmacies`  : Misr Pharmacies (Magento SSR `.product-item`, health/skincare)
- `tdawi`            : Tdawi Pharmacy (Magento SSR `.product-item`, health/beauty)
- `elnekhely`        : Elnekhely Technology (OpenCart SSR PC hardware)
- `maximum_hardware` : Maximum Hardware (OpenCart SSR PC hardware)
- `gamesworldegypt`  : Games World Egypt (OpenCart SSR gaming & peripherals)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
import math
import re
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
from .groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)
from .platform_stores import SSRCardScraper, _extract_prices_from_text
from .two_b import _extract_specs, _normalize_brand, _refine_sub_category

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")


class JumiaScraper(BaseScraper):
    """Live SSR + GA4 scraper for Jumia Egypt (`https://www.jumia.com.eg`).

    Runs in `local_only` mode (residential Egypt IP) to avoid cloud-IP WAF blocks.
    """

    store_name = "jumia"
    category: Category = "electronics"
    base_url = "https://www.jumia.com.eg"
    default_limit = 300
    discover_limit = 900
    groceries_limit = 200
    fashion_limit = 200
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries", "fashion")
    min_delay_seconds = 2.0
    request_timeout = 25.0

    _CORE_URLS: tuple[tuple[str, Category, str], ...] = (
        ("large_appliances", "home_appliances", "https://www.jumia.com.eg/mlp-category-appliances/"),
        ("tvs", "home_appliances", "https://www.jumia.com.eg/televisions/"),
        ("smartphones", "electronics", "https://www.jumia.com.eg/smartphones/"),
        ("laptops", "electronics", "https://www.jumia.com.eg/laptops/"),
        ("computing", "electronics", "https://www.jumia.com.eg/computing/"),
        ("gaming", "electronics", "https://www.jumia.com.eg/video-games/"),
        ("accessories", "electronics", "https://www.jumia.com.eg/electronics/"),
        ("skincare", "beauty", "https://www.jumia.com.eg/health-beauty/"),
        ("furniture", "home_furniture", "https://www.jumia.com.eg/home-office/"),
        ("sports_gear", "sports", "https://www.jumia.com.eg/sporting-goods/"),
        ("baby_care", "baby_kids", "https://www.jumia.com.eg/baby-products/"),
    )
    _GROCERIES_URLS: tuple[tuple[str, Category, str], ...] = (
        ("oils_ghee", "groceries", "https://www.jumia.com.eg/groceries/"),
        ("tea_coffee", "groceries", "https://www.jumia.com.eg/beverages/"),
        ("detergents", "groceries", "https://www.jumia.com.eg/household-cleaning/"),
        ("snacks", "groceries", "https://www.jumia.com.eg/food-cupboard/"),
    )
    _FASHION_URLS: tuple[tuple[str, Category, str], ...] = (
        ("apparel", "fashion", "https://www.jumia.com.eg/category-fashion-by-jumia/"),
        ("shoes", "fashion", "https://www.jumia.com.eg/mens-shoes/"),
        ("shoes", "fashion", "https://www.jumia.com.eg/womens-shoes/"),
    )

    def _active_urls(self) -> tuple[tuple[str, Category, str], ...]:
        if self.vertical == "groceries":
            return self._GROCERIES_URLS
        if self.vertical == "fashion":
            return self._FASHION_URLS
        return self._CORE_URLS

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        urls = self._active_urls()
        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_cat_cap = max(8, math.ceil(target_limit / max(1, len(urls))))
        max_pages = 5 if self.mode == "discover" else 2
        blocked = False

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.4, 1.1),
        ) as client:
            for default_sub, cat_name, cat_url in urls:
                if len(collected) >= target_limit or blocked:
                    break
                cat_collected = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                        break
                    logger.info("[jumia] Fetching %s/%s page %d (%s)", cat_name, default_sub, page, cat_url)
                    try:
                        resp = client.get(
                            cat_url,
                            params={"page": page} if page > 1 else None,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=True,
                            min_html_bytes=4096,
                        )
                    except ThrottledResponseError as exc:
                        logger.warning("[jumia] WAF/throttle block on %s (%s); exiting gracefully.", cat_url, exc)
                        blocked = True
                        break
                    except Exception as exc:
                        logger.warning("[jumia] Error fetching %s page %d: %s", cat_url, page, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select("article.prd")
                    if not cards:
                        break

                    page_records: list[RawProductSnapshot] = []
                    for card in cards:
                        link = card.select_one("a.core[href]") or card.select_one("a[href]")
                        if not link:
                            continue
                        href = str(link.get("href") or "").strip()
                        if not href or href.startswith("#"):
                            continue
                        product_url = urljoin(self.base_url, href)

                        title = str(link.get("data-ga4-item_name") or "").strip()
                        if len(title) < 4:
                            name_el = card.select_one(".name, h3")
                            title = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True)).strip() if name_el else ""
                        if len(title) < 4:
                            continue

                        prc_el = card.select_one(".prc")
                        old_el = card.select_one(".old")
                        current_price = parse_egp_price(prc_el.get_text(" ", strip=True)) if prc_el else None
                        if current_price is None:
                            current_price = parse_egp_price(link.get("data-ga4-price"))
                        if current_price is None:
                            continue
                        claimed_price = parse_egp_price(old_el.get_text(" ", strip=True)) if old_el else None
                        if claimed_price is not None and claimed_price <= current_price:
                            claimed_price = None

                        img_url: Optional[str] = None
                        img = card.select_one("img")
                        if img:
                            for attr in ("data-src", "src"):
                                cand = str(img.get(attr) or "").strip()
                                if cand.startswith("http") and not cand.startswith("data:") and "placeholder" not in cand.lower():
                                    img_url = cand
                                    break

                        sku = str(link.get("data-ga4-item_id") or "").strip()
                        slug = urlparse(product_url).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
                        ext_id = (sku or slug)[:120]
                        if not ext_id or ext_id in seen_ids:
                            continue

                        raw_brand = str(link.get("data-ga4-item_brand") or "").strip() or None
                        if cat_name == "groceries":
                            brand = extract_grocery_brand(title, raw_brand or "")
                            sub_cat = refine_grocery_sub_category(title, default_sub)
                            attrs: dict[str, Any] = {"jumia_category": sub_cat}
                            attrs.update(parse_grocery_packaging(title))
                        else:
                            brand = _normalize_brand(raw_brand, title)
                            sub_cat = _refine_sub_category(default_sub, cat_name, title)
                            attrs = _extract_specs(title, sub_cat)
                            attrs.pop("two_b_category", None)
                            attrs["jumia_category"] = str(link.get("data-ga4-item_category3") or sub_cat)
                        if sku:
                            attrs["sku"] = sku

                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": ext_id,
                                "canonical_product_key": None,
                                "category": cat_name,
                                "sub_category": sub_cat,
                                "brand": brand[:100],
                                "product_title": title,
                                "product_url": product_url,
                                "image_url": img_url,
                                "attributes_json": attrs,
                                "current_price": current_price,
                                "claimed_original_price": claimed_price,
                                "in_stock": True,
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

        logger.info("[jumia] Per-category counts: %s", self.category_counts)
        return collected


class ElGhazawyScraper(BaseScraper):
    """Live JSON API scraper for El Ghazawy Egypt (`https://elghazawy.com`).

    Queries El Ghazawy's official public Laravel API (`/api/search` & `/api/products`),
    extracting 13-digit EAN `part_number`, `model_number`, brand, and EGP pricing.
    """

    store_name = "elghazawy"
    category: Category = "home_appliances"
    base_url = "https://elghazawy.com"
    default_limit = 300
    discover_limit = 800
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 1.0
    request_timeout = 20.0

    # (default_sub, category, search_query)
    _SEARCH_QUERIES: tuple[tuple[str, Category, str], ...] = (
        ("refrigerators", "home_appliances", "refrigerator"),
        ("washing_machines", "home_appliances", "washing machine"),
        ("air_conditioners", "home_appliances", "air conditioner"),
        ("cookers", "home_appliances", "cooker"),
        ("tvs", "home_appliances", "tv"),
        ("microwaves", "home_appliances", "microwave"),
        ("water_heaters", "home_appliances", "heater"),
        ("vacuums", "home_appliances", "vacuum"),
        ("small_appliances", "home_appliances", "blender"),
        ("small_appliances", "home_appliances", "air fryer"),
        ("smartphones", "electronics", "samsung"),
        ("smartphones", "electronics", "iphone"),
        ("laptops", "electronics", "laptop"),
    )

    def _parse_item(
        self,
        raw: dict[str, Any],
        default_sub: str,
        cat_name: Category,
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        item_id = raw.get("id")
        slug = str(raw.get("slug") or "").strip()
        title = re.sub(r"\s+", " ", str(raw.get("name_en") or raw.get("name_ar") or "")).strip()
        if not item_id or len(title) < 4:
            return None

        reg_price = parse_egp_price(raw.get("regular_price") or raw.get("site_price") or raw.get("price"))
        disc_price = parse_egp_price(raw.get("price_after_discount") or raw.get("offer_price"))
        if disc_price is not None and (reg_price is None or disc_price < reg_price):
            current_price = disc_price
            claimed_original = reg_price if (reg_price is not None and reg_price > current_price) else None
        else:
            current_price = reg_price
            claimed_original = None
        if current_price is None:
            return None

        brand_obj = raw.get("brand")
        raw_brand = (
            str(brand_obj.get("name_en") or brand_obj.get("name_ar") or "").strip()
            if isinstance(brand_obj, dict)
            else None
        )
        brand = _normalize_brand(raw_brand or None, title)
        sub_cat = _refine_sub_category(default_sub, cat_name, title)

        img_url = str(raw.get("imageUrl") or raw.get("img") or "").strip() or None
        if img_url and not img_url.startswith("http"):
            img_url = urljoin(self.base_url, img_url)

        product_url = f"{self.base_url}/en/product/{slug}" if slug else f"{self.base_url}/en/product/{item_id}"
        stock_bal = raw.get("stock_balance")
        in_stock = True if stock_bal is None else (float(stock_bal) > 0)

        attrs: dict[str, Any] = _extract_specs(title, sub_cat)
        attrs.pop("two_b_category", None)
        attrs["elghazawy_category"] = sub_cat
        part_num = re.sub(r"\D", "", str(raw.get("part_number") or ""))
        if _EAN_RE.match(part_num):
            attrs["ean"] = part_num
        model_num = str(raw.get("model_number") or "").strip()
        if model_num:
            attrs["model_number"] = model_num

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": str(item_id)[:120],
                "canonical_product_key": None,
                "category": cat_name,
                "sub_category": sub_cat,
                "brand": brand[:100],
                "product_title": title,
                "product_url": product_url,
                "image_url": img_url,
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

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_q_cap = max(8, math.ceil(target_limit / len(self._SEARCH_QUERIES)))
        max_pages = 4 if self.mode == "discover" else 2

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=3,
            backoff_base=1.5,
            min_delay_seconds=effective_delay,
            jitter_range=(0.2, 0.6),
        ) as client:
            for default_sub, cat_name, query in self._SEARCH_QUERIES:
                if len(collected) >= target_limit:
                    break
                q_collected = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or q_collected >= per_q_cap:
                        break
                    logger.info("[elghazawy] Fetching /api/search?q=%r page %d", query, page)
                    try:
                        resp = client.get(
                            f"{self.base_url}/api/search",
                            params={"q": query, "page": page},
                            headers={"Accept": "application/json"},
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=False,
                        )
                        payload = resp.json()
                    except Exception as exc:
                        logger.warning("[elghazawy] API error on q=%r page %d: %s", query, page, exc)
                        break

                    self.pages_fetched += 1
                    data_block = payload.get("data") or {}
                    items = data_block.get("data") if isinstance(data_block, dict) else (data_block if isinstance(data_block, list) else [])
                    if not items:
                        break

                    page_records: list[RawProductSnapshot] = []
                    for raw in items:
                        if not isinstance(raw, dict):
                            continue
                        rec = self._parse_item(raw, default_sub, cat_name, snapshot_date, scraped_at)
                        if rec is not None and rec.external_id not in seen_ids:
                            page_records.append(rec)

                    page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                    added = 0
                    for rec in page_records:
                        if rec.external_id in seen_ids:
                            continue
                        seen_ids.add(rec.external_id)
                        collected.append(rec)
                        q_collected += 1
                        added += 1
                        if len(collected) >= target_limit or q_collected >= per_q_cap:
                            break

                    last_page = int(data_block.get("last_page") or 1) if isinstance(data_block, dict) else 1
                    if page >= last_page or added == 0:
                        break
                self.category_counts[f"{cat_name}/{default_sub}"] = (
                    self.category_counts.get(f"{cat_name}/{default_sub}", 0) + q_collected
                )

        logger.info("[elghazawy] Per-category counts: %s", self.category_counts)
        return collected


class HomzmartScraper(BaseScraper):
    """Live Next.js `__NEXT_DATA__` scraper for Homzmart Egypt (`https://homzmart.com/en`)."""

    store_name = "homzmart"
    category: Category = "home_furniture"
    base_url = "https://homzmart.com"
    default_limit = 250
    discover_limit = 650
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 1.5
    request_timeout = 25.0

    _CATEGORY_URLS: tuple[tuple[str, Category, str], ...] = (
        ("large_appliances", "home_appliances", "https://homzmart.com/en/c/home-appliances"),
        ("sofas", "home_furniture", "https://homzmart.com/en/c/furniture"),
        ("cookware", "home_furniture", "https://homzmart.com/en/c/kitchen"),
        ("lighting", "home_furniture", "https://homzmart.com/en/c/lighting"),
        ("accessories", "electronics", "https://homzmart.com/en/c/electronics"),
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
        per_cat_cap = max(8, math.ceil(target_limit / len(self._CATEGORY_URLS)))
        max_pages = 5 if self.mode == "discover" else 2

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 0.9),
        ) as client:
            for default_sub, cat_name, cat_url in self._CATEGORY_URLS:
                if len(collected) >= target_limit:
                    break
                cat_collected = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                        break
                    logger.info("[homzmart] Fetching %s/%s page %d (%s)", cat_name, default_sub, page, cat_url)
                    try:
                        resp = client.get(
                            cat_url,
                            params={"page": page} if page > 1 else None,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=False,
                        )
                    except Exception as exc:
                        logger.warning("[homzmart] Error fetching %s page %d: %s", cat_url, page, exc)
                        break

                    self.pages_fetched += 1
                    m = _NEXT_DATA_RE.search(resp.text or "")
                    if not m:
                        break
                    try:
                        nd = json.loads(m.group(1))
                    except json.JSONDecodeError:
                        break

                    prods_block = (
                        (((nd.get("props") or {}).get("pageProps") or {}).get("initialData") or {}).get("products")
                        or {}
                    )
                    raw_items = prods_block.get("items") or []
                    if not raw_items:
                        break

                    page_records: list[RawProductSnapshot] = []
                    for raw in raw_items:
                        if not isinstance(raw, dict):
                            continue
                        sku = str(raw.get("sku") or raw.get("id") or "").strip()
                        title = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()
                        url_key = str(raw.get("url_key") or "").strip()
                        if not sku or len(title) < 4:
                            continue

                        pr = (raw.get("price_range") or {}).get("minimum_price") or {}
                        curr_val = (pr.get("final_price") or {}).get("value")
                        reg_val = (pr.get("regular_price") or {}).get("value")
                        current_price = parse_egp_price(curr_val)
                        if current_price is None:
                            continue
                        reg_price = parse_egp_price(reg_val)
                        claimed_orig = reg_price if (reg_price is not None and reg_price > current_price) else None

                        img_obj = raw.get("image") or raw.get("small_image")
                        img_url = img_obj.get("url") if isinstance(img_obj, dict) else (str(img_obj) if isinstance(img_obj, str) else None)
                        if img_url and not img_url.startswith("http"):
                            img_url = urljoin(self.base_url, img_url)

                        ext_id = sku[:120]
                        if ext_id in seen_ids:
                            continue

                        sub_cat = _refine_sub_category(default_sub, cat_name, title)
                        brand = _normalize_brand(str(raw.get("seller_name") or "") or None, title)
                        attrs: dict[str, Any] = _extract_specs(title, sub_cat)
                        attrs.pop("two_b_category", None)
                        attrs["homzmart_category"] = str(raw.get("main_category") or sub_cat)
                        ean = re.sub(r"\D", "", str(raw.get("barcode_ean") or ""))
                        if _EAN_RE.match(ean):
                            attrs["ean"] = ean

                        stock_status = str(raw.get("stock_status") or "IN_STOCK").upper()
                        in_stock = stock_status == "IN_STOCK"
                        product_url = f"{self.base_url}/en/p/{url_key}" if url_key else f"{self.base_url}/en/p/{sku}"

                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": ext_id,
                                "canonical_product_key": None,
                                "category": cat_name,
                                "sub_category": sub_cat,
                                "brand": brand[:100],
                                "product_title": title,
                                "product_url": product_url,
                                "image_url": img_url,
                                "attributes_json": attrs,
                                "current_price": current_price,
                                "claimed_original_price": claimed_orig,
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

        logger.info("[homzmart] Per-category counts: %s", self.category_counts)
        return collected


class DecathlonEgScraper(SSRCardScraper):
    store_name = "decathlon_eg"
    category: Category = "sports"
    base_url = "https://www.decathlon.eg"
    card_selector = "article.product-card"
    title_selector = "h2, h3, .product-title, a[href*='/p/']"
    link_selector = "a[href*='/p/'], a[href]"
    price_selector = ".price, [data-price], .current-price"
    old_price_selector = ".regular-price, .old-price, del, s"
    use_impersonation = True
    check_throttle = False
    default_limit = 220
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("sports_gear", "sports", "https://www.decathlon.eg/en/4773-sports"),
        ("sports_gear", "sports", "https://www.decathlon.eg/en/4774-water-sports"),
        ("sports_gear", "sports", "https://www.decathlon.eg/en/4849-beach-sports"),
        ("sports_gear", "sports", "https://www.decathlon.eg/en/"),
    )


class MisrPharmaciesScraper(SSRCardScraper):
    store_name = "misr_pharmacies"
    category: Category = "health"
    base_url = "https://misr-online.com"
    card_selector = ".product-item"
    title_selector = ".product-item-link, a.product-item-link"
    link_selector = "a.product-item-link[href], a.product-item-photo[href]"
    price_selector = ".special-price .price, [data-price-type='finalPrice'] .price, .price"
    old_price_selector = ".old-price .price, [data-price-type='oldPrice'] .price"
    page_param = "p"
    use_impersonation = True
    check_throttle = False
    default_limit = 220
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("pharmacy", "health", "https://misr-online.com/en/skin-care.html"),
        ("pharmacy", "health", "https://misr-online.com/en/skin-care/face-care/sun-screen.html"),
        ("pharmacy", "health", "https://misr-online.com/en/skin-care/face-care/facial-cleansers.html"),
        ("pharmacy", "health", "https://misr-online.com/en/skin-care/face-care/facial-moisturizers.html"),
        ("pharmacy", "health", "https://misr-online.com/en/"),
    )


class TdawiScraper(SSRCardScraper):
    store_name = "tdawi"
    category: Category = "health"
    base_url = "https://tdawi.com"
    card_selector = ".product-item"
    title_selector = ".product-item-link, a.product-item-link"
    link_selector = "a.product-item-link[href], a.product-item-photo[href]"
    price_selector = ".special-price .price, [data-price-type='finalPrice'] .price, .price"
    old_price_selector = ".old-price .price, [data-price-type='oldPrice'] .price"
    page_param = "p"
    use_impersonation = True
    check_throttle = False
    default_limit = 220
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("pharmacy", "health", "https://tdawi.com/en_eg/health-beauty"),
        ("vitamins", "health", "https://tdawi.com/en_eg/vitamins-dietary-supplements"),
        ("pharmacy", "health", "https://tdawi.com/en_eg/perfumes-fragrances"),
        ("pharmacy", "health", "https://tdawi.com/en_eg/mom-baby"),
    )


class ElnekhelyScraper(SSRCardScraper):
    store_name = "elnekhely"
    category: Category = "electronics"
    base_url = "https://www.elnekhelytechnology.com"
    card_selector = ".product-thumb"
    title_selector = ".name a, h4 a"
    link_selector = ".name a[href], a[href]"
    price_selector = ".price-new, .price-normal"
    old_price_selector = ".price-old"
    use_impersonation = True
    check_throttle = False
    default_limit = 220
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("motherboards", "electronics", "https://www.elnekhelytechnology.com/motherboards"),
        ("cpus", "electronics", "https://www.elnekhelytechnology.com/processors"),
        ("ram", "electronics", "https://www.elnekhelytechnology.com/ram"),
        ("gpus", "electronics", "https://www.elnekhelytechnology.com/graphic-cards"),
        ("monitors", "electronics", "https://www.elnekhelytechnology.com/monitors"),
        ("storage", "electronics", "https://www.elnekhelytechnology.com/storage"),
    )


class MaximumHardwareScraper(SSRCardScraper):
    store_name = "maximum_hardware"
    category: Category = "electronics"
    base_url = "https://maximumhardware.store"
    card_selector = ".product-thumb"
    title_selector = ".name a, h4 a"
    link_selector = ".name a[href], a[href]"
    price_selector = ".price-new, .price-normal"
    old_price_selector = ".price-old"
    use_impersonation = True
    check_throttle = False
    default_limit = 220
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("accessories", "electronics", "https://maximumhardware.store/index.php?route=product/special"),
        ("accessories", "electronics", "https://maximumhardware.store/new-arrivals"),
        ("desktops", "electronics", "https://maximumhardware.store/bundles"),
        ("accessories", "electronics", "https://maximumhardware.store/"),
    )


class GamesWorldEgyptScraper(SSRCardScraper):
    store_name = "gamesworldegypt"
    category: Category = "electronics"
    base_url = "https://www.gamesworldegypt.com"
    card_selector = ".product-thumb"
    title_selector = ".name a, h4 a"
    link_selector = ".name a[href], a[href]"
    price_selector = ".price-new, .price-normal"
    old_price_selector = ".price-old"
    use_impersonation = True
    check_throttle = False
    default_limit = 220
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("gaming_consoles", "electronics", "https://www.gamesworldegypt.com/devices-accessories"),
        ("gaming_consoles", "electronics", "https://www.gamesworldegypt.com/devices-accessories/ps"),
        ("gaming_consoles", "electronics", "https://www.gamesworldegypt.com/devices-accessories/xbox-1"),
        ("gaming_consoles", "electronics", "https://www.gamesworldegypt.com/devices-accessories/nintendo-switch"),
    )


EXPANSION_SCRAPER_CLASSES: tuple[type[BaseScraper], ...] = (
    JumiaScraper,
    ElGhazawyScraper,
    HomzmartScraper,
    DecathlonEgScraper,
    MisrPharmaciesScraper,
    TdawiScraper,
    ElnekhelyScraper,
    MaximumHardwareScraper,
    GamesWorldEgyptScraper,
)
