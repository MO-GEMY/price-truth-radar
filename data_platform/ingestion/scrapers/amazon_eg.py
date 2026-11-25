"""
Live scraper for Amazon Egypt (`https://www.amazon.eg/-/en/`).

Uses TLS-impersonated HTTP (`ImpersonatedHttpClient` via `curl_cffi`) with
conservative jittered pacing (`>= 4.0s`) and session priming on
`https://www.amazon.eg/-/en/` prior to executing English search queries across
`electronics`, `home_appliances`, and `fashion`.

Extracts `[data-component-type="s-search-result"]` cards:
- Skips sponsored cards (`a[href*="/sspa/click"]`) and missing ASINs
- `external_id`: 10-character Amazon `data-asin`
- `product_url`: canonical `https://www.amazon.eg/-/en/dp/{ASIN}`
- `current_price`: `.a-price:not(.a-text-price) .a-offscreen`
- `claimed_original_price`: `.a-text-price .a-offscreen` (kept only when strictly `> current_price`)
- `image_url`: `img.s-image` (`m.media-amazon.com/images/I/...`)
"""

from __future__ import annotations

import logging
import math
import re
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

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
from .noon import (
    _extract_brand,
    _extract_specs,
    _refine_sub_category,
)

logger = logging.getLogger(__name__)

# Curated high-overlap search queries interleaved across ALL major Amazon Egypt departments
AMAZON_EG_QUERIES: list[tuple[str, Category, str]] = [
    ("smartphones", "electronics", "samsung galaxy smartphone"),
    ("tvs", "home_appliances", "smart tv 4k"),
    ("hoodies", "fashion", "men hoodie cotton"),
    ("laptops", "electronics", "gaming laptop rtx"),
    ("air_conditioners", "home_appliances", "inverter air conditioner"),
    ("footwear", "fashion", "nike sneakers"),
    ("headphones", "electronics", "wireless headphones anc"),
    ("washing_machines", "home_appliances", "automatic washing machine"),
    ("smartphones", "electronics", "xiaomi redmi smartphone"),
    ("kitchen_appliances", "home_appliances", "air fryer"),
    ("skincare", "beauty", "cerave la roche posay skincare"),
    ("perfumes", "beauty", "eau de parfum perfume"),
    ("vitamins", "health", "vitamins omega 3 supplements"),
    ("cookware", "home_furniture", "tefal cookware set"),
    ("fitness", "sports", "dumbbells fitness home gym"),
    ("baby_care", "baby_kids", "pampers baby diapers"),
    ("pet_food", "pet_care", "royal canin cat dog food"),
]

AMAZON_EG_DISCOVER_EXTRA_QUERIES: list[tuple[str, Category, str]] = [
    ("smartphones", "electronics", "apple iphone"),
    ("tablets", "electronics", "ipad samsung galaxy tab"),
    ("wearables", "electronics", "smartwatch apple watch amazfit"),
    ("gaming", "electronics", "playstation ps5 controller"),
    ("printers", "electronics", "hp laser printer"),
    ("storage", "electronics", "ssd nvme 1tb"),
    ("networking", "electronics", "tp-link wifi router"),
    ("cameras", "electronics", "canon digital camera"),
    ("refrigerators", "home_appliances", "refrigerator no frost"),
    ("cookers", "home_appliances", "gas cooker 5 burner"),
    ("dishwashers", "home_appliances", "dishwasher automatic"),
    ("microwaves", "home_appliances", "microwave oven"),
    ("vacuums", "home_appliances", "vacuum cleaner"),
    ("water_heaters", "home_appliances", "electric water heater"),
    ("kitchen_appliances", "home_appliances", "espresso coffee machine"),
    ("monitors", "electronics", "gaming monitor 144hz"),
    ("footwear", "fashion", "adidas running shoes"),
    ("haircare", "beauty", "loreal shampoo haircare"),
    ("supplements", "health", "whey protein optimum nutrition"),
    ("toys", "baby_kids", "lego toys kids"),
    ("bedding", "home_furniture", "memory foam pillow bedding"),
]

# Egyptian Groceries ("سلة البيت المصري") — 7 high-frequency household sub-categories
AMAZON_EG_GROCERY_QUERIES: list[tuple[str, Category, str]] = [
    ("oils_ghee", "groceries", "crystal sunflower oil"),
    ("rice_pasta", "groceries", "el maleka pasta"),
    ("dairy_cheese", "groceries", "juhayna milk"),
    ("tea_coffee", "groceries", "nescafe lipton tea"),
    ("canned_sauces", "groceries", "heinz tomato paste"),
    ("beverages", "groceries", "juhayna juice"),
    ("detergents", "groceries", "ariel persil detergent"),
    ("oils_ghee", "groceries", "rawabi fern ghee"),
    ("rice_pasta", "groceries", "el doha rice"),
    ("dairy_cheese", "groceries", "obour land domty cheese"),
    ("tea_coffee", "groceries", "abu auf coffee"),
    ("canned_sauces", "groceries", "sunshine tuna"),
    ("beverages", "groceries", "pepsi soft drink"),
    ("detergents", "groceries", "fairy pril dishwashing"),
]

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

