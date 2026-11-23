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
from .units import parse_unit_spec

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
    ("shaheen", "Shaheen"),
    ("شاهين", "Shaheen"),
    ("imtenan", "Imtenan"),
    ("امتنان", "Imtenan"),
    ("إمتنان", "Imtenan"),
    ("isis", "Isis"),
    ("إيزيس", "Isis"),
    ("ايزيس", "Isis"),
    ("el rashidi", "El Rashidi El Mizan"),
    ("الرشيدي", "El Rashidi El Mizan"),
    ("halwani", "Halwani"),
    ("حلواني", "Halwani"),
    ("lavazza", "Lavazza"),
    ("لافاتزا", "Lavazza"),
    ("davidoff", "Davidoff"),
    ("دافيدوف", "Davidoff"),
    ("jacobs", "Jacobs"),
    ("جاكوبس", "Jacobs"),
    ("starbucks", "Starbucks"),
    ("ستاربكس", "Starbucks"),
    ("illy", "Illy"),
    ("knorr", "Knorr"),
    ("كنور", "Knorr"),
    ("maggi", "Maggi"),
    ("ماجي", "Maggi"),
    ("indomie", "Indomie"),
    ("إندومي", "Indomie"),
    ("اندومي", "Indomie"),
    ("nido", "Nido"),
    ("نيدو", "Nido"),
    ("lurpak", "Lurpak"),
    ("لورباك", "Lurpak"),
    ("puck", "Puck"),
    ("بوك", "Puck"),
    ("red bull", "Red Bull"),
    ("ريد بول", "Red Bull"),
    ("شويبس", "Schweppes"),
    ("فيروز", "Fayrouz"),
    ("كوكاكولا", "Coca-Cola"),
    ("سبرايت", "Sprite"),
    ("فانتا", "Fanta"),
    ("ميرندا", "Mirinda"),
    ("7up", "7Up"),
    ("سفن اب", "7Up"),
    ("alpro", "Alpro"),
    ("twinings", "Twinings"),
    ("tilda", "Tilda"),
    ("el bawab", "El Bawab"),
    ("البواب", "El Bawab"),
    ("أطياب", "Atyab"),
    ("اطياب", "Atyab"),
    ("atyab", "Atyab"),
    ("nutella", "Nutella"),
    ("نوتيلا", "Nutella"),
    ("ferrero", "Ferrero"),
    ("cadbury", "Cadbury"),
    ("كادبوري", "Cadbury"),
    ("galaxy", "Galaxy"),
    ("جلاكسي", "Galaxy"),
    ("lindt", "Lindt"),
    ("kitkat", "KitKat"),
    ("oreo", "Oreo"),
    ("أوريو", "Oreo"),
    ("اوريو", "Oreo"),
    ("pringles", "Pringles"),
    ("برينجلز", "Pringles"),
    ("lays", "Lays"),
    ("ليز", "Lays"),
    ("doritos", "Doritos"),
    ("دوريتوس", "Doritos"),
    ("chipsy", "Chipsy"),
    ("شيبسي", "Chipsy"),
    ("bisco misr", "Bisco Misr"),
    ("بسكو مصر", "Bisco Misr"),
    ("corona", "Corona"),
    ("كورونا", "Corona"),
    ("molto", "Molto"),
    ("مولتو", "Molto"),
    ("todo", "Todo"),
    ("تودو", "Todo"),
    ("el shamadan", "El Shamadan"),
    ("الشمعدان", "El Shamadan"),
    ("mcvities", "McVities"),
    ("loacker", "Loacker"),
    ("kelloggs", "Kelloggs"),
    ("كيلوجز", "Kelloggs"),
    ("quaker", "Quaker"),
    ("كويكر", "Quaker"),
    ("dobella", "Dobella"),
    ("دوبلا", "Dobella"),
    ("lino", "Lino"),
    ("لينو", "Lino"),
    ("hero", "Hero"),
    ("هيرو", "Hero"),
    ("good france", "Good France"),
    ("president", "President"),
    ("بريزيدن", "President"),
    ("الضحي", "El Doha"),
    ("الملكه", "El Maleka"),
    ("العروسه", "El Arosa"),
    ("جهينه", "Juhayna"),
    ("عافيه", "Afia"),
    ("جنه", "Ganna"),
    ("حلوه", "Helwa"),
    ("بركه", "Baraka"),
    ("نستله", "Nestle"),
    ("فيبا", "Feba"),
    ("اوكسي", "Oxi"),
    # Pet care major brands (enables exact weight-strict matching across happet / amin_pet_shop / supermarkets)
    ("royal canin", "Royal Canin"),
    ("purina pro plan", "Purina Pro Plan"),
    ("pro plan", "Purina Pro Plan"),
    ("friskies", "Friskies"),
    ("felix", "Felix"),
    ("whiskas", "Whiskas"),
    ("sheba", "Sheba"),
    ("josera", "Josera"),
    ("monge", "Monge"),
    ("gemon", "Gemon"),
    ("oasy", "Oasy"),
    ("schesir", "Schesir"),
    ("farmina", "Farmina"),
    ("reflex", "Reflex"),
    ("bonacibo", "BonaCibo"),
    ("miglior", "Miglior"),
    ("leonardo", "Leonardo"),
    ("happy cat", "Happy Cat"),
    ("happy dog", "Happy Dog"),
    ("beaphar", "Beaphar"),
    ("mera", "Mera"),
    ("brit", "Brit"),
    ("pedigree", "Pedigree"),
    ("applaws", "Applaws"),
    ("carnilove", "Carnilove"),
    ("dr clauder", "Dr Clauder"),
    ("dr. clauder", "Dr Clauder"),
    ("taste of the wild", "Taste Of The Wild"),
    ("acana", "Acana"),
    ("orijen", "Orijen"),
    ("sanabelle", "Sanabelle"),
    ("hills", "Hills"),
    ("hill's", "Hills"),
    ("vitakraft", "Vitakraft"),
    ("biokat", "Biokat"),
    ("ever clean", "Ever Clean"),
    ("cat's best", "Cats Best"),
    ("cats best", "Cats Best"),
    ("lurpak", "Lurpak"),
    ("nido", "Nido"),
    ("نيدو", "Nido"),
    ("red bull", "Red Bull"),
    ("lipton", "Lipton"),
    # --- Wave 3 dictionary expansion (observed unmatched AR/EN pairs) ---
    ("labanita", "Labanita"),
    ("لبانتا", "Labanita"),
    ("لابنتا", "Labanita"),
    ("rotana", "Rotana"),
    ("روتانا", "Rotana"),
    ("rich bake", "Rich Bake"),
    ("ريتش بيك", "Rich Bake"),
    ("loacker", "Loacker"),
    ("لوكر", "Loacker"),
    ("tilda", "Tilda"),
    ("تيلدا", "Tilda"),
    ("avanti", "Avanti"),
    ("أفانتي", "Avanti"),
    ("wunder", "Wunder"),
    ("وندر", "Wunder"),
    ("sheraton", "Sheraton"),
    ("شيراتون", "Sheraton"),
    ("el nile", "El Nile"),
    ("النيل", "El Nile"),
    ("brunch", "Brunch"),
    ("برانش", "Brunch"),
    ("add me", "Add Me"),
    ("add-me", "Add Me"),
    ("اد مي", "Add Me"),
    ("hla ", "Hla"),
    ("هلا ", "Hla"),
    ("risovi", "Risovi"),
    ("ريسوفي", "Risovi"),
    ("misty", "Misty"),
    ("ميستي", "Misty"),
    ("pasta zara", "Pasta Zara"),
    ("زارا", "Pasta Zara"),
    ("fresco", "Fresco"),
    ("فرِسκο", "Fresco"),
    ("فرسكو", "Fresco"),
    ("faragello", "Faragello"),
    ("فراجيلو", "Faragello"),
    ("kaha", "Kaha"),
    ("كها", "Kaha"),
    ("rayeb", "Rayeb"),
    ("ريابي", "Rayeb"),
    ("primo", "Primo"),
    ("بريمو", "Primo"),
    ("san simone", "San Simone"),
    ("كتكوت", "Kotkot"),
    ("kotkot", "Kotkot"),
    ("fine tissues", "Fine"),
    ("فين تيشو", "Fine"),
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

    # 3. Fallback to shared bilingual unit parser (handles Arabic fractions like
    #    `ربع كيلو`, `نص كيلو`, `ثمن كيلو`, `نص لتر`, `دستة`, `باوند`, URL-encoded variants)
    if unit_kind is None:
        uspec = parse_unit_spec(title, variant_label=extra_text or None)
        if not uspec.has_ambiguous_multi_size:
            if uspec.weight_g:
                unit_kind = "g"
                unit_amount = uspec.weight_g
                if pack_count == 1 and uspec.pack_count > 1:
                    pack_count = uspec.pack_count
            elif uspec.volume_ml:
                unit_kind = "ml"
                unit_amount = uspec.volume_ml
                if pack_count == 1 and uspec.pack_count > 1:
                    pack_count = uspec.pack_count
            elif pack_count == 1 and uspec.pack_count > 1:
                pack_count = uspec.pack_count

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
    if (
        candidate
        and candidate.lower() not in {"generic", "other", "none", "null", "brand", "unbranded", "el", "al"}
    ):
        if candidate.isupper() and len(candidate) > 3:
            return candidate.title()
        return candidate[:100]

    # Fallback: leading title tokens. Arabic definite article ("El/Al" + name)
    # needs two tokens — "El Masa" and "El Matbakh" must stay different brands.
    tokens = title.strip().split(" ", 2) if title.strip() else []
    first_token = re.sub(r"[^A-Za-z0-9\u0600-\u06FF.\-+']", "", tokens[0]) if tokens else ""
    if first_token and first_token[:1].isalpha() and first_token.lower() in {"el", "al", "el-", "al-"}:
        second = re.sub(r"[^A-Za-z0-9\u0600-\u06FF.\-+']", "", tokens[1]) if len(tokens) > 1 else ""
        if second:
            candidate = f"{first_token} {second}".strip()
        else:
            candidate = first_token
    elif first_token:
        candidate = first_token
    else:
        return "Unknown"
    cleaned = candidate
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
    """Return `grocery_gtin_<digits>` if a valid 8–14 digit EAN/GTIN barcode is present.

    Rejects GS1 in-store restricted circulation / variable-weight PLU barcodes
    (prefix `20`–`29`) that collide across unrelated deli/nuts items between stores.
    """
    attrs = record.attributes_json or {}
    for key in ("ean", "gtin", "gtin13", "gtin14"):
        raw_code = attrs.get(key)
        if raw_code is not None:
            digits = re.sub(r"\D", "", str(raw_code).strip())
            if _EAN_GTIN_RE.match(digits):
                if len(digits) == 13 and digits[:2] in {f"2{d}" for d in range(10)}:
                    continue
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

    vlabel = str(attrs.get("variant_label") or "")
    parsed = parse_grocery_packaging(record.product_title, extra_text=vlabel)
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


