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
import random
import re
import time
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

# 5 parallel Priority-1 department shards covering ALL 10 canonical Asarak categories.
# Splitting Amazon Egypt into department shards lets GitHub Actions matrix runners
# scrape the full catalog concurrently every day without timing out.
AMAZON_EG_DEPARTMENT_SHARD_ORDER: tuple[str, ...] = (
    "electronics",
    "home_appliances",
    "fashion_beauty",
    "groceries_health",
    "home_sports_baby_pet",
)

AMAZON_EG_DEPARTMENT_QUERIES: dict[str, list[tuple[str, Category, str]]] = {
    "electronics": [
        ("smartphones", "electronics", "samsung galaxy smartphone"),
        ("smartphones", "electronics", "apple iphone"),
        ("smartphones", "electronics", "xiaomi redmi smartphone"),
        ("smartphones", "electronics", "oppo reno realme honor smartphone"),
        ("smartphones", "electronics", "infinix tecno nokia vivo smartphone"),
        ("laptops", "electronics", "gaming laptop rtx"),
        ("laptops", "electronics", "lenovo hp dell laptop"),
        ("laptops", "electronics", "asus acer msi apple macbook laptop"),
        ("tablets", "electronics", "ipad samsung galaxy tab lenovo tablet"),
        ("monitors", "electronics", "gaming monitor 144hz samsung lg"),
        ("gaming", "electronics", "playstation ps5 xbox nintendo controller"),
        ("gaming", "electronics", "gaming keyboard mouse headset"),
        ("headphones", "electronics", "wireless headphones anc earbuds"),
        ("headphones", "electronics", "apple airpods jbl soundcore anker earbuds"),
        ("speakers", "electronics", "bluetooth speaker soundbar jbl"),
        ("wearables", "electronics", "smartwatch apple watch samsung amazfit"),
        ("storage", "electronics", "ssd nvme external hard drive flash drive"),
        ("components", "electronics", "nvidia rtx ryzen intel motherboard ram psu"),
        ("networking", "electronics", "tp-link wifi router mesh extender"),
        ("printers", "electronics", "hp epson canon laser printer"),
        ("cameras", "electronics", "canon sony nikon gopro dji camera"),
        ("accessories", "electronics", "anker ugreen power bank charger usb c hub"),
    ],
    "home_appliances": [
        ("tvs", "home_appliances", "smart tv 4k samsung lg"),
        ("tvs", "home_appliances", "tcl tornado sharp toshiba xiaomi smart tv"),
        ("air_conditioners", "home_appliances", "inverter air conditioner carrier midea sharp"),
        ("air_conditioners", "home_appliances", "fresh tornado unionaire air conditioner"),
        ("refrigerators", "home_appliances", "refrigerator no frost sharp toshiba lg"),
        ("refrigerators", "home_appliances", "beko zanussi fresh kiriazi refrigerator"),
        ("freezers", "home_appliances", "deep freezer vertical chest"),
        ("washing_machines", "home_appliances", "automatic washing machine lg samsung bosch"),
        ("washing_machines", "home_appliances", "zanussi beko toshiba hoover washing machine"),
        ("dishwashers", "home_appliances", "dishwasher automatic bosch beko lg"),
        ("cookers", "home_appliances", "gas cooker 5 burner fresh unionaire zanussi"),
        ("ovens", "home_appliances", "built in oven electric oven"),
        ("microwaves", "home_appliances", "microwave oven sharp tornado fresh"),
        ("water_heaters", "home_appliances", "electric gas water heater ariston olympic"),
        ("vacuums", "home_appliances", "vacuum cleaner hoover philips bosch tornado"),
        ("kitchen_appliances", "home_appliances", "air fryer philips ninja tefal"),
        ("kitchen_appliances", "home_appliances", "espresso coffee machine delonghi nespresso"),
        ("kitchen_appliances", "home_appliances", "blender food processor kenwood braun moulinex"),
        ("kitchen_appliances", "home_appliances", "electric kettle toaster sandwich maker"),
        ("irons", "home_appliances", "steam iron garment steamer philips tefal"),
        ("fans", "home_appliances", "stand fan wall fan tornado fresh"),
    ],
    "fashion_beauty": [
        ("footwear", "fashion", "nike adidas running sneakers shoes"),
        ("footwear", "fashion", "skechers puma reebok new balance shoes"),
        ("hoodies", "fashion", "men women hoodie sweatshirt cotton"),
        ("apparel", "fashion", "men jeans polo t-shirt shirt jacket"),
        ("apparel", "fashion", "women dress cardigan blouse pants"),
        ("watches_jewelry", "fashion", "casio seiko fossil wristwatch men women"),
        ("accessories", "fashion", "backpack leather wallet sunglasses belt"),
        ("skincare", "beauty", "cerave la roche posay skincare cleanser"),
        ("skincare", "beauty", "bioderma vichy eucerin sunscreen serum"),
        ("skincare", "beauty", "garnier neutrogena nivea the ordinary skincare"),
        ("perfumes", "beauty", "eau de parfum perfume men women"),
        ("perfumes", "beauty", "lattafa armaf rasasi dior versace perfume"),
        ("haircare", "beauty", "loreal kerastase pantene shampoo haircare"),
        ("makeup", "beauty", "maybelline loreal nyx lipstick mascara foundation"),
        ("personal_care", "beauty", "braun philips trimmer shaver epilator hair dryer"),
        ("personal_care", "beauty", "oral b electric toothbrush deodorant body wash"),
    ],
    "groceries_health": [
        ("oils_ghee", "groceries", "crystal afia sunflower olive oil"),
        ("oils_ghee", "groceries", "rawabi fern ganna ghee butter"),
        ("rice_pasta", "groceries", "el maleka italiano regina pasta"),
        ("rice_pasta", "groceries", "el doha el saa rice flour sugar"),
        ("dairy_cheese", "groceries", "juhayna almarai lamar milk"),
        ("dairy_cheese", "groceries", "obour land domty president cheese"),
        ("tea_coffee", "groceries", "nescafe lipton el arosa tea coffee"),
        ("tea_coffee", "groceries", "abu auf davidoff jacobs starbucks coffee"),
        ("canned_sauces", "groceries", "heinz harvest vitrac tomato paste jam honey"),
        ("canned_sauces", "groceries", "sunshine rio mare tuna canned food"),
        ("beverages", "groceries", "juhayna pepsi schweppes mineral water juice"),
        ("detergents", "groceries", "ariel persil tide laundry detergent"),
        ("detergents", "groceries", "fairy pril dettol clorox downy cleaning"),
        ("snacks", "groceries", "cadbury galaxy nutella chocolate biscuits chips"),
        ("vitamins", "health", "vitamins omega 3 magnesium zinc centrum"),
        ("vitamins", "health", "now foods solgar vitamin d3 multivitamin"),
        ("supplements", "health", "whey protein creatine optimum nutrition muscletech"),
        ("medical_devices", "health", "blood pressure monitor thermometer oximeter"),
    ],
    "home_sports_baby_pet": [
        ("cookware", "home_furniture", "tefal neoflam zahran cookware set"),
        ("cookware", "home_furniture", "luminarc pyrex korkmaz granite cookware"),
        ("bedding", "home_furniture", "memory foam pillow bedsheet duvet mattress"),
        ("furniture", "home_furniture", "office chair gaming chair study desk"),
        ("home_decor", "home_furniture", "storage organizer shelf carpet curtain lamp"),
        ("fitness", "sports", "dumbbells barbell resistance bands home gym"),
        ("sports_gear", "sports", "treadmill exercise bike yoga mat"),
        ("sports_gear", "sports", "football basketball swimming cycling helmet"),
        ("camping", "sports", "camping tent sleeping bag thermos bottle"),
        ("baby_care", "baby_kids", "pampers molfix babyjoy baby diapers wipes"),
        ("baby_care", "baby_kids", "chicco avent baby bottle formula feeding"),
        ("baby_gear", "baby_kids", "baby stroller car seat high chair crib"),
        ("toys", "baby_kids", "lego barbie hot wheels intex kids toys"),
        ("school_supplies", "baby_kids", "school backpack stationery calculator notebook"),
        ("pet_food", "pet_care", "royal canin purina cat dog dry food"),
        ("pet_food", "pet_care", "whiskas friskies felix wet cat food"),
        ("pet_supplies", "pet_care", "cat litter box pet carrier collar toys"),
    ],
}

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

