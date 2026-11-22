"""
Config-driven store scrapers scaling Price Truth Radar from 13 -> 30 live Egyptian stores.

Built atop the 3 reusable platform adapters (`ShopifyBaseScraper`,
`MagentoGraphQLBaseScraper`, `WooCommerceBaseScraper`) plus a lightweight
config-driven `SSRCardScraper` for verified OpenCart / PrestaShop / CS-Cart /
Next.js RSC Egyptian storefronts.
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

from .adapters import (
    MagentoGraphQLBaseScraper,
    ShopifyBaseScraper,
    WooCommerceBaseScraper,
)
from .base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    ThrottledResponseError,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)
from .groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)
from .two_b import _extract_specs, _normalize_brand, _refine_sub_category

logger = logging.getLogger(__name__)

# ============================================================================
# 1. SHOPIFY STORES (5 stores: compumarts, tradeline, activ, carina, khotwh)
# ============================================================================


class CompuMartsScraper(ShopifyBaseScraper):
    store_name = "compumarts"
    category: Category = "electronics"
    base_url = "https://www.compumarts.com"
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)


class TradeLineScraper(ShopifyBaseScraper):
    store_name = "tradeline"
    category: Category = "electronics"
    base_url = "https://tradelinestores.com"
    default_brand = "Apple"
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)


class ActivScraper(ShopifyBaseScraper):
    store_name = "activ"
    category: Category = "fashion"
    base_url = "https://activaboualaa.com"
    default_brand = "Activ"
    override_brand = True
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)


class CarinaScraper(ShopifyBaseScraper):
    store_name = "carina"
    category: Category = "fashion"
    base_url = "https://carinawear.com"
    default_brand = "Carina"
    override_brand = True
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)


class KhotwhScraper(ShopifyBaseScraper):
    store_name = "khotwh"
    category: Category = "fashion"
    base_url = "https://khotwh.com"
    default_brand = "Khotwh"
    override_brand = True
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)


# ============================================================================
# 2. WOOCOMMERCE STORES (2 stores: concrete, abu_auf)
# ============================================================================


class ConcreteScraper(WooCommerceBaseScraper):
    store_name = "concrete"
    category: Category = "fashion"
    base_url = "https://concrete.store"
    default_brand = "Concrete"
    override_brand = True
    use_impersonation = True
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)


class AbuAufScraper(WooCommerceBaseScraper):
    store_name = "abu_auf"
    category: Category = "groceries"
    base_url = "https://www.abuauf.com"
    default_brand = "Abu Auf"
    override_brand = True
    default_limit = 180
    groceries_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)


# ============================================================================
# 3. MAGENTO 2 GRAPHQL STORES (3 stores: elaraby, mobaco, gourmet)
# ============================================================================


class ElArabyScraper(MagentoGraphQLBaseScraper):
    store_name = "elaraby"
    category: Category = "home_appliances"
    base_url = "https://www.elarabygroup.com"
    graphql_url = "https://www.elarabygroup.com/graphql"
    product_url_prefix = "/en/"
    product_url_suffix = ".html"
    use_impersonation = True
    use_post = True
    store_header = "en"
    default_limit = 200
    discover_limit = 1000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    search_queries: tuple[tuple[str, Category, str], ...] = (
        ("tvs", "home_appliances", "tornado"),
        ("air_conditioners", "home_appliances", "sharp"),
        ("refrigerators", "home_appliances", "toshiba"),
        ("washing_machines", "home_appliances", "hoover"),
        ("kitchen_appliances", "home_appliances", "kenwood"),
        ("small_appliances", "home_appliances", "braun"),
    )


class MobacoScraper(MagentoGraphQLBaseScraper):
    store_name = "mobaco"
    category: Category = "fashion"
    base_url = "https://mobaco.com"
    graphql_url = "https://mobaco.com/graphql"
    product_url_prefix = "/en/"
    product_url_suffix = ".html"
    default_brand = "Mobaco"
    override_brand = True
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)
    search_queries: tuple[tuple[str, Category, str], ...] = (
        ("polos", "fashion", "polo"),
        ("shirts", "fashion", "shirt"),
        ("pants", "fashion", "pants"),
        ("tees", "fashion", "tee"),
        ("knitwear", "fashion", "sweatshirt"),
        ("jackets", "fashion", "jacket"),
    )


class GourmetScraper(MagentoGraphQLBaseScraper):
    store_name = "gourmet"
    category: Category = "groceries"
    base_url = "https://gourmetegypt.com"
    graphql_url = "https://gourmetegypt.com/graphql"
    product_url_prefix = "/"
    product_url_suffix = ".html"
    default_limit = 200
    groceries_limit = 200
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    search_queries: tuple[tuple[str, Category, str], ...] = (
        ("oils_ghee", "groceries", "oil"),
        ("rice_pasta", "groceries", "pasta"),
        ("dairy_cheese", "groceries", "milk"),
        ("tea_coffee", "groceries", "coffee"),
        ("canned_sauces", "groceries", "sauce"),
        ("beverages", "groceries", "juice"),
        ("detergents", "groceries", "detergent"),
        ("dairy_cheese", "groceries", "cheese"),
        ("rice_pasta", "groceries", "rice"),
    )


# ============================================================================
# 4. CONFIG-DRIVEN SSR STORES (7 stores: elbadr, compuscience, cairosales,
#    egyptlaptop, dubaiphone, imtenan, metro_market)
# ============================================================================

_GENERIC_EGP_RE = re.compile(
    r"(?:EGP|LE|L\.E\.?|ج\.م)\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)|"
    r"(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:EGP|LE|L\.E\.?|ج\.م)",
    re.I,
)


def _extract_prices_from_text(txt: str) -> list[Decimal]:
    vals: list[Decimal] = []
    for m1, m2 in _GENERIC_EGP_RE.findall(txt or ""):
        parsed = parse_egp_price(m1 or m2)
        if parsed is not None and parsed >= Decimal("5"):
            vals.append(parsed)
    return vals


class SSRCardScraper(BaseScraper):
    """Config-driven HTML card scraper for verified OpenCart / PrestaShop / CS-Cart / SSR stores."""

    store_name: str = ""
    category: Category = "electronics"
    base_url: str = ""
    card_selector: str = ""
    title_selector: str = "h2, h3, h4, .name a, a.product-title, a"
    link_selector: str = "a[href]"
    price_selector: str = ""
    old_price_selector: str = ""
    page_param: str = "page"
    use_impersonation: bool = False
    check_throttle: bool = True
    default_brand: str = ""
    override_brand: bool = False
    category_urls: tuple[tuple[str, Category, str], ...] = ()
    default_limit: int = 180
    discover_limit: int = 900
    groceries_limit: int = 180
    discover_groceries_limit: int = 800
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds: float = 1.5
    request_timeout: float = 25.0

    def _scrape_with_fetcher(self, fetcher: Any, target_limit: int) -> list[RawProductSnapshot]:
        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_cat_cap = (
            target_limit
            if target_limit <= 10
            else max(5, math.ceil(target_limit / max(1, len(self.category_urls))))
        )
        max_pages = 8 if self.mode == "discover" else (3 if target_limit > 30 else 1)
        blocked = False

        for default_sub, cat_name, cat_url in self.category_urls:
            if len(collected) >= target_limit or blocked:
                break
            cat_collected = 0

            for page in range(1, max_pages + 1):
                if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                    break
                logger.info("[%s] Fetching %s/%s page %d (%s)", self.store_name, cat_name, default_sub, page, cat_url)
                params = {self.page_param: page} if (page > 1 and self.page_param) else None
                try:
                    if self.use_impersonation:
                        resp = fetcher.get(
                            cat_url,
                            params=params,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=self.check_throttle,
                            min_html_bytes=4096,
                        )
                    else:
                        resp = fetcher.get(
                            cat_url,
                            params=params,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                        )
                except ThrottledResponseError as exc:
                    logger.warning("[%s] WAF/throttle block on %s (%s); exiting gracefully.", self.store_name, cat_url, exc)
                    blocked = True
                    break
                except Exception as exc:
                    logger.warning("[%s] Error fetching %s page %d: %s", self.store_name, cat_url, page, exc)
                    break

                self.pages_fetched += 1
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select(self.card_selector)
                if not cards:
                    break

                page_records: list[RawProductSnapshot] = []
                for card in cards:
                    link = card.select_one(self.link_selector)
                    if not link:
                        continue
                    href = str(link.get("href") or "").strip()
                    if not href or href.startswith("#") or href.startswith("javascript"):
                        continue
                    product_url = urljoin(self.base_url, href)
                    slug = urlparse(product_url).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
                    if not slug:
                        continue

                    title = ""
                    title_el = card.select_one(self.title_selector)
                    if title_el:
                        title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)).strip()
                    if len(title) < 4:
                        img_alt = card.select_one("img[alt]")
                        title = re.sub(r"\s+", " ", str(img_alt.get("alt") or "")).strip() if img_alt else ""
                    if len(title) < 4:
                        continue

                    current_price: Optional[Decimal] = None
                    claimed_price: Optional[Decimal] = None

                    if self.price_selector:
                        pel = card.select_one(self.price_selector)
                        if pel:
                            current_price = parse_egp_price(pel.get_text(" ", strip=True))
                    if self.old_price_selector:
                        oel = card.select_one(self.old_price_selector)
                        if oel:
                            claimed_price = parse_egp_price(oel.get_text(" ", strip=True))

                    if current_price is None:
                        nums = _extract_prices_from_text(card.get_text(" ", strip=True))
                        if nums:
                            current_price = min(nums)
                            if len(nums) >= 2 and max(nums) > current_price:
                                claimed_price = max(nums)

                    if current_price is None:
                        continue
                    if claimed_price is not None and claimed_price <= current_price:
                        claimed_price = None

                    img_url: Optional[str] = None
                    _skip_img_tokens = ("placeholder", "/minus.", "/plus.", "/remove.", "/cart.", "/wishlist.", "/loader.", "icon")
                    # First check background-image / lazy data-src holders (e.g. Metro Market .img-holder)
                    for holder in card.select(".img-holder[data-src], [data-src][style*='background-image']"):
                        cand = str(holder.get("data-src") or "").strip()
                        if cand and not cand.startswith("data:") and not cand.lower().endswith(".svg"):
                            img_url = urljoin(self.base_url, cand)
                            break
                    if not img_url:
                        for img in card.select("img"):
                            for attr in ("data-original", "data-src", "src"):
                                val = str(img.get(attr) or "").strip()
                                low_val = val.lower()
                                if (
                                    val
                                    and not val.startswith("data:")
                                    and not low_val.endswith(".svg")
                                    and not any(tok in low_val for tok in _skip_img_tokens)
                                ):
                                    img_url = urljoin(self.base_url, val)
                                    break
                            if img_url:
                                break

                    ext_id = str(card.get("data-id-product") or card.get("data-product-id") or slug)[:120]
                    if ext_id in seen_ids:
                        continue

                    if cat_name == "groceries":
                        brand = self.default_brand if self.override_brand and self.default_brand else extract_grocery_brand(title, self.default_brand)
                        sub_cat = refine_grocery_sub_category(title, default_sub)
                        attrs: dict[str, Any] = {f"{self.store_name}_category": sub_cat}
                        attrs.update(parse_grocery_packaging(title))
                    else:
                        brand = (self.default_brand if self.override_brand else None) or _normalize_brand(self.default_brand or None, title)
                        sub_cat = _refine_sub_category(default_sub, cat_name, title)
                        attrs = _extract_specs(title, sub_cat)
                        attrs.pop("two_b_category", None)
                        attrs[f"{self.store_name}_category"] = sub_cat

                    card_low = card.get_text(" ", strip=True).lower()
                    in_stock = not ("out of stock" in card_low or "sold out" in card_low or "نفذت الكمية" in card_low)

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

        logger.info("[%s] Per-category counts: %s", self.store_name, self.category_counts)
        return collected

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []
        if self.use_impersonation:
            with ImpersonatedHttpClient(
                impersonate="chrome",
                timeout=self.request_timeout or 25.0,
                max_retries=3,
                backoff_base=2.0,
                min_delay_seconds=max(self.min_delay_seconds, self.http.min_delay_seconds),
                jitter_range=(0.25, 0.8),
            ) as client:
                return self._scrape_with_fetcher(client, target_limit)
        return self._scrape_with_fetcher(self.http, target_limit)


class ElBadrScraper(SSRCardScraper):
    store_name = "elbadr"
    category: Category = "electronics"
    base_url = "https://elbadrgroupeg.store"
    card_selector = ".product-thumb"
    title_selector = ".name a, h4 a"
    link_selector = ".name a[href], a[href]"
    price_selector = ".price-new, .price-normal"
    old_price_selector = ".price-old"
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("laptops", "electronics", "https://elbadrgroupeg.store/laptop"),
        ("monitors", "electronics", "https://elbadrgroupeg.store/monitors"),
        ("gpus", "electronics", "https://elbadrgroupeg.store/vga"),
        ("cpus", "electronics", "https://elbadrgroupeg.store/processor"),
    )


class CompuScienceScraper(SSRCardScraper):
    store_name = "compuscience"
    category: Category = "electronics"
    base_url = "https://compuscience.com.eg"
    card_selector = "article.product-miniature"
    title_selector = "h2.product-title a, h3.product-title a, .product-title a"
    link_selector = ".product-title a[href], a[href]"
    price_selector = ".price"
    old_price_selector = ".regular-price"
    use_impersonation = True
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("laptops", "electronics", "https://compuscience.com.eg/en/11-laptop"),
        ("monitors", "electronics", "https://compuscience.com.eg/en/13-monitors"),
        ("desktops", "electronics", "https://compuscience.com.eg/en/83-gaming-pc"),
        ("storage", "electronics", "https://compuscience.com.eg/en/17-storage"),
        ("networking", "electronics", "https://compuscience.com.eg/en/31-networking"),
    )


class CairoSalesScraper(SSRCardScraper):
    store_name = "cairosales"
    category: Category = "home_appliances"
    base_url = "https://cairosales.com"
    card_selector = ".ajax_block_product"
    title_selector = "a.product-name, h5 a"
    link_selector = "a.product-name[href], a[href]"
    price_selector = ".product-price, .price"
    old_price_selector = ".old-price"
    page_param = "p"
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("tvs", "home_appliances", "https://cairosales.com/en/tvs-screens"),
        ("large_appliances", "home_appliances", "https://cairosales.com/en/home-appliances"),
        ("smartphones", "electronics", "https://cairosales.com/en/mobiles-tablets"),
        ("laptops", "electronics", "https://cairosales.com/en/laptops-notebooks"),
    )


class EgyptLaptopScraper(SSRCardScraper):
    store_name = "egyptlaptop"
    category: Category = "electronics"
    base_url = "https://egyptlaptop.com"
    card_selector = ".ut2-gl__item"
    title_selector = "a.product-title"
    link_selector = "a.product-title[href], a[href]"
    price_selector = ".ty-price-num"
    old_price_selector = ".ty-list-price .ty-price-num, .ty-strike .ty-price-num"
    use_impersonation = True
    min_delay_seconds = 2.0
    default_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("laptops", "electronics", "https://egyptlaptop.com/laptops/laptops-and-notebooks"),
        ("laptops", "electronics", "https://egyptlaptop.com/laptops/gaming-laptops"),
        ("monitors", "electronics", "https://egyptlaptop.com/monitors"),
    )


class ImtenanScraper(SSRCardScraper):
    store_name = "imtenan"
    category: Category = "groceries"
    base_url = "https://imtenan.com"
    card_selector = "div.single_product"
    title_selector = "h4.product_name a, .product_name a"
    link_selector = "h4.product_name a[href], a[href*='/product/']"
    price_selector = "span.current_price"
    old_price_selector = "span.old_price"
    use_impersonation = True
    check_throttle = False
    default_brand = "Imtenan"
    override_brand = True
    default_limit = 180
    groceries_limit = 180
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("canned_sauces", "groceries", "https://imtenan.com/product-category/006-0005"),
        ("tea_coffee", "groceries", "https://imtenan.com/product-category/006-0001"),
        ("oils_ghee", "groceries", "https://imtenan.com/product-category/006-0002"),
        ("rice_pasta", "groceries", "https://imtenan.com/product-category/010-003"),
    )


class MetroMarketScraper(SSRCardScraper):
    store_name = "metro_market"
    category: Category = "groceries"
    base_url = "https://www.metro-markets.com"
    card_selector = ".product-card"
    title_selector = "h5, h4, h3, .product-name, a[href*='/product/']"
    link_selector = "a[href*='/product/'], a[href]"
    price_selector = ".after, .price, .current-price"
    old_price_selector = ".before, .old-price, del"
    default_limit = 200
    groceries_limit = 200
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("dairy_cheese", "groceries", "https://www.metro-markets.com/categoryl1/Dairy/6"),
        ("rice_pasta", "groceries", "https://www.metro-markets.com/categoryl1/Bakery/9"),
        ("canned_sauces", "groceries", "https://www.metro-markets.com/categoryl1/Confectionary/20"),
        ("oils_ghee", "groceries", "https://www.metro-markets.com/en/search?key=oil"),
        ("tea_coffee", "groceries", "https://www.metro-markets.com/en/search?key=tea"),
        ("beverages", "groceries", "https://www.metro-markets.com/en/search?key=juice"),
        ("detergents", "groceries", "https://www.metro-markets.com/en/search?key=ariel"),
    )


_RSC_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)


class DubaiPhoneScraper(BaseScraper):
    """Live Next.js RSC scraper for Dubai Phone Egypt (`https://dubaiphone.net`)."""

    store_name = "dubaiphone"
    category: Category = "electronics"
    base_url = "https://dubaiphone.net"
    default_limit = 180
    discover_limit = 600
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 3.0
    request_timeout = 25.0
    category_urls: tuple[tuple[str, Category, str], ...] = (
        ("tvs", "home_appliances", "https://dubaiphone.net/category/tvs"),
        ("smartphones", "electronics", "https://dubaiphone.net/category/mobiles"),
        ("laptops", "electronics", "https://dubaiphone.net/category/laptops"),
        ("accessories", "electronics", "https://dubaiphone.net/category/accessories"),
    )

    def _extract_rsc_products(self, html: str) -> list[dict[str, Any]]:
        chunks = _RSC_PUSH_RE.findall(html or "")
        parts: list[str] = []
        for ch in chunks:
            try:
                parts.append(json.loads(f'"{ch}"'))
            except json.JSONDecodeError:
                continue
        joined = "".join(parts)
        decoder = json.JSONDecoder()
        items: list[dict[str, Any]] = []
        # Scan for product arrays containing `"selling_price"`
        pos = 0
        while True:
            idx = joined.find('"selling_price"', pos)
            if idx == -1:
                break
            # Walk back to nearest `[` starting the array or `{` starting the object
            obj_start = joined.rfind("{", max(0, idx - 1200), idx)
            if obj_start != -1:
                # Find outer object start containing `"id"` or `"slug"`
                probe = joined.rfind('{"id":', max(0, idx - 1600), idx)
                start = probe if probe != -1 else obj_start
                try:
                    obj, end_pos = decoder.raw_decode(joined, start)
                    if isinstance(obj, dict) and obj.get("slug") and (obj.get("name") or obj.get("title")):
                        items.append(obj)
                        pos = end_pos
                        continue
                except json.JSONDecodeError:
                    pass
            pos = idx + 15
        return items

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(3.0, self.min_delay_seconds, self.http.min_delay_seconds)
        per_cat_cap = (
            target_limit
            if target_limit <= 10
            else max(5, math.ceil(target_limit / len(self.category_urls)))
        )

        max_pages = 4 if self.mode == "discover" else 1
        blocked = False

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 25.0,
            max_retries=4,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.5, 1.5),
        ) as client:
            for default_sub, cat_name, cat_url in self.category_urls:
                if len(collected) >= target_limit or blocked:
                    break
                cat_collected = 0
                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                        break
                    logger.info("[dubaiphone] Fetching %s/%s page %d (%s)", cat_name, default_sub, page, cat_url)
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
                        logger.warning(
                            "[dubaiphone] Rate-limit/WAF block on %s (%s); keeping %d collected items and exiting gracefully.",
                            cat_url,
                            exc,
                            len(collected),
                        )
                        blocked = True
                        break
                    except Exception as exc:
                        logger.warning("[dubaiphone] Error fetching %s page %d: %s", cat_url, page, exc)
                        break
                    self.pages_fetched += 1

                    raw_items = self._extract_rsc_products(resp.text)
                    page_records: list[RawProductSnapshot] = []
                    for raw in raw_items:
                        slug = str(raw.get("slug") or "").strip()
                        title = re.sub(r"\s+", " ", str(raw.get("name") or raw.get("title") or "")).strip()
                        if not slug or len(title) < 4:
                            continue
                        sp_obj = raw.get("selling_price")
                        pr_obj = raw.get("price")
                        curr_val = sp_obj.get("amount") if isinstance(sp_obj, dict) else sp_obj
                        reg_val = pr_obj.get("amount") if isinstance(pr_obj, dict) else pr_obj
                        current_price = parse_egp_price(curr_val)
                        if current_price is None:
                            continue
                        reg_price = parse_egp_price(reg_val)
                        claimed_original = reg_price if (reg_price is not None and reg_price > current_price) else None

                        img_raw = raw.get("base_image") or raw.get("thumbnail") or raw.get("image")
                        img_url = img_raw.get("path") if isinstance(img_raw, dict) else (str(img_raw) if isinstance(img_raw, str) else None)
                        if img_url and not img_url.startswith("http"):
                            img_url = urljoin(self.base_url, img_url)

                        ext_id = str(raw.get("id") or slug)[:120]
                        if ext_id in seen_ids:
                            continue

                        sub_cat = _refine_sub_category(default_sub, cat_name, title)
                        attrs: dict[str, Any] = _extract_specs(title, sub_cat)
                        attrs.pop("two_b_category", None)
                        attrs["dubaiphone_category"] = sub_cat

                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": ext_id,
                                "canonical_product_key": None,
                                "category": cat_name,
                                "sub_category": sub_cat,
                                "brand": _normalize_brand(None, f"{title} {slug.replace('-', ' ')}"),
                                "product_title": title,
                                "product_url": f"{self.base_url}/product/{slug}",
                                "image_url": img_url,
                                "attributes_json": attrs,
                                "current_price": current_price,
                                "claimed_original_price": claimed_original,
                                "in_stock": bool(raw.get("in_stock", True)),
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

        logger.info("[dubaiphone] Per-category counts: %s", self.category_counts)
        return collected


PLATFORM_SCRAPER_CLASSES: tuple[type[BaseScraper], ...] = (
    CompuMartsScraper,
    TradeLineScraper,
    ElArabyScraper,
    ActivScraper,
    CarinaScraper,
    KhotwhScraper,
    ConcreteScraper,
    MobacoScraper,
    AbuAufScraper,
    GourmetScraper,
    ElBadrScraper,
    CompuScienceScraper,
    CairoSalesScraper,
    EgyptLaptopScraper,
    DubaiPhoneScraper,
    ImtenanScraper,
    MetroMarketScraper,
)