# ---------------------------------------------------------------------------
# Pass-3 type matching: bilingual AR <-> EN product-type nouns so an Arabic
# title ("سمن بقرى 1400 جرام") matches its English counterpart ("Fern Ghee
# 1400g") at another store that carries no barcode. STRICT by design: the key
# requires canonical brand + product-type noun + exact package size, and
# scent/flavor words (Lavender vs Regular, Guava vs Mango) become part of the
# key whenever present — different flavors never merge.
# ---------------------------------------------------------------------------

# Canonical English type nouns, keyed by bilingual spellings.
_GROCERY_TYPE_AR: tuple[tuple[str, str], ...] = (
    ("حليب", "milk"),
    ("لبن رايب", "yogurt"),
    ("لبن", "yogurt"),
    ("زبادي", "yogurt"),
    ("جبنة", "cheese"),
    ("جبن", "cheese"),
    ("الجبن", "cheese"),
    ("زبدة", "butter"),
    ("قشطة", "cream"),
    ("كريمة", "cream"),
    ("عصير", "juice"),
    ("مياه", "water"),
    ("ماء", "water"),
    ("شاي", "tea"),
    ("قهوة", "coffee"),
    ("قهوه", "coffee"),
    ("بن", "coffee"),
    ("البن", "coffee"),
    ("نسكافيه", "coffee"),
    ("زيت", "oil"),
    ("سمنة", "ghee"),
    ("سمن", "ghee"),
    ("سكر", "sugar"),
    ("ملح", "salt"),
    ("أرز", "rice"),
    ("ارز", "rice"),
    ("مكرونة", "pasta"),
    ("معكرونة", "pasta"),
    ("دقيق", "flour"),
    ("عدس", "lentils"),
    ("فول", "beans"),
    ("فاصوليا", "beans"),
    ("تونة", "tuna"),
    ("كاتشب", "ketchup"),
    ("صلصة", "sauce"),
    ("معجون", "paste"),
    ("عسل", "honey"),
    ("طحينة", "tahini"),
    ("مسحوق", "detergent"),
    ("منظف", "detergent"),
    ("صابون", "soap"),
    ("شامبو", "shampoo"),
    ("مناديل", "tissues"),
    ("بسكويت", "biscuits"),
    ("شوكولاتة", "chocolate"),
    ("شيبسي", "chips"),
    ("مرقة", "bouillon"),
    ("بيض", "eggs"),
)