_BRAND_NORMALIZATION: dict[str, str] = {
    "hp": "HP",
    "lg": "LG",
    "asus": "ASUS",
    "msi": "MSI",
    "aoc": "AOC",
    "jbl": "JBL",
    "oppo": "OPPO",
    "tcl": "TCL",
    "tp-link": "TP-Link",
    "redmi": "Xiaomi",
    "poco": "Xiaomi",
    "playstation": "Sony",
}


def _normalize_amazon_brand(raw_brand: Optional[str], title: str) -> str:
    candidate = (raw_brand or "").strip()
    if candidate and candidate.lower() not in {"generic", "other", "none", "null", "brand", "unbranded"}:
        low = candidate.lower()
        if low in _BRAND_NORMALIZATION:
            return _BRAND_NORMALIZATION[low]
        if candidate.isupper() and len(candidate) > 3:
            return candidate.title()
        return candidate[:100]
    return _extract_brand(title)


def _is_sponsored_card(card: Tag) -> bool:
    if card.select_one('a[href*="/sspa/click"]'):
        return True
    if card.select_one(".puis-sponsored-label-text, .s-sponsored-label-info-icon"):
        return True
    return False


def _extract_title_and_brand(card: Tag) -> tuple[str, Optional[str]]:
    """
    Amazon Egypt search cards typically render two `<h2>` tags:
      1st `<h2>`: Brand (e.g., `"Samsung"`)
      2nd `<h2>`: Product title (e.g., `"Galaxy A17 5G, Android Smartphone, ..."`)
    """
    h2_texts = [h.get_text(" ", strip=True) for h in card.select("h2") if h.get_text(" ", strip=True)]
    raw_brand: Optional[str] = None
    raw_title = ""

    if len(h2_texts) >= 2 and len(h2_texts[0]) <= 35:
        raw_brand = h2_texts[0]
        raw_title = h2_texts[1]
    elif len(h2_texts) == 1:
        raw_title = h2_texts[0]

    if not raw_title or len(raw_title) < 5:
        recipe = card.select_one('[data-cy="title-recipe"] a')
        if recipe:
            cand = recipe.get_text(" ", strip=True)
            if len(cand) > len(raw_title):
                raw_title = cand

    if not raw_title or len(raw_title) < 5:
        img = card.select_one("img.s-image")
        if img and img.get("alt"):
            raw_title = str(img.get("alt")).strip()

    raw_title = re.sub(r"\s+", " ", raw_title).strip()

    # Prepend brand to title if Amazon separated it into the 1st <h2> and title doesn't already start with it
    if raw_brand and raw_title:
        if not raw_title.lower().startswith(raw_brand.lower()):
            raw_title = f"{raw_brand} {raw_title}"

    return raw_title, raw_brand