# Deep sharded brand/subcategory queries used ONLY in `mode="expand"` (keeps daily runs lean)
AMAZON_EG_EXPAND_EXTRA_QUERIES: list[tuple[str, Category, str]] = [
    # Wave 1: Electronics, Mobiles, Laptops, Gaming, Audio, Monitors, PC Parts
    ("smartphones", "electronics", "samsung galaxy a55 a35 a16"),
    ("smartphones", "electronics", "samsung galaxy s24 s25 ultra"),
    ("smartphones", "electronics", "oppo reno smartphone"),
    ("smartphones", "electronics", "realme smartphone"),
    ("smartphones", "electronics", "honor smartphone"),
    ("smartphones", "electronics", "infinix tecno smartphone"),
    ("smartphones", "electronics", "nokia vivo smartphone"),
    ("laptops", "electronics", "lenovo ideapad thinkpad laptop"),
    ("laptops", "electronics", "hp pavilion victus laptop"),
    ("laptops", "electronics", "dell inspiron vostro latitude laptop"),
    ("laptops", "electronics", "asus vivobook zenbook tuf laptop"),
    ("laptops", "electronics", "acer aspire nitro laptop"),
    ("laptops", "electronics", "msi gaming laptop"),
    ("laptops", "electronics", "apple macbook air pro"),
    ("tablets", "electronics", "lenovo xiaomi huawei tablet"),
    ("monitors", "electronics", "samsung lg monitor"),
    ("monitors", "electronics", "asus msi aoc benq monitor"),
    ("monitors", "electronics", "dell hp viewsonic monitor"),
    ("gaming", "electronics", "xbox nintendo switch console"),
    ("gaming", "electronics", "gaming keyboard mechanical"),
    ("gaming", "electronics", "gaming mouse logitech razer"),
    ("gaming", "electronics", "gaming headset hyperx"),
    ("headphones", "electronics", "apple airpods sony wh wf"),
    ("headphones", "electronics", "jbl soundcore anker earbuds"),
    ("headphones", "electronics", "oraimo xiaomi buds earbuds"),
    ("speakers", "electronics", "jbl bluetooth speaker soundbar"),
    ("wearables", "electronics", "samsung galaxy watch huawei watch"),
    ("wearables", "electronics", "xiaomi mi band amazfit smartwatch"),
    ("storage", "electronics", "kingston crucial western digital ssd"),
    ("storage", "electronics", "seagate external hard drive"),
    ("storage", "electronics", "sandisk flash drive memory card"),
    ("components", "electronics", "nvidia rtx graphics card"),
    ("components", "electronics", "amd ryzen intel core processor"),
    ("components", "electronics", "motherboard gigabyte asus msi"),
    ("components", "electronics", "ddr4 ddr5 desktop ram corsair"),
    ("components", "electronics", "power supply 80 plus gold psu"),
    ("components", "electronics", "pc case cpu cooler"),
    ("networking", "electronics", "mesh wifi router extender"),
    ("printers", "electronics", "epson canon brother printer"),
    ("accessories", "electronics", "anker ugreen power bank charger"),
    ("accessories", "electronics", "baseus joyroom usb c hub cable"),
    ("cameras", "electronics", "sony nikon gopro dji camera"),
    # Wave 1: Home Appliances (Egypt's top brands & sub-types)
    ("tvs", "home_appliances", "samsung lg smart tv"),
    ("tvs", "home_appliances", "tcl tornado sharp toshiba tv"),
    ("tvs", "home_appliances", "xiaomi haier hisense smart tv"),
    ("air_conditioners", "home_appliances", "carrier midea sharp air conditioner"),
    ("air_conditioners", "home_appliances", "fresh tornado unionaire air conditioner"),
    ("refrigerators", "home_appliances", "sharp toshiba lg refrigerator"),
    ("refrigerators", "home_appliances", "beko zanussi fresh kiriazi fridge"),
    ("freezers", "home_appliances", "deep freezer vertical chest"),
    ("washing_machines", "home_appliances", "lg samsung bosch washing machine"),
    ("washing_machines", "home_appliances", "zanussi beko toshiba hoover washer"),
    ("dishwashers", "home_appliances", "bosch beko lg ariston dishwasher"),
    ("cookers", "home_appliances", "fresh unionaire zanussi gas cooker"),
    ("ovens", "home_appliances", "built in oven electric oven"),
    ("microwaves", "home_appliances", "sharp tornado fresh black decker microwave"),
    ("water_heaters", "home_appliances", "ariston olympic fresh water heater"),
    ("vacuums", "home_appliances", "hoover philips bosch tornado vacuum"),
    ("kitchen_appliances", "home_appliances", "delonghi nespresso coffee machine"),
    ("kitchen_appliances", "home_appliances", "philips ninja tefal air fryer"),
    ("kitchen_appliances", "home_appliances", "kenwood braun moulinex blender mixer"),
    ("kitchen_appliances", "home_appliances", "electric kettle toaster sandwich maker"),
    ("irons", "home_appliances", "philips tefal braun steam iron"),
    ("fans", "home_appliances", "tornado fresh ata stand fan"),
    # Wave 2: Beauty, Skincare, Perfumes, Health, Home/Kitchen, Baby
    ("perfumes", "beauty", "lattafa armaf rasasi perfume"),
    ("perfumes", "beauty", "dior chanel versace calvin klein perfume"),
    ("perfumes", "beauty", "hugo boss giorgio armani ysl perfume"),
    ("skincare", "beauty", "bioderma vichy eucerin skincare"),
    ("skincare", "beauty", "garnier neutrogena nivea face wash"),
    ("skincare", "beauty", "the ordinary cetaphil serum sunscreen"),
    ("haircare", "beauty", "kerastase pantene tresemme shampoo"),
    ("makeup", "beauty", "maybelline loreal nyx makeup"),
    ("personal_care", "beauty", "braun philips trimmer shaver epilator"),
    ("personal_care", "beauty", "oral b electric toothbrush hair dryer"),
    ("vitamins", "health", "now foods centrum solgar vitamins"),
    ("supplements", "health", "creatine protein muscletech dymatize"),
    ("cookware", "home_furniture", "neoflam zahran luminarc cookware"),
    ("cookware", "home_furniture", "pyrex korkmaz granite cookware set"),
    ("baby_care", "baby_kids", "molfix babyjoy chicco avent baby"),
    ("baby_gear", "baby_kids", "baby stroller car seat"),
    ("toys", "baby_kids", "barbie hot wheels intex toys"),
    # Wave 3: Sports & Footwear overlap
    ("footwear", "fashion", "skechers puma reebok new balance shoes"),
    ("sports_gear", "sports", "treadmill exercise bike yoga mat"),
]