# English type nouns recognized in EN titles (canonical word -> itself).
_GROCERY_TYPE_EN: frozenset[str] = frozenset(
    {
        "milk", "cheese", "butter", "yogurt", "yoghurt", "cream", "juice", "water",
        "tea", "coffee", "oil", "ghee", "sugar", "salt", "rice", "pasta", "spaghetti",
        "penne", "macaroni", "flour", "lentils", "beans", "tuna", "ketchup",
        "mayonnaise", "mayo", "sauce", "paste", "honey", "tahini", "detergent",
        "soap", "shampoo", "tissues", "biscuits", "cookies", "chocolate", "chips",
        "bouillon", "eggs", "cornflakes", "oats", "vinegar",
    }
)

# Scent / flavor words: when present in a title they become part of the match
# key so Lavender-vs-Regular and Guava-vs-Mango variants never collide. Arabic
# spellings map to the English canonical token so AR and EN titles share keys.
# Pasta shapes, tuna cuts and detergent scents are variants too — they join the
# key for the same reason.
_FLAVOR_WORDS: frozenset[str] = frozenset(
    {
        "lavender", "vanilla", "mint", "apple", "guava", "mango", "orange", "grape",
        "strawberry", "banana", "pineapple", "berries", "peach", "pear", "lemon",
        "flowers", "floral", "breeze", "tropical", "rose", "jasmine", "regular",
        "sesame", "chocolate", "plain", "lavendar",
        "chili", "spicy", "tomato", "cocktail", "vermicelli", "rings", "penne",
        "fusilli", "spaghetti", "macaroni", "elbow", "rigate", "spirali",
        "farfalle", "shredded", "chunks", "chunk", "flakes", "beyti", "skimmed",
        "lactose", "fat", "express", "smoked", "pickle", "olive",
        "bukhoor", "downy", "light", "medium", "dark", "green", "black",
        "charcoal", "snowy", "crystal_clean", "vegan", "white", "yellow",
        "hazelnut", "caramel", "cinnamon", "cardamom", "spiced", "gold",
        "decaf", "espresso", "french",
        "sunflower", "corn", "canola", "olive", "mixed", "vegetable",
    }
)

