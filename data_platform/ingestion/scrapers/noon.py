"""
Live scraper for Noon Egypt (`https://www.noon.com/egypt-en/`).

Uses TLS-impersonated HTTP (`ImpersonatedHttpClient` via `curl_cffi`) with polite
jittered pacing (`>= 3.0s`) across SSR category grids covering `electronics`,
`home_appliances`, and `fashion` (`?page={N}` pagination).

Extracts product cards from `a[href*="/p/"]` containers:
- `external_id`: Noon SKU segment immediately preceding `/p/` (e.g. `N70158922V`)
- `product_url`: canonical Noon Egypt product URL stripped of tracking params
- `current_price`: selling price from `[data-qa="plp-product-box-price"]`
- `claimed_original_price`: strikethrough price from `.oldPrice.strikeThrough`
  (kept only when strictly `> current_price`)
- `image_url`: real `f.nooncdn.com/p/...` product image (skipping SVG placeholders)
"""

from __future__ import annotations

import logging
import math
import re
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

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

logger = logging.getLogger(__name__)

# Verified live SSR category grids on Noon Egypt spanning ALL major departments
NOON_CATEGORIES: list[tuple[str, Category, str]] = [
    (
        "smartphones",
        "electronics",
        "https://www.noon.com/egypt-en/electronics-and-mobiles/mobiles-and-accessories/mobiles-20905/",
    ),
    (
        "large_appliances",
        "home_appliances",
        "https://www.noon.com/egypt-en/home-and-kitchen/home-appliances-31235/",
    ),
    (
        "clothing",
        "fashion",
        "https://www.noon.com/egypt-en/fashion/",
    ),
    (
        "laptops",
        "electronics",
        "https://www.noon.com/egypt-en/electronics-and-mobiles/computers-and-accessories/laptops/",
    ),
    (
        "kitchen_appliances",
        "home_appliances",
        "https://www.noon.com/egypt-en/home-and-kitchen/",
    ),
    (
        "beauty",
        "beauty",
        "https://www.noon.com/egypt-en/beauty-and-health/beauty/",
    ),
    (
        "health",
        "health",
        "https://www.noon.com/egypt-en/beauty-and-health/health-and-nutrition/",
    ),
    (
        "tvs",
        "home_appliances",
        "https://www.noon.com/egypt-en/electronics-and-mobiles/television-and-video/",
    ),
    (
        "gaming",
        "electronics",
        "https://www.noon.com/egypt-en/electronics-and-mobiles/video-games-10181/",
    ),
    (
        "tablets",
        "electronics",
        "https://www.noon.com/egypt-en/electronics-and-mobiles/tablets/",
    ),
    (
        "headphones",
        "electronics",
        "https://www.noon.com/egypt-en/electronics-and-mobiles/headphones/",
    ),
    (
        "footwear",
        "fashion",
        "https://www.noon.com/egypt-en/fashion/footwear/",
    ),
    (
        "sports_gear",
        "sports",
        "https://www.noon.com/egypt-en/sports-and-outdoors/",
    ),
    (
        "baby_care",
        "baby_kids",
        "https://www.noon.com/egypt-en/baby-products/",
    ),
    (
        "toys",
        "baby_kids",
        "https://www.noon.com/egypt-en/toys-and-games/",
    ),
    (
        "furniture",
        "home_furniture",
        "https://www.noon.com/egypt-en/home-and-kitchen/furniture-10180/",
    ),
    (
        "electronics_general",
        "electronics",
        "https://www.noon.com/egypt-en/electronics-and-mobiles/",
    ),
]

