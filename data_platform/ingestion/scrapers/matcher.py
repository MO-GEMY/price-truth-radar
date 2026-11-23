"""
Deterministic Cross-Store Canonical Product Matcher for Price Truth Radar.

Computes normalized product fingerprints across Egyptian electronics stores
(`sigma`, `2b`, `btech`, etc.) using brand, product category, model identifiers,
RAM, and storage. Only assigns `canonical_product_key` when the same product
appears across `>= 2` distinct stores (with a sanity price-ratio guard to
prevent false accessory-vs-device matches).
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from .base import RawProductSnapshot, normalize_snake_slug
from .bilingual import normalize_arabic, translate_arabic_retail_terms
from .groceries import (
    compute_grocery_barcode_key,
    compute_grocery_candidate_key,
    compute_grocery_size_key,
    compute_grocery_type_key,
    extract_grocery_brand,
)
from .matcher_verticals import (
    compute_footwear_keys,
    compute_health_beauty_key,
    effective_category,
    extract_footwear_features,
    extract_health_beauty_features,
    is_accessory_listing,
    is_collapsed_multiprice_variant,
    is_footwear_record,
    resolve_footwear_brand,
    resolve_hb_brand,
)
from .units import parse_unit_spec, units_conflict

# Brands normalized to canonical lowercase slugs
_BRAND_ALIASES: dict[str, str] = {
    "hp": "hp",
    "hewlett-packard": "hp",
    "asus": "asus",
    "lenovo": "lenovo",
    "dell": "dell",
    "acer": "acer",
    "msi": "msi",
    "apple": "apple",
    "samsung": "samsung",
    "xiaomi": "xiaomi",
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "oppo": "oppo",
    "realme": "realme",
    "honor": "honor",
    "huawei": "huawei",
    "infinix": "infinix",
    "tecno": "tecno",
    "vivo": "vivo",
    "nokia": "nokia",
    "motorola": "motorola",
    "lg": "lg",
    "sony": "sony",
    "aoc": "aoc",
    "gigabyte": "gigabyte",
    "logitech": "logitech",
    "razer": "razer",
    "redragon": "redragon",
    "hyperx": "hyperx",
    "anker": "anker",
    "jbl": "jbl",
    "crucial": "crucial",
    "sandisk": "sandisk",
    "western digital": "wd",
    "wd": "wd",
    "kingston": "kingston",
    "intel": "intel",
    "amd": "amd",
    "toshiba": "toshiba",
    "sharp": "sharp",
    "tornado": "tornado",
    "fresh": "fresh",
    "zanussi": "zanussi",
    "beko": "beko",
    "bosch": "bosch",
    "haier": "haier",
    "midea": "midea",
    "carrier": "carrier",
    "unionaire": "unionaire",
    "kiriazi": "kiriazi",
    "white whale": "white_whale",
    "white point": "white_point",
    "electrolux": "electrolux",
    "ariston": "ariston",
    "indesit": "indesit",
    "hoover": "hoover",
    "kenwood": "kenwood",
    "braun": "braun",
    "philips": "philips",
    "tefal": "tefal",
    "moulinex": "moulinex",
    "black+decker": "black_decker",
    "black & decker": "black_decker",
    "de'longhi": "delonghi",
    "delonghi": "delonghi",
    "nespresso": "nespresso",
    "tcl": "tcl",
    "hisense": "hisense",
    "ultra": "ultra",
    "olympic": "olympic",
    "olympic electric": "olympic",
    "kieslect": "kieslect",
    "la germania": "la_germania",
    "la_germania": "la_germania",
    # Bilingual Arabic brand aliases (normalized)
    "سامسونج": "samsung",
    "ابل": "apple",
    "ايفون": "apple",
    "ال جي": "lg",
    "توشيبا": "toshiba",
    "شارب": "sharp",
    "تورنيدو": "tornado",
    "فريش": "fresh",
    "بوش": "bosch",
    "بيكو": "beko",
    "زانوسي": "zanussi",
    "كاريير": "carrier",
    "ميديا": "midea",
    "يونيون اير": "unionaire",
    "كريازي": "kiriazi",
    "هوفير": "hoover",
    "اريستون": "ariston",
    "اندست": "indesit",
    "وايت بوينت": "white_point",
    "وايت ويل": "white_whale",
    "لا جيرمانيا": "la_germania",
    "كينوود": "kenwood",
    "براون": "braun",
    "فيليبس": "philips",
    "تيفال": "tefal",
    "مولينكس": "moulinex",
    "هاير": "haier",
    "شاومي": "xiaomi",
    "ريدمي": "xiaomi",
    "اوبو": "oppo",
    "ريلمي": "realme",
    "انفينكس": "infinix",
    "تكنو": "tecno",
    "هواوي": "huawei",
    "هونر": "honor",
    "لينوفو": "lenovo",
    "ديل": "dell",
    "اتش بي": "hp",
    "اسوس": "asus",
    "ايسر": "acer",
    "سوني": "sony",
    # Expanded Egyptian Home Appliances, Small Appliances & Personal Care Brands
    "sokany": "sokany",
    "سوكاني": "sokany",
    "mienta": "mienta",
    "مينتا": "mienta",
    "ariete": "ariete",
    "ارييتي": "ariete",
    "tank": "tank",
    "تانك": "tank",
    "ido": "ido",
    "ايدو": "ido",
    "ata": "ata",
    "jac": "jac",
    "جاك": "jac",
    "panasonic": "panasonic",
    "باناسونيك": "panasonic",
    "sonai": "sonai",
    "سوناي": "sonai",
    "korkmaz": "korkmaz",
    "gastroback": "gastroback",
    "sencor": "sencor",
    "rowenta": "rowenta",
    "karcher": "karcher",
    "rush brush": "rush_brush",
    "رش برش": "rush_brush",
    "babyliss": "babyliss",
    "بيبي ليس": "babyliss",
    "remington": "remington",
    "siemens": "siemens",
    "whirlpool": "whirlpool",
    "frigidaire": "frigidaire",
    "gorenje": "gorenje",
    "candy": "candy",
    "skyworth": "skyworth",
    "syinix": "syinix",
    "contex": "contex",
    "black and decker": "black_decker",
    "بلاك اند ديكر": "black_decker",
    "braun home appliances": "braun",
    # Expanded PC, Gaming, Peripherals, Networking, Audio & Accessories Brands
    "corsair": "corsair",
    "steelseries": "steelseries",
    "cooler master": "cooler_master",
    "coolermaster": "cooler_master",
    "deepcool": "deepcool",
    "nzxt": "nzxt",
    "thermaltake": "thermaltake",
    "be quiet": "be_quiet",
    "be quiet!": "be_quiet",
    "evga": "evga",
    "seasonic": "seasonic",
    "antec": "antec",
    "aerocool": "aerocool",
    "xigmatek": "xigmatek",
    "cougar": "cougar",
    "lian li": "lian_li",
    "lian-li": "lian_li",
    "id-cooling": "id_cooling",
    "id cooling": "id_cooling",
    "arctic": "arctic",
    "noctua": "noctua",
    "thermalright": "thermalright",
    "fractal design": "fractal",
    "montech": "montech",
    "phanteks": "phanteks",
    "hyte": "hyte",
    "galax": "galax",
    "palit": "palit",
    "zotac": "zotac",
    "pny": "pny",
    "sapphire": "sapphire",
    "powercolor": "powercolor",
    "xfx": "xfx",
    "asrock": "asrock",
    "biostar": "biostar",
    "benq": "benq",
    "viewsonic": "viewsonic",
    "iiyama": "iiyama",
    "tp-link": "tp_link",
    "tp link": "tp_link",
    "tplink": "tp_link",
    "d-link": "d_link",
    "d link": "d_link",
    "mikrotik": "mikrotik",
    "ubiquiti": "ubiquiti",
    "mercusys": "mercusys",
    "tenda": "tenda",
    "hikvision": "hikvision",
    "ezviz": "ezviz",
    "imou": "imou",
    "epson": "epson",
    "canon": "canon",
    "brother": "brother",
    "lexmark": "lexmark",
    "gopro": "gopro",
    "dji": "dji",
    "garmin": "garmin",
    "amazfit": "amazfit",
    "mibro": "mibro",
    "haylou": "haylou",
    "qcy": "qcy",
    "soundpeats": "soundpeats",
    "edifier": "edifier",
    "marshall": "marshall",
    "bose": "bose",
    "beats": "beats",
    "sennheiser": "sennheiser",
    "jabra": "jabra",
    "soundcore": "soundcore",
    "oraimo": "oraimo",
    "ugreen": "ugreen",
    "baseus": "baseus",
    "joyroom": "joyroom",
    "remax": "remax",
    "hoco": "hoco",
    "ldnio": "ldnio",
    "belkin": "belkin",
    "promate": "promate",
    "wiwu": "wiwu",
    "porodo": "porodo",
    "green lion": "green_lion",
    "lenyes": "lenyes",
    "fantech": "fantech",
    "marvo": "marvo",
    "bloody": "bloody",
    "a4tech": "a4tech",
    "rapoo": "rapoo",
    "havit": "havit",
    "ajazz": "ajazz",
    "attack shark": "attack_shark",
    "aula": "aula",
    "royal kludge": "royal_kludge",
    "keychron": "keychron",
    "akko": "akko",
    "glorious": "glorious",
    "elgato": "elgato",
    "fifine": "fifine",
    "boya": "boya",
    "maono": "maono",
    "lexar": "lexar",
    "adata": "adata",
    "xpg": "xpg",
    "teamgroup": "teamgroup",
    "team group": "teamgroup",
    "patriot": "patriot",
    "apacer": "apacer",
    "hiksemi": "hiksemi",
    "transcend": "transcend",
    "seagate": "seagate",
    "sk hynix": "sk_hynix",
    "kioxia": "kioxia",
    "g.skill": "gskill",
    "gskill": "gskill",
    "netac": "netac",
    "twinmos": "twinmos",
    "silicon power": "silicon_power",
    "apc": "apc",
    "schneider": "schneider",
    "nintendo": "nintendo",
    "xbox": "xbox",
    "playstation": "playstation",
    "logitech g": "logitech",
    "hp inc": "hp",
}

_STORE_SUFFIX_NOISE_RE = re.compile(
    r"(?:"
    r"\|\s*(?:tax\s*paid|no\s*tax|official\s*warranty|local\s*warranty|international\s*warranty|"
    r"\d+\s*years?\s*(?:official\s*|local\s*|manufacturer\s*)?warranty|dual[\s-]?sim|single[\s-]?sim|"
    r"5g|4g|lte|unlocked|middle\s*east\s*version|international\s*version|global\s*version|egypt\s*version|"
    r"uae\s*version|gcc\s*version|ksa\s*version|free\s*shipping|express)[^|]*|"
    r"[\(\[\-–—]\s*(?:international\s*version|middle\s*east\s*version|global\s*version|"
    r"uae\s*version|egypt\s*version|gcc\s*version|local\s*version|tax\s*paid|official\s*warranty|"
    r"local\s*warranty|\d+\s*years?\s*(?:official\s*|local\s*)?warranty(?:\s*/\s*local\s*version)?)[\)\]]?"
    r")",
    re.I,
)

_SLASH_RAM_STORAGE_RE = re.compile(r"\b(\d{1,2})\s*(?:gb)?\s*[+/]\s*(64|128|256|512|1024)\s*gb\b", re.I)
_SLASH_STORAGE_RAM_RE = re.compile(r"\b(64|128|256|512|1024)\s*(?:gb)?\s*[+/]\s*(\d{1,2})\s*gb?\b", re.I)
_PHONE_SPEC_NOISE_RE = re.compile(
    r"(?:\b\d(?:\.\d{1,2})?\s*(?:\"|''|-?\s*inch(?:es)?)\b|"
    r"\b\d{2,3}\s*mp\b|"
    r"\b\d{4,5}\s*mah\b|"
    r"\b\d{2,3}\s*w\b|"
    r"\b\d{2,3}\s*hz\b)",
    re.I,
)


def _strip_marketplace_noise(title: str) -> str:
    """Strip Amazon pipe suffixes, Noon/Jumia version tags, normalize Arabic & translate retail terms."""
    # Separate glued Arabic + ASCII/digit runs (e.g. `موديلSK-16052` -> `موديل SK-16052`)
    spaced = re.sub(r"([\u0600-\u06FF])([A-Za-z0-9])", r"\1 \2", title or "")
    spaced = re.sub(r"([A-Za-z0-9])([\u0600-\u06FF])", r"\1 \2", spaced)
    cleaned = translate_arabic_retail_terms(spaced)
    cleaned = re.sub(r"[\u200b\u200c\u200d®™]", "", cleaned)
    cleaned = _STORE_SUFFIX_NOISE_RE.sub(" ", cleaned)
    # Remove any remaining trailing "| ..." marketplace marketing clauses after the core title
    if "|" in cleaned:
        first_seg = cleaned.split("|", 1)[0].strip()
        if len(first_seg) >= 12:
            cleaned = first_seg
    return re.sub(r"\s+", " ", cleaned).strip()


_PHONE_NOISE_RE = re.compile(
    r"\b("
    r"pre[\s-]?order|dual[\s-]?sim|single[\s-]?sim|sim|esim|"
    r"5g|4g|lte|nfc|wifi|wi[\s-]?fi|bluetooth|gps|"
    r"global\s+version|local\s+version|middle\s+east\s+version|international\s+version|official\s+warranty|local\s+warranty|international\s+warranty|warranty|egypt|"
    r"android|ios|smartphone|mobile\s+phone|cell\s*phone|mobile|phone|tablet|ram|rom|storage|internal|memory|"
    r"display|screen|amoled|super\s+amoled|oled|lcd|ips|fhd\+?|hd\+?|camera|battery|ois|ip\d{2}|official\s+store|"
    r"os\s+upgrades|os\s+upgrade|upgrades|upgrade|"
    r"\d{1,3}\s*x\b|"
    r"new|sealed|original|edition|unlocked|with|free|gift"
    r")\b",
    re.I,
)

# Common multi-word & single-word finish/color names stripped from model cores
_COLOR_WORDS: frozenset[str] = frozenset(
    {
        "black",
        "white",
        "gray",
        "grey",
        "blue",
        "red",
        "green",
        "silver",
        "gold",
        "pink",
        "purple",
        "violet",
        "orange",
        "yellow",
        "brown",
        "beige",
        "bronze",
        "copper",
        "cream",
        "coral",
        "cyan",
        "teal",
        "mint",
        "olive",
        "navy",
        "indigo",
        "lavender",
        "lilac",
        "burgundy",
        "crimson",
        "emerald",
        "graphite",
        "titanium",
        "platinum",
        "charcoal",
        "obsidian",
        "onyx",
        "pearl",
        "ivory",
        "champagne",
        "midnight",
        "starlight",
        "space",
        "cosmic",
        "aurora",
        "cypress",
        "master",
        "shadow",
        "ocean",
        "polaris",
        "twilight",
        "cobalt",
        "pop",
        "sunlike",
        "dawn",
        "cloud",
        "blush",
        "satin",
        "pistachio",
        "mocha",
        "sapphire",
        "parrot",
        "air",
        "ice",
        "dark",
        "light",
        "deep",
        "bright",
        "matte",
        "glossy",
        "metallic",
        "natural",
        "desert",
        "phantom",
        "awesome",
        "mystic",
        "starry",
        "glow",
        "frost",
        "sand",
        "stone",
        "slate",
        "forest",
        "arctic",
        "gentle",
        "mica",
        "luna",
        "eclipse",
        "storm",
        "iceblue",
        "darkblue",
        "lightblue",
        "skyblue",
        "navyblue",
        "rosegold",
        "spacegray",
        "spacegrey",
        "midnightblack",
        "phantomblack",
        "obsidianblack",
        "large",
        "small",
        "medium",
        "xl",
        "xxl",
    }
)

_CAPACITY_TOKEN_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(tb|gb)\b(?:\s*(?:ram|rom|ssd|hdd|nvme|m\.2|ddr[345]|lpddr[45]x?|storage|internal))?",
    re.I,
)
_GLUED_LETTER_DIGIT_RE = re.compile(r"\b([a-z]{3,})(\d+[a-z]?)\b", re.I)
_CPU_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bapple\s+(m[1-5](?:\s+(?:pro|max|ultra))?)\b", re.I), ""),
    (re.compile(r"\b(m[1-5](?:\s+(?:pro|max|ultra))?)\s+chip\b", re.I), ""),
    (re.compile(r"\b(?:core\s+)?ultra\s+([3579])[\s-]+(\d{3}[a-z]{0,2})\b", re.I), "ultra"),
    (re.compile(r"\b(?:core\s+)?(i[3579])[\s-]+(\d{4,5}[a-z]{0,2})\b", re.I), ""),
    (re.compile(r"\bcore\s+([357])[\s-]+(\d{3}[a-z]?)\b", re.I), "core"),
    (re.compile(r"\bryzen\s+([3579])[\s-]+(\d{4}[a-z]{0,2})\b", re.I), "r"),
]
_GPU_RE = re.compile(r"\b((?:rtx|gtx|rx)\s*\d{3,4}(?:\s*(?:ti|super|xt))?)\b", re.I)
_LAPTOP_CHASSIS_RE = re.compile(
    r"\b("
    r"1[34567][a-z]{2,4}\d{1,2}|"
    r"[a-z]\d{3,4}[a-z]{1,3}(?:-[a-z0-9]{4,7})?|"
    r"fa\d{3,4}[a-z]{2}|"
    r"fx\d{3,4}[a-z]{2}|"
    r"an\d{3}-\d{2}|"
    r"g\d{3}[a-z]{2}|"
    r"8[1234][a-z0-9]{2,8}|"
    r"m[a-z]\d[a-z]\d"
    r")\b",
    re.I,
)
_GENERIC_MODEL_CODE_RE = re.compile(r"\b([a-z]{1,4}[-]?\d{2,5}[a-z0-9-]{0,6})\b", re.I)
# Loose pattern for appliance part numbers that mix letters+digits from the
# first character (M1SEFT-12CRN8F-Q8, KHEFT12N, 7MD68A, 50C350RP) — the strict
# regex above requires 2+ digits immediately after the letters and misses these.
_LOOSE_MODEL_CODE_RE = re.compile(r"\b([a-z]{0,6}[-]?\d{1,6}[a-z0-9-]{0,18})\b", re.I)
_SCREEN_INCH_RE = re.compile(r"\b(\d{2}(?:\.\d)?)\s*(?:\"|-?\s*inch)\b", re.I)

# ---------------------------------------------------------------------------
# Store taxonomies disagree constantly (the same Logitech mouse is `gaming` at
# 2B and `peripherals` at Sigma; an AIO cooler is `cooling` at one store and
# `monitors` at another). Embedding the raw sub_category in the match key
# therefore splits identical products across stores. We instead collapse
# sub_category slugs into canonical *families* and rely on brand + model code
# + strict variant guards for precision.
# ---------------------------------------------------------------------------
_SUBCATEGORY_FAMILY: dict[str, str] = {
    # Electronics families
    "smartphones": "smartphone",
    "mobiles": "smartphone",
    "mobile_phones": "smartphone",
    "phones": "smartphone",
    "tablets": "tablet",
    "laptops": "laptop",
    "notebooks": "laptop",
    "monitors": "monitor",
    "tvs": "tv",
    "smart_tvs": "tv",
    "headphones": "audio",
    "earphones": "audio",
    "earbuds": "audio",
    "speakers": "audio",
    "soundbars": "audio",
    "audio": "audio",
    "gaming": "gaming_peripherals",
    "peripherals": "gaming_peripherals",
    "mouse": "gaming_peripherals",
    "mice": "gaming_peripherals",
    "keyboards": "gaming_peripherals",
    "mousepads": "gaming_peripherals",
    "cooling": "cooling",
    "gpus": "gpu",
    "graphics_cards": "gpu",
    "cpus": "cpu",
    "processors": "cpu",
    "motherboards": "motherboard",
    "psus": "psu",
    "power_supplies": "psu",
    "cases": "pc_case",
    "storage": "storage",
    "memory": "storage",
    "ram": "storage",
    "printers": "printer",
    "printer": "printer",
    "scanners": "printer",
    "cameras": "camera",
    "networking": "networking",
    "routers": "networking",
    "gaming_consoles": "console",
    "consoles": "console",
    "accessories": "accessories",
    "cables": "accessories",
    "chargers": "accessories",
    "wearables": "wearable",
    "smart_watches": "wearable",
    # Home-appliance families
    "air_conditioners": "air_conditioner",
    "split_air_conditioners": "air_conditioner",
    "washing_machines": "washing_machine",
    "dishwashers": "dishwasher",
    "refrigerators": "refrigerator",
    "freezers": "refrigerator",
    "cookers": "cooker",
    "ovens": "cooker",
    "microwaves": "microwave",
    "vacuums": "vacuum",
    "water_heaters": "water_heater",
    "kitchen_appliances": "small_kitchen",
    "blenders": "small_kitchen",
    "mixers": "small_kitchen",
    "toasters": "small_kitchen",
    "large_appliances": "large_appliance",
    "small_appliances": "small_appliance",
    "home_appliances": "home_appliance",
}

# Families whose model numbers embed the screen size (e.g. Toshiba `50C350RP`,
# LG `65NU830B6LA`) — the size digits must be stripped before comparison and
# re-attached as an explicit inch guard.
_SIZE_EMBEDDED_FAMILIES = {"tv", "monitor"}

# Families that get explicit capacity/power guards so a 1.5 HP AC never merges
# with a 2.25 HP unit, and an 8 kg washer never merges with a 6 kg one.
_HP_BTU_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:hp|horsepower|h\.p\.|حصان)\b", re.I)
_BTU_RE = re.compile(r"\b(\d{4,6})\s*btu\b", re.I)
_CAPACITY_KG_RE = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*(?:kg|kgs|كجم|كيلو)\b", re.I)
_CAPACITY_L_RE = re.compile(r"\b(\d{1,3}(?:\.\d)?)\s*(?:liter|liters|litre|litres|l|لتر)\b", re.I)


def _normalize_model_code(raw_code: str) -> str:
    """Strip separators from a manufacturer model code and canonicalize digits.

    `M1SEFT-12CRN8F-Q8` and `M1SEFT12CRN8FQ8` must compare equal; and within
    digit-heavy part numbers, `MOSEFT` and `M0SEFT` (letter-O vs zero) are the
    same code on Egyptian retail sites.
    """
    code = re.sub(r"[^a-zA-Z0-9]", "", raw_code).lower()
    digits = sum(c.isdigit() for c in code)
    if digits >= 2:
        code = code.replace("o", "0").replace("O", "0")
    return code


def _family_of(sub_category: str) -> str:
    sub = sub_category.strip().lower()
    return _SUBCATEGORY_FAMILY.get(sub, normalize_snake_slug(sub, fallback="other", max_len=40))


def _tv_monitor_size(title: str, codes_norm: list[str]) -> Optional[int]:
    """Screen size in inches: explicit `NN Inch` token, else digits embedded at
    the start of a model code (`50C350RP`, `65NU830B6LA`)."""
    m = _SCREEN_INCH_RE.search(title)
    if m:
        size = int(float(m.group(1)))
        if 15 <= size <= 110:
            return size
    for code in codes_norm:
        m = re.match(r"(\d{2})([a-z]{2,})", code)
        if m:
            size = int(m.group(1))
            if 15 <= size <= 110:
                return size
    return None


def _strip_leading_size(code_norm: str, size: Optional[int]) -> str:
    """Remove the screen-size digits embedded at the front of a TV model code."""
    if size is not None and code_norm.startswith(str(size)):
        return code_norm[len(str(size)):]
    return code_norm


def _variant_token_after(cleaned_title: str, code_raw: str) -> Optional[str]:
    """Product-line sub-variant word directly after the model code (G502 **HERO** vs
    G502 **X** Plus, FX360 **LCD** vs FX360 **TD**). Restricted strictly to canonical
    sub-variant markers so marketing nicknames ("TRIDENT", "FORGE", "HYLAS") don't
    split identical SKUs across stores."""
    idx = cleaned_title.lower().find(code_raw.lower())
    if idx == -1:
        return None
    tail = cleaned_title[idx + len(code_raw):]
    line_words = {
        "pro", "max", "plus", "x", "ultra", "hero", "lite", "note",
        "mini", "se", "fe", "ti", "neo", "gt", "lcd", "td", "super",
        "xt", "air", "fold", "flip", "slim", "nc", "anc",
    }
    for tok in re.split(r"[^A-Za-z0-9]+", tail):
        if not tok:
            continue
        if any(c.isdigit() for c in tok):  # part numbers (7MD68A) aren't variants
            continue
        low = tok.lower()
        if low in line_words:
            return low
        return None  # first non-qualifying word ends the variant window
    return None


@dataclass
class MatchSummary:
    matched_groups: int
    matched_products: int
    group_details: dict[str, list[tuple[str, float, str]]]
    tier1_groups: int = 0
    tier2_groups: int = 0
    tier3_groups: int = 0
    grocery_groups: int = 0
    health_beauty_groups: int = 0
    footwear_groups: int = 0


_STORE_PLACEHOLDER_BRANDS: frozenset[str] = frozenset({
    "unknown", "generic", "other", "none", "null", "brand", "unbranded", "my_store",
    "kaufen_egypt_online_store", "shamy_stores", "shamystores", "el_araby_group",
    "ehab_center", "btech", "raneen", "rayashop", "compumarts", "sigma",
    "hardware_market", "smartkoshk", "dream2000", "dubaiphone", "ennap",
    "up_to_date_eg", "ahw_store", "alfrensia", "kimostore", "myxprs",
})


def _canonical_brand(brand: str, title: str = "") -> str:
    cleaned = normalize_arabic(brand or "").strip().lower()
    if cleaned in _BRAND_ALIASES:
        return _BRAND_ALIASES[cleaned]
    slug = normalize_snake_slug(cleaned, fallback="unknown", max_len=32)
    if slug != "unknown" and slug in _BRAND_ALIASES:
        return _BRAND_ALIASES[slug]
    if slug not in _STORE_PLACEHOLDER_BRANDS and not re.search(r"[\u0600-\u06FF]", cleaned):
        return slug
    # Fallback: infer known brand from bilingual-normalized title (e.g. Arabic titles or store placeholder brand)
    if title:
        norm_title = normalize_arabic(translate_arabic_retail_terms(title)).lower()
        for alias, canon in _BRAND_ALIASES.items():
            if re.search(r"[\u0600-\u06FF]", alias):
                if re.search(rf"(?:^|[^a-z\u0621-\u064a]){re.escape(alias)}(?=$|[^a-z\u0621-\u064a])", norm_title):
                    return canon
            elif re.search(rf"\b{re.escape(alias)}\b", norm_title):
                return canon
    return "unknown" if slug in _STORE_PLACEHOLDER_BRANDS else slug


def _extract_ram_storage(record: RawProductSnapshot) -> tuple[Optional[int], Optional[int]]:
    """Extract (ram_gb, storage_gb) from attributes_json and/or product_title."""
    attrs = record.attributes_json or {}
    ram_gb = attrs.get("ram_gb") if isinstance(attrs.get("ram_gb"), int) else None
    storage_gb = attrs.get("storage_gb") if isinstance(attrs.get("storage_gb"), int) else None

    if ram_gb is not None and storage_gb is not None:
        return ram_gb, storage_gb

    # Handle compact "8+256GB" / "8/256GB" (Amazon/Noon) or "256GB/8GB" / "256/8GB" (Jumia)
    if m := _SLASH_RAM_STORAGE_RE.search(record.product_title):
        if ram_gb is None:
            ram_gb = int(m.group(1))
        if storage_gb is None:
            storage_gb = int(m.group(2))
        return ram_gb, storage_gb

    if m := _SLASH_STORAGE_RAM_RE.search(record.product_title):
        if storage_gb is None:
            storage_gb = int(m.group(1))
        if ram_gb is None:
            ram_gb = int(m.group(2))
        return ram_gb, storage_gb

    # Parse all GB/TB tokens from title; smaller value (<= 24 for phones, <= 64 for laptops) is RAM, larger is storage
    gb_vals: list[int] = []
    for num_str, unit in _CAPACITY_TOKEN_RE.findall(record.product_title):
        val = float(num_str)
        if unit.lower() == "tb":
            gb = int(round(val * 1024))
        else:
            gb = int(round(val))
        if gb > 0:
            gb_vals.append(gb)

    if gb_vals:
        uniq_sorted = sorted(set(gb_vals))
        if len(uniq_sorted) >= 2:
            if ram_gb is None and uniq_sorted[0] <= 64:
                ram_gb = uniq_sorted[0]
            if storage_gb is None and uniq_sorted[-1] >= 32:
                storage_gb = uniq_sorted[-1]
        elif len(uniq_sorted) == 1:
            if storage_gb is None and uniq_sorted[0] >= 32:
                storage_gb = uniq_sorted[0]
            elif ram_gb is None and uniq_sorted[0] <= 32:
                ram_gb = uniq_sorted[0]

    return ram_gb, storage_gb


def _smartphone_fingerprint(record: RawProductSnapshot, brand: str) -> Optional[str]:
    ram_gb, storage_gb = _extract_ram_storage(record)
    if storage_gb is None:
        return None

    text = _strip_marketplace_noise(record.product_title)
    # Strip trailing "- Color" segment when clearly a finish/color suffix
    text = re.sub(r"\s*[-–—]\s*[A-Za-z][A-Za-z\s]{1,28}$", lambda m: (
        "" if all(w.lower() in _COLOR_WORDS for w in m.group(0).lstrip("-–— ").split()) else m.group(0)
    ), text)

    # Remove capacity specs, screen/camera/battery spec noise, and marketing noise
    text = _SLASH_RAM_STORAGE_RE.sub(" ", text)
    text = _SLASH_STORAGE_RAM_RE.sub(" ", text)
    text = _PHONE_SPEC_NOISE_RE.sub(" ", text)
    text = _CAPACITY_TOKEN_RE.sub(" ", text)
    text = text.replace("+", " plus ")
    text = re.sub(r"[\u200b\u200c\u200d®™]", "", text)
    text = _GLUED_LETTER_DIGIT_RE.sub(r"\1 \2", text)
    text = _PHONE_NOISE_RE.sub(" ", text)
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)

    # Strip Apple regional MPN suffixes (e.g. MYEC3ZD/A, MFYN4AF/A) and finish words
    # so iPhone listings match across stores regardless of regional SKU code.
    if brand == "apple":
        text = re.sub(r"\b[a-z]{1,2}[a-z0-9]{4,7}(?:/[a-z]{1,2})?\b", lambda m: (
            " " if (any(c.isdigit() for c in m.group(0)) and len(m.group(0)) >= 6 and not m.group(0).lower().startswith("iphone")) else m.group(0)
        ), text, flags=re.I)

    tokens = [tok.lower() for tok in text.split() if tok]
    # Remove leading brand token(s)
    brand_tokens = set(brand.split("_"))
    apple_extra_colors = {"ultramarine", "sage", "teal", "desert", "natural", "soft", "lavender", "mist"} if brand == "apple" else set()
    filtered: list[str] = []
    for tok in tokens:
        if not filtered and tok in brand_tokens:
            continue
        if tok in _COLOR_WORDS or tok in apple_extra_colors:
            continue
        if tok.isdigit() and int(tok) in {ram_gb, storage_gb}:
            continue
        if brand == "apple" and tok == "a" and filtered:
            continue
        filtered.append(tok)

    if not filtered:
        return None

    # Keep concise model core (at most 5 tokens)
    model_slug = "_".join(filtered[:5])
    if not model_slug or not any(ch.isdigit() for ch in model_slug):
        return None

    parts = [brand, model_slug, f"{storage_gb}gb"]
    # Apple iPhone RAM is fixed per model (and omitted by half of Egyptian stores),
    # whereas Android phones ship multiple RAM configs (4GB vs 6GB vs 8GB) for the same storage.
    if ram_gb is not None and brand != "apple":
        parts.append(f"{ram_gb}gb")
    return normalize_snake_slug("_".join(parts), max_len=160)


def _laptop_fingerprint(record: RawProductSnapshot, brand: str) -> Optional[str]:
    ram_gb, storage_gb = _extract_ram_storage(record)
    title = _strip_marketplace_noise(record.product_title)

    # Extract CPU
    cpu_tag: Optional[str] = None
    for pat, prefix in _CPU_PATTERNS:
        m = pat.search(title)
        if m:
            cpu_tag = f"{prefix}{'_'.join(g.lower() for g in m.groups() if g)}"
            cpu_tag = normalize_snake_slug(cpu_tag, max_len=32)
            break

    # Extract dedicated GPU if present
    gpu_tag: Optional[str] = None
    if gm := _GPU_RE.search(title):
        gpu_tag = normalize_snake_slug(gm.group(1), max_len=20)

    # Extract specific chassis/model code (or MacBook series)
    model_tag: Optional[str] = None
    if brand == "apple" and "macbook" in title.lower():
        series = "macbook_pro" if "pro" in title.lower() else (
            "macbook_air" if "air" in title.lower() else "macbook"
        )
        screen_m = _SCREEN_INCH_RE.search(title)
        inch = screen_m.group(1).split(".")[0] if screen_m else ""
        model_tag = f"{series}_{inch}" if inch else series
    else:
        chassis_matches = [
            m.group(1).lower()
            for m in _LAPTOP_CHASSIS_RE.finditer(title)
            if not re.match(r"^(?:rtx|gtx|ddr|ssd|usb|fhd|qhd|ips|win)\d*", m.group(1), re.I)
        ]
        if chassis_matches:
            model_tag = normalize_snake_slug(chassis_matches[0], max_len=32)

    if not model_tag or not cpu_tag:
        return None

    parts = [brand, model_tag, cpu_tag]
    if gpu_tag:
        parts.append(gpu_tag)
    if storage_gb is not None:
        parts.append(f"{storage_gb}gb")
    if ram_gb is not None:
        parts.append(f"{ram_gb}gb")
    return normalize_snake_slug("_".join(parts), max_len=160)


def _collect_model_codes(cleaned_title: str, min_len: int, loose: bool = False) -> tuple[list[str], Optional[str]]:
    """Normalized model codes in title order + the raw text of the first one.

    Normalization strips separators (`LS24CG552`, `LS24-CG-552` and
    `ls24cg552` compare equal) and canonicalizes letter-O vs zero inside
    digit-heavy part numbers (`MOSEFT` == `M0SEFT`). `loose=True` adds the
    appliance-grade pattern that captures codes like `M1SEFT…`/`7MD68A`
    whose letter run contains a single digit.
    """
    codes_norm: list[str] = []
    first_raw: Optional[str] = None
    patterns = [_GENERIC_MODEL_CODE_RE, _LOOSE_MODEL_CODE_RE] if loose else [_GENERIC_MODEL_CODE_RE]
    seen_spans: set[tuple[int, int]] = set()
    for pattern in patterns:
        for m in pattern.finditer(cleaned_title):
            span = (m.start(), m.end())
            if any(s <= span[0] < e or s < span[1] <= e for s, e in seen_spans):
                continue
            raw = m.group(1)
            norm = _normalize_model_code(raw)
            if len(norm) < min_len:
                continue
            if not (any(c.isalpha() for c in norm) and any(c.isdigit() for c in norm)):
                continue
            if re.fullmatch(r"\d+(?:inch|in|ml|g|kg|w|hz|mm|cm)", norm):
                continue  # size/unit artifact ("55-inch" -> "55inch"), not a model code
            seen_spans.add(span)
            if norm not in codes_norm:
                codes_norm.append(norm)
            if first_raw is None:
                first_raw = raw
    return codes_norm, first_raw


def _electronics_generic_fingerprint(record: RawProductSnapshot, brand: str) -> Optional[str]:
    """Model-code based fingerprint for monitors, TVs, headphones, storage,
    peripherals, printers — with store-taxonomy families and strict guards."""
    title = _strip_marketplace_noise(record.product_title)
    # Remove specs/units that look like alphanumeric codes (e.g. 240hz, 512gb, 1tb, 1ms, 60w, usb3)
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?[\s\-]*(?:gb|tb|mb|mhz|ghz|hz|ms|mm|cm|inch|w|v|mah|dpi|fps|bit|gen\d?|usb\d?)\b",
        " ",
        title,
        flags=re.I,
    )
    cleaned = re.sub(
        r"\b(?:ddr[345]|pcie\d?|sata\d?|nvme|fhd|qhd|uhd|4k|8k|rgb|argb|pwm|atx|matx|ips|va|oled|qled|"
        r"hdr\d+\+?|ip\d{2}|wifi\d[a-z]?|bt\d(?:\.\d)?|hdmi\d(?:\.\d)?|usb\d(?:\.\d)?|dp\d(?:\.\d)?|pd\d+|qc\d)\b",
        " ",
        cleaned,
        flags=re.I,
    )

    codes_norm, first_raw = _collect_model_codes(cleaned, min_len=4)
    if not codes_norm:
        return None

    primary = codes_norm[0]
    family = _family_of(record.sub_category)

    # NOTE: the store-specific `sub_category` slug is deliberately NOT part of
    # the key — stores file identical products under different taxonomies
    # (Logitech mouse = `gaming` at 2B but `peripherals` at Sigma; an AIO
    # cooler = `cooling` vs `monitors`). Brand + model code + variant + guards
    # carry the precision instead. The family only drives guard selection.
    parts = [brand, primary]

    # Disambiguate product-line variants sharing a code (Logitech G502 HERO vs
    # G502 X Plus) — only when the title carries a SINGLE model code; multi-code
    # titles (indoor + outdoor AC units) are matched on their primary code.
    if len(codes_norm) == 1:
        variant = _variant_token_after(record.product_title, first_raw) if first_raw else None
        if variant and len(variant) <= 24:
            parts.append(variant)

    # Motherboard chipset sub-model guard: `A520M K V2` != `A520M S2H` != `A520M DS3H`
    if family == "motherboard" or re.search(r"\b(?:motherboard|mainboard|am[45]|lga\s*1[127]\d{2}|m-?atx|micro[\s-]?atx)\b", title, re.I) or re.fullmatch(r"[abhxz]\d{3}m?", primary):
        if first_raw:
            idx_mb = record.product_title.lower().find(first_raw.lower())
            if idx_mb != -1:
                mb_tail = record.product_title[idx_mb + len(first_raw):]
                mb_sub_tokens: list[str] = []
                for tok in re.split(r"[^A-Za-z0-9]+", mb_tail):
                    low_t = tok.lower()
                    if not low_t:
                        continue
                    if low_t in {"ddr4", "ddr5", "am4", "am5", "motherboard", "socket", "micro", "atx", "matx", "rev", "amd", "intel", "black", "white", "gaming"}:
                        break
                    if low_t in {"k", "h", "a", "m", "e", "f", "s2h", "ds3h", "ud", "pro", "plus", "prime", "tuf", "mortar", "tomahawk", "bazooka", "eagle", "aorus", "hdv", "pro4", "steel", "legend", "elite", "wifi", "ax", "ac", "ii", "v2"}:
                        if low_t not in parts and low_t not in mb_sub_tokens:
                            mb_sub_tokens.append(low_t)
                    if len(mb_sub_tokens) >= 2:
                        break
                parts.extend(mb_sub_tokens)

    # Strict size guard for screens (a 50-inch TV is never a 55-inch TV).
    # Applied only when a size is actually present — titles without one are
    # matched on brand + model code alone.
    if family in _SIZE_EMBEDDED_FAMILIES:
        size = _tv_monitor_size(title, codes_norm)
        if size is not None:
            parts = [brand, family, _strip_leading_size(primary, size)]
            parts.append(f"{size}in")

    # Storage capacity stays a strict guard for storage devices.
    _, storage_gb = _extract_ram_storage(record)
    if family == "storage" and storage_gb is not None:
        parts.append(f"{storage_gb}gb")

    return normalize_snake_slug("_".join(parts), max_len=160)


def _appliance_fingerprint(record: RawProductSnapshot, brand: str) -> Optional[str]:
    """Model-code fingerprint for home appliances (ACs, TVs, fridges, washers,
    cookers) with strict capacity/HP/BTU/screen-size variant guards."""
    title = _strip_marketplace_noise(record.product_title)
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?[\s\-]*(?:hp|btu|kg|kgs|liter|liters|litre|litres|l|w|watt|watts|cm|mm|inch|hz|bar|ml|rpm|v|kw)\b",
        " ",
        title,
        flags=re.I,
    )
    cleaned = re.sub(
        r"\b(?:4k|8k|fhd|uhd|qled|oled|led|hdr\d+\+?|ip\d{2}|wifi\d?[a-z]?|wi-fi|smart|inverter|digital|frost|nofrost|bt\d(?:\.\d)?)\b",
        " ",
        cleaned,
        flags=re.I,
    )

    family = _family_of(record.sub_category)
    min_code_len = 4 if family in _SIZE_EMBEDDED_FAMILIES else 5
    codes_norm, first_raw = _collect_model_codes(cleaned, min_len=min_code_len, loose=True)
    if not codes_norm:
        return None

    primary = codes_norm[0]

    # TVs inside home_appliances get the same size-embedded model treatment.
    size: Optional[int] = None
    if family in _SIZE_EMBEDDED_FAMILIES:
        size = _tv_monitor_size(title, codes_norm)
        if size is not None:
            primary = _strip_leading_size(primary, size)

    # Omit store-dependent `family` slug (except size-embedded TVs/monitors) so
    # identical appliances filed under `small_appliances` vs `blenders` vs `home_appliances`
    # match cleanly on exact `(brand, model_code, capacity/HP/inch)`.
    parts = [brand, family, primary] if size is not None else [brand, primary]
    if size is not None:
        parts.append(f"{size}in")

    # Variant token (product-line word right after the code) — single-code
    # titles only, same rationale as the electronics path.
    if len(codes_norm) == 1:
        variant = _variant_token_after(record.product_title, first_raw) if first_raw else None
        if variant and len(variant) <= 24 and variant not in {p.split("_")[-1] for p in parts}:
            parts.append(variant)

    # Strict capacity / power guards — 1.5 HP vs 2.25 HP and 8 kg vs 6 kg are
    # different SKUs, never the same canonical product.
    if family == "air_conditioner" or _HP_BTU_RE.search(title):
        if hm := _HP_BTU_RE.search(title):
            parts.append(f"{hm.group(1)}hp")
        elif bm := _BTU_RE.search(title):
            parts.append(f"{bm.group(1)}btu")
    elif family in ("washing_machine", "refrigerator", "dishwasher"):
        if km := _CAPACITY_KG_RE.search(title):
            parts.append(f"{km.group(1)}kg")
        elif lm := _CAPACITY_L_RE.search(title):
            parts.append(f"{lm.group(1)}L")

    return normalize_snake_slug("_".join(parts), max_len=160)


_TITLE_EAN13_RE = re.compile(r"(?:^|[^0-9])(\d{13})(?=$|[^0-9])")


def _valid_ean13(digits: str) -> bool:
    if len(digits) != 13 or not digits.isdigit():
        return False
    # Reject trivial fake IDs AND GS1 in-store variable-weight PLU barcodes (20..29)
    if len(set(digits)) <= 2 or digits.startswith("00000") or digits[0] == "2":
        return False
    total = sum(int(d) * (1 if idx % 2 == 0 else 3) for idx, d in enumerate(digits[:12]))
    return ((10 - (total % 10)) % 10) == int(digits[12])


def _extract_global_ean_key(record: RawProductSnapshot) -> Optional[str]:
    """Return `ean_<13digits>` if a checksum-verified EAN-13 barcode exists in attributes or title."""
    attrs = record.attributes_json or {}
    for k in ("ean", "gtin13", "gtin", "barcode"):
        val = attrs.get(k)
        if val is not None:
            digits = re.sub(r"\D", "", str(val))
            if _valid_ean13(digits):
                cat = effective_category(record)
                prefix = "grocery_gtin" if cat == "groceries" else "ean"
                return f"{prefix}_{digits}"
    for m in _TITLE_EAN13_RE.finditer(record.product_title or ""):
        digits = m.group(1)
        if _valid_ean13(digits):
            cat = effective_category(record)
            prefix = "grocery_gtin" if cat == "groceries" else "ean"
            return f"{prefix}_{digits}"
    return None


def _looks_like_smartphone_or_laptop(record: RawProductSnapshot) -> Optional[str]:
    """Detect smartphones/laptops listed inside appliance stores (e.g. ehab_center)."""
    sub = (record.sub_category or "").strip().lower()
    if sub in ("smartphones", "mobiles", "mobile_phones", "phones", "tablets"):
        return "smartphone"
    if sub in ("laptops", "notebooks"):
        return "laptop"
    low = (record.product_title or "").lower()
    if re.search(r"\b(?:iphone|galaxy\s+[asmz]\d|redmi\s+note|poco\s+[xfmc]\d|honor\s+x\d|oppo\s+[ar]\d|realme\s+\d|infinix\s+(?:hot|note|smart)|tecno\s+(?:spark|camon|pova))\b", low):
        if not is_accessory_listing(record):
            return "smartphone"
    if re.search(r"\b(?:macbook|thinkpad|ideapad|vivobook|zenbook|legion\s+\d|pavilion|elitebook|probook|inspiron|latitude|vostro|nitro\s+\d|aspire\s+\d|victus|omen\s+\d)\b", low):
        if not is_accessory_listing(record):
            return "laptop"
    return None


def compute_candidate_key(record: RawProductSnapshot) -> Optional[str]:
    """Compute a deterministic candidate canonical key across all supported verticals."""
    cat = effective_category(record)
    if cat == "groceries":
        return compute_grocery_candidate_key(record)

    if cat in ("health", "beauty"):
        return compute_health_beauty_key(record)

    if cat in ("fashion", "sports") and is_footwear_record(record):
        style_key, model_key = compute_footwear_keys(record)
        return style_key or model_key

    if cat not in ("electronics", "home_appliances"):
        return None

    brand = _canonical_brand(record.brand, record.product_title)
    if not brand or brand == "unknown":
        return None

    device_hint = _looks_like_smartphone_or_laptop(record)
    if device_hint == "smartphone":
        return _smartphone_fingerprint(record, brand)
    if device_hint == "laptop":
        return _laptop_fingerprint(record, brand)

    if cat == "home_appliances":
        return _appliance_fingerprint(record, brand)

    return _electronics_generic_fingerprint(record, brand)


_COOKER_CM_RE = re.compile(r"\b(50|55|60|80|90|100)\s*cm\b", re.I)
_COOKER_BURNERS_RE = re.compile(r"\b([3456])\s*(?:gas\s+)?burners?\b", re.I)
_DISHWASHER_PLACES_RE = re.compile(r"\b(\d{1,2})\s*(?:place(?:s)?|person(?:s)?|setting(?:s)?)\b", re.I)
_WATTS_RE = re.compile(r"\b(\d{3,4})\s*(?:w|watt|watts)\b", re.I)
_FEET_RE = re.compile(r"\b(\d{1,2})\s*(?:ft|feet|foot)\b", re.I)

_TIER2_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "with", "and", "for", "from", "by", "in", "on", "of", "to", "a", "an",
        "new", "original", "official", "warranty", "egypt", "version", "global", "local",
        "middle", "east", "international", "free", "shipping", "gift", "offer", "deal",
        "smart", "digital", "electric", "automatic", "full", "built", "builtin",
        "inches", "inch", "cm", "mm", "kg", "kgs", "liter", "liters", "litre", "litres",
        "watt", "watts", "hp", "btu", "gb", "tb", "ram", "rom", "ssd", "hdd",
        "tv", "television", "led", "fridge", "refrigerator", "washer", "washing", "machine",
        "cooker", "gas", "air", "conditioner", "split", "dishwasher", "microwave", "vacuum",
        "laptop", "notebook", "smartphone", "mobile", "phone", "tablet", "monitor", "screen",
        "stainless", "steel", "door", "doors", "burner", "burners", "programs", "settings",
        "place", "places", "dual", "sim", "4g", "5g", "lte", "wifi", "bluetooth",
        "inverter", "cooling", "heating", "cool", "heat", "only", "nofrost", "frost",
        "defrost", "top", "front", "load", "oled", "qled", "uhd", "fhd", "hd", "4k", "8k",
    }
) | _COLOR_WORDS


def _extract_spec_block(
    record: RawProductSnapshot,
    brand: str,
    family: str,
    norm_title: str,
) -> Optional[str]:
    """Extract a strict normalized spec signature for Tier-2 / Tier-3 blocking.

    Guarantees mismatched storage/size/tonnage/capacity/width items can never
    enter the same candidate block.
    """
    low = norm_title.lower()
    ram_gb, storage_gb = _extract_ram_storage(record)

    if family in ("smartphone", "tablet"):
        if storage_gb is None:
            return None
        parts = [f"{storage_gb}gb"]
        if ram_gb is not None:
            parts.append(f"{ram_gb}ram")
        return "_".join(parts)

    if family in ("tv", "monitor"):
        codes_norm, _ = _collect_model_codes(low, min_len=4)
        size = _tv_monitor_size(low, codes_norm)
        if size is None:
            return None
        panel = "oled" if "oled" in low else ("qled" if "qled" in low else ("nanocell" if "nanocell" in low else "led"))
        res = "8k" if "8k" in low else ("4k" if ("4k" in low or "uhd" in low) else ("fhd" if ("fhd" in low or "1080" in low) else "hd"))
        return f"{size}in_{panel}_{res}"

    if family == "air_conditioner":
        power = None
        if hm := _HP_BTU_RE.search(low):
            power = f"{hm.group(1)}hp"
        elif bm := _BTU_RE.search(low):
            power = f"{bm.group(1)}btu"
        if not power:
            return None
        inv = "inv" if "inverter" in low else "std"
        mode = "hc" if ("heat" in low or "ساخن" in record.product_title) else "cool"
        return f"{power}_{inv}_{mode}"

    if family == "washing_machine":
        km = _CAPACITY_KG_RE.search(low)
        if not km:
            return None
        load = "top" if "top" in low else ("front" if "front" in low else "std")
        return f"{km.group(1)}kg_{load}"

    if family == "dishwasher":
        pm = _DISHWASHER_PLACES_RE.search(low)
        if not pm:
            return None
        return f"{pm.group(1)}places"

    if family == "refrigerator":
        cap = None
        if lm := _CAPACITY_L_RE.search(low):
            liters = int(round(float(lm.group(1)) / 5.0) * 5)
            cap = f"{liters}l"
        elif fm := _FEET_RE.search(low):
            cap = f"{fm.group(1)}ft"
        if not cap:
            return None
        frost = "nofrost" if ("no frost" in low or "nofrost" in low) else "defrost"
        return f"{cap}_{frost}"

    if family == "cooker":
        cm = _COOKER_CM_RE.search(low)
        bm = _COOKER_BURNERS_RE.search(low)
        if not cm and not bm:
            return None
        parts = []
        if cm:
            parts.append(f"{cm.group(1)}cm")
        if bm:
            parts.append(f"{bm.group(1)}b")
        return "_".join(parts)

    if family == "laptop":
        cpu_tag = None
        for pat, prefix in _CPU_PATTERNS:
            m = pat.search(low)
            if m:
                cpu_tag = normalize_snake_slug(f"{prefix}{'_'.join(g.lower() for g in m.groups() if g)}", max_len=24)
                break
        if not cpu_tag or storage_gb is None:
            return None
        parts = [cpu_tag, f"{storage_gb}gb"]
        if ram_gb is not None:
            parts.append(f"{ram_gb}ram")
        if gm := _GPU_RE.search(low):
            parts.append(normalize_snake_slug(gm.group(1), max_len=16))
        return "_".join(parts)

    if family in ("microwave", "water_heater", "vacuum"):
        if lm := _CAPACITY_L_RE.search(low):
            return f"{int(round(float(lm.group(1))))}l"
        if wm := _WATTS_RE.search(low):
            return f"{wm.group(1)}w"
        return None

    return None


def _core_tokens_for_matching(norm_title: str, brand: str) -> list[str]:
    """Extract informative non-color, non-stopword alphanumeric tokens."""
    brand_parts = set(brand.split("_"))
    raw_tokens = re.findall(r"[a-z0-9]+", norm_title.lower())
    out: list[str] = []
    for tok in raw_tokens:
        if tok in _TIER2_STOPWORDS or tok in brand_parts:
            continue
        if len(tok) < 2:
            continue
        if re.fullmatch(r"\d+(?:gb|tb|inch|in|cm|mm|kg|l|w|hp|hz|mp|mah|btu|ft)", tok):
            continue
        if tok not in out:
            out.append(tok)
    return out


def _series_number_signature(tokens: list[str]) -> frozenset[str]:
    """Critical numeric/alphanumeric series markers that must agree in Tier 2/3."""
    sig: set[str] = set()
    for tok in tokens:
        if any(c.isdigit() for c in tok) and len(tok) >= 2:
            sig.add(_normalize_model_code(tok))
    return frozenset(sig)


def _token_ngram_vector(tokens: list[str]) -> Counter[str]:
    """Build lightweight local token + character 3-gram vector (zero external deps)."""
    vec: Counter[str] = Counter()
    for tok in tokens:
        # Word tokens carry higher weight than character trigrams
        vec[f"w:{tok}"] += 2.0
        if len(tok) >= 3:
            padded = f"^{tok}$"
            for i in range(len(padded) - 2):
                vec[f"g:{padded[i:i+3]}"] += 0.5
    return vec


def _cosine_similarity(v1: Counter[str], v2: Counter[str]) -> float:
    if not v1 or not v2:
        return 0.0
    common = set(v1.keys()) & set(v2.keys())
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    n1 = math.sqrt(sum(val * val for val in v1.values()))
    n2 = math.sqrt(sum(val * val for val in v2.values()))
    if n1 <= 0.0 or n2 <= 0.0:
        return 0.0
    return dot / (n1 * n2)


def _resolve_guard_brand(rec: RawProductSnapshot, eff_cat: str) -> Optional[str]:
    """Resolve canonical brand for cross-store Brand Conflict Blocker."""
    if eff_cat in ("electronics", "home_appliances"):
        b = _canonical_brand(rec.brand, rec.product_title)
        return None if (not b or b == "unknown") else b
    if eff_cat in ("health", "beauty"):
        return resolve_hb_brand(rec)
    if eff_cat in ("fashion", "sports"):
        return resolve_footwear_brand(rec)
    if eff_cat == "groceries":
        b = normalize_snake_slug(extract_grocery_brand(rec.product_title, rec.brand), fallback="unknown", max_len=32)
        return None if (not b or b == "unknown") else b
    return None


def _filter_group_guardrails(
    group: list[RawProductSnapshot],
    *,
    price_ratio_cap: float,
    check_units: bool,
    check_accessory: bool,
) -> list[RawProductSnapshot]:
    """Enforce mandatory anti-false-positive guardrails on every candidate group.

    1. Distinct stores >= 2.
    2. Brand conflict blocker (never mix two conflicting canonical brands).
    3. Accessory vs. Main Product blocker (never mix accessory with main device).
    4. Unit/Quantity conflict blocker (weight/volume/count/pack/dosage must agree).
    5. Price ratio sanity guard with median-based single-outlier pruning for >= 3 stores.
    """
    if len({r.store_name for r in group}) < 2:
        return []

    filtered = list(group)

    # 1. Accessory vs. Main Product separation (electronics & home_appliances)
    if check_accessory:
        acc_flags = [is_accessory_listing(r) for r in filtered]
        if any(acc_flags) and not all(acc_flags):
            # Keep the majority side if it still spans >= 2 distinct stores; else reject
            non_acc = [r for r, flag in zip(filtered, acc_flags) if not flag]
            acc_only = [r for r, flag in zip(filtered, acc_flags) if flag]
            if len({r.store_name for r in non_acc}) >= 2:
                filtered = non_acc
            elif len({r.store_name for r in acc_only}) >= 2:
                filtered = acc_only
            else:
                return []

    # 2. Brand Conflict Blocker
    brand_counts: Counter[str] = Counter()
    rec_brands: list[Optional[str]] = []
    for r in filtered:
        b = _resolve_guard_brand(r, effective_category(r))
        rec_brands.append(b)
        if b:
            brand_counts[b] += 1
    if len(brand_counts) > 1:
        # Keep only the dominant brand if it has >= 2 distinct stores; else hard-reject
        dominant_brand = brand_counts.most_common(1)[0][0]
        dom_recs = [r for r, b in zip(filtered, rec_brands) if b is None or b == dominant_brand]
        if len({r.store_name for r in dom_recs}) >= 2:
            filtered = dom_recs
        else:
            return []

    # 3. Unit / Quantity Conflict Blocker (groceries, health, beauty, pet_care)
    if check_units:
        specs = [
            parse_unit_spec(
                r.product_title,
                variant_label=(r.attributes_json or {}).get("variant_label")
                if isinstance((r.attributes_json or {}).get("variant_label"), str)
                else None,
                attributes=r.attributes_json or {},
            )
            for r in filtered
        ]
        # Verify pairwise unit compatibility; if a single outlier conflicts, drop it
        consistent: list[RawProductSnapshot] = []
        for idx, rec in enumerate(filtered):
            if specs[idx].has_ambiguous_multi_size:
                continue
            conflicts = sum(
                1 for jdx, sp_j in enumerate(specs)
                if jdx != idx and not sp_j.has_ambiguous_multi_size and units_conflict(specs[idx], sp_j)
            )
            if conflicts == 0:
                consistent.append(rec)
        if len({r.store_name for r in consistent}) < 2:
            return []
        filtered = consistent

    # 4. Price Ratio Sanity Guard (with median-based outlier trimming when >= 3 stores)
    prices = [float(r.current_price) for r in filtered]
    if not prices or min(prices) <= 0:
        return []
    if (max(prices) / min(prices)) > price_ratio_cap:
        if len({r.store_name for r in filtered}) >= 3:
            sorted_p = sorted(prices)
            med = sorted_p[len(sorted_p) // 2]
            band = math.sqrt(price_ratio_cap)
            trimmed = [
                r for r in filtered
                if (med / band) <= float(r.current_price) <= (med * band)
            ]
            if len({r.store_name for r in trimmed}) >= 2:
                t_prices = [float(r.current_price) for r in trimmed]
                if min(t_prices) > 0 and (max(t_prices) / min(t_prices)) <= price_ratio_cap:
                    filtered = trimmed
                else:
                    return []
            else:
                return []
        else:
            return []

    return filtered


def assign_canonical_keys(
    records: list[RawProductSnapshot],
    *,
    max_price_ratio: float = 2.5,
    tier3_similarity_threshold: float = 0.72,
    tier3_max_price_ratio: float = 1.75,
) -> MatchSummary:
    """Assign `canonical_product_key` in-place via a precision-first multi-vertical hybrid matcher.

    Covers:
    - Pass 0: Checksum-verified EAN-13 barcode matching (attributes or embedded title EANs)
    - Core Electronics & Home Appliances:
        * Tier 1: Exact normalized model/MPN + brand (bilingual AR <-> EN)
        * Tier 2: Spec-blocked structured match `(brand, family, spec_block, core_tokens)`
        * Tier 3: Local token/character-ngram vector similarity inside strict spec blocks
    - Groceries: 3-pass matcher (EAN -> Exact Size -> Bilingual Type + Arabic fractions)
    - Health & Beauty: Exact Brand+ProductLine+ExactSize/Dosage/Conc + strict spec-blocked similarity
    - Footwear (`fashion` & `sports`): Style-Code Pass -> Parent Model-Name Pass (stripping shoe sizes)

    Every emitted group passes mandatory guardrails: >=2 distinct stores, brand consistency,
    accessory-vs-main-product separation, unit/quantity conflict blocking, and category price-ratio caps.
    """
    for rec in records:
        rec.canonical_product_key = None

    strict_cap_22 = 2.2 if max_price_ratio <= 2.5 else max_price_ratio
    strict_cap_25 = 2.5 if max_price_ratio <= 2.5 else max_price_ratio

    core_records: list[RawProductSnapshot] = []
    grocery_records: list[RawProductSnapshot] = []
    hb_records: list[RawProductSnapshot] = []
    footwear_records: list[RawProductSnapshot] = []
    global_ean_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)

    for rec in records:
        eff_cat = effective_category(rec)
        if eff_cat in ("groceries", "pet_care"):
            grocery_records.append(rec)
            continue
        if eff_cat in ("electronics", "home_appliances"):
            core_records.append(rec)
        elif eff_cat in ("health", "beauty"):
            hb_records.append(rec)
        elif eff_cat in ("fashion", "sports") and is_footwear_record(rec):
            footwear_records.append(rec)

        ean_key = _extract_global_ean_key(rec)
        if ean_key:
            global_ean_buckets[ean_key].append(rec)

    matched_groups = 0
    matched_products = 0
    tier1_groups = 0
    tier2_groups = 0
    tier3_groups = 0
    grocery_groups = 0
    health_beauty_groups = 0
    footwear_groups = 0
    group_details: dict[str, list[tuple[str, float, str]]] = {}

    def _commit_buckets(
        candidate_buckets: dict[str, list[RawProductSnapshot]],
        *,
        price_ratio_cap: float = strict_cap_22,
        tier_counter: str = "tier1",
        check_units: bool = False,
        check_accessory: bool = False,
    ) -> set[int]:
        nonlocal matched_groups, matched_products, tier1_groups, tier2_groups
        nonlocal tier3_groups, grocery_groups, health_beauty_groups, footwear_groups
        assigned_ids: set[int] = set()
        for key, group in sorted(candidate_buckets.items()):
            clean_group = _filter_group_guardrails(
                group,
                price_ratio_cap=price_ratio_cap,
                check_units=check_units,
                check_accessory=check_accessory,
            )
            if not clean_group:
                continue

            for rec in clean_group:
                rec.canonical_product_key = key
                assigned_ids.add(id(rec))

            matched_groups += 1
            matched_products += len(clean_group)
            if tier_counter == "tier1":
                tier1_groups += 1
            elif tier_counter == "tier2":
                tier2_groups += 1
            elif tier_counter == "tier3":
                tier3_groups += 1
            elif tier_counter == "grocery":
                grocery_groups += 1
            elif tier_counter == "health_beauty":
                health_beauty_groups += 1
            elif tier_counter == "footwear":
                footwear_groups += 1

            group_details[key] = sorted(
                [(r.store_name, float(r.current_price), r.product_title) for r in clean_group],
                key=lambda x: (x[1], x[0]),
            )
        return assigned_ids

    # ------------------------------------------------------------------
    # PASS 0: Global Checksum-Verified EAN-13 Barcodes (non-grocery)
    # ------------------------------------------------------------------
    matched_global_ids = _commit_buckets(
        global_ean_buckets,
        price_ratio_cap=strict_cap_22,
        tier_counter="tier1",
        check_units=True,
        check_accessory=True,
    )

    # ------------------------------------------------------------------
    # TIER 1: Exact Model / MPN + Brand (core electronics & appliances)
    # ------------------------------------------------------------------
    tier1_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for rec in core_records:
        if id(rec) in matched_global_ids:
            continue
        cand = compute_candidate_key(rec)
        if cand:
            tier1_buckets[cand].append(rec)

    matched_core_ids = matched_global_ids | _commit_buckets(
        tier1_buckets,
        price_ratio_cap=strict_cap_22,
        tier_counter="tier1",
        check_accessory=True,
    )

    # ------------------------------------------------------------------
    # TIER 2: Spec-Blocked Match (brand + family + strict spec_block + core tokens)
    # ------------------------------------------------------------------
    unmatched_core = [r for r in core_records if id(r) not in matched_core_ids]
    spec_blocks: dict[tuple[str, str, str], list[tuple[RawProductSnapshot, list[str]]]] = defaultdict(list)
    tier2_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)

    for rec in unmatched_core:
        if is_accessory_listing(rec):
            continue
        brand = _canonical_brand(rec.brand, rec.product_title)
        if not brand or brand == "unknown":
            continue
        family = _family_of(rec.sub_category)
        hint = _looks_like_smartphone_or_laptop(rec)
        if hint in ("smartphone", "laptop"):
            family = hint
        norm_title = _strip_marketplace_noise(rec.product_title)
        spec_sig = _extract_spec_block(rec, brand, family, norm_title)
        if not spec_sig:
            continue
        core_toks = _core_tokens_for_matching(norm_title, brand)
        if not core_toks:
            continue
        spec_blocks[(brand, family, spec_sig)].append((rec, core_toks))

        series_toks = sorted(t for t in core_toks if any(c.isdigit() for c in t))[:3]
        word_toks = [t for t in core_toks if not any(c.isdigit() for c in t)][:2]
        key_tokens = series_toks + word_toks if series_toks else core_toks[:3]
        if key_tokens:
            t2_key = normalize_snake_slug(
                f"t2_{brand}_{family}_{spec_sig}_{'_'.join(sorted(key_tokens))}",
                max_len=160,
            )
            tier2_buckets[t2_key].append(rec)

    matched_t2_ids = _commit_buckets(
        tier2_buckets,
        price_ratio_cap=min(strict_cap_22, 2.2) if max_price_ratio <= 2.5 else max_price_ratio,
        tier_counter="tier2",
        check_accessory=True,
    )
    matched_core_ids |= matched_t2_ids

    # ------------------------------------------------------------------
    # TIER 3: Lightweight Local Semantic / Token-Vector Similarity inside strict spec blocks
    # ------------------------------------------------------------------
    tier3_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    effective_t3_ratio = min(max_price_ratio, tier3_max_price_ratio) if max_price_ratio <= 2.5 else max_price_ratio

    for (brand, family, spec_sig), entries in sorted(spec_blocks.items()):
        remaining = [(rec, toks) for rec, toks in entries if id(rec) not in matched_core_ids]
        if len(remaining) < 2 or len({r.store_name for r, _ in remaining}) < 2:
            continue

        vectors = [_token_ngram_vector(toks) for _, toks in remaining]
        series_sigs = [_series_number_signature(toks) for _, toks in remaining]
        used = [False] * len(remaining)

        for i in range(len(remaining)):
            if used[i]:
                continue
            rec_i, toks_i = remaining[i]
            cluster = [rec_i]
            cluster_stores = {rec_i.store_name}
            used[i] = True

            for j in range(i + 1, len(remaining)):
                if used[j]:
                    continue
                rec_j, _ = remaining[j]
                if rec_j.store_name in cluster_stores:
                    continue
                if series_sigs[i] and series_sigs[j] and not (series_sigs[i] & series_sigs[j]):
                    continue
                sim = _cosine_similarity(vectors[i], vectors[j])
                if sim < tier3_similarity_threshold:
                    continue
                pi, pj = float(rec_i.current_price), float(rec_j.current_price)
                if min(pi, pj) <= 0 or (max(pi, pj) / min(pi, pj)) > effective_t3_ratio:
                    continue
                cluster.append(rec_j)
                cluster_stores.add(rec_j.store_name)
                used[j] = True

            if len(cluster_stores) >= 2:
                anchor = "_".join(toks_i[:3]) or "sim"
                t3_key = normalize_snake_slug(
                    f"t3_{brand}_{family}_{spec_sig}_{anchor}",
                    max_len=160,
                )
                tier3_buckets[t3_key].extend(cluster)

    matched_core_ids |= _commit_buckets(
        tier3_buckets,
        price_ratio_cap=effective_t3_ratio,
        tier_counter="tier3",
        check_accessory=True,
    )

    # ------------------------------------------------------------------
    # Groceries 3-Pass Matcher (Barcode -> Exact Size -> Bilingual Type)
    # ------------------------------------------------------------------
    barcode_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for rec in grocery_records:
        if is_collapsed_multiprice_variant(rec):
            continue
        bkey = compute_grocery_barcode_key(rec)
        if bkey:
            barcode_buckets[bkey].append(rec)
    matched_grocery_ids = _commit_buckets(
        barcode_buckets,
        price_ratio_cap=strict_cap_22,
        tier_counter="grocery",
        check_units=True,
    )

    size_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for rec in grocery_records:
        if id(rec) in matched_grocery_ids or is_collapsed_multiprice_variant(rec):
            continue
        skey = compute_grocery_size_key(rec)
        if skey:
            size_buckets[skey].append(rec)
    matched_grocery_ids |= _commit_buckets(
        size_buckets,
        price_ratio_cap=strict_cap_22,
        tier_counter="grocery",
        check_units=True,
    )

    type_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for rec in grocery_records:
        if id(rec) in matched_grocery_ids or is_collapsed_multiprice_variant(rec):
            continue
        tkey = compute_grocery_type_key(rec)
        if tkey:
            type_buckets[tkey].append(rec)
    _commit_buckets(
        type_buckets,
        price_ratio_cap=strict_cap_22,
        tier_counter="grocery",
        check_units=True,
    )

    # ------------------------------------------------------------------
    # Health & Beauty 3-Pass Matcher:
    #   Pass 1: Exact Sized Key `(brand, tokens, conc, dosage, size)`
    #   Pass 2: Strict Size/Dosage/Form-Blocked Similarity (`>= 0.78`)
    #   Pass 3: High-Specificity Sizeless Line (`>= 3` core tokens, tight `<= 1.65x`, units_conflict guarded)
    # ------------------------------------------------------------------
    hb_exact_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    hb_sizeless_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    hb_blocks: dict[str, list[tuple[RawProductSnapshot, list[str]]]] = defaultdict(list)

    for rec in hb_records:
        if id(rec) in matched_global_ids:
            continue
        feats = extract_health_beauty_features(rec)
        if not feats:
            continue
        exact_key, sizeless_key, block_id, core_toks = feats
        if exact_key:
            hb_exact_buckets[exact_key].append(rec)
        if block_id:
            hb_blocks[block_id].append((rec, core_toks))
        if sizeless_key:
            hb_sizeless_buckets[sizeless_key].append(rec)

    matched_hb_ids = matched_global_ids | _commit_buckets(
        hb_exact_buckets,
        price_ratio_cap=strict_cap_22,
        tier_counter="health_beauty",
        check_units=True,
    )

    # Pass 2 for Health & Beauty: high-threshold cosine similarity (>= 0.78) strictly
    # inside identical `(brand, quantized_size, dosage, perfume_conc, form, gender)` blocks
    hb_sim_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    hb_sim_ratio = min(strict_cap_22, 2.0) if max_price_ratio <= 2.5 else max_price_ratio

    for block_id, entries in sorted(hb_blocks.items()):
        remaining = [(rec, toks) for rec, toks in entries if id(rec) not in matched_hb_ids]
        if len(remaining) < 2 or len({r.store_name for r, _ in remaining}) < 2:
            continue

        vectors = [_token_ngram_vector(toks) for _, toks in remaining]
        token_sets = [set(toks) for _, toks in remaining]
        num_sigs = [_series_number_signature(toks) for _, toks in remaining]
        used = [False] * len(remaining)

        for i in range(len(remaining)):
            if used[i]:
                continue
            rec_i, toks_i = remaining[i]
            cluster = [rec_i]
            cluster_stores = {rec_i.store_name}
            used[i] = True

            for j in range(i + 1, len(remaining)):
                if used[j]:
                    continue
                rec_j, _ = remaining[j]
                if rec_j.store_name in cluster_stores:
                    continue
                shared = token_sets[i] & token_sets[j]
                min_needed = min(2, len(token_sets[i]), len(token_sets[j]))
                if len(shared) < min_needed:
                    continue
                if num_sigs[i] and num_sigs[j] and not (num_sigs[i] & num_sigs[j]):
                    continue
                if _cosine_similarity(vectors[i], vectors[j]) < 0.78:
                    continue
                pi, pj = float(rec_i.current_price), float(rec_j.current_price)
                if min(pi, pj) <= 0 or (max(pi, pj) / min(pi, pj)) > hb_sim_ratio:
                    continue
                cluster.append(rec_j)
                cluster_stores.add(rec_j.store_name)
                used[j] = True

            if len(cluster_stores) >= 2:
                b_slug = normalize_snake_slug(block_id.replace("|", "_"), max_len=90)
                anchor = "_".join(sorted(toks_i[:3])) or "sim"
                sim_key = normalize_snake_slug(f"hbs_{b_slug}_{anchor}", max_len=160)
                hb_sim_buckets[sim_key].extend(cluster)

    matched_hb_ids |= _commit_buckets(
        hb_sim_buckets,
        price_ratio_cap=hb_sim_ratio,
        tier_counter="health_beauty",
        check_units=True,
    )

    # Pass 3 for Health & Beauty: high-specificity sizeless product lines (e.g. when
    # one store omits `ml`/`caps` on standard SKUs like `Eucerin Even Pigment Perfector Night Cream`)
    # guarded by tight `<= 1.65x` price ratio + `check_units=True` (so 30ml vs 50ml STILL blocked!).
    hb_sizeless_rem: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for k, grp in hb_sizeless_buckets.items():
        rem = [r for r in grp if id(r) not in matched_hb_ids]
        if len({r.store_name for r in rem}) >= 2:
            hb_sizeless_rem[k] = rem
    hb_sizeless_cap = 1.65 if max_price_ratio <= 2.5 else max_price_ratio
    matched_hb_ids |= _commit_buckets(
        hb_sizeless_rem,
        price_ratio_cap=hb_sizeless_cap,
        tier_counter="health_beauty",
        check_units=True,
    )

    # ------------------------------------------------------------------
    # Footwear 4-Pass Matcher:
    #   Pass 1: Exact Manufacturer Style Code
    #   Pass 2: Exact Gender + Parent Model Name
    #   Pass 3: Adult Neutral Model Name (allows unstated gender to match men/women,
    #           while strictly blocking men-vs-women and kids-vs-adult conflicts!)
    #   Pass 4: High-threshold similarity (`>= 0.80`) inside `(brand, age_guard, ftype)`
    # ------------------------------------------------------------------
    fw_style_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    fw_exact_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    fw_neutral_buckets: dict[str, list[tuple[RawProductSnapshot, str]]] = defaultdict(list)
    fw_blocks: dict[str, list[tuple[RawProductSnapshot, str, list[str]]]] = defaultdict(list)

    for rec in footwear_records:
        if id(rec) in matched_global_ids:
            continue
        feats = extract_footwear_features(rec)
        if not feats:
            continue
        style_key, exact_key, neutral_key, gender, block_id, core_toks = feats
        if style_key:
            fw_style_buckets[style_key].append(rec)
        if exact_key:
            fw_exact_buckets[exact_key].append(rec)
        if neutral_key:
            fw_neutral_buckets[neutral_key].append((rec, gender))
        if len(core_toks) >= 2:
            fw_blocks[block_id].append((rec, gender, core_toks))

    matched_fw_ids = matched_global_ids | _commit_buckets(
        fw_style_buckets,
        price_ratio_cap=strict_cap_25,
        tier_counter="footwear",
    )

    fw_exact_rem: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for k, grp in fw_exact_buckets.items():
        rem = [r for r in grp if id(r) not in matched_fw_ids]
        if rem:
            fw_exact_rem[k] = rem
    matched_fw_ids |= _commit_buckets(
        fw_exact_rem,
        price_ratio_cap=strict_cap_25,
        tier_counter="footwear",
    )

    # Pass 3: Adult neutral model name (rejects any group with BOTH explicit `men` and `women`)
    fw_neutral_rem: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for k, entries in fw_neutral_buckets.items():
        rem = [(r, g) for r, g in entries if id(r) not in matched_fw_ids]
        genders = {g for _, g in rem}
        if "men" in genders and "women" in genders:
            continue
        if len({r.store_name for r, _ in rem}) >= 2:
            fw_neutral_rem[k] = [r for r, _ in rem]
    matched_fw_ids |= _commit_buckets(
        fw_neutral_rem,
        price_ratio_cap=min(strict_cap_25, 2.2) if max_price_ratio <= 2.5 else max_price_ratio,
        tier_counter="footwear",
    )

    # Pass 4: Strict `(brand, age_guard, ftype)` footwear similarity (`>= 0.80`)
    fw_sim_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    fw_sim_ratio = min(strict_cap_25, 2.2) if max_price_ratio <= 2.5 else max_price_ratio
    for block_id, entries in sorted(fw_blocks.items()):
        remaining = [(rec, g, toks) for rec, g, toks in entries if id(rec) not in matched_fw_ids]
        if len(remaining) < 2 or len({r.store_name for r, _, _ in remaining}) < 2:
            continue
        vectors = [_token_ngram_vector(toks) for _, _, toks in remaining]
        tok_sets = [set(toks) for _, _, toks in remaining]
        num_sigs = [frozenset(t for t in toks if any(c.isdigit() for c in t)) for _, _, toks in remaining]
        used = [False] * len(remaining)

        for i in range(len(remaining)):
            if used[i]:
                continue
            rec_i, gi, toks_i = remaining[i]
            cluster = [rec_i]
            cluster_stores = {rec_i.store_name}
            cluster_genders = {gi}
            used[i] = True

            for j in range(i + 1, len(remaining)):
                if used[j]:
                    continue
                rec_j, gj, _ = remaining[j]
                if rec_j.store_name in cluster_stores:
                    continue
                # Never mix explicit men & women shoes
                if (gj == "men" and "women" in cluster_genders) or (gj == "women" and "men" in cluster_genders):
                    continue
                # Exact version number equality (Downshifter 13 != 14, Cumulus 26 != 27)
                if num_sigs[i] != num_sigs[j]:
                    continue
                if len(tok_sets[i] & tok_sets[j]) < 2:
                    continue
                if _cosine_similarity(vectors[i], vectors[j]) < 0.80:
                    continue
                pi, pj = float(rec_i.current_price), float(rec_j.current_price)
                if min(pi, pj) <= 0 or (max(pi, pj) / min(pi, pj)) > fw_sim_ratio:
                    continue
                cluster.append(rec_j)
                cluster_stores.add(rec_j.store_name)
                cluster_genders.add(gj)
                used[j] = True

            if len(cluster_stores) >= 2:
                b_slug = normalize_snake_slug(block_id.replace("|", "_"), max_len=60)
                anchor = "_".join(toks_i[:3])
                sim_key = normalize_snake_slug(f"fws_{b_slug}_{anchor}", max_len=140)
                fw_sim_buckets[sim_key].extend(cluster)

    _commit_buckets(
        fw_sim_buckets,
        price_ratio_cap=fw_sim_ratio,
        tier_counter="footwear",
    )

    return MatchSummary(
        matched_groups=matched_groups,
        matched_products=matched_products,
        group_details=group_details,
        tier1_groups=tier1_groups,
        tier2_groups=tier2_groups,
        tier3_groups=tier3_groups,
        grocery_groups=grocery_groups,
        health_beauty_groups=health_beauty_groups,
        footwear_groups=footwear_groups,
    )