# English flavor spelling variants -> canonical token.
_EN_FLAVOR_SYNONYMS: dict[str, str] = {
    "xpress": "express",
    "chilli": "chili",
    "mahaweg": "spiced",
    "mehaweg": "spiced",
    "sada": "plain",
}

_AR_FLAVOR_TO_EN: dict[str, str] = {
    "لافندر": "lavender",
    "باللافندر": "lavender",
    "فانيلا": "vanilla",
    "فانيليا": "vanilla",
    "نعنع": "mint",
    "نعناع": "mint",
    "تفاح": "apple",
    "مانجو": "mango",
    "جوافة": "guava",
    "جوافه": "guava",
    "برتقال": "orange",
    "عنب": "grape",
    "فراولة": "strawberry",
    "فراوله": "strawberry",
    "موز": "banana",
    "ليمون": "lemon",
    "اناناس": "pineapple",
    "أناناس": "pineapple",
    "خوخ": "peach",
    "كمثرى": "pear",
    "جزر": "carrot",
    "روز": "rose",
    "ياسمين": "jasmine",
    "زهر": "orange_blossom",
    "بندق": "hazelnut",
    "بالبندق": "hazelnut",
    "كراميل": "caramel",
    "قرفة": "cinnamon",
    "حبهان": "cardamom",
    "سادة": "plain",
    "ساده": "plain",
    "محوج": "spiced",
    "محوجة": "spiced",
    "فاتح": "light",
    "وسط": "medium",
    "غامق": "dark",
    "عباد": "sunflower",
    "دوار": "sunflower",
    "ذرة": "corn",
    "ذره": "corn",
    "زيتون": "olive",
    "تركي": "turkish",
    "فرنساوي": "french",
    "اسبريسو": "espresso",
}