# Egyptian Groceries ("سلة البيت المصري") — 7 high-frequency household sub-categories
NOON_GROCERY_SEEDS: list[tuple[str, Category, str]] = [
    ("oils_ghee", "groceries", "https://www.noon.com/egypt-en/search/?q=cooking+oil"),
    ("rice_pasta", "groceries", "https://www.noon.com/egypt-en/search/?q=pasta"),
    ("dairy_cheese", "groceries", "https://www.noon.com/egypt-en/search/?q=milk"),
    ("tea_coffee", "groceries", "https://www.noon.com/egypt-en/search/?q=nescafe"),
    ("canned_sauces", "groceries", "https://www.noon.com/egypt-en/search/?q=tuna"),
    ("beverages", "groceries", "https://www.noon.com/egypt-en/search/?q=juice"),
    ("detergents", "groceries", "https://www.noon.com/egypt-en/search/?q=ariel"),
    ("oils_ghee", "groceries", "https://www.noon.com/egypt-en/search/?q=ghee"),
    ("rice_pasta", "groceries", "https://www.noon.com/egypt-en/search/?q=rice"),
    ("dairy_cheese", "groceries", "https://www.noon.com/egypt-en/search/?q=domty"),
    ("tea_coffee", "groceries", "https://www.noon.com/egypt-en/search/?q=lipton+tea"),
    ("canned_sauces", "groceries", "https://www.noon.com/egypt-en/search/?q=heinz+ketchup"),
    ("beverages", "groceries", "https://www.noon.com/egypt-en/search/?q=pepsi"),
    ("detergents", "groceries", "https://www.noon.com/egypt-en/search/?q=persil"),
    ("detergents", "groceries", "https://www.noon.com/egypt-en/search/?q=fairy"),
]

