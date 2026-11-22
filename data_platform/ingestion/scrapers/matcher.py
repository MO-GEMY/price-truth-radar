"""
Deterministic Cross-Store Canonical Product Matcher for Price Truth Radar.

Computes normalized product fingerprints across Egyptian electronics stores
(`sigma`, `2b`, `btech`, etc.) using brand, product category, model identifiers,
RAM, and storage. Only assigns `canonical_product_key` when the same product
appears across `>= 2` distinct stores (with a sanity price-ratio guard to
prevent false accessory-vs-device matches).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .base import RawProductSnapshot, normalize_snake_slug
from .groceries import (
    compute_grocery_barcode_key,
    compute_grocery_candidate_key,
    compute_grocery_size_key,
    compute_grocery_type_key,
)

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
    """Strip Amazon pipe suffixes, Noon/Jumia version tags, and invisible chars."""
    cleaned = re.sub(r"[\u200b\u200c\u200d®™]", "", title)
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
    """Product-line word directly after the model code (G502 **HERO** vs
    G502 **X** Plus). Only ALL-CAPS or canonical product-line words count —
    lowercase marketing/spec words ("LaserJet", "Wireless", "Black") are
    ignored so printer/tv titles don't drift."""
    idx = cleaned_title.lower().find(code_raw.lower())
    if idx == -1:
        return None
    tail = cleaned_title[idx + len(code_raw):]
    line_words = {"pro", "max", "plus", "x", "ultra", "hero", "lite", "note",
                  "mini", "se", "fe", "ti", "neo", "gt"}
    for tok in re.split(r"[^A-Za-z0-9]+", tail):
        if not tok:
            continue
        if any(c.isdigit() for c in tok):  # part numbers (7MD68A) aren't variants
            continue
        if tok.isupper() and len(tok) >= 1:
            return tok.lower()
        if tok.lower() in line_words:
            return tok.lower()
        return None  # first non-qualifying word ends the variant window
    return None


@dataclass
class MatchSummary:
    matched_groups: int
    matched_products: int
    group_details: dict[str, list[tuple[str, float, str]]]


def _canonical_brand(brand: str) -> str:
    cleaned = re.sub(r"\s+", " ", (brand or "").strip().lower())
    return _BRAND_ALIASES.get(cleaned, normalize_snake_slug(cleaned, fallback="unknown", max_len=32))


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

    tokens = [tok.lower() for tok in text.split() if tok]
    # Remove leading brand token(s)
    brand_tokens = set(brand.split("_"))
    filtered: list[str] = []
    for tok in tokens:
        if not filtered and tok in brand_tokens:
            continue
        if tok in _COLOR_WORDS:
            continue
        if tok.isdigit() and int(tok) in {ram_gb, storage_gb}:
            continue
        filtered.append(tok)

    if not filtered:
        return None

    # Keep concise model core (at most 5 tokens)
    model_slug = "_".join(filtered[:5])
    if not model_slug or not any(ch.isdigit() for ch in model_slug):
        return None

    parts = [brand, model_slug, f"{storage_gb}gb"]
    if ram_gb is not None:
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
    cleaned = re.sub(r"\b(?:ddr[345]|pcie|sata|nvme|fhd|qhd|uhd|4k|8k|rgb|argb|pwm|atx|matx|ips|va|oled|qled|usb\d?)\b", " ", cleaned, flags=re.I)

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
        variant = _variant_token_after(cleaned, first_raw) if first_raw else None
        if variant and len(variant) <= 24:
            parts.append(variant)

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
        r"\b(?:4k|8k|fhd|uhd|qled|oled|led|hdr10|wifi|wi-fi|smart|inverter|digital|frost|nofrost)\b",
        " ",
        cleaned,
        flags=re.I,
    )

    codes_norm, first_raw = _collect_model_codes(cleaned, min_len=5, loose=True)
    if not codes_norm:
        return None

    family = _family_of(record.sub_category)
    primary = codes_norm[0]

    # TVs inside home_appliances get the same size-embedded model treatment.
    size: Optional[int] = None
    if family in _SIZE_EMBEDDED_FAMILIES:
        size = _tv_monitor_size(title, codes_norm)
        if size is not None:
            primary = _strip_leading_size(primary, size)

    parts = [brand, family, primary]
    if size is not None:
        parts.append(f"{size}in")

    # Variant token (product-line word right after the code) — single-code
    # titles only, same rationale as the electronics path.
    if len(codes_norm) == 1:
        variant = _variant_token_after(cleaned, first_raw) if first_raw else None
        if variant and len(variant) <= 24 and variant not in {p.split("_")[-1] for p in parts}:
            parts.append(variant)

    # Strict capacity / power guards — 1.5 HP vs 2.25 HP and 8 kg vs 6 kg are
    # different SKUs, never the same canonical product.
    if family == "air_conditioner":
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