def _extract_amazon_prices(card: Tag) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Extract `(current_price, claimed_original_price)` from Amazon search result card."""
    current_price: Optional[Decimal] = None
    claimed_price: Optional[Decimal] = None

    # Primary selling price: `.a-price` that is NOT `.a-text-price` (strikethrough)
    for price_span in card.select(".a-price"):
        classes = set(price_span.get("class") or [])
        offscreen = price_span.select_one(".a-offscreen")
        if not offscreen:
            continue
        parsed = parse_egp_price(offscreen.get_text(" ", strip=True))
        if parsed is None:
            continue
        if "a-text-price" in classes:
            if claimed_price is None:
                claimed_price = parsed
        else:
            if current_price is None:
                current_price = parsed

    # Fallback: check explicit strikethrough selector if not yet found
    if claimed_price is None:
        strike_el = card.select_one(".a-text-price .a-offscreen")
        if strike_el:
            claimed_price = parse_egp_price(strike_el.get_text(" ", strip=True))

    if claimed_price is not None and (current_price is None or claimed_price <= current_price):
        claimed_price = None

    return current_price, claimed_price


def _extract_amazon_image(card: Tag) -> Optional[str]:
    img = card.select_one("img.s-image")
    if not img:
        return None
    for attr in ("src", "data-src"):
        val = str(img.get(attr) or "").strip()
        if val.startswith("http") and "m.media-amazon.com/images/" in val:
            return val
    src = str(img.get("src") or "").strip()
    return src if src.startswith("http") else None


class AmazonEgScraper(BaseScraper):
    """Live scraper for Amazon Egypt across electronics, home_appliances, and fashion."""

    store_name = "amazon_eg"
    category: Category = "electronics"
    base_url = "https://www.amazon.eg"
    default_limit = 500
    discover_limit = 2000
    expand_limit = 3500
    groceries_limit = 400
    discover_groceries_limit = 1200
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries")
    min_delay_seconds = 4.0
    request_timeout = 30.0

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []
        snapshots: list[RawProductSnapshot] = []
        seen_asins: set[str] = set()
        now = utc_now_naive()
        today = now.date()

        is_groceries = self.vertical == "groceries"
        if is_groceries:
            queries = AMAZON_EG_GROCERY_QUERIES
        elif self.mode in ("discover", "expand"):
            queries = AMAZON_EG_QUERIES + AMAZON_EG_DISCOVER_EXTRA_QUERIES
        else:
            queries = AMAZON_EG_QUERIES

        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_query_cap = (
            max(2, math.ceil(target_limit / len(queries)))
            if is_groceries
            else max(3, math.ceil(target_limit / len(queries)))
        )
        max_pages = (
            (5 if self.mode in ("discover", "expand") else 2)
            if is_groceries
            else (6 if self.mode in ("discover", "expand") else (2 if target_limit <= 120 else 3))
        )
        throttled = False

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 30.0,
            max_retries=3,
            backoff_base=2.5,
            min_delay_seconds=effective_delay,
            jitter_range=(0.5, 1.5),
            headers={"Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            # Prime session cookies on the English storefront before hitting /s?k=
            logger.info("[amazon_eg] Priming session on %s/-/en/", self.base_url)
            try:
                client.get(f"{self.base_url}/-/en/", check_throttle=True, min_html_bytes=5120)
            except ThrottledResponseError as exc:
                logger.warning("[amazon_eg] Throttled during session priming: %s; exiting gracefully.", exc)
                return snapshots
            except Exception as exc:
                logger.warning("[amazon_eg] Failed to prime session: %s; exiting gracefully.", exc)
                return snapshots

            for default_sub, top_category, query in queries:
                if len(snapshots) >= target_limit or throttled:
                    break
                query_collected = 0

                for page in range(1, max_pages + 1):
                    if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                        break

                    qs = urlencode({"k": query, "page": page})
                    search_url = f"{self.base_url}/-/en/s?{qs}"
                    logger.info("[amazon_eg] Fetching query=%r (%s) page %d", query, top_category, page)
                    try:
                        resp = client.get(search_url, check_throttle=True, min_html_bytes=5120)
                    except ThrottledResponseError as exc:
                        logger.warning(
                            "[amazon_eg] Throttled on query=%r page %d (%s); exiting gracefully with %d snapshots.",
                            query,
                            page,
                            exc,
                            len(snapshots),
                        )
                        throttled = True
                        break
                    except Exception as exc:
                        logger.warning("[amazon_eg] Failed query=%r page %d: %s", query, page, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select('[data-component-type="s-search-result"]')
                    if not cards:
                        logger.info("[amazon_eg] No search result cards for query=%r page %d", query, page)
                        break

                    page_records: list[RawProductSnapshot] = []
                    for card in cards:
                        asin = str(card.get("data-asin") or "").strip().upper()
                        if not asin or not _ASIN_RE.match(asin) or asin in seen_asins:
                            continue
                        if _is_sponsored_card(card):
                            continue

                        title, raw_brand = _extract_title_and_brand(card)
                        if not title or len(title) < 4:
                            continue

                        current_price, claimed_price = _extract_amazon_prices(card)
                        if current_price is None:
                            self.skipped_count += 1
                            continue

                        image_url = _extract_amazon_image(card)
                        card_text_low = card.get_text(" ", strip=True).lower()
                        in_stock = not (
                            "currently unavailable" in card_text_low
                            or "temporarily out of stock" in card_text_low
                        )

                        if top_category == "groceries":
                            brand = extract_grocery_brand(title, raw_brand)
                            sub_category = refine_grocery_sub_category(title, default_sub)
                            attrs = parse_grocery_packaging(title)
                            attrs["amazon_query"] = query
                        else:
                            brand = _normalize_amazon_brand(raw_brand, title)
                            sub_category = _refine_sub_category(title, top_category, default_sub)
                            attrs = _extract_specs(title, top_category, sub_category)
                            attrs.pop("noon_category", None)
                            attrs["amazon_query"] = query

                        product_url = f"{self.base_url}/-/en/dp/{asin}"
                        snap = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": asin,
                                "canonical_product_key": None,
                                "category": top_category,
                                "sub_category": sub_category,
                                "brand": brand,
                                "product_title": title,
                                "product_url": product_url,
                                "image_url": image_url,
                                "attributes_json": attrs,
                                "current_price": current_price,
                                "claimed_original_price": claimed_price,
                                "in_stock": in_stock,
                                "snapshot_date": today,
                                "scraped_at": now,
                            }
                        )
                        if snap is not None:
                            page_records.append(snap)

                    page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                    page_added = 0
                    for snap in page_records:
                        if snap.external_id in seen_asins:
                            continue
                        seen_asins.add(snap.external_id)
                        snapshots.append(snap)
                        query_collected += 1
                        page_added += 1
                        if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                            break

                    if page_added == 0:
                        break

        return snapshots