# Deep sharded Noon Egypt categories & brand searches (ONLY active in `mode="expand"`)
NOON_EXPAND_EXTRA_SEEDS: list[tuple[str, Category, str]] = [
    ("smartphones", "electronics", "https://www.noon.com/egypt-en/search/?q=samsung+galaxy+smartphone"),
    ("smartphones", "electronics", "https://www.noon.com/egypt-en/search/?q=apple+iphone"),
    ("smartphones", "electronics", "https://www.noon.com/egypt-en/search/?q=xiaomi+redmi"),
    ("smartphones", "electronics", "https://www.noon.com/egypt-en/search/?q=oppo+realme+honor"),
    ("laptops", "electronics", "https://www.noon.com/egypt-en/search/?q=lenovo+hp+dell+laptop"),
    ("laptops", "electronics", "https://www.noon.com/egypt-en/search/?q=asus+acer+msi+gaming+laptop"),
    ("monitors", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/computers-and-accessories/monitors/"),
    ("printers", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/computers-and-accessories/printers-and-accessories/"),
    ("storage", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/computers-and-accessories/data-storage/"),
    ("networking", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/computers-and-accessories/networking-products/"),
    ("wearables", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/wearable-technology/"),
    ("cameras", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/camera-and-photo-16150/"),
    ("speakers", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/portable-audio-and-video/speakers-16146/"),
    ("accessories", "electronics", "https://www.noon.com/egypt-en/electronics-and-mobiles/mobiles-and-accessories/accessories-16176/"),
    ("refrigerators", "home_appliances", "https://www.noon.com/egypt-en/search/?q=refrigerator+no+frost"),
    ("washing_machines", "home_appliances", "https://www.noon.com/egypt-en/search/?q=washing+machine+automatic"),
    ("air_conditioners", "home_appliances", "https://www.noon.com/egypt-en/search/?q=air+conditioner+split"),
    ("kitchen_appliances", "home_appliances", "https://www.noon.com/egypt-en/home-and-kitchen/home-appliances-31235/small-appliances/"),
    ("kitchen_appliances", "home_appliances", "https://www.noon.com/egypt-en/search/?q=air+fryer"),
    ("kitchen_appliances", "home_appliances", "https://www.noon.com/egypt-en/search/?q=coffee+espresso+machine"),
    ("vacuums", "home_appliances", "https://www.noon.com/egypt-en/search/?q=vacuum+cleaner"),
    ("microwaves", "home_appliances", "https://www.noon.com/egypt-en/search/?q=microwave+oven"),
    ("water_heaters", "home_appliances", "https://www.noon.com/egypt-en/search/?q=water+heater"),
    ("perfumes", "beauty", "https://www.noon.com/egypt-en/beauty-and-health/beauty/fragrance/"),
    ("skincare", "beauty", "https://www.noon.com/egypt-en/beauty-and-health/beauty/skin-care/"),
    # Deep leaf-category & brand shards for uncapped full-catalog sweeps
    ("smartphones", "electronics", "https://www.noon.com/egypt-en/search/?q=infinix+tecno+vivo+nokia"),
    ("smartphones", "electronics", "https://www.noon.com/egypt-en/search/?q=samsung+galaxy+a+series"),
    ("laptops", "electronics", "https://www.noon.com/egypt-en/search/?q=macbook+ipad+apple"),
    ("gaming", "electronics", "https://www.noon.com/egypt-en/search/?q=playstation+xbox+nintendo"),
    ("headphones", "electronics", "https://www.noon.com/egypt-en/search/?q=anker+soundcore+jbl+sony"),
    ("accessories", "electronics", "https://www.noon.com/egypt-en/search/?q=ugreen+oraimo+power+bank+charger"),
    ("tvs", "home_appliances", "https://www.noon.com/egypt-en/search/?q=smart+tv+4k+samsung+lg+tcl+tornado"),
    ("refrigerators", "home_appliances", "https://www.noon.com/egypt-en/search/?q=toshiba+sharp+fresh+beko+refrigerator"),
    ("washing_machines", "home_appliances", "https://www.noon.com/egypt-en/search/?q=lg+samsung+zanussi+beko+washing+machine"),
    ("cookers", "home_appliances", "https://www.noon.com/egypt-en/search/?q=gas+cooker+fresh+unionaire+zanussi"),
    ("kitchen_appliances", "home_appliances", "https://www.noon.com/egypt-en/search/?q=kenwood+braun+moulinex+tefal+blender"),
    ("cookware", "home_furniture", "https://www.noon.com/egypt-en/search/?q=tefal+neoflam+zahran+cookware+set"),
    ("bedding", "home_furniture", "https://www.noon.com/egypt-en/search/?q=bedsheet+duvet+pillow+mattress"),
    ("furniture", "home_furniture", "https://www.noon.com/egypt-en/search/?q=office+chair+desk+table+organizer"),
    ("apparel", "fashion", "https://www.noon.com/egypt-en/fashion/men-31225/"),
    ("apparel", "fashion", "https://www.noon.com/egypt-en/fashion/women-31229/"),
    ("kids_fashion", "baby_kids", "https://www.noon.com/egypt-en/fashion/kids-31231/"),
    ("footwear", "fashion", "https://www.noon.com/egypt-en/search/?q=nike+adidas+puma+skechers+sneakers"),
    ("watches_jewelry", "fashion", "https://www.noon.com/egypt-en/search/?q=casio+fossil+seiko+watch"),
    ("bags", "fashion", "https://www.noon.com/egypt-en/search/?q=backpack+handbag+luggage+suitcase"),
    ("skincare", "beauty", "https://www.noon.com/egypt-en/search/?q=cerave+la+roche+posay+bioderma+vichy"),
    ("haircare", "beauty", "https://www.noon.com/egypt-en/search/?q=loreal+garnier+pantene+shampoo"),
    ("makeup", "beauty", "https://www.noon.com/egypt-en/search/?q=maybelline+nyx+essence+makeup"),
    ("perfumes", "beauty", "https://www.noon.com/egypt-en/search/?q=lattafa+armaf+dior+versace+perfume"),
    ("vitamins", "health", "https://www.noon.com/egypt-en/search/?q=vitamins+omega+magnesium+protein+creatine"),
    ("baby_care", "baby_kids", "https://www.noon.com/egypt-en/search/?q=pampers+molfix+chicco+avent+stroller"),
    ("toys", "baby_kids", "https://www.noon.com/egypt-en/search/?q=lego+barbie+hot+wheels+kids+toys"),
    ("pet_food", "pet_care", "https://www.noon.com/egypt-en/search/?q=cat+dog+food+royal+canin+whiskas+litter"),
    ("sports_gear", "sports", "https://www.noon.com/egypt-en/search/?q=dumbbells+treadmill+yoga+mat+bicycle"),
    ("stationery", "baby_kids", "https://www.noon.com/egypt-en/search/?q=school+backpack+stationery+books"),
    ("makeup", "beauty", "https://www.noon.com/egypt-en/beauty-and-health/beauty/makeup-16230/"),
    ("haircare", "beauty", "https://www.noon.com/egypt-en/beauty-and-health/beauty/hair-care/"),
    ("personal_care", "beauty", "https://www.noon.com/egypt-en/beauty-and-health/personal-care/"),
    ("vitamins", "health", "https://www.noon.com/egypt-en/search/?q=vitamins+supplements"),
    ("sports_nutrition", "health", "https://www.noon.com/egypt-en/search/?q=whey+protein+creatine"),
    ("cookware", "home_furniture", "https://www.noon.com/egypt-en/home-and-kitchen/kitchen-and-dining/cookware/"),
    ("bedding_linens", "home_furniture", "https://www.noon.com/egypt-en/home-and-kitchen/bedding/"),
    ("pet_food", "pet_care", "https://www.noon.com/egypt-en/pet-supplies/"),
]

NOON_GROCERY_EXPAND_SEEDS: list[tuple[str, Category, str]] = [
    ("oils_ghee", "groceries", "https://www.noon.com/egypt-en/search/?q=olive+oil"),
    ("dairy_cheese", "groceries", "https://www.noon.com/egypt-en/search/?q=cheese"),
    ("tea_coffee", "groceries", "https://www.noon.com/egypt-en/search/?q=coffee"),
    ("canned_sauces", "groceries", "https://www.noon.com/egypt-en/search/?q=honey+jam"),
    ("snacks", "groceries", "https://www.noon.com/egypt-en/search/?q=chocolate+biscuits"),
    ("detergents", "groceries", "https://www.noon.com/egypt-en/search/?q=dettol+downy"),
    ("baby_care", "baby_kids", "https://www.noon.com/egypt-en/search/?q=pampers+diapers"),
]

_NOON_SKU_RE = re.compile(r"/([A-Za-z0-9_-]{4,32})/p(?:/|$|\?)")
_PRICE_NUM_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{2,7}(?:\.\d{1,2})?)(?!\s*%)")

_RAM_RE = re.compile(r"\b(\d{1,2})\s*GB\s*(?:RAM|DDR[345])?\b", re.I)
_STORAGE_TB_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*TB\b", re.I)
_STORAGE_GB_RE = re.compile(
    r"\b(64|128|256|512|1000|1024)\s*GB\s*(?:SSD|NVMe|M\.2|ROM|Storage|Internal)?\b",
    re.I,
)
_REFRESH_HZ_RE = re.compile(r"\b(60|75|90|100|120|144|165|170|180|240)\s*Hz\b", re.I)
_SCREEN_INCH_RE = re.compile(
    r"\b(6\.\d|10\.\d|11(?:\.\d)?|13\.3|14(?:\.\d)?|15\.\d|16(?:\.\d)?|17\.3|23\.8|24|27|32|43|50|55|65|75)\s*(?:\"|-?\s*inch)\b",
    re.I,
)

_MULTI_WORD_BRANDS: tuple[tuple[str, str], ...] = (
    ("black & decker", "Black & Decker"),
    ("black+decker", "Black+Decker"),
    ("lc waikiki", "LC Waikiki"),
    ("town team", "Town Team"),
    ("under armour", "Under Armour"),
    ("new balance", "New Balance"),
    ("tommy hilfiger", "Tommy Hilfiger"),
    ("calvin klein", "Calvin Klein"),
    ("jack & jones", "Jack & Jones"),
    ("tp-link", "TP-Link"),
    ("western digital", "Western Digital"),
    ("redragon", "Redragon"),
)

_BRAND_ACRONYMS: dict[str, str] = {
    "hp": "HP",
    "lg": "LG",
    "asus": "ASUS",
    "msi": "MSI",
    "aoc": "AOC",
    "jbl": "JBL",
    "oppo": "OPPO",
    "tcl": "TCL",
    "hmd": "HMD",
    "dkny": "DKNY",
    "redmi": "Xiaomi",
    "poco": "Xiaomi",
    "realme": "Realme",
    "infinix": "Infinix",
    "tecno": "Tecno",
    "honor": "Honor",
    "huawei": "Huawei",
    "xiaomi": "Xiaomi",
    "samsung": "Samsung",
    "apple": "Apple",
    "iphone": "Apple",
    "ipad": "Apple",
    "macbook": "Apple",
    "airpods": "Apple",
    "lenovo": "Lenovo",
    "dell": "Dell",
    "acer": "Acer",
    "sony": "Sony",
    "playstation": "Sony",
    "nokia": "Nokia",
    "vivo": "Vivo",
    "oneplus": "OnePlus",
    "anker": "Anker",
    "oraimo": "Oraimo",
    "soundcore": "Soundcore",
    "tornado": "Tornado",
    "fresh": "Fresh",
    "sharp": "Sharp",
    "toshiba": "Toshiba",
    "beko": "Beko",
    "midea": "Midea",
    "carrier": "Carrier",
    "zanussi": "Zanussi",
    "hoover": "Hoover",
    "kenwood": "Kenwood",
    "braun": "Braun",
    "philips": "Philips",
    "tefal": "Tefal",
    "moulinex": "Moulinex",
    "delonghi": "DeLonghi",
    "bosch": "Bosch",
    "whirlpool": "Whirlpool",
    "haier": "Haier",
    "unionaire": "Unionaire",
    "kiriazi": "Kiriazi",
    "nike": "Nike",
    "adidas": "Adidas",
    "puma": "Puma",
    "reebok": "Reebok",
    "skechers": "Skechers",
    "defacto": "DeFacto",
    "zara": "Zara",
    "mango": "Mango",
    "activ": "Activ",
    "concrete": "Concrete",
    "mobaco": "Mobaco",
}

_ELECTRONICS_SUBCAT_REFINERS: list[tuple[tuple[str, ...], str]] = [
    (("iphone", "galaxy a", "galaxy s", "galaxy z", "redmi", "smartphone", "dual sim", "5g", "4g lte"), "smartphones"),
    (("laptop", "macbook", "notebook", "thinkpad", "ideapad", "vivobook", "zenbook", "inspiron", "pavilion", "victus"), "laptops"),
    (("ipad", "tablet", "galaxy tab", "matepad"), "tablets"),
    (("headphone", "earbud", "earphone", "airpods", "headset", "buds"), "headphones"),
    (("smartwatch", "smart watch", "watch", "band"), "wearables"),
    (("monitor", "gaming monitor"), "monitors"),
    (("playstation", "xbox", "nintendo", "controller", "gaming chair"), "gaming"),
    (("power bank", "charger", "cable", "adapter", "speaker", "mouse", "keyboard", "router"), "accessories"),
]

_APPLIANCE_SUBCAT_REFINERS: list[tuple[tuple[str, ...], str]] = [
    (("smart tv", "led tv", "qled", "oled", "uhd tv", "4k tv", "television"), "tvs"),
    (("refrigerator", "fridge"), "refrigerators"),
    (("freezer",), "freezers"),
    (("washing machine", "washer", "dryer"), "washing_machines"),
    (("dishwasher",), "dishwashers"),
    (("air conditioner", "split ac", "inverter ac", "1.5 hp", "2.25 hp", "3 hp"), "air_conditioners"),
    (("microwave",), "microwaves"),
    (("cooker", "gas stove", "hob"), "cookers"),
    (("oven",), "ovens"),
    (("vacuum",), "vacuums"),
    (("water heater",), "water_heaters"),
    (("fan", "air cooler"), "fans"),
    (("air fryer", "blender", "mixer", "kettle", "coffee", "espresso", "toaster", "juicer", "food processor", "grill", "iron", "steamer"), "kitchen_appliances"),
]

_FASHION_SUBCAT_REFINERS: list[tuple[tuple[str, ...], str]] = [
    (("sneaker", "running shoe", "trainer", "shoe", "boot", "sandal", "slipper", "loafer", "heel"), "footwear"),
    (("hoodie", "sweatshirt", "pullover", "sweater", "cardigan"), "hoodies"),
    (("jacket", "coat", "blazer", "vest", "puffer", "windbreaker"), "jackets"),
    (("jeans", "denim", "trouser", "pant", "chino", "jogger", "short"), "bottoms"),
    (("dress", "abaya", "jumpsuit", "skirt", "kaftan"), "dresses"),
    (("t-shirt", "tee", "polo", "shirt", "blouse", "top"), "tops"),
    (("bag", "backpack", "handbag", "wallet", "belt", "sunglasses", "cap"), "accessories"),
]


def _extract_brand(title: str) -> str:
    low = title.lower()
    for needle, canonical in _MULTI_WORD_BRANDS:
        if low.startswith(needle) or f" {needle} " in f" {low} ":
            return canonical

    first_token = title.strip().split(" ", 1)[0] if title.strip() else ""
    cleaned_first = re.sub(r"[^A-Za-z0-9.\-+']", "", first_token)
    if cleaned_first.lower() in _BRAND_ACRONYMS:
        return _BRAND_ACRONYMS[cleaned_first.lower()]

    # Check if any known brand appears near the start (first 4 words)
    words = re.findall(r"[A-Za-z0-9+\-']+", title)[:4]
    for w in words:
        if w.lower() in _BRAND_ACRONYMS:
            return _BRAND_ACRONYMS[w.lower()]

    if cleaned_first:
        if cleaned_first.isupper() and len(cleaned_first) > 3:
            return cleaned_first.title()
        return cleaned_first[:100]
    return "Unknown"


def _refine_sub_category(title: str, category: Category, default_sub: str) -> str:
    low = title.lower()
    if category == "home_appliances":
        for keywords, sub in _APPLIANCE_SUBCAT_REFINERS:
            if any(k in low for k in keywords):
                return sub
    elif category == "fashion":
        for keywords, sub in _FASHION_SUBCAT_REFINERS:
            if any(k in low for k in keywords):
                return sub
    elif default_sub == "electronics_general":
        for keywords, sub in _ELECTRONICS_SUBCAT_REFINERS:
            if any(k in low for k in keywords):
                return sub
        return "accessories"
    return default_sub


def _extract_specs(title: str, category: Category, sub_category: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {"noon_category": sub_category}
    if category == "fashion":
        return attrs

    ram_matches = [int(m) for m in _RAM_RE.findall(title) if 2 <= int(m) <= 64]
    if ram_matches:
        attrs["ram_gb"] = ram_matches[0]

    if m := _STORAGE_TB_RE.search(title):
        tb_val = float(m.group(1))
        if 0.5 <= tb_val <= 16:
            attrs["storage_gb"] = int(tb_val * 1024)
    elif m := _STORAGE_GB_RE.search(title):
        attrs["storage_gb"] = int(m.group(1))

    if m := _REFRESH_HZ_RE.search(title):
        attrs["refresh_rate_hz"] = int(m.group(1))
    if m := _SCREEN_INCH_RE.search(title):
        attrs["screen_inches"] = float(m.group(1))
    return attrs


def _canonical_noon_url(href: str, base_url: str) -> tuple[Optional[str], Optional[str]]:
    """Return `(sku, canonical_url)` from a Noon product anchor href."""
    full_url = urljoin(base_url, href.strip())
    parsed = urlparse(full_url)
    m = _NOON_SKU_RE.search(parsed.path)
    if not m:
        return None, None
    sku = m.group(1).upper()
    # Keep clean path up through `/p/` without tracking query params (`?o=...`)
    p_end = m.end()
    clean_path = parsed.path[:p_end]
    if not clean_path.endswith("/"):
        clean_path += "/"
    canonical = f"https://www.noon.com{clean_path}"
    return sku, canonical


def _find_card_container(anchor: Tag) -> Tag:
    """Return the enclosing product-box element containing both name and price."""
    if anchor.select_one('[data-qa="plp-product-box-price"]'):
        return anchor
    node: Optional[Tag] = anchor.parent
    for _ in range(4):
        if node is None or not isinstance(node, Tag):
            break
        if node.select_one('[data-qa="plp-product-box-price"]'):
            return node
        node = node.parent
    return anchor


def _extract_noon_image(card: Tag) -> Optional[str]:
    """Extract the real `f.nooncdn.com/p/...` product image, skipping SVG placeholders."""
    candidates: list[str] = []
    for img in card.select("img"):
        for attr in ("src", "data-src", "srcset"):
            val = img.get(attr)
            if not val:
                continue
            raw = str(val).strip()
            if attr == "srcset":
                # Take the first URL token in srcset
                raw = raw.split(",")[0].strip().split(" ")[0].strip()
            if raw.startswith("//"):
                raw = "https:" + raw
            if raw.startswith("http"):
                candidates.append(raw)

    # First pass: prefer real Noon product CDN images (`f.nooncdn.com/p/`)
    for url in candidates:
        low = url.lower()
        if "media-placeholder" in low or low.endswith(".svg") or "/s/app/" in low:
            continue
        if "nooncdn.com/p/" in low:
            return url

    # Second pass: any non-placeholder raster image
    for url in candidates:
        low = url.lower()
        if "media-placeholder" in low or low.endswith(".svg") or "/s/app/" in low:
            continue
        return url
    return None


def _extract_noon_prices(card: Tag) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Extract `(current_price, claimed_original_price)` from Noon PLP card."""
    price_box = card.select_one('[data-qa="plp-product-box-price"]')
    if not price_box:
        return None, None

    claimed_price: Optional[Decimal] = None
    old_el = (
        price_box.select_one(".oldPrice.strikeThrough")
        or price_box.select_one('[class*="oldPrice"]')
        or price_box.select_one("del, s")
    )
    if old_el:
        claimed_price = parse_egp_price(old_el.get_text(" ", strip=True))

    current_price: Optional[Decimal] = None
    # Prefer dedicated selling-price element when present
    for sel in ('[class*="amount"]', '[class*="sellingPrice"]', "strong"):
        el = price_box.select_one(sel)
        if el and el is not old_el:
            parsed = parse_egp_price(el.get_text(" ", strip=True))
            if parsed is not None:
                current_price = parsed
                break

    # Fallback: parse ordered numbers from price box text
    if current_price is None:
        raw_text = price_box.get_text(" ", strip=True)
        nums = [parse_egp_price(m) for m in _PRICE_NUM_RE.findall(raw_text)]
        nums = [n for n in nums if n is not None and n >= Decimal("10")]
        if nums:
            current_price = nums[0]
            if claimed_price is None and len(nums) >= 2 and nums[1] > current_price:
                claimed_price = nums[1]

    if claimed_price is not None and (current_price is None or claimed_price <= current_price):
        claimed_price = None

    return current_price, claimed_price


class NoonScraper(BaseScraper):
    """Live scraper for Noon Egypt across electronics, home_appliances, and fashion."""

    store_name = "noon"
    category: Category = "electronics"
    base_url = "https://www.noon.com"
    default_limit = 500
    discover_limit = 2000
    expand_limit = 200000
    groceries_limit = 400
    discover_groceries_limit = 1200
    supported_verticals: tuple[ScrapeVertical, ...] = ("core", "groceries")
    min_delay_seconds = 2.5
    request_timeout = 30.0

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        now = utc_now_naive()
        today = now.date()

        is_groceries = self.vertical == "groceries"
        if is_groceries:
            seeds = (
                NOON_GROCERY_SEEDS + NOON_GROCERY_EXPAND_SEEDS
                if self.mode == "expand"
                else NOON_GROCERY_SEEDS
            )
        else:
            seeds = (
                NOON_CATEGORIES + NOON_EXPAND_EXTRA_SEEDS
                if self.mode == "expand"
                else NOON_CATEGORIES
            )
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_cat_cap = (
            max(2, math.ceil(target_limit / len(seeds)))
            if is_groceries
            else max(5, math.ceil(target_limit / len(seeds)))
        )
        if self.mode == "expand":
            max_pages = max(15, min(60, self.expand_max_pages or 40))
            per_cat_cap = max(per_cat_cap, 5000)
        elif is_groceries:
            max_pages = 6 if self.mode == "discover" else 3
        else:
            max_pages = 12 if self.mode == "discover" else 5
        throttled = False
        consecutive_throttles = 0

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 30.0,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.4, 1.3),
        ) as client:
            for default_sub, top_category, cat_url in seeds:
                if len(snapshots) >= target_limit or throttled:
                    break
                cat_collected = 0

                for page in range(1, max_pages + 1):
                    if len(snapshots) >= target_limit or cat_collected >= per_cat_cap:
                        break

                    if page == 1:
                        page_url = cat_url
                    else:
                        sep = "&" if "?" in cat_url else "?"
                        page_url = f"{cat_url}{sep}page={page}"
                    logger.info("[noon] Fetching %s (%s) page %d", default_sub, top_category, page)
                    try:
                        resp = client.get(page_url, check_throttle=True, min_html_bytes=5120)
                        consecutive_throttles = 0
                    except ThrottledResponseError as exc:
                        consecutive_throttles += 1
                        logger.warning(
                            "[noon] Throttled on %s page %d (%s; strike=%d); %d snapshots so far.",
                            default_sub,
                            page,
                            exc,
                            consecutive_throttles,
                            len(snapshots),
                        )
                        if self.mode == "expand" and consecutive_throttles < 3:
                            import time as _time
                            _time.sleep(8.0 * consecutive_throttles)
                            break
                        throttled = True
                        break
                    except Exception as exc:
                        logger.warning("[noon] Failed to fetch %s page %d: %s", default_sub, page, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    anchors = soup.select('a[href*="/p/"]')
                    if not anchors:
                        logger.info("[noon] No product anchors on %s page %d; stopping category.", default_sub, page)
                        break

                    page_records: list[RawProductSnapshot] = []
                    for anchor in anchors:
                        href = anchor.get("href")
                        if not href:
                            continue

                        sku, product_url = _canonical_noon_url(str(href), self.base_url)
                        if not sku or not product_url or sku in seen_ids:
                            continue

                        card = _find_card_container(anchor)
                        name_el = card.select_one('[data-qa="plp-product-box-name"]')
                        title = ""
                        if name_el:
                            title_attr = str(name_el.get("title") or "").strip()
                            text_val = name_el.get_text(" ", strip=True)
                            title = title_attr if len(title_attr) > len(text_val) else text_val
                        if not title:
                            title = str(anchor.get("title") or "").strip()
                        if not title:
                            img = card.select_one("img[alt]")
                            title = str(img.get("alt") or "").strip() if img else ""
                        if not title or len(title) < 4:
                            continue

                        current_price, claimed_price = _extract_noon_prices(card)
                        if current_price is None:
                            self.skipped_count += 1
                            continue

                        image_url = _extract_noon_image(card)
                        card_text_low = card.get_text(" ", strip=True).lower()
                        in_stock = not ("out of stock" in card_text_low or "sold out" in card_text_low)

                        if top_category == "groceries":
                            sub_category = refine_grocery_sub_category(title, default_sub)
                            brand = extract_grocery_brand(title)
                            attrs = {"noon_category": sub_category}
                            attrs.update(parse_grocery_packaging(title))
                        else:
                            sub_category = _refine_sub_category(title, top_category, default_sub)
                            brand = _extract_brand(title)
                            attrs = _extract_specs(title, top_category, sub_category)

                        snap = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": sku,
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
                        if snap.external_id in seen_ids:
                            continue
                        seen_ids.add(snap.external_id)
                        snapshots.append(snap)
                        cat_collected += 1
                        page_added += 1
                        if len(snapshots) >= target_limit or cat_collected >= per_cat_cap:
                            break

                    if page_added == 0:
                        break

        return snapshots