def _strip_arabic_prefix(token: str) -> str:
    """Strip the definite article 'ال' so 'الجبن' and 'جبن' compare equal."""
    if token.startswith("ال") and len(token) > 4:
        return token[2:]
    return token


def compute_grocery_type_key(record: RawProductSnapshot) -> Optional[str]:
    """
    Pass-3 strict key: `groc_type_<brand>_<type_noun>_<flavor?>_<exact size>`.

    Requires canonical brand + a recognized bilingual product-type noun +
    exact net weight/volume + pack count. Scent/flavor words join the key when
    present, so 'Persil Gel Lavender 2.65L' and 'Persil Gel Regular 3.9L' never
    merge, while 'Fern سمن بقرى 1400g' and 'Fern Ghee 1400g' do.
    """
    attrs = record.attributes_json or {}
    brand_slug = normalize_snake_slug(
        extract_grocery_brand(record.product_title, record.brand),
        fallback="unknown",
        max_len=32,
    )
    if not brand_slug or brand_slug == "unknown":
        return None

    vlabel = str(attrs.get("variant_label") or "")
    parsed = parse_grocery_packaging(record.product_title, extra_text=vlabel)
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

    text = record.product_title.translate(_ARABIC_DIGITS_MAP)
    text = _MULTIPACK_UNIT_RE.sub(" ", text)
    text = _SINGLE_UNIT_RE.sub(" ", text)
    text = _PACK_COUNT_RE.sub(" ", text)
    # Drop promo bundle tails ("+ Knorr Mix 70G") — bundles are store-specific
    # promos, and their freebie contents must not influence the key.
    text = re.sub(r"\s*\+.*$", " ", text)

    # 1. Bilingual type noun (first Arabic match wins, then English tokens).
    type_noun: Optional[str] = None
    low = text.lower()
    for needle, canonical in _GROCERY_TYPE_AR:
        if needle in low:
            type_noun = canonical
            break
    flavors: list[str] = []

    tokens = re.findall(r"[A-Za-z\u0600-\u06FF]+", text)
    for tok in tokens:
        low_tok = _strip_arabic_prefix(tok.lower())
        if type_noun is None and low_tok in _GROCERY_TYPE_EN:
            type_noun = low_tok
        flavor_en = _AR_FLAVOR_TO_EN.get(tok) or _AR_FLAVOR_TO_EN.get(low_tok)
        if flavor_en:
            if flavor_en not in flavors:
                flavors.append(flavor_en)
        else:
            low_flavor = _EN_FLAVOR_SYNONYMS.get(low_tok) or (
                tok.lower() if tok.lower() in _FLAVOR_WORDS else None
            )
            if low_flavor:
                canon_flavor = _EN_FLAVOR_SYNONYMS.get(low_flavor, low_flavor)
                if canon_flavor not in flavors:
                    flavors.append(canon_flavor)

    if not type_noun:
        return None

    # Order-insensitive: "shredded express" and "express shredded" are the same
    # product described differently across stores.
    flavor_slug = f"_fl_{('_'.join(sorted(flavors[:2])))}" if flavors else ""
    return normalize_snake_slug(
        f"groc_type_{brand_slug}_{type_noun}{flavor_slug}_{size_sig}",
        max_len=160,
    )