def compute_candidate_key(record: RawProductSnapshot) -> Optional[str]:
    """Compute a deterministic candidate canonical key for electronics, appliances, & groceries."""
    if record.category == "groceries":
        return compute_grocery_candidate_key(record)

    if record.category not in ("electronics", "home_appliances"):
        return None

    brand = _canonical_brand(record.brand)
    if not brand or brand == "unknown":
        return None

    if record.category == "home_appliances":
        return _appliance_fingerprint(record, brand)

    sub = record.sub_category.lower()
    if sub in ("smartphones", "tablets"):
        return _smartphone_fingerprint(record, brand)
    if sub == "laptops":
        return _laptop_fingerprint(record, brand)
    return _electronics_generic_fingerprint(record, brand)


def assign_canonical_keys(
    records: list[RawProductSnapshot],
    *,
    max_price_ratio: float = 2.5,
) -> MatchSummary:
    """Assign `canonical_product_key` in-place ONLY for multi-store matches (`>= 2` stores).

    For `category == "groceries"`, runs a strict 2-pass match:
      Pass 1: Multi-store EAN/GTIN barcode match (`grocery_gtin_<digits>`).
      Pass 2: Remaining unmatched groceries matched by strict
              `brand + core_tokens + exact net_weight_g/net_volume_ml/pack_count`
              so stores exposing EAN (e.g. HyperOne) still match stores without
              EAN (e.g. Noon, Amazon.eg, Spinneys) when package sizes match exactly.

    Applies a `max_price_ratio` sanity guard so mismatched accessory-vs-device
    outliers are never linked together.
    """
    for rec in records:
        rec.canonical_product_key = None

    buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    grocery_records: list[RawProductSnapshot] = []
    for rec in records:
        if rec.category == "groceries":
            grocery_records.append(rec)
            continue
        cand = compute_candidate_key(rec)
        if cand:
            buckets[cand].append(rec)

    matched_groups = 0
    matched_products = 0
    group_details: dict[str, list[tuple[str, float, str]]] = {}

    def _commit_buckets(candidate_buckets: dict[str, list[RawProductSnapshot]]) -> set[int]:
        nonlocal matched_groups, matched_products
        assigned_ids: set[int] = set()
        for key, group in sorted(candidate_buckets.items()):
            distinct_stores = {r.store_name for r in group}
            if len(distinct_stores) < 2:
                continue

            prices = [float(r.current_price) for r in group]
            min_p, max_p = min(prices), max(prices)
            if min_p <= 0 or (max_p / min_p) > max_price_ratio:
                continue

            for rec in group:
                rec.canonical_product_key = key
                assigned_ids.add(id(rec))

            matched_groups += 1
            matched_products += len(group)
            group_details[key] = sorted(
                [(r.store_name, float(r.current_price), r.product_title) for r in group],
                key=lambda x: (x[1], x[0]),
            )
        return assigned_ids

    # Core verticals (electronics, home_appliances)
    _commit_buckets(buckets)

    # Groceries Pass 1: Multi-store EAN/GTIN barcode matches
    barcode_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for rec in grocery_records:
        bkey = compute_grocery_barcode_key(rec)
        if bkey:
            barcode_buckets[bkey].append(rec)
    matched_grocery_ids = _commit_buckets(barcode_buckets)

    # Groceries Pass 2: Strict brand + core tokens + exact package size/pack_count
    size_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for rec in grocery_records:
        if id(rec) in matched_grocery_ids:
            continue
        skey = compute_grocery_size_key(rec)
        if skey:
            size_buckets[skey].append(rec)
    matched_grocery_ids |= _commit_buckets(size_buckets)

    # Groceries Pass 3: Bilingual AR <-> EN type matching. Arabic and English
    # titles of the SAME product rarely share core tokens ("سمن بقرى" vs
    # "Fern Ghee"), so this pass matches on canonical brand + bilingual type
    # noun + exact package size + scent/flavor words. Strictness preserved:
    # brand, type, size, pack count and flavors must all agree.
    type_buckets: dict[str, list[RawProductSnapshot]] = defaultdict(list)
    for rec in grocery_records:
        if id(rec) in matched_grocery_ids:
            continue
        tkey = compute_grocery_type_key(rec)
        if tkey:
            type_buckets[tkey].append(rec)
    _commit_buckets(type_buckets)

    return MatchSummary(
        matched_groups=matched_groups,
        matched_products=matched_products,
        group_details=group_details,
    )
