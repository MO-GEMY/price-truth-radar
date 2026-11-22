"""
Egyptian Groceries ("سلة البيت المصري") packaging parser, brand normalizer,
sub-category classifier, and strict size-aware cross-store matcher.

Extracts standardized packaging attributes from EN & AR product titles/specs:
- `net_weight_g`  : total net weight in grams (int)
- `net_volume_ml` : total net volume in milliliters (int)
- `pack_count`    : multipack count (int, >= 1)
- `pack_size`     : human-friendly label (e.g. `1L`, `700ml`, `500g`, `1kg`, `6x1L`)
- `ean` / `gtin`  : 8–14 digit barcode string when present in JSON-LD / payload
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .base import RawProductSnapshot, normalize_snake_slug

GROCERY_SUB_CATEGORIES: tuple[str, ...] = (
    "oils_ghee",
    "rice_pasta",
    "dairy_cheese",
    "tea_coffee",
    "canned_sauces",
    "beverages",
    "detergents",
)

# Normalize Arabic-Indic digits (٠-٩) & Eastern Arabic digits (۰-۹) to ASCII
_ARABIC_DIGITS_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# Egyptian household grocery brands (case-insensitive substring -> canonical English name)
_GROCERY_BRAND_PATTERNS: tuple[tuple[str, str], ...] = (
    ("el maleka", "El Maleka"),
    ("al maleka", "El Maleka"),
    ("الملكة", "El Maleka"),
    ("el doha", "El Doha"),
    ("al doha", "El Doha"),
    ("الضحى", "El Doha"),
    ("el saa", "El Saa"),
    ("al saa", "El Saa"),
    ("الساعة", "El Saa"),
    ("el arosa", "El Arosa"),
    ("al arosa", "El Arosa"),
    ("العروسة", "El Arosa"),
    ("abu auf", "Abu Auf"),
    ("أبو عوف", "Abu Auf"),
    ("ابو عوف", "Abu Auf"),
    ("obour land", "Obour Land"),
    ("obourland", "Obour Land"),
    ("عبور لاند", "Obour Land"),
    ("wadi food", "Wadi Food"),
    ("وادي فود", "Wadi Food"),
    ("la vache qui rit", "La Vache Qui Rit"),
    ("laughing cow", "La Vache Qui Rit"),
    ("البقرة الضاحكة", "La Vache Qui Rit"),
    ("dina farms", "Dina Farms"),
    ("مزارع دينا", "Dina Farms"),
    ("al osra", "Al Osra"),
    ("el osra", "Al Osra"),
    ("الأسرة", "Al Osra"),
    ("el mizan", "El Mizan"),
    ("الميزان", "El Mizan"),
    ("spiro spathis", "Spiro Spathis"),
    ("سبيرو سباتس", "Spiro Spathis"),
    ("ahmed tea", "Ahmed Tea"),
    ("ahmad tea", "Ahmad Tea"),
    ("rio mare", "Rio Mare"),
    ("coca-cola", "Coca-Cola"),
    ("coca cola", "Coca-Cola"),
    ("crystal", "Crystal"),
    ("كريستال", "Crystal"),
    ("afia", "Afia"),
    ("عافية", "Afia"),
    ("rawabi", "Rawabi"),
    ("rawaby", "Rawabi"),
    ("روابي", "Rawabi"),
    ("ganna", "Ganna"),
    ("جنة", "Ganna"),
    ("fern", "Fern"),
    ("فيرن", "Fern"),
    ("helwa", "Helwa"),
    ("حلوة", "Helwa"),
    ("slite", "Slite"),
    ("سلايت", "Slite"),
    ("regina", "Regina"),
    ("ريجينا", "Regina"),
    ("lametna", "Lametna"),
    ("rehana", "Rehana"),
    ("dolphin", "Dolphin"),
    ("italiano", "Italiano"),
    ("إيطاليانو", "Italiano"),
    ("star", "Star"),
    ("juhayna", "Juhayna"),
    ("جهينة", "Juhayna"),
    ("almarai", "Almarai"),
    ("المراعي", "Almarai"),
    ("domty", "Domty"),
    ("دومتي", "Domty"),
    ("president", "President"),
    ("بريزيدون", "President"),
    ("lamar", "Lamar"),
    ("لمار", "Lamar"),
    ("beyti", "Beyti"),
    ("بيتي", "Beyti"),
    ("kiri", "Kiri"),
    ("كيري", "Kiri"),
    ("panda", "Panda"),
    ("باندا", "Panda"),
    ("lipton", "Lipton"),
    ("ليبتون", "Lipton"),
    ("nescafe", "Nescafe"),
    ("نسكافيه", "Nescafe"),
    ("bonjorno", "Bonjorno"),
    ("dilmah", "Dilmah"),
    ("heinz", "Heinz"),
    ("هاينز", "Heinz"),
    ("harvest", "Harvest"),
    ("هارفست", "Harvest"),
    ("vitrac", "Vitrac"),
    ("فيتراك", "Vitrac"),
    ("americana", "Americana"),
    ("أمريكانا", "Americana"),
    ("sunshine", "Sunshine"),
    ("صن شاين", "Sunshine"),
    ("nestle", "Nestle"),
    ("نستله", "Nestle"),
    ("baraka", "Baraka"),
    ("بركة", "Baraka"),
    ("dasani", "Dasani"),
    ("aquafina", "Aquafina"),
    ("hayat", "Hayat"),
    ("pepsi", "Pepsi"),
    ("بيبسي", "Pepsi"),
    ("schweppes", "Schweppes"),
    ("fayrouz", "Fayrouz"),
    ("ariel", "Ariel"),
    ("أريال", "Ariel"),
    ("اريال", "Ariel"),
    ("persil", "Persil"),
    ("برسيل", "Persil"),
    ("tide", "Tide"),
    ("تايد", "Tide"),
    ("oxi", "Oxi"),
    ("أوكسي", "Oxi"),
    ("fairy", "Fairy"),
    ("فيري", "Fairy"),
    ("pril", "Pril"),
    ("بريل", "Pril"),
    ("feba", "Feba"),
    ("فيبا", "Feba"),
    ("dettol", "Dettol"),
    ("ديتول", "Dettol"),
    ("clorox", "Clorox"),
    ("كلوركس", "Clorox"),
    ("downy", "Downy"),
    ("داوني", "Downy"),
    ("comfort", "Comfort"),
    ("finish", "Finish"),
    ("lurpak", "Lurpak"),
    ("nido", "Nido"),
    ("نيدو", "Nido"),
    ("red bull", "Red Bull"),
    ("lipton", "Lipton"),
)

# Multi-pack pattern like `6x1L`, `12 x 330 ml`, `6 × 1 لتر`
_MULTIPACK_UNIT_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s*[x×\*]\s*(\d+(?:\.\d+)?)\s*"
    r"(kg|kgs|kilo|kilogram|kilograms|كجم|كيلو(?:جرام|غرام)?|"
    r"gm|gr|grams|gram|g|جم|جرام|غرام|"
    r"ml|milliliter|milliliters|millilitre|millilitres|مللي|ملل|مل|"
    r"liters|liter|litres|litre|ltr|lt|l|لتر)\b",
    re.I,
)

# Single quantity + unit pattern (EN & AR)
_SINGLE_UNIT_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*"
    r"(kg|kgs|kilo|kilogram|kilograms|k|كجم|كيلو(?:جرام|غرام)?|"
    r"gm|gr|grams|gram|g|جم|جرام|غرام|"
    r"ml|milliliter|milliliters|millilitre|millilitres|مللي|ملل|مل|"
    r"liters|liter|litres|litre|ltr|lt|l|لتر)(?![a-zA-Z\u0600-\u06FF])",
    re.I,
)

# Standalone pack count patterns: `Pack of 6`, `3 Pieces`, `6 Pcs`, `2 Bottles`, `عبوة من 6`, `6 قطع`
_PACK_COUNT_RE = re.compile(
    r"(?:"
    r"(?:pack|set|box|bundle|case|carton)\s+of\s+(\d{1,3})\b|"
    r"\b(\d{1,3})\s*(?:packs?|pieces?|pcs|pc|bottles?|cans?|jars?|pouches?|sachets?|bags?|bars?|units?)\b|"
    r"(?:عبوة\s*من|عدد)\s*(\d{1,3})\b|"
    r"\b(\d{1,3})\s*(?:عبوات|عبوة|قطع|قطعة|زجاجات|علب)"
    r")",
    re.I,
)

_EAN_GTIN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")

_WEIGHT_KG_UNITS = {"k", "kg", "kgs", "kilo", "kilogram", "kilograms", "كجم", "كيلو", "كيلوجرام", "كيلوغرام"}
_WEIGHT_G_UNITS = {"g", "gm", "gr", "gram", "grams", "جم", "جرام", "غرام"}
_VOL_L_UNITS = {"l", "lt", "ltr", "liter", "liters", "litre", "litres", "لتر"}
_VOL_ML_UNITS = {"ml", "milliliter", "milliliters", "millilitre", "millilitres", "مل", "ملل", "مللي"}

_SUBCAT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "oils_ghee",
        (
            "sunflower oil", "corn oil", "cooking oil", "olive oil", "vegetable oil",
            "frying oil", "canola oil", "ghee", "samna", "sمنة", "سمنة", "سمن", "زيت",
            "crystal", "afia", "rawabi", "ganna", "fern", "slite",
        ),
    ),
    (
        "detergents",
        (
            "detergent", "laundry", "dishwashing", "dishwash", "washing powder",
            "washing gel", "fabric softener", "bleach", "disinfectant", "cleaner",
            "ariel", "persil", "tide", "oxi", "fairy", "pril", "feba", "clorox",
            "downy", "comfort", "finish", "dettol", "مسحوق غسيل", "سائل اطباق", "منظف",
        ),
    ),
    (
        "tea_coffee",
        (
            "tea", "coffee", "espresso", "cappuccino", "nescafe", "lipton", "el arosa",
            "abu auf", "turkish coffee", "arabic coffee", "instant coffee", "herbal",
            "شاي", "قهوة", "نسكافيه", "بن",
        ),
    ),
    (
        "dairy_cheese",
        (
            "milk", "cheese", "butter", "yogurt", "yoghurt", "cream", "labneh",
            "feta", "cheddar", "mozzarella", "romano", "juhayna", "almarai",
            "domty", "obour land", "president", "kiri", "lurpak", "nido", "lamar",
            "حليب", "لبن", "جبنة", "جبن", "زبدة", "زبادي",
        ),
    ),
    (
        "canned_sauces",
        (
            "tomato paste", "ketchup", "mayonnaise", "mustard", "hot sauce", "bbq sauce",
            "soy sauce", "sauce", "tuna", "fava beans", "foul", "beans", "corned beef",
            "sardines", "mackerel", "olives", "jam", "honey", "tahini", "halawa",
            "heinz", "harvest", "vitrac", "sunshine", "rio mare", "صلصة", "تونة", "فول", "كاتشب",
        ),
    ),
    (
        "rice_pasta",
        (
            "rice", "pasta", "spaghetti", "penne", "macaroni", "noodles", "indomie",
            "flour", "sugar", "lentils", "oats", "couscous", "bulgur", "semolina",
            "el doha", "el maleka", "regina", "italiano", "el saa", "al osra",
            "أرز", "ارز", "مكرونة", "دقيق", "سكر", "عدس",
        ),
    ),
    (
        "beverages",
        (
            "water", "juice", "nectar", "soda", "cola", "pepsi", "schweppes",
            "fayrouz", "spiro spathis", "energy drink", "red bull", "iced tea",
            "sparkling", "baraka", "dasani", "aquafina", "hayat", "nestle pure",
            "مياه", "عصير", "مشروب",
        ),
    ),
)

_GROCERY_MATCH_STOP_WORDS: frozenset[str] = frozenset(
    {
        "bottle", "bottles", "pouch", "pouches", "jar", "jars", "can", "cans",
        "tin", "tins", "box", "boxes", "bag", "bags", "carton", "cartons",
        "pack", "packs", "piece", "pieces", "pcs", "pc", "set", "bundle",
        "pet", "plastic", "glass", "sachet", "sachets", "bar", "bars", "tube",
        "refill", "family", "value", "economy", "super", "mega", "saver",
        "egypt", "egyptian", "original", "classic", "premium", "natural",
        "fresh", "pure", "100", "new", "size", "offer", "combo", "deal",
        "with", "for", "and", "of", "in", "by", "from", "the", "a", "an",
        "liquid", "powder", "gel",  # keep gel/powder? wait — keep gel/powder OUT of stop words!
    }
    - {"liquid", "powder", "gel"}
)


def _format_single_size(value: float, unit_kind: str) -> str:
    """Format a single-unit weight/volume cleanly (e.g. `1L`, `700ml`, `500g`, `1kg`)."""
    if unit_kind == "g":
        if value >= 1000 and abs((value / 1000.0) - round(value / 1000.0, 2)) < 1e-6:
            kg = value / 1000.0
            s = f"{kg:.2f}".rstrip("0").rstrip(".")
            return f"{s}kg"
        return f"{int(round(value))}g"
    if value >= 1000 and abs((value / 1000.0) - round(value / 1000.0, 2)) < 1e-6:
        liters = value / 1000.0
        s = f"{liters:.2f}".rstrip("0").rstrip(".")
        return f"{s}L"
    return f"{int(round(value))}ml"


def _normalize_unit(raw_unit: str, num: float) -> tuple[Optional[str], Optional[int]]:
    u = raw_unit.strip().lower()
    if u in _WEIGHT_KG_UNITS:
        grams = int(round(num * 1000))
        return ("g", grams) if 10 <= grams <= 100_000 else (None, None)
    if u in _WEIGHT_G_UNITS:
        grams = int(round(num))
        return ("g", grams) if 5 <= grams <= 100_000 else (None, None)
    if u in _VOL_L_UNITS:
        ml = int(round(num * 1000))
        return ("ml", ml) if 50 <= ml <= 100_000 else (None, None)
    if u in _VOL_ML_UNITS:
        ml = int(round(num))
        return ("ml", ml) if 10 <= ml <= 100_000 else (None, None)
    return (None, None)


def extract_ean_gtin(payload: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Extract a validated 8/12/13/14-digit EAN/GTIN barcode from JSON-LD or raw dict."""
    if not isinstance(payload, dict):
        return None
    for key in ("gtin13", "gtin14", "gtin12", "gtin8", "gtin", "ean", "barcode"):
        val = payload.get(key)
        if val is None:
            continue
        digits = re.sub(r"\D", "", str(val).strip())
        if _EAN_GTIN_RE.match(digits):
            return digits
    return None