AMAZON_EG_GROCERY_EXPAND_QUERIES: list[tuple[str, Category, str]] = [
    ("oils_ghee", "groceries", "afia slite olive oil"),
    ("rice_pasta", "groceries", "italiano regina barilla pasta"),
    ("dairy_cheese", "groceries", "almarai lamar president cheese"),
    ("tea_coffee", "groceries", "el arosa dilmah ahmad tea"),
    ("tea_coffee", "groceries", "davidoff jacobs starbucks coffee"),
    ("canned_sauces", "groceries", "harvest vitrac jam honey"),
    ("beverages", "groceries", "red bull schweppes mineral water"),
    ("detergents", "groceries", "downy comfort dettol clorox"),
    ("snacks", "groceries", "cadbury galaxy lindt nutella chocolate"),
    ("snacks", "groceries", "lays chipsy doritos biscuits"),
    ("pet_food", "pet_care", "whiskas friskies purina cat litter"),
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
    """Live full-catalog scraper for Amazon Egypt across ALL 10 canonical categories.

    Supports optional `department_group` sharding (`electronics`, `home_appliances`,
    `fashion_beauty`, `groceries_health`, `home_sports_baby_pet`) so Priority-1 matrix
    runners can scrape all Amazon Egypt departments concurrently without timing out.
    """

    store_name = "amazon_eg"
    category: Category = "electronics"
    base_url = "https://www.amazon.eg"
    default_limit = 2000
    discover_limit = 5000
    expand_limit = 15000
    groceries_limit = 1000
    discover_groceries_limit = 2500
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries")
    min_delay_seconds = 3.0
    request_timeout = 30.0
    max_consecutive_throttles = 4
    throttle_cooldown_range: tuple[float, float] = (10.0, 18.0)
    page_delay_range: tuple[float, float] = (1.5, 3.5)

    _SESSION_HEADER_PROFILES: tuple[dict[str, str], ...] = (
        {
            "Accept-Language": "en-US,en;q=0.9,ar-EG;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        },
        {
            "Accept-Language": "en-GB,en;q=0.9,ar;q=0.7",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        },
        {
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        },
        {
            "Accept-Language": "en-EG,en;q=0.9,ar-EG;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            ),
        },
    )

    def _open_client(self, effective_delay: float, session_idx: int) -> ImpersonatedHttpClient:
        headers = dict(self._SESSION_HEADER_PROFILES[session_idx % len(self._SESSION_HEADER_PROFILES)])
        return ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 30.0,
            max_retries=3,
            backoff_base=2.5,
            min_delay_seconds=effective_delay,
            jitter_range=(0.5, 1.5),
            headers=headers,
        )

    def _prime_client(self, client: ImpersonatedHttpClient) -> bool:
        try:
            client.get(f"{self.base_url}/-/en/", check_throttle=True, min_html_bytes=5120)
            return True
        except Exception as exc:
            logger.warning("[amazon_eg] Session prime attempt failed: %s", exc)
            return False

    def __init__(
        self,
        *args: Any,
        department_group: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        clean_group = (department_group or "").strip().lower() or None
        if clean_group is not None and clean_group not in AMAZON_EG_DEPARTMENT_QUERIES:
            raise ValueError(
                f"Unknown Amazon Egypt department_group={clean_group!r}; "
                f"expected one of {AMAZON_EG_DEPARTMENT_SHARD_ORDER}"
            )
        self.department_group = clean_group

    def _resolve_queries(self) -> list[tuple[str, Category, str]]:
        """Resolve query list for the active department shard (or full 10-category sweep)."""
        if self.department_group is not None:
            base = list(AMAZON_EG_DEPARTMENT_QUERIES[self.department_group])
            if self.mode in ("discover", "expand"):
                # Append deep brand/model queries matching this department shard's categories
                shard_cats = {cat for _, cat, _ in base}
                extra_pool = (
                    AMAZON_EG_DISCOVER_EXTRA_QUERIES
                    + AMAZON_EG_EXPAND_EXTRA_QUERIES
                    + AMAZON_EG_GROCERY_EXPAND_QUERIES
                )
                seen_q = {q.lower() for _, _, q in base}
                for sub, cat, q in extra_pool:
                    if cat in shard_cats and q.lower() not in seen_q:
                        base.append((sub, cat, q))
                        seen_q.add(q.lower())
            return base

        if self.vertical == "groceries":
            return (
                AMAZON_EG_GROCERY_QUERIES + AMAZON_EG_GROCERY_EXPAND_QUERIES
                if self.mode in ("discover", "expand")
                else AMAZON_EG_GROCERY_QUERIES
            )
        if self.mode == "expand":
            return (
                AMAZON_EG_QUERIES
                + AMAZON_EG_DISCOVER_EXTRA_QUERIES
                + AMAZON_EG_EXPAND_EXTRA_QUERIES
                + AMAZON_EG_GROCERY_QUERIES
                + AMAZON_EG_GROCERY_EXPAND_QUERIES
            )
        if self.mode == "discover":
            return (
                AMAZON_EG_QUERIES
                + AMAZON_EG_DISCOVER_EXTRA_QUERIES
                + AMAZON_EG_GROCERY_QUERIES
            )
        # Daily unsharded fallback: interleaved across all 5 department shards (all 10 categories)
        interleaved: list[tuple[str, Category, str]] = []
        buckets = [AMAZON_EG_DEPARTMENT_QUERIES[g] for g in AMAZON_EG_DEPARTMENT_SHARD_ORDER]
        max_len = max(len(b) for b in buckets)
        for idx in range(max_len):
            for bucket in buckets:
                if idx < len(bucket):
                    interleaved.append(bucket[idx])
        return interleaved

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []
        snapshots: list[RawProductSnapshot] = []
        seen_asins: set[str] = set()
        now = utc_now_naive()
        today = now.date()

        is_groceries = self.vertical == "groceries"
        queries = self._resolve_queries()

        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_query_cap = max(3, math.ceil(target_limit / max(1, len(queries))))
        if self.mode == "expand":
            max_pages = max(5, min(7, self.expand_max_pages or 7))
            per_query_cap = max(per_query_cap, 280)
        elif self.mode == "discover":
            max_pages = 6
            per_query_cap = max(per_query_cap, 180)
        else:
            max_pages = 2 if target_limit <= 120 else (4 if self.department_group else 3)
        throttled = False
        consecutive_throttles = 0
        session_idx = 0
        client = self._open_client(effective_delay, session_idx)
        try:
            # Prime session cookies on the English storefront with transient-503 retry & rotation
            logger.info("[amazon_eg] Priming session on %s/-/en/", self.base_url)
            primed = False
            for attempt in range(3):
                if self._prime_client(client):
                    primed = True
                    break
                if attempt < 2:
                    cooldown = random.uniform(*self.throttle_cooldown_range)
                    logger.warning(
                        "[amazon_eg] Prime strike %d/3; cooling down %.1fs and rotating session.",
                        attempt + 1,
                        cooldown,
                    )
                    time.sleep(cooldown)
                    client.close()
                    session_idx += 1
                    client = self._open_client(effective_delay, session_idx)
            if not primed:
                logger.warning("[amazon_eg] Failed to prime session after retries; exiting gracefully.")
                return snapshots

            for default_sub, top_category, query in queries:
                if len(snapshots) >= target_limit or throttled:
                    break
                query_collected = 0

                for page in range(1, max_pages + 1):
                    if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                        break

                    if page > 1 and self.page_delay_range[1] > 0:
                        time.sleep(random.uniform(*self.page_delay_range))

                    qs = urlencode({"k": query, "page": page})
                    search_url = f"{self.base_url}/-/en/s?{qs}"
                    logger.info("[amazon_eg] Fetching query=%r (%s) page %d", query, top_category, page)
                    try:
                        resp = client.get(search_url, check_throttle=True, min_html_bytes=5120)
                        consecutive_throttles = 0
                    except ThrottledResponseError as exc:
                        consecutive_throttles += 1
                        logger.warning(
                            "[amazon_eg] Throttled on query=%r page %d (%s; strike=%d/%d); %d snapshots so far.",
                            query,
                            page,
                            exc,
                            consecutive_throttles,
                            self.max_consecutive_throttles,
                            len(snapshots),
                        )
                        if consecutive_throttles >= self.max_consecutive_throttles:
                            throttled = True
                            break
                        cooldown = random.uniform(*self.throttle_cooldown_range)
                        logger.info(
                            "[amazon_eg] Cooling down %.1fs, resetting session/cookies, and advancing to next query.",
                            cooldown,
                        )
                        time.sleep(cooldown)
                        client.close()
                        session_idx += 1
                        client = self._open_client(effective_delay, session_idx)
                        self._prime_client(client)
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
        finally:
            client.close()

        return snapshots
