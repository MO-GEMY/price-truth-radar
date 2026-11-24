"""Wave 2 expansion store scrapers (Batches 2 & 3, `local_only`).

All scrapers prefer structured JSON / GraphQL / SSR microdata endpoints over
brittle DOM scraping and never bypass CAPTCHAs or anti-bot challenges:

Batch 2 (Priority 1):
- `fresh_eg`         : Fresh Egypt official Magento 2 GraphQL (`be.fresh.com.eg/graphql`)
- `chefaa`           : Chefaa Pharmacy SSR Schema.org `.item_content` microdata
- `seif_pharmacies`  : Seif Pharmacies REST JSON API via Playwright browser session

Batch 3 (Priority 2):
- `ikea_eg`          : IKEA Egypt official SIK Search JSON API
- `oriental_weavers` : Oriental Weavers Egypt Magento 2 GraphQL (`shop.orientalweavers.com/graphql`)
- `mazaya_eg`        : Mazaya Egypt Magento 2 GraphQL (`backend.mazaya.eg/graphql`)
- `faces_eg`         : Faces Egypt SFCC SSR product tiles + grid pagination
- `lc_waikiki_eg`    : LC Waikiki Egypt SSR `.product-card` catalog
- `defacto_eg`       : DeFacto Egypt official JSON Catalog API (`PartialIndexScrollResult`)
- `pets_egypt`       : PetsEgypt SSR `__NUXT_DATA__` flat-reference JSON catalog
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import html as html_lib
import json
import logging
import math
import re
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlparse

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

_NUXT_DATA_RE = re.compile(r'<script[^>]+id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _clean_text(raw: Any) -> str:
    if raw is None:
        return ""
    return re.sub(r"\s+", " ", html_lib.unescape(str(raw))).strip()


def _infer_health_sub(title: str, default_sub: str = "pharmacy") -> str:
    low = title.lower()
    if any(k in low for k in ("sunscreen", "sunblock", "spf", "anthelios", "photoderm", "واقي")):
        return "sunscreen"
    if any(k in low for k in ("shampoo", "conditioner", "hair", "scalp", "شامبو", "شعر")):
        return "haircare"
    if any(k in low for k in ("vitamin", "omega", "magnesium", "zinc", "collagen", "calcium", "iron", "فيتامين")):
        return "vitamins"
    if any(k in low for k in ("cream", "serum", "cleanser", "lotion", "moisturiz", "gel", "micellar", "acne", "كريم", "غسول", "سيروم")):
        return "skincare"
    if any(k in low for k in ("diaper", "baby", "infant", "bottle", "nipple", "حفاض", "أطفال")):
        return "baby_care"
    return default_sub


def _infer_beauty_sub(title: str, default_sub: str = "perfumes") -> str:
    low = title.lower()
    if any(k in low for k in ("eau de", "edp", "edt", "parfum", "perfume", "cologne", "fragrance", "mist", "oud", "عطر")):
        return "perfumes"
    if any(k in low for k in ("mascara", "lipstick", "lip ", "foundation", "concealer", "blush", "eyeliner", "palette", "primer", "powder", "bronzer")):
        return "makeup"
    if any(k in low for k in ("shampoo", "conditioner", "hair", "mask")):
        return "haircare"
    if any(k in low for k in ("serum", "cream", "cleanser", "toner", "moisturiz", "sunscreen", "spf", "lotion", "oil")):
        return "skincare"
    return default_sub


def _infer_fashion_sub(title: str, default_sub: str = "apparel") -> str:
    low = title.lower()
    if any(k in low for k in ("shoe", "sneaker", "boot", "sandal", "loafer", "slipper", "trainer")):
        return "shoes"
    if any(k in low for k in ("jacket", "coat", "puffer", "blazer", "vest", "trench", "parka")):
        return "jackets"
    if any(k in low for k in ("jeans", "denim")):
        return "jeans"
    if any(k in low for k in ("dress", "abaya", "jumpsuit")):
        return "dresses"
    if any(k in low for k in ("hoodie", "sweatshirt", "sweater", "cardigan", "pullover", "knit")):
        return "sweaters"
    if any(k in low for k in ("t-shirt", "tshirt", "tee", "polo")):
        return "t_shirts"
    if any(k in low for k in ("shirt", "overshirt", "blouse")):
        return "shirts"
    if any(k in low for k in ("trouser", "pant", "jogger", "chino", "short", "legging")):
        return "pants"
    if any(k in low for k in ("bag", "backpack", "belt", "cap", "hat", "scarf", "sock", "wallet")):
        return "accessories"
    return default_sub


def _infer_furniture_sub(title: str, default_sub: str = "furniture") -> str:
    low = title.lower()
    if any(k in low for k in ("rug", "carpet", "mat", "runner", "سجاد")):
        return "rugs"
    if any(k in low for k in ("sofa", "couch", "sectional", "armchair", "loveseat")):
        return "sofas"
    if any(k in low for k in ("mattress",)):
        return "mattresses"
    if any(k in low for k in ("bed", "duvet", "pillow", "sheet")):
        return "beds"
    if any(k in low for k in ("desk", "table", "dining")):
        return "tables"
    if any(k in low for k in ("chair", "stool", "bench")):
        return "chairs"
    if any(k in low for k in ("wardrobe", "cabinet", "shelf", "bookcase", "drawer", "chest")):
        return "storage"
    if any(k in low for k in ("lamp", "light", "chandelier", "bulb")):
        return "lighting"
    return default_sub


class _SimpleMagentoGraphQLScraper(BaseScraper):
    """Lightweight Magento 2 GraphQL scraper supporting custom URL templates and GET/POST."""

    graphql_url: str = ""
    product_url_template: str = ""  # e.g. "https://fresh.com.eg/en/products/{url_key}"
    use_post: bool = False
    include_stock_status: bool = False
    default_brand: str = ""
    override_brand: bool = False
    search_queries: tuple[tuple[str, str, Category], ...] = ()
    min_delay_seconds: float = 1.5
    request_timeout: float = 25.0
    page_size: int = 36

    def _infer_sub(self, title: str, default_sub: str) -> str:
        return default_sub

    def _infer_brand(self, title: str) -> str:
        if self.override_brand and self.default_brand:
            return self.default_brand
        b = _normalize_brand(None, title)
        if b and b.lower() not in ("unknown", "other", "generic"):
            return b
        return self.default_brand or (title.split()[0][:60] if title.split() else "Unknown")

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
        per_q_cap = max(20, math.ceil(target_limit / max(1, len(self.search_queries))) + 15)
        max_pages = 3 if self.mode == "discover" else 1
        stock_field = " stock_status" if self.include_stock_status else ""

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=2,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.25, 0.7),
        ) as client:
            for query_term, default_sub, cat_name in self.search_queries:
                if len(collected) >= target_limit:
                    break
                q_count = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or q_count >= per_q_cap:
                        break
                    gql = (
                        f'{{products(search:"{query_term}",pageSize:{self.page_size},currentPage:{page})'
                        f'{{total_count items{{sku name url_key{stock_field} '
                        f'price_range{{minimum_price{{regular_price{{value currency}}final_price{{value currency}}}}}} '
                        f'small_image{{url}}}}}}}}'
                    )
                    logger.info("[%s] GraphQL query='%s' page %d", self.store_name, query_term, page)
                    try:
                        if self.use_post:
                            resp = client.post(
                                self.graphql_url,
                                json={"query": gql},
                                min_delay_seconds=effective_delay,
                                timeout=self.request_timeout,
                                check_throttle=False,
                            )
                        else:
                            resp = client.get(
                                f"{self.graphql_url}?query={quote(gql)}",
                                min_delay_seconds=effective_delay,
                                timeout=self.request_timeout,
                                check_throttle=False,
                            )
                        payload = resp.json()
                    except Exception as exc:
                        logger.warning("[%s] GraphQL error for '%s' p%d: %s", self.store_name, query_term, page, exc)
                        break

                    self.pages_fetched += 1
                    items = ((payload.get("data") or {}).get("products") or {}).get("items") or []
                    if not items:
                        break

                    added_page = 0
                    for it in items:
                        if len(collected) >= target_limit or q_count >= per_q_cap:
                            break
                        sku = _clean_text(it.get("sku"))
                        title = _clean_text(it.get("name"))
                        url_key = _clean_text(it.get("url_key"))
                        if not sku or not title or not url_key or sku in seen_ids:
                            continue

                        pr = ((it.get("price_range") or {}).get("minimum_price")) or {}
                        fin = (pr.get("final_price") or {})
                        reg = (pr.get("regular_price") or {})
                        curr_code = str(fin.get("currency") or reg.get("currency") or "EGP").upper()
                        if curr_code != "EGP":
                            continue
                        cur_price = parse_egp_price(fin.get("value"))
                        reg_price = parse_egp_price(reg.get("value"))
                        if cur_price is None:
                            continue
                        claimed = reg_price if (reg_price is not None and reg_price > cur_price) else None

                        in_stock = True
                        if self.include_stock_status and it.get("stock_status"):
                            in_stock = str(it.get("stock_status")).upper() != "OUT_OF_STOCK"

                        img = _clean_text((it.get("small_image") or {}).get("url"))
                        if img and not img.startswith("http"):
                            img = urljoin(self.base_url + "/", img)
                        if img and "placeholder" in img.lower():
                            img = None

                        prod_url = self.product_url_template.format(url_key=url_key.lstrip("/"))
                        sub = self._infer_sub(title, default_sub)
                        brand = self._infer_brand(title)
                        attrs: dict[str, Any] = {
                            f"{self.store_name}_category": sub,
                            "sku": sku,
                        }
                        if cat_name in ("electronics", "home_appliances"):
                            attrs.update(_extract_specs(title, sub))

                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": sku[:120],
                                "canonical_product_key": None,
                                "category": cat_name,
                                "sub_category": sub,
                                "brand": brand[:100],
                                "product_title": title[:500],
                                "product_url": prod_url,
                                "image_url": img or None,
                                "attributes_json": attrs,
                                "current_price": cur_price,
                                "claimed_original_price": claimed,
                                "in_stock": in_stock,
                                "snapshot_date": snapshot_date,
                                "scraped_at": scraped_at,
                            }
                        )
                        if rec is not None:
                            seen_ids.add(sku)
                            collected.append(rec)
                            q_count += 1
                            added_page += 1

                    if len(items) < self.page_size or added_page == 0:
                        break
                self.category_counts[f"{cat_name}/{default_sub}"] = q_count

        return collected


class FreshEgScraper(_SimpleMagentoGraphQLScraper):
    """Official Fresh Egypt home appliances scraper via `be.fresh.com.eg/graphql`."""

    store_name = "fresh_eg"
    category: Category = "home_appliances"
    base_url = "https://fresh.com.eg"
    graphql_url = "https://be.fresh.com.eg/graphql"
    product_url_template = "https://fresh.com.eg/en/products/{url_key}"
    use_post = True
    include_stock_status = True
    default_brand = "Fresh"
    override_brand = True
    default_limit = 300
    discover_limit = 600
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    search_queries: tuple[tuple[str, str, Category], ...] = (
        ("refrigerator", "refrigerators", "home_appliances"),
        ("washing", "washing_machines", "home_appliances"),
        ("cooker", "cookers", "home_appliances"),
        ("conditioner", "air_conditioners", "home_appliances"),
        ("tv", "tvs", "home_appliances"),
        ("heater", "water_heaters", "home_appliances"),
        ("freezer", "freezers", "home_appliances"),
        ("microwave", "microwaves", "home_appliances"),
        ("fan", "fans", "home_appliances"),
        ("fresh", "small_appliances", "home_appliances"),
    )

    def _infer_sub(self, title: str, default_sub: str) -> str:
        return _refine_sub_category(default_sub, "home_appliances", title)


class OrientalWeaversScraper(_SimpleMagentoGraphQLScraper):
    """Oriental Weavers Egypt official online store via `shop.orientalweavers.com/graphql`."""

    store_name = "oriental_weavers"
    category: Category = "home_furniture"
    base_url = "https://shop.orientalweavers.com"
    graphql_url = "https://shop.orientalweavers.com/graphql"
    product_url_template = "https://shop.orientalweavers.com/en/products/{url_key}"
    use_post = False
    include_stock_status = False
    default_brand = "Oriental Weavers"
    override_brand = True
    default_limit = 250
    discover_limit = 450
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    search_queries: tuple[tuple[str, str, Category], ...] = (
        ("modern", "rugs", "home_furniture"),
        ("classic", "rugs", "home_furniture"),
        ("carpet", "rugs", "home_furniture"),
        ("rug", "rugs", "home_furniture"),
        ("runner", "rugs", "home_furniture"),
        ("kitchen", "rugs", "home_furniture"),
        ("outdoor", "rugs", "home_furniture"),
    )


class MazayaEgScraper(_SimpleMagentoGraphQLScraper):
    """Mazaya Egypt luxury perfumes & beauty via `backend.mazaya.eg/graphql`."""

    store_name = "mazaya_eg"
    category: Category = "beauty"
    base_url = "https://mazaya.eg"
    graphql_url = "https://backend.mazaya.eg/graphql"
    product_url_template = "https://mazaya.eg/en/{url_key}"
    use_post = False
    include_stock_status = False
    default_brand = "Mazaya"
    override_brand = False
    default_limit = 250
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "fashion")
    search_queries: tuple[tuple[str, str, Category], ...] = (
        ("parfum", "perfumes", "beauty"),
        ("dior", "perfumes", "beauty"),
        ("lancome", "perfumes", "beauty"),
        ("yves", "perfumes", "beauty"),
        ("gucci", "perfumes", "beauty"),
        ("versace", "perfumes", "beauty"),
        ("armani", "perfumes", "beauty"),
        ("givenchy", "perfumes", "beauty"),
        ("boss", "perfumes", "beauty"),
        ("calvin", "perfumes", "beauty"),
        ("serum", "skincare", "beauty"),
        ("cream", "skincare", "beauty"),
        ("mascara", "makeup", "beauty"),
        ("lipstick", "makeup", "beauty"),
    )

    def _infer_sub(self, title: str, default_sub: str) -> str:
        return _infer_beauty_sub(title, default_sub)


class ChefaaScraper(BaseScraper):
    """Chefaa Pharmacy SSR Schema.org microdata scraper (`https://chefaa.com/eg-en/now/...`)."""

    store_name = "chefaa"
    category: Category = "health"
    base_url = "https://chefaa.com"
    default_limit = 300
    discover_limit = 600
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries")
    min_delay_seconds = 1.8
    request_timeout = 25.0

    _CATEGORIES: tuple[tuple[str, str], ...] = (
        ("skincare", "https://chefaa.com/eg-en/now/category/skin-care"),
        ("haircare", "https://chefaa.com/eg-en/now/category/hair-care"),
        ("vitamins", "https://chefaa.com/eg-en/now/category/vitamins-and-supplements"),
        ("baby_care", "https://chefaa.com/eg-en/now/category/mom-and-baby"),
        ("daily_essentials", "https://chefaa.com/eg-en/now/category/daily-essentials"),
        ("pharmacy", "https://chefaa.com/eg-en/now/category/medications"),
        ("devices", "https://chefaa.com/eg-en/now/category/health-care-devices"),
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
        per_cat_cap = max(20, math.ceil(target_limit / len(self._CATEGORIES)) + 10)
        max_pages = 5 if self.mode == "discover" else 2

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=2,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 0.8),
        ) as client:
            for default_sub, cat_url in self._CATEGORIES:
                if len(collected) >= target_limit:
                    break
                cat_cnt = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or cat_cnt >= per_cat_cap:
                        break
                    url = cat_url if page == 1 else f"{cat_url}?page={page}"
                    logger.info("[chefaa] Fetching %s page %d", default_sub, page)
                    try:
                        resp = client.get(url, min_delay_seconds=effective_delay, timeout=self.request_timeout, check_throttle=False)
                    except Exception as exc:
                        logger.warning("[chefaa] Error fetching %s: %s", url, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select(".item_content")
                    if not cards:
                        break

                    added_page = 0
                    for card in cards:
                        if len(collected) >= target_limit or cat_cnt >= per_cat_cap:
                            break
                        link_el = card.select_one("a.product_details_link[href]")
                        name_el = card.select_one('[itemprop="name"]')
                        price_el = card.select_one('[itemprop="price"]')
                        if not link_el or not price_el:
                            continue

                        raw_href = _clean_text(link_el.get("href"))
                        if not raw_href:
                            continue
                        prod_url = raw_href.replace(":443/", "/")
                        if not prod_url.startswith("http"):
                            prod_url = urljoin(self.base_url + "/", prod_url)

                        slug = urlparse(prod_url).path.rstrip("/").split("/")[-1]
                        if not slug or slug in seen_ids:
                            continue

                        title = _clean_text(
                            (name_el.get("content") if name_el else None)
                            or (name_el.get_text(" ", strip=True) if name_el else "")
                            or link_el.get_text(" ", strip=True)
                        )
                        if not title:
                            continue

                        cur_price = parse_egp_price(price_el.get("content") or price_el.get_text(" ", strip=True))
                        if cur_price is None or float(cur_price) < 5.0:
                            continue

                        old_el = card.select_one(".old_price, del, s, [class*='old-price'], [class*='before']")
                        claimed = parse_egp_price(old_el.get_text(" ", strip=True)) if old_el else None
                        if claimed is not None and claimed <= cur_price:
                            claimed = None

                        img_meta = card.select_one('meta[itemprop="image"]')
                        img_el = card.select_one("img")
                        img_url = _clean_text(
                            (img_meta.get("content") if img_meta else None)
                            or (img_el.get("data-src") if img_el else None)
                            or (img_el.get("src") if img_el else None)
                        )

                        # Chefaa titles follow "Brand | Product Name | Size"
                        if "|" in title:
                            brand = _clean_text(title.split("|", 1)[0])[:100] or "Unknown"
                        else:
                            brand = _normalize_brand(None, title) or title.split()[0]

                        sub = _infer_health_sub(title, default_sub)
                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": slug[:120],
                                "canonical_product_key": None,
                                "category": "health",
                                "sub_category": sub,
                                "brand": brand[:100],
                                "product_title": title[:500],
                                "product_url": prod_url,
                                "image_url": img_url if img_url.startswith("http") else None,
                                "attributes_json": {"chefaa_category": default_sub},
                                "current_price": cur_price,
                                "claimed_original_price": claimed,
                                "in_stock": True,
                                "snapshot_date": snapshot_date,
                                "scraped_at": scraped_at,
                            }
                        )
                        if rec is not None:
                            seen_ids.add(slug)
                            collected.append(rec)
                            cat_cnt += 1
                            added_page += 1

                    if added_page == 0:
                        break
                self.category_counts[f"health/{default_sub}"] = cat_cnt

        return collected


class SeifPharmaciesScraper(BaseScraper):
    """Seif Pharmacies scraper calling `/api/customer/products/search` via Playwright session."""

    store_name = "seif_pharmacies"
    category: Category = "health"
    base_url = "https://seif-online.com"
    default_limit = 300
    discover_limit = 600
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries")
    min_delay_seconds = 1.5
    request_timeout = 30.0

    _CAT_SLUGS: tuple[tuple[str, str], ...] = (
        ("skincare", "skin-care"),
        ("haircare", "hair-care"),
        ("vitamins", "vitamins-supplements"),
        ("baby_care", "mom-baby"),
        ("cosmetics", "cosmetics"),
        ("daily_essentials", "every-day-essentials"),
        ("pharmacy", "medicine"),
    )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        from playwright.sync_api import sync_playwright

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        per_cat_cap = max(24, math.ceil(target_limit / len(self._CAT_SLUGS)) + 12)
        max_pages = 4 if self.mode == "discover" else 2

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    locale="en-US",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                page = ctx.new_page()
                logger.info("[seif_pharmacies] Establishing browser session on seif-online.com")
                page.goto("https://seif-online.com/en/products", wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1200)

                for default_sub, cat_slug in self._CAT_SLUGS:
                    if len(collected) >= target_limit:
                        break
                    cat_cnt = 0
                    for pno in range(1, max_pages + 1):
                        if len(collected) >= target_limit or cat_cnt >= per_cat_cap:
                            break
                        logger.info("[seif_pharmacies] POST search category='%s' page %d", cat_slug, pno)
                        payload = {
                            "q": "",
                            "search": "",
                            "brand_ids": [],
                            "sub_categories": [],
                            "sub_categories_slugs": [],
                            "categories": [],
                            "category_id": "",
                            "category_slug": cat_slug,
                            "price_from": None,
                            "price_to": None,
                            "page": pno,
                            "page_size": "24",
                            "sort": "popular",
                        }
                        try:
                            res = page.evaluate(
                                """async (body) => {
                                    const r = await fetch('/api/customer/products/search?enable_search_side_filters=1', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'Accept-Language': 'en'},
                                        body: JSON.stringify(body)
                                    });
                                    return await r.json();
                                }""",
                                payload,
                            )
                        except Exception as exc:
                            logger.warning("[seif_pharmacies] API fetch error on %s p%d: %s", cat_slug, pno, exc)
                            break

                        self.pages_fetched += 1
                        prods = ((res or {}).get("data") or {}).get("products") or []
                        if not prods:
                            break

                        added_page = 0
                        for item in prods:
                            if len(collected) >= target_limit or cat_cnt >= per_cat_cap:
                                break
                            sku = _clean_text(item.get("sku") or item.get("id"))
                            if not sku or sku in seen_ids:
                                continue
                            title = _clean_text(item.get("name_en") or item.get("name") or item.get("name_ar"))
                            if not title:
                                continue

                            base_price = parse_egp_price(item.get("price"))
                            disc_price = parse_egp_price(item.get("discount_price"))
                            if disc_price is not None and base_price is not None and disc_price < base_price:
                                cur_price = disc_price
                                claimed = base_price
                            else:
                                cur_price = base_price
                                claimed = None
                            if cur_price is None or float(cur_price) < 5.0:
                                continue

                            slug = _clean_text(item.get("slug") or item.get("encoded_name_en") or sku)
                            prod_url = f"https://seif-online.com/en/product/{quote(slug, safe='-_')}"
                            img = _clean_text(item.get("image"))
                            if img and not img.startswith("http"):
                                img = urljoin(self.base_url + "/", img)

                            brand_obj = item.get("brand")
                            if isinstance(brand_obj, dict):
                                brand = _clean_text(brand_obj.get("name_en") or brand_obj.get("name"))
                            else:
                                brand = ""
                            if not brand:
                                brand = _normalize_brand(None, title) or title.split()[0]

                            sub = _infer_health_sub(title, default_sub)
                            rec = self.validate_record(
                                {
                                    "store_name": self.store_name,
                                    "external_id": sku[:120],
                                    "canonical_product_key": None,
                                    "category": "health",
                                    "sub_category": sub,
                                    "brand": brand[:100],
                                    "product_title": title[:500],
                                    "product_url": prod_url,
                                    "image_url": img if img.startswith("http") else None,
                                    "attributes_json": {"seif_category": cat_slug, "sku": sku},
                                    "current_price": cur_price,
                                    "claimed_original_price": claimed,
                                    "in_stock": bool(item.get("in_stock", True)),
                                    "snapshot_date": snapshot_date,
                                    "scraped_at": scraped_at,
                                }
                            )
                            if rec is not None:
                                seen_ids.add(sku)
                                collected.append(rec)
                                cat_cnt += 1
                                added_page += 1

                        page.wait_for_timeout(600)
                        if len(prods) < 20 or added_page == 0:
                            break
                    self.category_counts[f"health/{default_sub}"] = cat_cnt
            finally:
                browser.close()

        return collected


class IkeaEgScraper(BaseScraper):
    """IKEA Egypt official Search/SIK JSON API scraper."""

    store_name = "ikea_eg"
    category: Category = "home_furniture"
    base_url = "https://www.ikea.com/eg/en"
    default_limit = 300
    discover_limit = 600
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 1.2
    request_timeout = 20.0

    _QUERIES: tuple[tuple[str, str], ...] = (
        ("sofa", "sofas"),
        ("bed", "beds"),
        ("mattress", "mattresses"),
        ("desk", "tables"),
        ("table", "tables"),
        ("chair", "chairs"),
        ("wardrobe", "storage"),
        ("shelf", "storage"),
        ("lamp", "lighting"),
        ("rug", "rugs"),
        ("kitchen", "cookware"),
        ("curtain", "bedding_linens"),
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
        per_q = min(60, max(12, math.ceil(target_limit / len(self._QUERIES)) + 8))

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=2,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.2, 0.5),
        ) as client:
            for query_term, default_sub in self._QUERIES:
                if len(collected) >= target_limit:
                    break
                url = (
                    "https://sik.search.blue.cdtapps.com/eg/en/search-result-page"
                    f"?q={quote(query_term)}&size={per_q}&types=PRODUCT&c=sr&v=20210322"
                )
                logger.info("[ikea_eg] Fetching SIK API q='%s' size=%d", query_term, per_q)
                try:
                    resp = client.get(url, min_delay_seconds=effective_delay, timeout=self.request_timeout, check_throttle=False)
                    data = resp.json()
                except Exception as exc:
                    logger.warning("[ikea_eg] SIK error for '%s': %s", query_term, exc)
                    continue

                self.pages_fetched += 1
                items = (
                    ((data.get("searchResultPage") or {}).get("products") or {}).get("main") or {}
                ).get("items") or []
                q_cnt = 0
                for entry in items:
                    if len(collected) >= target_limit:
                        break
                    prod = entry.get("product") if isinstance(entry, dict) else None
                    if not isinstance(prod, dict):
                        continue
                    item_no = _clean_text(prod.get("itemNoGlobal") or prod.get("itemNo") or prod.get("id"))
                    if not item_no or item_no in seen_ids:
                        continue

                    sp = prod.get("salesPrice") or {}
                    if str(sp.get("currencyCode") or "EGP").upper() != "EGP":
                        continue
                    cur_price = parse_egp_price(sp.get("numeral"))
                    if cur_price is None:
                        continue
                    prev = sp.get("previous") or {}
                    prev_num = parse_egp_price(prev.get("wholeNumber") or prev.get("numeral"))
                    claimed = prev_num if (prev_num is not None and prev_num > cur_price) else None

                    name = _clean_text(prod.get("name"))
                    type_name = _clean_text(prod.get("typeName"))
                    measure = _clean_text(prod.get("itemMeasureReferenceText"))
                    design = _clean_text(prod.get("validDesignText"))
                    title_parts = [p for p in (f"IKEA {name}" if name else "", type_name, design, measure) if p]
                    title = " - ".join(title_parts) if title_parts else f"IKEA {item_no}"

                    pip_url = _clean_text(prod.get("pipUrl"))
                    if not pip_url.startswith("http"):
                        continue
                    img_url = _clean_text(prod.get("mainImageUrl"))
                    sub = _infer_furniture_sub(title, default_sub)

                    rec = self.validate_record(
                        {
                            "store_name": self.store_name,
                            "external_id": item_no[:120],
                            "canonical_product_key": None,
                            "category": "home_furniture",
                            "sub_category": sub,
                            "brand": "IKEA",
                            "product_title": title[:500],
                            "product_url": pip_url,
                            "image_url": img_url if img_url.startswith("http") else None,
                            "attributes_json": {"ikea_item_no": item_no, "ikea_category": default_sub},
                            "current_price": cur_price,
                            "claimed_original_price": claimed,
                            "in_stock": bool(prod.get("onlineSellable", True)),
                            "snapshot_date": snapshot_date,
                            "scraped_at": scraped_at,
                        }
                    )
                    if rec is not None:
                        seen_ids.add(item_no)
                        collected.append(rec)
                        q_cnt += 1
                self.category_counts[f"home_furniture/{default_sub}"] = q_cnt

        return collected


class FacesEgScraper(BaseScraper):
    """Faces Egypt SFCC SSR scraper (`https://www.faces.eg/en/...`)."""

    store_name = "faces_eg"
    category: Category = "beauty"
    base_url = "https://www.faces.eg"
    default_limit = 250
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "fashion")
    min_delay_seconds = 2.0
    request_timeout = 25.0

    _CAT_URLS: tuple[tuple[str, str], ...] = (
        ("perfumes", "https://www.faces.eg/en/fragrance"),
        ("skincare", "https://www.faces.eg/en/skincare"),
        ("makeup", "https://www.faces.eg/en/makeup"),
        ("haircare", "https://www.faces.eg/en/haircare"),
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
        per_cat_cap = max(25, math.ceil(target_limit / len(self._CAT_URLS)) + 15)

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=2,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 0.8),
        ) as client:
            for default_sub, cat_url in self._CAT_URLS:
                if len(collected) >= target_limit:
                    break
                cat_cnt = 0
                for start in (0, 60, 120):
                    if len(collected) >= target_limit or cat_cnt >= per_cat_cap:
                        break
                    url = cat_url if start == 0 else f"{cat_url}?start={start}&sz=60"
                    logger.info("[faces_eg] Fetching %s start=%d", default_sub, start)
                    try:
                        resp = client.get(url, min_delay_seconds=effective_delay, timeout=self.request_timeout, check_throttle=False)
                    except Exception as exc:
                        logger.warning("[faces_eg] Error fetching %s: %s", url, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    tiles = soup.select(".js-product-tile-container[data-pid]")
                    if not tiles:
                        break

                    added_page = 0
                    for tile in tiles:
                        if len(collected) >= target_limit or cat_cnt >= per_cat_cap:
                            break
                        pid = _clean_text(tile.get("data-pid"))
                        if not pid or pid in seen_ids:
                            continue

                        link_el = tile.select_one("a[href*='/en/p/'], a[href*='/p/'], a[href]")
                        if not link_el:
                            continue
                        prod_url = urljoin(self.base_url + "/", _clean_text(link_el.get("href")))

                        name_el = tile.select_one(".pdp-link a, [class*='product-name'], [class*='tile-name'], h2, h3")
                        brand_el = tile.select_one(".product-brand, .brand-name, [class*='brand-title']")
                        name_txt = _clean_text(name_el.get_text(" ", strip=True)) if name_el else ""
                        brand_txt = _clean_text(brand_el.get_text(" ", strip=True)) if brand_el else ""

                        # Fallback brand from pid like PM_LANCOME_La_Vie_Est_Belle_EDP
                        if not brand_txt and "_" in pid:
                            parts = pid.split("_")
                            if len(parts) >= 2 and len(parts[1]) >= 2:
                                brand_txt = parts[1].title()
                        if not name_txt:
                            continue
                        import unicodedata
                        fold_b = unicodedata.normalize("NFKD", brand_txt).encode("ascii", "ignore").decode().lower()
                        fold_n = unicodedata.normalize("NFKD", name_txt).encode("ascii", "ignore").decode().lower()
                        title = f"{brand_txt} {name_txt}".strip() if (brand_txt and fold_b not in fold_n) else name_txt

                        # Prices: check sales/current and strike-through (skip multi-size "from" claimed discount)
                        price_box = tile.select_one(".price, [class*='price']")
                        if not price_box:
                            continue
                        price_txt = price_box.get_text(" ", strip=True)
                        # Strip Unicode directional markers (⁦, ⁩)
                        price_txt_clean = re.sub(r"[\u2066-\u2069\u200e\u200f]", "", price_txt)
                        is_from_range = "from" in price_txt_clean.lower()

                        sale_el = price_box.select_one(".sales .value, .sales, .value")
                        strike_el = price_box.select_one(".strike-through .value, .strike-through, del, s")
                        cur_price = parse_egp_price(
                            (sale_el.get("content") if sale_el else None)
                            or (re.sub(r"[\u2066-\u2069\u200e\u200f]", "", sale_el.get_text(" ", strip=True)) if sale_el else price_txt_clean)
                        )
                        if cur_price is None or float(cur_price) < 50.0:
                            continue
                        claimed = None
                        if not is_from_range and strike_el:
                            c_p = parse_egp_price(
                                strike_el.get("content")
                                or re.sub(r"[\u2066-\u2069\u200e\u200f]", "", strike_el.get_text(" ", strip=True))
                            )
                            if c_p is not None and c_p > cur_price:
                                claimed = c_p

                        img_el = tile.select_one("img")
                        img_url = _clean_text(
                            (img_el.get("data-src") if img_el else None)
                            or (img_el.get("src") if img_el else None)
                        )
                        if img_url and not img_url.startswith("http"):
                            img_url = urljoin(self.base_url + "/", img_url)

                        sub = _infer_beauty_sub(title, default_sub)
                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": pid[:120],
                                "canonical_product_key": None,
                                "category": "beauty",
                                "sub_category": sub,
                                "brand": (brand_txt or _normalize_brand(None, title) or "Faces")[:100],
                                "product_title": title[:500],
                                "product_url": prod_url,
                                "image_url": img_url if img_url.startswith("http") else None,
                                "attributes_json": {"faces_category": default_sub, "pid": pid},
                                "current_price": cur_price,
                                "claimed_original_price": claimed,
                                "in_stock": True,
                                "snapshot_date": snapshot_date,
                                "scraped_at": scraped_at,
                            }
                        )
                        if rec is not None:
                            seen_ids.add(pid)
                            collected.append(rec)
                            cat_cnt += 1
                            added_page += 1

                    if added_page == 0 or self.mode != "discover":
                        break
                self.category_counts[f"beauty/{default_sub}"] = cat_cnt

        return collected


class LcWaikikiEgScraper(BaseScraper):
    """LC Waikiki Egypt SSR `.product-card` scraper."""

    store_name = "lc_waikiki_eg"
    category: Category = "fashion"
    base_url = "https://www.lcwaikiki.eg"
    default_limit = 250
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion", "core")
    min_delay_seconds = 1.8
    request_timeout = 25.0

    _GROUPS: tuple[tuple[str, str], ...] = (
        ("women", "https://www.lcwaikiki.eg/en-US/EG/product-group/women"),
        ("men", "https://www.lcwaikiki.eg/en-US/EG/product-group/men"),
        ("kids", "https://www.lcwaikiki.eg/en-US/EG/product-group/kids"),
        ("baby", "https://www.lcwaikiki.eg/en-US/EG/product-group/baby"),
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
        per_grp = max(25, math.ceil(target_limit / len(self._GROUPS)) + 10)
        max_pages = 2 if self.mode == "discover" else 1

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=2,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 0.8),
        ) as client:
            for grp_name, grp_url in self._GROUPS:
                if len(collected) >= target_limit:
                    break
                grp_cnt = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or grp_cnt >= per_grp:
                        break
                    url = grp_url if page == 1 else f"{grp_url}?PageIndex={page}"
                    logger.info("[lc_waikiki_eg] Fetching %s page %d", grp_name, page)
                    try:
                        resp = client.get(url, min_delay_seconds=effective_delay, timeout=self.request_timeout, check_throttle=False)
                    except Exception as exc:
                        logger.warning("[lc_waikiki_eg] Error fetching %s: %s", url, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select(".product-card")
                    if not cards:
                        break

                    added_page = 0
                    for card in cards:
                        if len(collected) >= target_limit or grp_cnt >= per_grp:
                            break
                        link_el = card.select_one("a[href]")
                        if not link_el:
                            continue
                        href = _clean_text(link_el.get("href"))
                        if not href:
                            continue
                        opt_id = _clean_text(link_el.get("data-optionid") or urlparse(href).path.rstrip("/").split("-")[-1])
                        if not opt_id or opt_id in seen_ids:
                            continue

                        prod_url = urljoin(self.base_url + "/", href)
                        img_el = card.select_one("img")
                        img_url = _clean_text(
                            (img_el.get("data-src") if img_el else None)
                            or (img_el.get("src") if img_el else None)
                        )

                        title_el = card.select_one(".product-card__title, h5, h4, .title")
                        brand_el = card.select_one(".product-card__brand-title, .brand")
                        title = _clean_text(
                            (title_el.get_text(" ", strip=True) if title_el else "")
                            or (img_el.get("alt") if img_el else "")
                        )
                        brand = _clean_text(brand_el.get_text(" ", strip=True)) if brand_el else "LC Waikiki"
                        if not title:
                            continue
                        if brand and brand.lower() not in title.lower() and "lcw" not in title.lower():
                            title = f"{brand} {title}"

                        # Extract EGP prices cleanly from card price elements
                        card_txt = card.get_text(" ", strip=True)
                        egp_matches = [parse_egp_price(m) for m in re.findall(r"([\d,]+(?:\.\d{1,2})?)\s*EGP", card_txt)]
                        egp_vals = [p for p in egp_matches if p is not None and float(p) >= 30.0]
                        if not egp_vals:
                            continue
                        cur_price = min(egp_vals)
                        claimed = max(egp_vals) if (len(egp_vals) >= 2 and max(egp_vals) > cur_price) else None

                        sub = _infer_fashion_sub(title, "apparel")
                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": opt_id[:120],
                                "canonical_product_key": None,
                                "category": "fashion",
                                "sub_category": sub,
                                "brand": (brand or "LC Waikiki")[:100],
                                "product_title": title[:500],
                                "product_url": prod_url,
                                "image_url": img_url if img_url.startswith("http") else None,
                                "attributes_json": {"lcw_group": grp_name, "option_id": opt_id},
                                "current_price": cur_price,
                                "claimed_original_price": claimed,
                                "in_stock": True,
                                "snapshot_date": snapshot_date,
                                "scraped_at": scraped_at,
                            }
                        )
                        if rec is not None:
                            seen_ids.add(opt_id)
                            collected.append(rec)
                            grp_cnt += 1
                            added_page += 1

                    if added_page == 0:
                        break
                self.category_counts[f"fashion/{grp_name}"] = grp_cnt

        return collected


class DefactoEgScraper(BaseScraper):
    """DeFacto Egypt official JSON Catalog API scraper (`PartialIndexScrollResult`)."""

    store_name = "defacto_eg"
    category: Category = "fashion"
    base_url = "https://www.defacto.com.eg"
    default_limit = 250
    discover_limit = 500
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion", "core")
    min_delay_seconds = 1.5
    request_timeout = 20.0

    _QUERIES: tuple[tuple[str, str], ...] = (
        ("shirt", "shirts"),
        ("jacket", "jackets"),
        ("jeans", "jeans"),
        ("dress", "dresses"),
        ("sweater", "sweaters"),
        ("t-shirt", "t_shirts"),
        ("pants", "pants"),
        ("hoodie", "sweaters"),
        ("shoes", "shoes"),
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
        per_q = max(24, math.ceil(target_limit / len(self._QUERIES)) + 8)
        max_pages = 3 if self.mode == "discover" else 1

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=2,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.25, 0.6),
        ) as client:
            for query_term, default_sub in self._QUERIES:
                if len(collected) >= target_limit:
                    break
                q_cnt = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or q_cnt >= per_q:
                        break
                    url = (
                        "https://www.defacto.com.eg/en-eg/Catalog/PartialIndexScrollResult"
                        f"?page={page}&SortOrder=0&pageSize=24&q={quote(query_term)}"
                    )
                    logger.info("[defacto_eg] Fetching JSON q='%s' page %d", query_term, page)
                    try:
                        resp = client.get(url, min_delay_seconds=effective_delay, timeout=self.request_timeout, check_throttle=False)
                        data = resp.json()
                    except Exception as exc:
                        logger.warning("[defacto_eg] Error for '%s' p%d: %s", query_term, page, exc)
                        break

                    self.pages_fetched += 1
                    rows = ((data.get("Data") or {}).get("SearchResponse") or {}).get("Template") or []
                    if not rows:
                        break

                    added_page = 0
                    for row in rows:
                        for col in row.get("columns") or []:
                            if len(collected) >= target_limit or q_cnt >= per_q:
                                break
                            w = (col.get("content") or {}).get("widget") or {}
                            if w.get("widgetType") != "productCard":
                                continue
                            wc = w.get("widgetContent") or {}
                            ext_id = _clean_text(wc.get("ProductLongCode") or wc.get("ProductVariantId") or wc.get("ProductId"))
                            if not ext_id or ext_id in seen_ids:
                                continue

                            title = _clean_text(wc.get("ProductName") or wc.get("ProductGtmName"))
                            color = _clean_text(wc.get("ColorGtmName"))
                            if not title:
                                continue
                            if color and color.lower() not in title.lower():
                                title = f"DeFacto {title} - {color}"
                            elif "defacto" not in title.lower():
                                title = f"DeFacto {title}"

                            reg_p = parse_egp_price(wc.get("ProductPriceInclTax"))
                            disc_p = parse_egp_price(wc.get("ProductVariantDiscountedPriceInclTax"))
                            cur_price = disc_p if (disc_p is not None and (reg_p is None or disc_p <= reg_p)) else reg_p
                            if cur_price is None or float(cur_price) < 30.0:
                                continue
                            claimed = reg_p if (reg_p is not None and reg_p > cur_price) else None

                            seo_slug = ""
                            for swn in wc.get("ProductVariantShortWebNames") or []:
                                if swn.get("LanguageIndex") == 89 and swn.get("ProductShortSeoName"):
                                    seo_slug = _clean_text(swn["ProductShortSeoName"])
                                    break
                            if not seo_slug:
                                seo_slug = _clean_text(wc.get("ProductSeoName")) or "product"
                            var_idx = (wc.get("ProductVariantColorName") or {}).get("ProductVariantIndex")
                            prod_url = (
                                f"https://www.defacto.com.eg/en-eg/{seo_slug}-{var_idx}"
                                if var_idx
                                else f"https://www.defacto.com.eg/en-eg/{seo_slug}"
                            )

                            img_url = None
                            pics = wc.get("ProductPictures") or []
                            if pics and isinstance(pics[0], dict) and pics[0].get("ProductPicturePath"):
                                img_url = f"https://dfcdn.defacto.com.tr/7/{pics[0]['ProductPicturePath']}"

                            stock_val = wc.get("Stock")
                            in_stock = True if stock_val is None else (int(stock_val) > 0)
                            sub = _infer_fashion_sub(title, default_sub)

                            rec = self.validate_record(
                                {
                                    "store_name": self.store_name,
                                    "external_id": ext_id[:120],
                                    "canonical_product_key": None,
                                    "category": "fashion",
                                    "sub_category": sub,
                                    "brand": "DeFacto",
                                    "product_title": title[:500],
                                    "product_url": prod_url,
                                    "image_url": img_url,
                                    "attributes_json": {"defacto_code": ext_id, "color": color or None},
                                    "current_price": cur_price,
                                    "claimed_original_price": claimed,
                                    "in_stock": in_stock,
                                    "snapshot_date": snapshot_date,
                                    "scraped_at": scraped_at,
                                }
                            )
                            if rec is not None:
                                seen_ids.add(ext_id)
                                collected.append(rec)
                                q_cnt += 1
                                added_page += 1

                    if added_page == 0:
                        break
                self.category_counts[f"fashion/{default_sub}"] = q_cnt

        return collected


def _resolve_nuxt3_val(arr: list[Any], idx: Any, depth: int = 0) -> Any:
    if depth > 4 or not isinstance(idx, int) or idx < 0 or idx >= len(arr):
        return idx
    val = arr[idx]
    if isinstance(val, list) and len(val) == 2 and val[0] in ("Reactive", "ShallowReactive", "Ref"):
        return _resolve_nuxt3_val(arr, val[1], depth + 1)
    return val


class PetsEgyptScraper(BaseScraper):
    """PetsEgypt SSR `__NUXT_DATA__` catalog scraper (`https://petsegypt.com`)."""

    store_name = "pets_egypt"
    category: Category = "pet_care"
    base_url = "https://petsegypt.com"
    default_limit = 250
    discover_limit = 450
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries")
    min_delay_seconds = 1.8
    request_timeout = 25.0

    _CAT_URLS: tuple[tuple[str, str], ...] = (
        ("cat_food", "https://petsegypt.com/category/cat-food"),
        ("dog_food", "https://petsegypt.com/category/dog-food"),
        ("cat_litter", "https://petsegypt.com/category/cat-litter"),
        ("pet_supplies", "https://petsegypt.com/category/cat"),
        ("pet_supplies", "https://petsegypt.com/category/dog"),
        ("pet_accessories", "https://petsegypt.com/category/cat-cat-toys"),
        ("pet_supplies", "https://petsegypt.com/category/birds"),
        ("pet_supplies", "https://petsegypt.com/category/small-pet"),
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
        max_pages = 3 if self.mode == "discover" else 1

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout,
            max_retries=2,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 0.8),
        ) as client:
            for default_sub, cat_url in self._CAT_URLS:
                if len(collected) >= target_limit:
                    break
                cat_cnt = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit:
                        break
                    url = cat_url if page == 1 else f"{cat_url}?page={page}"
                    logger.info("[pets_egypt] Fetching %s page %d", cat_url, page)
                    try:
                        resp = client.get(url, min_delay_seconds=effective_delay, timeout=self.request_timeout, check_throttle=False)
                    except Exception as exc:
                        logger.warning("[pets_egypt] Error fetching %s: %s", url, exc)
                        break

                    self.pages_fetched += 1
                    m = _NUXT_DATA_RE.search(resp.text)
                    if not m:
                        break
                    try:
                        arr = json.loads(m.group(1))
                    except json.JSONDecodeError:
                        break
                    if not isinstance(arr, list):
                        break

                    added_page = 0
                    for entry in arr:
                        if len(collected) >= target_limit:
                            break
                        if not isinstance(entry, dict):
                            continue
                        if not {"id", "name", "slug", "combinationInfoVariant"}.issubset(entry.keys()):
                            continue
                        pid = _resolve_nuxt3_val(arr, entry["id"])
                        name = _resolve_nuxt3_val(arr, entry["name"])
                        slug = _resolve_nuxt3_val(arr, entry["slug"])
                        comb = _resolve_nuxt3_val(arr, entry["combinationInfoVariant"])
                        if not isinstance(pid, (int, str)) or not isinstance(name, str) or not isinstance(comb, dict):
                            continue
                        ext_id = str(pid).strip()
                        if not ext_id or ext_id in seen_ids:
                            continue

                        cur_raw = _resolve_nuxt3_val(arr, comb.get("price"))
                        list_raw = _resolve_nuxt3_val(arr, comb.get("list_price"))
                        free_qty = _resolve_nuxt3_val(arr, comb.get("free_qty"))
                        cur_price = parse_egp_price(cur_raw)
                        list_price = parse_egp_price(list_raw)
                        if cur_price is None or float(cur_price) < 5.0:
                            continue
                        claimed = list_price if (list_price is not None and list_price > cur_price) else None

                        img_path = _resolve_nuxt3_val(arr, entry.get("image"))
                        img_url = None
                        if isinstance(img_path, str) and img_path:
                            img_url = img_path if img_path.startswith("http") else f"https://app.petsegypt.com{img_path}"

                        slug_str = str(slug or "").strip()
                        prod_url = (
                            f"https://petsegypt.com{slug_str}"
                            if slug_str.startswith("/")
                            else f"https://petsegypt.com/product/{slug_str or ext_id}"
                        )
                        title = _clean_text(name)
                        brand = _normalize_brand(None, title)
                        if not brand or brand.lower() in ("unknown", "other"):
                            brand = title.split()[0] if title.split() else "PetsEgypt"

                        in_stock = True
                        if isinstance(free_qty, (int, float)):
                            in_stock = free_qty > 0

                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": ext_id[:120],
                                "canonical_product_key": None,
                                "category": "pet_care",
                                "sub_category": default_sub,
                                "brand": brand[:100],
                                "product_title": title[:500],
                                "product_url": prod_url,
                                "image_url": img_url,
                                "attributes_json": {"pets_egypt_category": default_sub},
                                "current_price": cur_price,
                                "claimed_original_price": claimed,
                                "in_stock": in_stock,
                                "snapshot_date": snapshot_date,
                                "scraped_at": scraped_at,
                            }
                        )
                        if rec is not None:
                            seen_ids.add(ext_id)
                            collected.append(rec)
                            cat_cnt += 1
                            added_page += 1

                    if added_page == 0:
                        break
                self.category_counts[f"pet_care/{default_sub}"] = self.category_counts.get(f"pet_care/{default_sub}", 0) + cat_cnt

        return collected


class CarrefourEgScraper(BaseScraper):
    """Carrefour Egypt public XML sitemap + Schema.org JSON-LD scraper (`local_only`).

    Uses strictly standard HTTP (`httpx`) against the public English product sitemaps
    declared in `robots.txt` (`products0_en.xml`..`products2_en.xml`) and parses
    standard `<script type="application/ld+json">` (`schema.org/Product`) metadata.
    Respects `HTTP 403`/`429` immediately without any anti-bot bypass.
    """

    store_name = "carrefour_eg"
    category: Category = "groceries"
    base_url = "https://www.carrefouregypt.com"
    default_limit = 150
    discover_limit = 300
    groceries_limit = 100
    discover_groceries_limit = 150
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries")
    min_delay_seconds = 1.5
    request_timeout = 20.0

    _CORE_SLUGS: dict[str, tuple[Category, str]] = {
        "smartphones": ("electronics", "smartphones"),
        "notebooks-computers": ("electronics", "laptops"),
        "entry-level-laptops": ("electronics", "laptops"),
        "smart-watches-wearables": ("electronics", "smartwatches"),
        "air-conditioners": ("home_appliances", "air_conditioners"),
        "washing-machine": ("home_appliances", "washing_machines"),
        "gas-cookers": ("home_appliances", "cookers"),
        "uhd-tv": ("home_appliances", "tvs"),
        "qled-qned-tv": ("home_appliances", "tvs"),
        "small-smart-tvs": ("home_appliances", "tvs"),
        "oled-tv": ("home_appliances", "tvs"),
        "fridge-351l-to-400l": ("home_appliances", "refrigerators"),
        "fridge-301l-to-350l": ("home_appliances", "refrigerators"),
        "fridge-401l-to-500l": ("home_appliances", "refrigerators"),
        "fridge-501l-to-600l": ("home_appliances", "refrigerators"),
        "freezers": ("home_appliances", "freezers"),
        "electric-water-heater": ("home_appliances", "water_heaters"),
        "microwave-with-grill": ("home_appliances", "microwaves"),
        "microwave": ("home_appliances", "microwaves"),
        "bagged-vacuum": ("home_appliances", "vacuums"),
        "bagless-vacuum": ("home_appliances", "vacuums"),
        "drum-vacuum-cleaners": ("home_appliances", "vacuums"),
        "blender": ("home_appliances", "kitchen_appliances"),
    }

    _GROCERY_SLUGS: dict[str, tuple[Category, str]] = {
        "olive-oil": ("groceries", "oils_ghee"),
        "sunflower-oil": ("groceries", "oils_ghee"),
        "frying-oil": ("groceries", "oils_ghee"),
        "vegetable-ghee": ("groceries", "oils_ghee"),
        "ghee": ("groceries", "oils_ghee"),
        "turkish-coffee": ("groceries", "tea_coffee"),
        "regular-instant-coffee": ("groceries", "tea_coffee"),
        "loose-tea": ("groceries", "tea_coffee"),
        "tea-bags": ("groceries", "tea_coffee"),
        "full-cream-milk": ("groceries", "dairy_cheese"),
        "uht-milk-skimmed": ("groceries", "dairy_cheese"),
        "soft-cream-cheese": ("groceries", "dairy_cheese"),
        "feta-white-cheese": ("groceries", "dairy_cheese"),
        "egyptian-rice": ("groceries", "rice_pasta"),
        "indian-basmati-rice": ("groceries", "rice_pasta"),
        "short-cut-pasta": ("groceries", "rice_pasta"),
        "automatic-powder-detergent": ("groceries", "detergents"),
        "detergent-liquid": ("groceries", "detergents"),
    }

    @staticmethod
    def _clean_cf_brand(raw_brand: Any, title: str, is_grocery: bool) -> str:
        from .groceries import extract_grocery_brand

        b = ""
        if isinstance(raw_brand, dict):
            b = _clean_text(raw_brand.get("name"))
        elif isinstance(raw_brand, str):
            b = _clean_text(raw_brand)
        b = re.sub(r"^(?:nonfood|food)_+", "", b, flags=re.I).replace("_", " ").strip()
        if b and b.lower() not in ("unknown", "other", "generic", "none"):
            return b.title()[:100]
        if is_grocery:
            return extract_grocery_brand(title)[:100]
        nb = _normalize_brand(None, title)
        if nb and nb.lower() not in ("unknown", "other"):
            return nb[:100]
        return (title.split()[0] if title.split() else "Carrefour")[:100]

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        import time
        import httpx
        from .groceries import parse_grocery_packaging, refine_grocery_sub_category

        slug_map = self._GROCERY_SLUGS if self.vertical == "groceries" else self._CORE_SLUGS
        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # 1. Read public English product sitemaps declared in robots.txt
        buckets: dict[str, list[tuple[str, str, Category, str]]] = {}
        with httpx.Client(headers=headers, follow_redirects=True, timeout=self.request_timeout) as client:
            for idx in range(3):
                sm_url = f"{self.base_url}/sitemaps/products{idx}_en.xml"
                try:
                    r_sm = client.get(sm_url)
                except Exception as exc:
                    logger.warning("[carrefour_eg] Sitemap fetch error (%s): %s", sm_url, exc)
                    continue
                if r_sm.status_code in (403, 429):
                    logger.warning("[carrefour_eg] HTTP %d on sitemap %s; stopping immediately.", r_sm.status_code, sm_url)
                    return collected
                if r_sm.status_code != 200:
                    continue
                for m in re.finditer(r"<loc>(https://www\.carrefouregypt\.com/mafegy/en/([^/]+)/[^<]+/p/(\d+))</loc>", r_sm.text):
                    prod_url, cat_slug, sku = m.group(1), m.group(2), m.group(3)
                    if cat_slug in slug_map:
                        cat_name, sub_cat = slug_map[cat_slug]
                        buckets.setdefault(sub_cat, []).append((prod_url, sku, cat_name, sub_cat))

            # Round-robin across sub-categories for balanced coverage
            ordered_urls: list[tuple[str, str, Category, str]] = []
            max_bucket_len = max((len(v) for v in buckets.values()), default=0)
            bucket_keys = sorted(buckets.keys())
            for i in range(max_bucket_len):
                for bk in bucket_keys:
                    if i < len(buckets[bk]):
                        ordered_urls.append(buckets[bk][i])

            logger.info(
                "[carrefour_eg] Selected %d candidate sitemap URLs across %d sub-categories (vertical=%s)",
                len(ordered_urls),
                len(buckets),
                self.vertical,
            )

            # 2. Fetch public product pages politely & extract standard Schema.org JSON-LD
            max_attempts = min(len(ordered_urls), max(target_limit * 2, target_limit + 60))
            for prod_url, url_sku, cat_name, default_sub in ordered_urls[:max_attempts]:
                if len(collected) >= target_limit:
                    break
                if url_sku in seen_ids:
                    continue
                try:
                    rp = client.get(prod_url)
                except Exception as exc:
                    logger.debug("[carrefour_eg] Request error for %s: %s", prod_url, exc)
                    continue

                if rp.status_code in (403, 429):
                    logger.warning("[carrefour_eg] HTTP %d on %s; stopping cleanly.", rp.status_code, prod_url)
                    break
                self.pages_fetched += 1
                if rp.status_code != 200:
                    continue

                soup = BeautifulSoup(rp.text, "html.parser")
                prod_ld: Optional[dict[str, Any]] = None
                for sc in soup.select('script[type="application/ld+json"]'):
                    try:
                        parsed = json.loads(sc.get_text() or "{}")
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict) and str(parsed.get("@type", "")).lower() == "product":
                        prod_ld = parsed
                        break
                if not prod_ld:
                    continue

                offers = prod_ld.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if not isinstance(offers, dict):
                    continue
                if str(offers.get("priceCurrency") or "EGP").upper() != "EGP":
                    continue
                cur_price = parse_egp_price(offers.get("price"))
                if cur_price is None:
                    continue

                avail = str(offers.get("availability") or "")
                in_stock = "outofstock" not in avail.lower()
                title = _clean_text(prod_ld.get("name"))
                sku = _clean_text(prod_ld.get("sku") or url_sku)
                if not title or not sku or sku in seen_ids:
                    continue

                img = prod_ld.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                img_url = _clean_text(img)

                unesc = rp.text.replace('\\"', '"')
                ean_m = re.search(r'"ean"\s*:\s*"(\d{8,14})"', unesc)
                ean = ean_m.group(1) if ean_m else None

                claimed = None
                orig_m = re.search(r'"originalPrice"\s*:\s*"?(\d+(?:\.\d+)?)"?', unesc)
                if orig_m:
                    orig_p = parse_egp_price(orig_m.group(1))
                    if orig_p is not None and orig_p > cur_price:
                        claimed = orig_p

                is_grocery = cat_name == "groceries"
                brand = self._clean_cf_brand(prod_ld.get("brand"), title, is_grocery)
                sub = (
                    refine_grocery_sub_category(title, default_sub)
                    if is_grocery
                    else _refine_sub_category(default_sub, cat_name, title)
                )

                attrs: dict[str, Any] = {"carrefour_sku": sku, "carrefour_category": default_sub}
                if ean:
                    attrs["ean"] = ean
                if is_grocery:
                    attrs.update(parse_grocery_packaging(title, raw_payload={"ean": ean} if ean else None))
                else:
                    attrs.update(_extract_specs(title, sub))

                rec = self.validate_record(
                    {
                        "store_name": self.store_name,
                        "external_id": (ean or sku)[:120],
                        "canonical_product_key": None,
                        "category": cat_name,
                        "sub_category": sub,
                        "brand": brand,
                        "product_title": title[:500],
                        "product_url": prod_url,
                        "image_url": img_url if img_url.startswith("http") else None,
                        "attributes_json": attrs,
                        "current_price": cur_price,
                        "claimed_original_price": claimed,
                        "in_stock": in_stock,
                        "snapshot_date": snapshot_date,
                        "scraped_at": scraped_at,
                    }
                )
                if rec is not None:
                    seen_ids.add(sku)
                    seen_ids.add(url_sku)
                    collected.append(rec)
                    self.category_counts[f"{cat_name}/{sub}"] = self.category_counts.get(f"{cat_name}/{sub}", 0) + 1

                if self.min_delay_seconds > 0:
                    time.sleep(self.min_delay_seconds)

        return collected


class AdidasEgScraper(BaseScraper):
    """Adidas Egypt scraper using standard unmodified Playwright Firefox (`local_only`).

    Strictly uses lazy Playwright import (zero cloud dependency), standard unmodified
    `p.firefox.launch(headless=False)` (zero stealth/evasion flags), polite 3.5s
    delays between category pages, and stops immediately on HTTP 403/429.
    """

    store_name = "adidas_eg"
    category: Category = "fashion"
    base_url = "https://www.adidas.com.eg"
    default_limit = 250
    discover_limit = 450
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion", "core")
    min_delay_seconds = 3.5
    request_timeout = 30.0

    _CAT_PAGES: tuple[tuple[str, str], ...] = (
        ("shoes", "https://www.adidas.com.eg/en/men-shoes"),
        ("shoes", "https://www.adidas.com.eg/en/women-shoes"),
        ("shoes", "https://www.adidas.com.eg/en/kids-shoes"),
        ("apparel", "https://www.adidas.com.eg/en/men-clothing"),
        ("apparel", "https://www.adidas.com.eg/en/women-clothing"),
        ("accessories", "https://www.adidas.com.eg/en/accessories"),
    )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[adidas_eg] Playwright not installed; skipping local_only scrape cleanly.")
            return []

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        per_cat_cap = max(25, math.ceil(target_limit / len(self._CAT_PAGES)) + 15)
        starts = (0, 48) if self.mode == "discover" else (0,)
        blocked = False

        with sync_playwright() as pw:
            try:
                browser = pw.firefox.launch(headless=False)
            except Exception as exc:
                logger.warning("[adidas_eg] Standard Firefox unavailable (%s); skipping cleanly.", exc)
                return []
            try:
                page = browser.new_page()
                for default_sub, base_cat_url in self._CAT_PAGES:
                    if len(collected) >= target_limit or blocked:
                        break
                    cat_cnt = 0
                    for start in starts:
                        if len(collected) >= target_limit or cat_cnt >= per_cat_cap or blocked:
                            break
                        url = base_cat_url if start == 0 else f"{base_cat_url}?start={start}"
                        logger.info("[adidas_eg] Navigating standard Firefox to %s", url)
                        try:
                            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        except Exception as exc:
                            logger.warning("[adidas_eg] Navigation error on %s: %s", url, exc)
                            break

                        status = resp.status if resp else 0
                        if status in (403, 429):
                            logger.warning("[adidas_eg] HTTP %d on %s; stopping immediately.", status, url)
                            blocked = True
                            break
                        if status != 200:
                            break

                        page.wait_for_timeout(int(self.min_delay_seconds * 1000))
                        # Gentle scroll to load lazy images on the rendered grid
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
                        page.wait_for_timeout(800)
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(800)
                        self.pages_fetched += 1

                        cards = page.evaluate(
                            """() => {
                                const links = Array.from(document.querySelectorAll("a[href*='.html']"))
                                    .filter(a => /\\/[A-Z0-9]{5,7}\\.html$/i.test(a.href.split('?')[0]));
                                const seen = new Set();
                                const out = [];
                                for (const a of links) {
                                    const cleanHref = a.href.split('?')[0];
                                    if (seen.has(cleanHref)) continue;
                                    let card = a.closest("[data-auto-id*='product'], [class*='product-card'], [class*='grid-item'], article, [data-pid], .product-tile") || a.parentElement?.parentElement;
                                    const txt = (card ? card.innerText : a.innerText || "").replace(/\\s+/g, " ").trim();
                                    if (!/EGP/i.test(txt)) continue;
                                    seen.add(cleanHref);
                                    const img = card ? card.querySelector("img") : null;
                                    out.push({
                                        href: cleanHref,
                                        img: img ? (img.getAttribute("src") || img.getAttribute("data-src") || "") : "",
                                        text: txt.slice(0, 320),
                                    });
                                }
                                return out;
                            }"""
                        )

                        if not cards:
                            break

                        added_page = 0
                        for c in cards:
                            if len(collected) >= target_limit or cat_cnt >= per_cat_cap:
                                break
                            href = _clean_text(c.get("href"))
                            code_m = re.search(r"/([A-Z0-9]{5,7})\.html$", href, re.I)
                            if not code_m:
                                continue
                            article_code = code_m.group(1).upper()
                            if article_code in seen_ids:
                                continue

                            txt = _clean_text(c.get("text"))
                            # Extract all EGP prices from card text
                            price_strs = re.findall(r"EGP\s*([\d,]+(?:\.\d{1,2})?)", txt, re.I)
                            if not price_strs:
                                price_strs = re.findall(r"([\d,]+(?:\.\d{1,2})?)\s*EGP", txt, re.I)
                            vals = [parse_egp_price(ps) for ps in price_strs]
                            vals = [v for v in vals if v is not None and float(v) >= 50.0]
                            if not vals:
                                continue
                            cur_price = min(vals)
                            claimed = max(vals) if (len(vals) >= 2 and max(vals) > cur_price) else None

                            # Clean title: take text before the first EGP price & strip badge prefixes
                            title_raw = re.split(r"\bEGP\b", txt, maxsplit=1, flags=re.I)[0].strip()
                            title_raw = re.sub(r"^(?:Selected|New|Best Seller|Sale|-\d+%)\s+", "", title_raw, flags=re.I).strip()
                            if len(title_raw) < 3:
                                # Fallback to URL slug
                                slug_part = urlparse(href).path.split("/")[-2].replace("-", " ").title()
                                title_raw = slug_part
                            title_clean = title_raw.title() if title_raw.isupper() else title_raw
                            if "adidas" not in title_clean.lower():
                                title_clean = f"Adidas {title_clean}"
                            if article_code.lower() not in title_clean.lower():
                                title_clean = f"{title_clean} ({article_code})"

                            img_url = _clean_text(c.get("img"))
                            sub = _infer_fashion_sub(title_clean, default_sub)

                            rec = self.validate_record(
                                {
                                    "store_name": self.store_name,
                                    "external_id": article_code[:120],
                                    "canonical_product_key": None,
                                    "category": "fashion",
                                    "sub_category": sub,
                                    "brand": "Adidas",
                                    "product_title": title_clean[:500],
                                    "product_url": href,
                                    "image_url": img_url if img_url.startswith("http") else None,
                                    "attributes_json": {
                                        "article_code": article_code,
                                        "model_number": article_code,
                                        "sku": article_code,
                                        "adidas_category": default_sub,
                                    },
                                    "current_price": cur_price,
                                    "claimed_original_price": claimed,
                                    "in_stock": True,
                                    "snapshot_date": snapshot_date,
                                    "scraped_at": scraped_at,
                                }
                            )
                            if rec is not None:
                                seen_ids.add(article_code)
                                collected.append(rec)
                                cat_cnt += 1
                                added_page += 1

                        if added_page == 0:
                            break
                    self.category_counts[f"fashion/{default_sub}"] = self.category_counts.get(f"fashion/{default_sub}", 0) + cat_cnt
            finally:
                browser.close()

        return collected


WAVE2_EXPANSION_SCRAPER_CLASSES: tuple[type[BaseScraper], ...] = (
    FreshEgScraper,
    ChefaaScraper,
    SeifPharmaciesScraper,
    IkeaEgScraper,
    OrientalWeaversScraper,
    MazayaEgScraper,
    FacesEgScraper,
    LcWaikikiEgScraper,
    DefactoEgScraper,
    PetsEgyptScraper,
    CarrefourEgScraper,
    AdidasEgScraper,
)