def parse_grocery_packaging(
    title: str,
    extra_text: str = "",
    raw_payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Parse standardized grocery packaging metadata from EN/AR titles and optional payload.

    Returns a dict containing only populated keys among:
    - `net_weight_g`: total net weight in grams (unit_g * pack_count)
    - `net_volume_ml`: total net volume in milliliters (unit_ml * pack_count)
    - `pack_count`: integer >= 1
    - `pack_size`: display string like `1L`, `700ml`, `500g`, `1kg`, `6x1L`
    - `ean`: 8-14 digit barcode when available
    """
    combined = f"{title} {extra_text}".translate(_ARABIC_DIGITS_MAP)
    combined = re.sub(r"[\u200b\u200c\u200d®™]", " ", combined)

    result: dict[str, Any] = {}
    pack_count: int = 1
    unit_kind: Optional[str] = None
    unit_amount: Optional[int] = None

    # 1. Explicit multipack + unit (e.g. "6x1L", "12 x 330ml", "4x400g")
    if m := _MULTIPACK_UNIT_RE.search(combined):
        cnt = int(m.group(1))
        num = float(m.group(2))
        kind, amt = _normalize_unit(m.group(3), num)
        if kind and amt and 1 <= cnt <= 200:
            pack_count = cnt
            unit_kind = kind
            unit_amount = amt

    # 2. Single unit + optional separate pack count (e.g. "Juhayna Milk 1L - Pack of 6")
    if unit_kind is None:
        for m in _SINGLE_UNIT_RE.finditer(combined):
            num = float(m.group(1))
            kind, amt = _normalize_unit(m.group(2), num)
            if kind and amt:
                unit_kind = kind
                unit_amount = amt
                break

        if pm := _PACK_COUNT_RE.search(combined):
            for grp in pm.groups():
                if grp and grp.isdigit():
                    val = int(grp)
                    if 2 <= val <= 200:
                        pack_count = val
                        break

    if unit_kind == "g" and unit_amount is not None:
        total_g = unit_amount * pack_count
        result["net_weight_g"] = total_g
        result["pack_count"] = pack_count
        single_label = _format_single_size(unit_amount, "g")
        result["pack_size"] = f"{pack_count}x{single_label}" if pack_count > 1 else single_label
    elif unit_kind == "ml" and unit_amount is not None:
        total_ml = unit_amount * pack_count
        result["net_volume_ml"] = total_ml
        result["pack_count"] = pack_count
        single_label = _format_single_size(unit_amount, "ml")
        result["pack_size"] = f"{pack_count}x{single_label}" if pack_count > 1 else single_label
    elif pack_count > 1:
        result["pack_count"] = pack_count
        result["pack_size"] = f"{pack_count}pcs"

    barcode = extract_ean_gtin(raw_payload)
    if barcode:
        result["ean"] = barcode

    return result


def extract_grocery_brand(title: str, raw_brand: Optional[str] = None) -> str:
    """Resolve canonical Egyptian grocery brand from raw brand or title (EN & AR)."""
    for haystack in (raw_brand or "", title):
        low = haystack.strip().lower()
        if not low:
            continue
        for needle, canonical in _GROCERY_BRAND_PATTERNS:
            if needle in low:
                return canonical

    candidate = (raw_brand or "").strip()
    if candidate and candidate.lower() not in {"generic", "other", "none", "null", "brand", "unbranded"}:
        if candidate.isupper() and len(candidate) > 3:
            return candidate.title()
        return candidate[:100]

    first_token = title.strip().split(" ", 1)[0] if title.strip() else ""
    cleaned = re.sub(r"[^A-Za-z0-9\u0600-\u06FF.\-+']", "", first_token)
    if cleaned:
        return cleaned.title() if cleaned.isupper() and len(cleaned) > 3 else cleaned[:100]
    return "Unknown"


def refine_grocery_sub_category(title: str, default_sub: str) -> str:
    """Classify a grocery item into one of the 7 Egyptian household sub-categories."""
    low = title.lower()
    for sub_cat, keywords in _SUBCAT_KEYWORDS:
        if any(kw in low for kw in keywords):
            return sub_cat
    if default_sub in GROCERY_SUB_CATEGORIES:
        return default_sub
    return "canned_sauces"


def compute_grocery_barcode_key(record: RawProductSnapshot) -> Optional[str]:
    """Return `grocery_gtin_<digits>` if a valid 8–14 digit EAN/GTIN barcode is present."""
    attrs = record.attributes_json or {}
    for key in ("ean", "gtin", "gtin13", "gtin14"):
        raw_code = attrs.get(key)
        if raw_code is not None:
            digits = re.sub(r"\D", "", str(raw_code).strip())
            if _EAN_GTIN_RE.match(digits):
                return f"grocery_gtin_{digits}"
    return None


def compute_grocery_size_key(record: RawProductSnapshot) -> Optional[str]:
    """
    Return strict `groc_<brand>_<core_tokens>_<exact_weight_or_volume>_x<pack_count>` key.
    Returns None if brand or exact net_weight_g/net_volume_ml is missing.
    """
    attrs = record.attributes_json or {}
    brand_slug = normalize_snake_slug(
        extract_grocery_brand(record.product_title, record.brand),
        fallback="unknown",
        max_len=32,
    )
    if not brand_slug or brand_slug == "unknown":
        return None

    parsed = parse_grocery_packaging(record.product_title)
    weight_g = attrs.get("net_weight_g") if isinstance(attrs.get("net_weight_g"), int) else parsed.get("net_weight_g")
    volume_ml = attrs.get("net_volume_ml") if isinstance(attrs.get("net_volume_ml"), int) else parsed.get("net_volume_ml")
    pack_count = attrs.get("pack_count") if isinstance(attrs.get("pack_count"), int) else parsed.get("pack_count", 1)

    if weight_g is None and volume_ml is None:
        return None

    size_parts: list[str] = []
    if weight_g is not None:
        size_parts.append(f"w{int(weight_g)}g")
    if volume_ml is not None:
        size_parts.append(f"v{int(volume_ml)}ml")
    size_parts.append(f"x{int(pack_count or 1)}")
    size_sig = "_".join(size_parts)

    # Strip packaging specs, punctuation, and filler words from title
    text = record.product_title.translate(_ARABIC_DIGITS_MAP)
    text = _MULTIPACK_UNIT_RE.sub(" ", text)
    text = _SINGLE_UNIT_RE.sub(" ", text)
    text = _PACK_COUNT_RE.sub(" ", text)
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text).lower()

    brand_tokens = set(brand_slug.split("_"))
    core_tokens: list[str] = []
    for tok in text.split():
        if not tok or tok.isdigit():
            continue
        if tok in brand_tokens or tok in _GROCERY_MATCH_STOP_WORDS:
            continue
        if tok not in core_tokens:
            core_tokens.append(tok)
        if len(core_tokens) >= 4:
            break

    if not core_tokens:
        return None

    core_slug = "_".join(core_tokens)
    return normalize_snake_slug(f"groc_{brand_slug}_{core_slug}_{size_sig}", max_len=160)


def compute_grocery_candidate_key(record: RawProductSnapshot) -> Optional[str]:
    """
    Strict cross-store matching key for `category == "groceries"`:
      1. Exact EAN/GTIN barcode (`grocery_gtin_<digits>`) when present.
      2. Otherwise: `normalized_brand + core_product_tokens + exact net_weight_g / net_volume_ml / pack_count`.
         NEVER matches products lacking verified weight/volume or differing in package size/pack_count.
    """
    return compute_grocery_barcode_key(record) or compute_grocery_size_key(record)
