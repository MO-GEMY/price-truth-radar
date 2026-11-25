"""High-Recall, High-Precision Local RAM Cross-Store Entity Resolution Pipeline.

Architecture (single streaming Neon read, zero O(N^2) DB joins, delta-only upsert):
  Pass 0 — Unified Brand Inference (AR+EN brand dictionary + catalog phonetic
           resolver via `bilingual_search.py`), Bilingual Canonicalization,
           and Hard Spec Profile Extraction per SKU.
  Pass 1 — Exact Identifier Graph (checksum-verified EAN-13 / GTIN-14 / MPN)
           across distinct stores.
  Pass 2 — Structured Vertical Keys + Cross-Subcategory Alphanumeric Model-Code
           Matching `(inferred_brand, model_code)` across all categories.
  Pass 3 — TF-IDF Weighted Sparse Cosine Similarity (`>= 0.78`) inside
           `(inferred_brand, coarse_domain, is_accessory)` blocks using a
           pure-Python sparse inverted index (O(B), zero external deps).
  Pass 4 — Hard Spec Guards + Price Sanity (`<= 2.5x`) + Diameter-Checked
           Union-Find (`GuardedUnionFind`) so transitive chaining NEVER creates
           impure clusters.
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .base import RawProductSnapshot, normalize_snake_slug
from .groceries import (
    compute_grocery_barcode_key,
    compute_grocery_size_key,
    compute_grocery_type_key,
    extract_grocery_brand,
)
from .matcher_verticals import (
    _FOOTWEAR_BRANDS,
    _HB_BRAND_ALIASES,
    _PERFUME_CONC_PATTERNS,
    _HEALTH_FORM_RE,
    _is_bundle_or_promo,
    effective_category,
    extract_footwear_features,
    extract_hb_form,
    extract_health_beauty_features,
    is_accessory_listing,
    is_collapsed_multiprice_variant,
    is_footwear_record,
    resolve_footwear_brand,
    resolve_hb_brand,
)
from .units import UnitSpec, normalize_unit_text, parse_unit_spec, units_conflict

# Import unified bilingual semantic & phonetic module from `web_app/backend/app`
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "web_app" / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.bilingual_search import (  # noqa: E402
    CatalogPhoneticIndex,
    canonicalize_bilingual_text,
    has_arabic,
    normalize_arabic_text,
    split_glued_units,
)

# ---------------------------------------------------------------------------
# Constants, Regexes, and Guardrail Vocabularies
# ---------------------------------------------------------------------------

_COARSE_DOMAIN_BY_CAT: dict[str, str] = {
    "electronics": "tech_appliances",
    "home_appliances": "tech_appliances",
    "health": "health_beauty",
    "beauty": "health_beauty",
    "groceries": "groceries_pet",
    "pet_care": "groceries_pet",
    "fashion": "fashion_sports",
    "sports": "fashion_sports",
    "home_furniture": "home_furniture",
    "baby_kids": "baby_kids",
}

# Store slugs that are retailers/marketplaces, NOT product brands
_PLACEHOLDER_BRANDS: frozenset[str] = frozenset(
    {
        "", "unknown", "generic", "other", "none", "null", "brand", "unbranded",
        "my_store", "my store", "default", "n_a", "na", "no_brand", "various",
        "kaufen_egypt_online_store", "shamy_stores", "shamystores", "el_araby_group",
        "elaraby", "ehab_center", "btech", "raneen", "rayashop", "compumarts",
        "sigma", "hardware_market", "smartkoshk", "dream2000", "dubaiphone",
        "ennap", "up_to_date_eg", "ahw_store", "alfrensia", "kimostore", "myxprs",
        "amazon_eg", "amazon", "noon", "jumia_eg", "jumia", "2b", "cairosales",
        "egyptlaptop", "elbadr", "compuscience", "tradeline", "seoudi", "spinneys",
        "hyperone", "metro_market", "gourmet", "carrefour_eg", "carrefour",
        "chefaa", "el_ezaby", "seif_pharmacies", "misr_pharmacies", "roshdy_pharmacies",
        "bloom_pharmacy", "soukare_eg", "yodawy", "tdawi", "beseha", "source_beauty",
        "bashrety", "homzmart", "efreshli", "in_and_out", "egysupps", "ifit_eg",
        "gofit_eg", "mfsupps_eg", "powerstore_eg", "mr_vitamins_eg", "protein_house_eg",
        "house_of_supplements", "super_supplements", "wayup_sports", "intersport_eg",
        "gosport_eg", "athlete_home", "union_sport", "happet", "amin_pet_shop",
        "pets_egypt", "egypuppy", "hedeya", "kassem_store", "bingo_toys", "le3ab_store",
        "diwan_books", "samir_and_aly", "shorouk_books", "bernasos", "faces_eg", "mazaya_eg",
    }
)

# Official single-brand stores where store_name itself reliably implies the brand
_SINGLE_BRAND_STORE_MAP: dict[str, str] = {
    "adidas_eg": "adidas",
    "puma_eg": "puma",
    "ikea_eg": "ikea",
    "zanussi_eg": "zanussi",
    "unionaire_eg": "unionaire",
    "sokany_eg": "sokany",
    "decathlon_eg": "decathlon",
    "bobana": "bobana",
    "eva_cosmetics": "eva",
    "bless_eg": "bless",
    "raw_african": "raw_african",
    "the_hair_addict": "the_hair_addict",
    "hayah_labs": "hayah",
    "cleo_labs": "cleo",
    "melano_pharma": "melano",
    "dermaelle": "dermaelle",
    "telofill_eg": "telofill",
    "neuth_eg": "neuth",
    "norshek": "norshek",
    "eparkville": "eparkville",
    "infinity_clinic": "infinity",
    "nowfoods_eg": "now_foods",
    "organic_nation": "organic_nation",
    "limitless_naturals": "limitless",
    "max_muscle_eg": "max_muscle",
    "kabbani": "kabbani",
    "ariika": "ariika",
    "chichomz": "chichomz",
    "neoflam_eg": "neoflam",
    "nouval_eg": "nouval",
    "oriental_weavers": "oriental_weavers",
    "taki_eg": "taki",
    "bed_janssen": "janssen",
    "janssen_stores": "janssen",
    "mffco": "mffco",
    "town_team": "town_team",
    "mobaco": "mobaco",
    "concrete": "concrete",
    "dalydress": "dalydress",
    "dejavu": "dejavu",
    "carina": "carina",
    "activ": "activ",
    "abu_auf": "abu_auf",
    "imtenan": "imtenan",
}

# Model tier modifiers that MUST match between merged SKUs
_TIER_MODIFIERS: frozenset[str] = frozenset(
    {
        "pro", "max", "plus", "ultra", "mini", "lite", "fe", "se", "air", "neo",
        "ti", "super", "xt", "xtx", "fold", "flip", "slim", "hero", "lcd", "td", "anc",
        "prime", "note", "edge", "gt", "xl", "xxl",
    }
)
# Standalone `x` acts as tier modifier only in electronics/tech (e.g. G502 X vs G502 HERO, iPhone X)
_TECH_EXTRA_TIERS: frozenset[str] = frozenset({"x"})

# Common non-brand generic English/Arabic material/room/adjective words that MUST NEVER
# be auto-discovered as brands from multi-store listings (prevents e.g. "Memory Foam Pillow"
# across private-label bedding stores from inferring brand="memory").
_NON_BRAND_WORDS: frozenset[str] = frozenset(
    {
        "memory", "foam", "gel", "cotton", "silk", "wool", "linen", "velvet", "leather",
        "pocket", "spring", "orthopedic", "medical", "latex", "quilt", "duvet", "bed", "cushion",
        "wood", "wooden", "metal", "steel", "stainless", "glass", "ceramic", "granite",
        "marble", "plastic", "silicone", "bamboo", "fabric", "microfiber", "polyester",
        "pillow", "pillows", "mattress", "blanket", "towel", "sheet", "sheets", "curtain",
        "carpet", "rug", "sofa", "chair", "table", "desk", "lamp", "mirror", "clock",
        "frame", "vase", "cookware", "kitchenware", "kitchen", "dining", "living",
        "bedroom", "bathroom", "outdoor", "garden", "office", "travel", "school",
        "baby", "kids", "junior", "youth", "sport", "sports", "fitness", "active",
        "classic", "modern", "urban", "royal", "luxury", "premium", "basic", "essential",
        "essentials", "studio", "collection", "house", "world", "planet", "market",
        "shop", "store", "egypt", "cairo", "arab", "magic", "wonder", "super", "mega",
        "ultra", "power", "energy", "pure", "organic", "natural", "healthy", "fresh",
        "green", "blue", "red", "pink", "gold", "silver", "black", "white", "grey",
        "gray", "brown", "beige", "navy", "dark", "light", "soft", "hard", "heavy",
        "smart", "digital", "electric", "manual", "portable", "mini", "extra", "double",
        "single", "triple", "multi", "combo", "bundle", "set", "kit", "pack", "box",
        "pro", "max", "plus", "lite", "air", "slim", "prime", "elite", "master", "expert",
        "beauty", "care", "health", "wellness", "pharma", "clinic", "lab", "labs",
        "fashion", "style", "wear", "design", "art", "craft", "gift", "gifts", "toy", "toys",
        "food", "foods", "drink", "drinks", "coffee", "tea", "water", "milk", "cream",
        "oil", "honey", "spice", "sweet", "chocolate", "snack", "snacks", "pet", "pets",
        "cat", "dog", "animal", "animals", "book", "books", "paper", "pen", "note",
    }
)

# Extra curated Egyptian kitchenware / home / baby / toy / pet brands for Pass 0 recovery
_EXTRA_CURATED_BRANDS: dict[str, str] = {
    "luminarc": "luminarc",
    "لومينارك": "luminarc",
    "pyrex": "pyrex",
    "بايركس": "pyrex",
    "pasabahce": "pasabahce",
    "arcoroc": "arcoroc",
    "zahran": "zahran",
    "زهران": "zahran",
    "elzenouki": "elzenouki",
    "الزنوكي": "elzenouki",
    "neoflam": "neoflam",
    "نيوفلام": "neoflam",
    "nouval": "nouval",
    "نوفال": "nouval",
    "berlinger haus": "berlinger_haus",
    "taki": "taki",
    "تاكي": "taki",
    "janssen": "janssen",
    "يانسن": "janssen",
    "habitat": "habitat",
    "هابيتات": "habitat",
    "oriental weavers": "oriental_weavers",
    "النساجون الشرقيون": "oriental_weavers",
    "chicco": "chicco",
    "شيكو": "chicco",
    "avent": "philips_avent",
    "philips avent": "philips_avent",
    "pampers": "pampers",
    "بامبرز": "pampers",
    "molfix": "molfix",
    "مولفيكس": "molfix",
    "babyjoy": "babyjoy",
    "بيبي جوي": "babyjoy",
    "lego": "lego",
    "ليجو": "lego",
    "hot wheels": "hot_wheels",
    "barbie": "barbie",
    "fisher price": "fisher_price",
    "fisher-price": "fisher_price",
    "intex": "intex",
    "bestway": "bestway",
    "rastar": "rastar",
    "maisto": "maisto",
    "lorelli": "lorelli",
    "royal canin": "royal_canin",
    "رويال كانين": "royal_canin",
    "whiskas": "whiskas",
    "friskies": "friskies",
    "purina": "purina",
    "pedigree": "pedigree",
    "josera": "josera",
    "leonardo": "leonardo",
    "reflex": "reflex",
    "promaster": "promaster",
    "kajito": "kajito",
    "syinix": "syinix",
    "سينكس": "syinix",
    "meetion": "meetion",
}

# Generic alphanumeric tokens that look like model codes (letters+digits) but are NOT model codes!
_GENERIC_SPEC_CODE_RE = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+)?(?:gb|tb|mb|kb|ml|mls|milliliters?|millilitres?|l|ltr|ltrs|liters?|litres?|"
    r"kg|kgs|kilos?|kilograms?|g|gm|gms|grams?|mg|mcg|iu|oz|ounces?|lb|lbs|pounds?|"
    r"hp|btu|w|watt|watts|kw|v|volts?|hz|khz|mhz|ghz|mah|wh|mp|mm|cm|m|ft|feet|in|inch|inches|"
    r"p|k|g|fps|dpi|ms|db|bar|rpm|deg|h|hr|hrs|d|yr|yrs|y|pcs|pc|pieces?|pk|ct|s|x|b|"
    r"serv|servs|serving|servings|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|softgel|softgels|scoop|scoops|"
    r"door|doors|mbps|gbps|mode|modes|stage|stages|blade|blades|burner|burners|speed|speeds|port|ports|pin|pins|fan|fans)$|"
    r"(?:20[12]\d|19\d\d)$|"
    r"(?:ddr[2345]|lpddr[345]x?|gddr[567]x?|pcie\d|sata\d|usb[234]|hdmi\d|dp\d|"
    r"wifi[4567]e?|bt[45]|ip\d{2}k?|hdr\d+|spf\d+|uv[ab]\d*|pa\+*|"
    r"gen\d+|typec|usbc|2in1|3in1|4in1|5in1|6in1|7in1|8in1|10in1|12in1|trimode|dualmode|"
    r"(?:ac|ax|be)\d{3,5}|cl\d{2}|"
    r"[abhxz]\d{3}m?e?|"
    r"cat[5678]e?|pd\d+|qc\d+|r\d{2,3}a?|no\d+|pack\d+|set\d+|size\d+|"
    r"b1|b2|b3|b5|b6|b9|b12|d2|d3|k1|k2|c500|c1000|omega3|coq10|h2o|"
    r"eu\d{2}|uk\d{1,2}|us\d{1,2}|a4|a5|a3|m[1-5]|i[3579]|r[3579]|"
    r"(?:core)?i[3579]\d{4,5}[a-z]{0,2}|(?:ryzen)?r?[3579]\d{4}[a-z]{0,2}|"
    r"ultra[3579]\d{3}[a-z]{0,2}|n[1-9]\d{2,3}|"
    r"(?:rtx|gtx|rx|mx|arc)\d{3,4}[a-z]{0,2}|"
    r"fhd\d*|qhd\d*|uhd\d*|oled\d*|qled\d*|led\d*|lcd\d*|ips\d*|va\d*|"
    r"\d+x\d+(?:x\d+)?)$"
    r")",
    re.I,
)

# Color / finish words separated from core product identity
_COLOR_WORDS: frozenset[str] = frozenset(
    {
        "black", "white", "gray", "grey", "blue", "red", "green", "silver", "gold",
        "pink", "purple", "violet", "orange", "yellow", "brown", "beige", "bronze",
        "copper", "cream", "coral", "cyan", "teal", "mint", "olive", "navy", "indigo",
        "lavender", "lilac", "burgundy", "crimson", "emerald", "graphite", "titanium",
        "platinum", "charcoal", "obsidian", "onyx", "pearl", "ivory", "champagne",
        "midnight", "starlight", "space", "cosmic", "aurora", "shadow", "ocean",
        "cobalt", "dawn", "cloud", "blush", "satin", "pistachio", "mocha", "sapphire",
        "ice", "dark", "light", "deep", "bright", "matte", "glossy", "metallic",
        "natural", "desert", "phantom", "awesome", "mystic", "starry", "glow", "frost",
        "sand", "stone", "slate", "forest", "arctic", "rose", "rosegold", "spacegray",
        "spacegrey", "midnightblack", "darkblue", "lightblue", "skyblue", "navyblue",
        "inox", "stainless", "steel", "chrome", "multicolor", "multi", "assorted",
        "transparent", "clear", "nude", "taupe", "maroon", "turquoise", "khaki",
    }
)

# Store fluff / marketing / warranty / generic stopwords stripped before TF-IDF
_TFIDF_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "and", "with", "for", "from", "by", "in", "on", "of", "to", "a", "an", "or",
        "new", "original", "official", "warranty", "egypt", "version", "global", "local",
        "middle", "east", "international", "free", "shipping", "gift", "offer", "deal",
        "sale", "best", "price", "quality", "high", "edition", "unlocked", "sealed",
        "tax", "paid", "express", "store", "online", "imported", "authentic", "brand",
        "model", "series", "type", "class", "color", "colour", "size", "sizes", "pack",
        "piece", "pieces", "pcs", "pc", "unit", "item", "product", "products", "year",
        "years", "month", "months", "day", "days", "daily", "care", "use", "home",
        "dual", "single", "sim", "esim", "lte", "nfc", "wifi", "bluetooth", "gps", "usb",
        "ram", "rom", "storage", "internal", "memory", "display", "screen", "camera",
        "battery", "android", "ios", "smart", "digital", "electric", "automatic", "auto",
        "full", "built", "builtin", "inch", "inches", "cm", "mm", "kg", "kgs", "g", "gm",
        "gms", "ml", "l", "liter", "liters", "litre", "litres", "watt", "watts", "w",
        "hp", "btu", "gb", "tb", "mb", "hz", "mhz", "ghz", "mah", "mp", "mg", "mcg", "iu",
        "lb", "lbs", "oz", "ft", "feet", "bar", "rpm", "volt", "volts", "v",
        "men", "mens", "women", "womens", "unisex", "kids", "boys", "girls", "adult",
        "tv", "television", "led", "uhd", "fhd", "hd", "4k", "8k", "oled", "qled", "ips",
        "smartphone", "mobile", "phone", "laptop", "notebook", "tablet", "monitor",
        "refrigerator", "fridge", "washing", "machine", "washer", "air", "conditioner",
        "ac", "split", "inverter", "cooling", "heating", "cool", "heat", "only", "no",
        "frost", "nofrost", "defrost", "cooker", "gas", "dishwasher", "microwave",
        "vacuum", "cleaner", "blender", "kettle", "oven", "iron", "fan", "heater",
        "shoes", "shoe", "sneakers", "sneaker", "footwear", "trainers", "running",
        "bottle", "jar", "tube", "box", "pouch", "sachet", "sachets", "caps", "cap",
        "capsule", "capsules", "tabs", "tab", "tablets", "softgels", "servings",
        "supplement", "supplements", "nutrition", "nutritional", "dietary", "formula",
        "skin", "skincare", "hair", "haircare", "body", "face", "facial", "personal",
        "beauty", "cosmetics", "pharma", "labs", "lab", "laboratories", "natural", "pure",
        "edp", "edt", "edc", "eau", "de", "parfum", "toilette", "perfume", "fragrance",
        "upgrade", "upgrades", "os", "large", "small", "medium", "advanced", "picture",
        "engine", "hdr", "hdr10", "receiver", "wired", "wireless", "performance", "gaming",
    }
) | _COLOR_WORDS

# Grocery flavor/scent/shape/cut markers that MUST NOT conflict when matching groceries
_GROCERY_DISTINGUISHERS: frozenset[str] = frozenset(
    {
        # Flavors / juices / dairy / snacks
        "mango", "guava", "orange", "apple", "pineapple", "peach", "strawberry", "banana",
        "cocktail", "grape", "lemon", "lime", "berry", "cherry", "pomegranate", "tomato", "carrot",
        "chocolate", "vanilla", "caramel", "hazelnut", "coffee", "mocha", "cinnamon",
        "honey", "coconut", "almond", "pistachio", "peanut", "mint", "ginger", "hibiscus",
        "plain", "original", "classic", "classics", "pure", "regular", "natural", "unsalted", "salted",
        "spicy", "chili", "chilli", "hot", "pepper", "garlic", "onion", "cheese", "cheddar",
        "feta", "mozzarella", "gouda", "parmesan", "parmigiano", "grana", "padano", "reggiano",
        "edam", "brie", "emmental", "halloumi", "kashkaval", "ricotta", "mascarpone", "roquefort",
        "roumi", "istambouli", "baramili", "olive", "olives",
        "quinoa", "oat", "oats", "soy", "soya", "wholewheat", "chickpea", "buckwheat", "rye", "glutenfree",
        "full", "skimmed", "skim", "lowfat", "halfcream", "fullcream", "lactose", "zero", "diet", "sugarfree",
        # Detergent / home scents
        "lavender", "jasmine", "rose", "floral", "ocean", "fresh", "breeze", "oud", "musk",
        "black", "white", "color", "colors", "gel", "powder", "liquid", "pods", "capsules",
        "automatic", "top", "front", "handwash", "manual", "power",
        # Pasta shapes / rice / tuna cuts / oils
        "penne", "spaghetti", "fusilli", "macaroni", "rings", "big", "small", "elbow",
        "vermicelli", "beyti", "orzo", "lasagna", "fettuccine", "farfalle", "shells",
        "basmati", "egyptian", "white", "brown", "golden", "jasmine",
        "shredded", "chunk", "chunks", "solid", "flakes", "smoked", "sunflower", "corn",
        "canola", "vegetable", "ghee", "butter", "margarine", "green", "red", "decaf",
        "medium", "dark", "light", "roast", "turkish", "brazilian", "colombian", "ethiopian",
        "french", "arabic", "espresso", "instant", "cardamom",
        "whipping", "cooking", "heavy", "sour", "table", "double", "condensed",
        "evaporated", "unsweetened", "sweetened", "greek", "labneh", "sparkling", "still",
    }
)

# Mutually exclusive grocery subtype pairs enforced across ALL passes (even Pass 2a)
_GROCERY_EXCLUSIVE_PAIRS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (frozenset({"whipping"}), frozenset({"cooking"})),
    (frozenset({"powder"}), frozenset({"gel", "liquid"})),
    (frozenset({"sparkling"}), frozenset({"still"})),
    (frozenset({"skimmed", "skim"}), frozenset({"full", "fullcream"})),
    (frozenset({"halfcream"}), frozenset({"fullcream", "skimmed", "skim"})),
    (frozenset({"unsalted"}), frozenset({"salted"})),
    (frozenset({"shredded"}), frozenset({"chunk", "chunks", "solid"})),
    (frozenset({"classic", "classics"}), frozenset({"pure"})),
    (frozenset({"sunflower"}), frozenset({"corn", "olive", "canola"})),
    (frozenset({"corn"}), frozenset({"olive", "canola"})),
)

# Distinct grocery taxonomy sets: if both sides specify a variety (or one specifies a distinct base), never merge!
_CHEESE_VARIETIES: frozenset[str] = frozenset({
    "gouda", "parmesan", "parmigiano", "grana", "padano", "reggiano", "cheddar",
    "feta", "mozzarella", "edam", "brie", "emmental", "halloumi", "kashkaval",
    "roumi", "istambouli", "baramili", "ricotta", "mascarpone", "roquefort",
})
_GRAIN_PLANT_BASES: frozenset[str] = frozenset({
    "quinoa", "almond", "oat", "oats", "soy", "soya", "coconut", "chickpea", "buckwheat", "rye",
})
_SUGAR_FREE_TOKENS: frozenset[str] = frozenset({"zero", "diet", "sugarfree", "unsweetened"})
_COFFEE_ORIGIN_TOKENS: frozenset[str] = frozenset({"brazilian", "colombian", "ethiopian", "french", "arabic"})

# Regexes for hard spec extraction
_DIM_RE = re.compile(r"\b(\d{2,3})\s*[x*×]\s*(\d{2,3})(?:\s*[x*×]\s*(\d{2,3}))?\b", re.I)
_SINGLE_CM_RE = re.compile(r"(?:^|[^0-9])(\d{2,3})\s*(?:cm|سم)(?=$|[^a-z0-9\u0621-\u064a])", re.I)
_NET_5G_RE = re.compile(r"\b5g\b", re.I)
_NET_4G_RE = re.compile(r"\b(?:4g|lte)\b", re.I)
_SCREEN_INCH_RE = re.compile(r"\b(\d{2,3}(?:\.\d)?)\s*(?:\"|''|-?\s*inch(?:es)?\b|بوص[ةه])", re.I)
_HP_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:hp|horsepower|h\.p\.)\b", re.I)
_BTU_RE = re.compile(r"\b(\d{4,6})\s*btu\b", re.I)
_WASHER_KG_RE = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*kg\b", re.I)
_COOKER_CM_RE = re.compile(r"\b(50|55|60|80|90|100)\s*cm\b", re.I)
_COOKER_BURNERS_RE = re.compile(r"\b([3456])\s*(?:gas\s+)?burners?\b", re.I)
_WATTAGE_RE = re.compile(r"\b(\d{2,4})\s*(?:w|watt|watts)\b", re.I)
_REFRESH_HZ_RE = re.compile(r"\b(\d{2,3})\s*hz\b", re.I)
_RAM_MHZ_RE = re.compile(r"\b(\d{4})\s*mhz\b|\bddr[345][\s\-]+(\d{4})\b", re.I)
_DDR_GEN_RE = re.compile(r"\b(ddr[345])\b", re.I)
_BATTERY_MAH_RE = re.compile(r"\b(\d{3,5})\s*mah\b", re.I)
_APPLIANCE_LITERS_RE = re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*(?:l|ltr|ltrs|liter|liters|litre|litres)\b", re.I)
_PSU_EFFICIENCY_RE = re.compile(r"\b(?:80\s*(?:\+|plus)\s*)?(bronze|silver|gold|platinum|titanium)\b", re.I)
_CHIPSET_TOKEN_RE = re.compile(r"\b([abhxz]\d{3}m?e?)\b", re.I)
_ROMAN_GEN_RE = re.compile(r"(?<!sata\s)(?<!pcie\s)(?<!usb\s)(?<!hdmi\s)\b(ii|iii|iv)\b", re.I)
_VERSION_GEN_RE = re.compile(r"\b(?:v([2-9])|gen\s*([2-9])|mark\s*(ii|iii|iv|\d)|mk\s*([2-9]))\b", re.I)
_DECIMAL_VER_RE = re.compile(r"\b([1-9]\.[0-9])\b")
_SUFFIX_S_TIER_RE = re.compile(r"\b\d+\s+s\b(?!\s*(?:gb|tb|w|v|hz|cm|mm|inch|pack|pcs|mode|sec|second))", re.I)
_BOARD_TRIM_WORDS: frozenset[str] = frozenset({
    "aorus", "stealth", "eagle", "elite", "d3hp", "ds3h", "s2h", "ud",
    "rog", "tuf", "strix", "prime", "proart", "mpg", "meg", "mag",
    "carbon", "godlike", "tomahawk", "mortar", "bazooka", "edge", "ice",
    "steel", "legend", "pro4", "hdv", "wifi", "ax", "ac",
})
_BOARD_SINGLE_SUFFIXES: frozenset[str] = frozenset({"k", "h", "p", "a", "m", "e", "f", "x"})

# Explicit device-type classifiers (ordered from most specific to broader)
_DEVICE_TYPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pc_build", re.compile(r"\b(?:desktop\s+pc|gaming\s+pc|pc\s+build|workstation\s+pc|prebuilt|تجميعة|تجميعه)\b", re.I)),
    ("laptop", re.compile(r"\b(?:laptop|notebook|macbook|thinkpad|ideapad|vivobook|zenbook|chromebook|legion\s+\d|loq\s+\d|pavilion|elitebook|probook|inspiron|latitude|vostro|victus|omen\s+\d|aspire\s+\d|nitro\s+[v5]|predator\s+helios|matebook|magicbook)\b", re.I)),
    ("smartphone", re.compile(r"\b(?:smartphone|mobile\s+phone|iphone|galaxy\s+[asmz]\d|redmi\s+note|poco\s+[xfmc]\d)\b", re.I)),
    ("tablet", re.compile(r"\b(?:tablet|ipad|galaxy\s+tab)\b", re.I)),
    ("mousepad", re.compile(r"\b(?:mouse\s*pad|desk\s*mat|gaming\s*mat)\b", re.I)),
    ("mouse", re.compile(r"\b(?:gaming\s+mouse|wireless\s+mouse|wired\s+mouse|optical\s+mouse|bluetooth\s+mouse|mouse)\b|ماوس", re.I)),
    ("keyboard", re.compile(r"\b(?:keyboard|mechanical\s+keyboard|gaming\s+keyboard)\b|كيبورد", re.I)),
    ("headset", re.compile(r"\b(?:headset|headphone|headphones|earphone|earphones|earbuds|airpods|tws)\b|سماعة|سماعه", re.I)),
    ("microphone", re.compile(r"\b(?:microphone|quadcast|solocast|condenser\s+mic)\b|مايكروفون", re.I)),
    ("webcam", re.compile(r"\b(?:webcam|web\s*cam)\b", re.I)),
    ("speaker", re.compile(r"\b(?:speaker|soundbar|subwoofer)\b", re.I)),
    ("monitor", re.compile(r"\b(?:gaming\s+monitor|ips\s+monitor|curved\s+monitor|led\s+monitor|monitor)\b", re.I)),
    ("tv", re.compile(r"\b(?:smart\s+tv|led\s+tv|qled\s+tv|oled\s+tv|uhd\s+tv|4k\s+tv|television|google\s+tv)\b|تلفزيون", re.I)),
    ("extender", re.compile(r"\b(?:wifi\s+extender|range\s+extender|mesh\s+wifi\s+extender|mesh\s+extender|repeater|extender)\b", re.I)),
    ("router", re.compile(r"\b(?:router|modem|access\s+point)\b|راوتر", re.I)),
    ("motherboard", re.compile(r"\b(?:motherboard|mainboard)\b|ماذربورد", re.I)),
    ("psu", re.compile(r"\b(?:power\s+supply|psu|80\s*(?:\+|plus)\s*(?:bronze|silver|gold|platinum|titanium)|full\s+modular)\b|باور\s*سبلاي", re.I)),
    ("gpu", re.compile(r"\b(?:graphics\s+card|video\s+card|vga\s+card)\b|كارت\s*شاش[ةه]", re.I)),
    ("ram", re.compile(r"\b(?:udimm|sodimm|so-dimm|desktop\s+memory|laptop\s+memory|ram\s+kit|memory\s+kit|dimm)\b|رامات", re.I)),
    ("ssd", re.compile(r"\b(?:solid\s+state\s+drive|internal\s+ssd|external\s+ssd|nvme\s+ssd|sata\s+ssd|ssd)\b", re.I)),
    ("pc_case", re.compile(r"\b(?:mid[\s-]?tower|full[\s-]?tower|pc\s+case|gaming\s+case|atx\s+case|chassis)\b", re.I)),
    ("cooler", re.compile(r"\b(?:cpu\s+cooler|liquid\s+cooler|aio\s+cooler|water\s+cooler|air\s+cooler|case\s+fan)\b", re.I)),
    ("printer", re.compile(r"\b(?:printer|laserjet|deskjet|inkjet|scanner)\b|طابعة|طابعه", re.I)),
    ("watch", re.compile(r"\b(?:smartwatch|smart\s+watch|fitness\s+band)\b", re.I)),
    ("dishwasher", re.compile(r"\b(?:dishwasher|dish\s+washer)\b|غسالة\s*اطباق", re.I)),
    ("washer", re.compile(r"\b(?:washing\s+machine|washer)\b|غسالة|غساله", re.I)),
    ("refrigerator", re.compile(r"\b(?:refrigerator|fridge|deep\s+freezer|freezer)\b|ثلاجة|تلاجة|فريزر", re.I)),
    ("ac", re.compile(r"\b(?:air\s+conditioner|split\s+ac)\b|تكييف", re.I)),
    ("cooker", re.compile(r"\b(?:gas\s+cooker|electric\s+cooker|cooker|built[\s-]?in\s+(?:oven|hob)|hob|oven)\b|بوتاجاز|فرن", re.I)),
    ("microwave", re.compile(r"\b(?:microwave)\b|ميكروويف", re.I)),
    ("heater", re.compile(r"\b(?:water\s+heater|gas\s+heater|fan\s+heater|electric\s+heater|heater)\b|سخان|دفاية", re.I)),
    ("vacuum", re.compile(r"\b(?:vacuum\s+cleaner|vacuum)\b|مكنسة|مكنسه", re.I)),
    ("air_fryer", re.compile(r"\b(?:air\s+fryer|aero\s+fry|fryer)\b|قلاية|قلايه", re.I)),
    ("blender", re.compile(r"\b(?:blender|hand\s+blender|food\s+processor|stand\s+mixer|mixer)\b|خلاط|كبة", re.I)),
    ("kettle", re.compile(r"\b(?:kettle)\b|غلاية|غلايه", re.I)),
    ("fan", re.compile(r"\b(?:stand\s+fan|ceiling\s+fan|wall\s+fan|box\s+fan|desk\s+fan|pedestal\s+fan)\b|مروحة|مروحه", re.I)),
)

# Generic non-model sport/fashion descriptors that alone CANNOT justify a Pass 3 match
_GENERIC_FASHION_SPORTS_TOKENS: frozenset[str] = frozenset({
    "cross", "training", "trainer", "trainers", "running", "walking", "lifestyle", "casual",
    "basic", "classic", "sport", "sports", "active", "comfort", "fitness", "outdoor", "indoor",
    "shoes", "shoe", "sneakers", "sneaker", "boots", "boot", "sandals", "sandal", "slippers",
    "slides", "jersey", "shirt", "tshirt", "tee", "polo", "pants", "shorts", "jacket", "hoodie",
    "sweatshirt", "leggings", "joggers", "sweatpants", "swimsuit", "bag", "backpack", "socks",
    "cap", "hat", "pencil", "case", "zipper", "two", "full", "zip", "cotton", "set",
})
_SLASH_RAM_STORAGE_RE = re.compile(r"\b(\d{1,2})\s*(?:gb)?\s*[+/]\s*(32|64|128|256|512|1024)\s*gb\b", re.I)
_SLASH_STORAGE_RAM_RE = re.compile(r"\b(32|64|128|256|512|1024)\s*(?:gb)?\s*[+/]\s*(\d{1,2})\s*gb?\b", re.I)
_CAP_GB_TB_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(tb|gb)\b(?:\s*(?:ram|rom|ssd|hdd|nvme|m\.2|ddr[345]|lpddr[45]x?|storage|internal))?",
    re.I,
)
_CPU_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bapple\s+(m[1-5](?:\s+(?:pro|max|ultra))?)\b", re.I), ""),
    (re.compile(r"\b(m[1-5](?:\s+(?:pro|max|ultra))?)\s+chip\b", re.I), ""),
    (re.compile(r"\b(?:core\s+)?ultra\s+([3579])[\s\-–—]+(\d{3}[a-z]{0,2})\b", re.I), "ultra"),
    (re.compile(r"\b(?:core\s+)?(i[3579])[\s\-–—]+(\d{4,5}[a-z]{0,2})\b", re.I), ""),
    (re.compile(r"\bcore\s+([357])[\s\-–—]+(\d{3}[a-z]?)\b", re.I), "core"),
    (re.compile(r"\bryzen\s+([3579])[\s\-–—]+(\d{4}[a-z]{0,2})\b", re.I), "r"),
)
_GPU_RE = re.compile(r"\b((?:rtx|gtx|rx|mx)\s*\d{3,4}(?:\s*(?:ti|super|xt))?|arc\s*a\d{3})\b", re.I)
_MODEL_CODE_RE = re.compile(r"\b([a-z0-9]+(?:-[a-z0-9]+){0,3})\b", re.I)
_EAN13_RE = re.compile(r"(?:^|[^0-9])(\d{13,14})(?=$|[^0-9])")

_KIDS_RE = re.compile(r"\b(?:kids?|boys?|girls?|youth|junior|jr|infant|toddler|children)\b", re.I)
_WOMEN_RE = re.compile(r"\b(?:women'?s?|woman|ladies|female|wmn|wmns)\b", re.I)
_MEN_RE = re.compile(r"\b(?:men'?s?|man|male)\b", re.I)
_WOMEN_ONLY_STORES: frozenset[str] = frozenset({"dalydress", "carina", "dejavu", "emeli_eg", "palma_eg", "okhtein"})

_BIG_APPLIANCE_TV_RE = re.compile(
    r"\b(?:smart\s+tv|led\s+tv|qled|oled|uhd\s+tv|4k\s+tv|television|refrigerator|fridge|"
    r"washing\s+machine|washer|dishwasher|air\s+conditioner|split\s+ac|deep\s+freezer|"
    r"gas\s+cooker|water\s+heater|microwave)\b",
    re.I,
)


def _valid_ean13(digits: str) -> Optional[str]:
    if len(digits) == 14 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 13 or not digits.isdigit():
        return None
    if len(set(digits)) <= 2 or digits.startswith("00000") or digits[0] == "2":
        return None
    total = sum(int(d) * (1 if idx % 2 == 0 else 3) for idx, d in enumerate(digits[:12]))
    if ((10 - (total % 10)) % 10) == int(digits[12]):
        return digits
    return None


def _normalize_code_str(raw: str) -> str:
    code = re.sub(r"[^a-z0-9]", "", raw.lower())
    digits = sum(c.isdigit() for c in code)
    if digits >= 2:
        code = code.replace("o", "0")
    return code


def _extract_high_entropy_model_codes(canon_text: str, raw_title: str) -> tuple[str, ...]:
    """Extract high-entropy alphanumeric manufacturer model codes (letters + digits, len >= 4).

    Strictly filters out generic specs (`256gb`, `5g`, `4k`, `120hz`, `30serv`, `60caps`,
    `2door`, `300mbps`, `ac1200`, `cl30`, `3mode`, standalone motherboard chipsets `b850m`, etc.).
    """
    # Strip unit/serving/rating expressions first so `55-inch`, `30-serv`, `2-door`, `3-mode` never mimic codes
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?[\s\-]*(?:gb|tb|mb|ml|l|ltr|kg|kgs|g|gm|gms|mg|mcg|iu|oz|lb|lbs|"
        r"hp|btu|w|watt|watts|kw|v|hz|khz|mhz|ghz|mah|wh|mp|mm|cm|ft|inch|inches|fps|dpi|ms|bar|rpm|"
        r"serv(?:ings?)?|tabs?|tablets?|caps?|capsules?|softgels?|scoops?|doors?|mbps|gbps|modes?|stages?)\b",
        " ",
        f"{canon_text} {raw_title}",
        flags=re.I,
    )
    codes: list[str] = []
    seen: set[str] = set()
    for m in _MODEL_CODE_RE.finditer(cleaned):
        raw = m.group(1)
        if not (any(c.isalpha() for c in raw) and any(c.isdigit() for c in raw)):
            continue
        low_raw = raw.lower()
        if _GENERIC_SPEC_CODE_RE.fullmatch(low_raw):
            continue
        norm = _normalize_code_str(low_raw)
        if len(norm) < 4 or len(norm) > 22:
            continue
        if _GENERIC_SPEC_CODE_RE.fullmatch(norm):
            continue
        # Reject pure spec combinations like `16gb512gb` or `8gb256gb` or `128gb5g` or `30serv90tabs`
        if re.fullmatch(r"(?:\d+(?:gb|tb|mb|ml|kg|w|hz|mp|mah|cm|mm|v|hp|in|serv|tabs|caps|door|mode|mbps))+", norm):
            continue
        # Reject Apple regional MPNs on iPhones (e.g. MYEC3ZDA / MFYN4AFA) which differ by region
        if re.fullmatch(r"m[a-z]{2,3}\d[a-z0-9]{2,4}[a-z]?", norm) and "iphone" in canon_text:
            continue
        if norm not in seen:
            seen.add(norm)
            codes.append(norm)
    return tuple(codes[:6])


def _extract_ram_storage(record: RawProductSnapshot, canon_text: str) -> tuple[Optional[int], Optional[int]]:
    attrs = record.attributes_json or {}
    ram_gb = attrs.get("ram_gb") if isinstance(attrs.get("ram_gb"), int) else None
    storage_gb = attrs.get("storage_gb") if isinstance(attrs.get("storage_gb"), int) else None
    if ram_gb is not None and storage_gb is not None:
        return ram_gb, storage_gb

    if m := _SLASH_RAM_STORAGE_RE.search(canon_text):
        ram_gb = ram_gb if ram_gb is not None else int(m.group(1))
        storage_gb = storage_gb if storage_gb is not None else int(m.group(2))
        return ram_gb, storage_gb
    if m := _SLASH_STORAGE_RAM_RE.search(canon_text):
        storage_gb = storage_gb if storage_gb is not None else int(m.group(1))
        ram_gb = ram_gb if ram_gb is not None else int(m.group(2))
        return ram_gb, storage_gb

    gb_vals: list[int] = []
    for num_str, unit in _CAP_GB_TB_RE.findall(canon_text):
        val = float(num_str)
        gb = int(round(val * 1024)) if unit.lower() == "tb" else int(round(val))
        if gb > 0:
            gb_vals.append(gb)
    if gb_vals:
        uniq = sorted(set(gb_vals))
        is_ram_only = bool(
            re.search(r"\b(?:ddr[2345]|udimm|sodimm|so-dimm|desktop\s+memory|laptop\s+memory|memory\s+kit|dimm)\b", canon_text)
        ) and not bool(re.search(r"\b(?:ssd|nvme|hdd|laptop|notebook|iphone|galaxy|redmi|poco|smartphone|tablet|ipad)\b", canon_text))
        if len(uniq) >= 2:
            if ram_gb is None and uniq[0] <= 64:
                ram_gb = uniq[0]
            if storage_gb is None and uniq[-1] >= 32:
                storage_gb = uniq[-1]
        elif len(uniq) == 1:
            if is_ram_only:
                if ram_gb is None:
                    ram_gb = uniq[0]
            elif storage_gb is None and uniq[0] >= 32:
                storage_gb = uniq[0]
            elif ram_gb is None and uniq[0] <= 32:
                ram_gb = uniq[0]
    return ram_gb, storage_gb


@dataclass(frozen=True)
class HardSpecs:
    storage_gb: Optional[int] = None
    ram_gb: Optional[int] = None
    screen_inch: Optional[int] = None
    hp: Optional[str] = None
    unit_spec: UnitSpec = field(default_factory=UnitSpec)
    tiers: frozenset[str] = frozenset()
    network_gen: Optional[str] = None  # "4g" | "5g" | None
    cpu: Optional[str] = None
    gpu: Optional[str] = None
    dimensions: Optional[str] = None
    cm_values: frozenset[int] = frozenset()
    burners: Optional[int] = None
    width_cm: Optional[int] = None
    washer_kg: Optional[str] = None
    washer_load: Optional[str] = None  # "top" | "front" | None
    perfume_conc: Optional[str] = None
    hb_form: Optional[str] = None
    hb_time: Optional[str] = None  # "day" | "night" | None
    gender: Optional[str] = None  # "men" | "women" | "kids" | None
    grocery_distinguishers: frozenset[str] = frozenset()
    discriminative_numbers: frozenset[str] = frozenset()
    # Systemic precision fields (Phase 2)
    device_type: Optional[str] = None
    wattage_w: Optional[int] = None
    psu_efficiency: Optional[str] = None
    refresh_hz: Optional[int] = None
    ram_mhz: Optional[int] = None
    ddr_gen: Optional[str] = None
    battery_mah: Optional[int] = None
    appliance_liters: Optional[float] = None
    frost_type: Optional[str] = None  # "nofrost" | "defrost" | None
    generation_tag: Optional[str] = None  # "ii", "iii", "v2", "2.0", etc.
    chipset: Optional[str] = None
    form_factor: Optional[str] = None  # "atx" | "matx" | "itx" | "eatx" | None
    board_trims: frozenset[str] = frozenset()
    sub_code_suffixes: frozenset[str] = frozenset()  # e.g. `e20`, `x30mv` after shared model code
    size_tier: Optional[str] = None  # "small" | "medium" | "large" | None (toys/furniture)
    pet_clumping: Optional[str] = None  # "clumping" | "non_clumping" | None


@dataclass
class SkuProfile:
    idx: int
    record: RawProductSnapshot
    eff_cat: str
    coarse_domain: str
    brand: str
    is_accessory: bool
    is_bundle: bool
    is_collapsed_variant: bool
    canon_text: str
    core_tokens: tuple[str, ...]
    exact_eans: tuple[str, ...]
    exact_mpns: tuple[str, ...]
    model_codes: tuple[str, ...]
    specs: HardSpecs
    has_big_appliance_tv_cue: bool = False


def _extract_hard_specs(
    record: RawProductSnapshot,
    eff_cat: str,
    coarse_domain: str,
    brand: str,
    canon_text: str,
    model_codes: tuple[str, ...],
) -> HardSpecs:
    low = canon_text.lower()
    raw_t = record.product_title or ""
    raw_low = raw_t.lower()
    raw_tokens = re.findall(r"[a-z0-9]+", low)
    token_set = set(raw_tokens)

    # Device type classifier (tech & appliances — reads title, not noisy store sub_category)
    device_type: Optional[str] = None
    if coarse_domain == "tech_appliances":
        dt_haystack = low if low == raw_low else f"{low} {raw_low}"
        for dtype, pat in _DEVICE_TYPE_PATTERNS:
            if pat.search(dt_haystack):
                device_type = dtype
                break
        # If sub_category is explicitly laptops/notebooks and title had an internal SSD/RAM spec, treat as laptop
        if device_type in ("ssd", "ram", None) and (record.sub_category or "").strip().lower() in ("laptops", "notebooks"):
            device_type = "laptop"

    # Storage & RAM (tech)
    ram_gb: Optional[int] = None
    storage_gb: Optional[int] = None
    if coarse_domain == "tech_appliances":
        ram_gb, storage_gb = _extract_ram_storage(record, low)
        # Apple iPhone RAM is fixed per model and often omitted by half of Egyptian stores
        if brand == "apple" and "iphone" in token_set:
            ram_gb = None

    # Screen size in inches (explicit `NN"`, `NNN-inch`, Arabic `بوصة`, or leading 2-3 digits of TV model code)
    screen_inch: Optional[int] = None
    if coarse_domain == "tech_appliances":
        m = _SCREEN_INCH_RE.search(low) or _SCREEN_INCH_RE.search(raw_low)
        if m:
            sz = int(float(m.group(1)))
            if 10 <= sz <= 115:
                screen_inch = sz
        if screen_inch is None and (
            device_type in ("tv", "monitor")
            or record.sub_category in ("tvs", "smart_tvs", "monitors")
            or "tv" in token_set
            or "monitor" in token_set
        ):
            for code in model_codes:
                if m := re.match(r"^(\d{2,3})([a-z]{2,})", code):
                    sz = int(m.group(1))
                    if 19 <= sz <= 115:
                        screen_inch = sz
                        break

    # AC HP / BTU
    hp: Optional[str] = None
    if coarse_domain == "tech_appliances":
        if m := _HP_RE.search(low):
            hp = f"{float(m.group(1)):g}hp"
        elif m := _BTU_RE.search(low):
            hp = f"{int(m.group(1))}btu"

    # Hardware / Electronics / Appliance numeric & architecture specs
    wattage_w: Optional[int] = None
    psu_efficiency: Optional[str] = None
    refresh_hz: Optional[int] = None
    ram_mhz: Optional[int] = None
    ddr_gen: Optional[str] = None
    battery_mah: Optional[int] = None
    appliance_liters: Optional[float] = None
    frost_type: Optional[str] = None
    generation_tag: Optional[str] = None
    chipset: Optional[str] = None
    form_factor: Optional[str] = None
    board_trims: frozenset[str] = frozenset()
    sub_code_suffixes: frozenset[str] = frozenset()

    if coarse_domain == "tech_appliances":
        if wm := _WATTAGE_RE.search(low):
            w_val = int(wm.group(1))
            if 10 <= w_val <= 6000:
                wattage_w = w_val
        if device_type == "psu" or "power supply" in low or "psu" in token_set or "80+" in raw_low or "80 plus" in low:
            if pm := _PSU_EFFICIENCY_RE.search(low):
                psu_efficiency = pm.group(1).lower()
        if hm := _REFRESH_HZ_RE.search(low):
            hz_val = int(hm.group(1))
            if 60 <= hz_val <= 540:
                refresh_hz = hz_val
        if mm := _RAM_MHZ_RE.search(low):
            mhz_val = int(mm.group(1) or mm.group(2))
            if 1333 <= mhz_val <= 9600:
                ram_mhz = mhz_val
        if dm := _DDR_GEN_RE.search(low):
            ddr_gen = dm.group(1).lower()
        if bm := _BATTERY_MAH_RE.search(low):
            mah_val = int(bm.group(1))
            if 500 <= mah_val <= 100000:
                battery_mah = mah_val
        if device_type in ("refrigerator", "heater", "microwave", "cooker", "air_fryer") or "liter" in low or "litre" in low:
            if lm := _APPLIANCE_LITERS_RE.search(low):
                lit_val = float(lm.group(1))
                if 1.0 <= lit_val <= 1500.0:
                    appliance_liters = lit_val
        if "no frost" in low or "nofrost" in low or "نو فروست" in raw_low:
            frost_type = "nofrost"
        elif "defrost" in low or "دي فروست" in raw_low:
            frost_type = "defrost"

        # Motherboard chipset, form factor & series/trim tokens (only for motherboards, NOT PC builds)
        if device_type != "pc_build":
            if chm := _CHIPSET_TOKEN_RE.search(low):
                cand_ch = chm.group(1).lower()
                # Confirm motherboard/PC context (or known chipset family number >= 300)
                ch_digits = int(re.sub(r"\D", "", cand_ch))
                if device_type == "motherboard" or ch_digits >= 400 or any(
                    k in token_set for k in ("am4", "am5", "lga1700", "lga1851", "lga1200", "ddr4", "ddr5", "atx", "matx", "socket")
                ):
                    chipset = cand_ch
                    if cand_ch.endswith("m"):
                        form_factor = "matx"
            if re.search(r"\b(?:e-?atx|extended\s+atx)\b", low):
                form_factor = "eatx"
            elif re.search(r"\b(?:m-?atx|micro[\s-]?atx)\b", low):
                form_factor = "matx"
            elif re.search(r"\b(?:mini[\s-]?itx|itx)\b", low):
                form_factor = "itx"
            elif re.search(r"\batx\b", low) and form_factor is None:
                form_factor = "atx"

            if chipset is not None or device_type == "motherboard":
                trims: set[str] = {t for t in token_set if t in _BOARD_TRIM_WORDS}
                if chipset is not None:
                    for pos, tok in enumerate(raw_tokens):
                        if tok == chipset and pos + 1 < len(raw_tokens):
                            nxt = raw_tokens[pos + 1]
                            if nxt in _BOARD_SINGLE_SUFFIXES:
                                trims.add(f"sfx_{nxt}")
                            break
                board_trims = frozenset(trims)

        # Capture immediate 3-6 char alphanumeric sub-model suffix after a model code (e.g. `274QPF E20` vs `274QPF X30MV`)
        if model_codes:
            sub_sfx: set[str] = set()
            mc_set = set(model_codes)
            for pos, tok in enumerate(raw_tokens):
                if _normalize_code_str(tok) in mc_set and pos + 1 < len(raw_tokens):
                    nxt = raw_tokens[pos + 1]
                    if (
                        3 <= len(nxt) <= 7
                        and any(c.isalpha() for c in nxt)
                        and any(c.isdigit() for c in nxt)
                        and not _GENERIC_SPEC_CODE_RE.fullmatch(nxt)
                    ):
                        sub_sfx.add(_normalize_code_str(nxt))
            sub_code_suffixes = frozenset(sub_sfx)

    # Generation / Revision tag (Roman II/III/IV, v2/v3, Gen 4/5, decimal 2.0/3.0 on PSUs/electronics/footwear)
    if rm := _ROMAN_GEN_RE.search(low):
        generation_tag = rm.group(1).lower()
    elif vm := _VERSION_GEN_RE.search(low):
        g = next(x for x in vm.groups() if x is not None).lower()
        generation_tag = f"v{g}"
    elif coarse_domain == "fashion_sports" and (dm := _DECIMAL_VER_RE.search(low)):
        generation_tag = dm.group(1)

    # Package weight / volume / count / pack / dosage
    attrs = record.attributes_json or {}
    vlabel = attrs.get("variant_label") if isinstance(attrs.get("variant_label"), str) else None
    if (
        coarse_domain in ("groceries_pet", "health_beauty", "baby_kids")
        or any(ch.isdigit() for ch in raw_t)
        or vlabel
        or attrs.get("net_weight_g")
        or attrs.get("net_volume_ml")
        or attrs.get("pack_count")
    ):
        unit_spec = parse_unit_spec(raw_t, variant_label=vlabel, attributes=attrs)
    else:
        unit_spec = UnitSpec()

    # Tier modifiers (`pro`, `max`, `plus`, `ultra`, `mini`, `lite`, `fe`, `se`, `air`, `neo`, ...)
    # Strip phrase contexts where `air` or `pro` is a noun/component, NOT a model tier
    tier_text = re.sub(
        r"\b(?:air\s+(?:conditioner|conditioners|conditioning|fryer|cooler|cleaner|purifier|humidifier|flow|vent|circulator)|"
        r"pro\s+(?:pump|grade|motor|filter|blade|series|tech|care|finish|edition|version|inverter)|"
        r"max\s+(?:power|speed|load|capacity|flow|temp))\b",
        " ",
        low,
    )
    tier_tokens = set(re.findall(r"[a-z0-9]+", tier_text))
    tier_pool = _TIER_MODIFIERS | (_TECH_EXTRA_TIERS if coarse_domain == "tech_appliances" else frozenset())
    tiers_set = {t for t in tier_tokens if t in tier_pool}
    if coarse_domain == "tech_appliances" and _SUFFIX_S_TIER_RE.search(low):
        tiers_set.add("suffix_s")
    tiers = frozenset(tiers_set)

    # Network generation (`4g` vs `5g`)
    network_gen: Optional[str] = None
    if _NET_5G_RE.search(low):
        network_gen = "5g"
    elif _NET_4G_RE.search(low):
        network_gen = "4g"

    # CPU & GPU (laptops / PCs)
    cpu: Optional[str] = None
    gpu: Optional[str] = None
    if coarse_domain == "tech_appliances":
        for pat, prefix in _CPU_PATTERNS:
            if m := pat.search(low):
                cpu = normalize_snake_slug(f"{prefix}{'_'.join(g.lower() for g in m.groups() if g)}", max_len=24)
                break
        if gm := _GPU_RE.search(low):
            gpu = normalize_snake_slug(gm.group(1), max_len=16)

    # Dimensions & single-width cm (furniture / rugs / mattresses)
    dimensions: Optional[str] = None
    cm_values: frozenset[int] = frozenset()
    if coarse_domain in ("home_furniture", "baby_kids"):
        if dm := _DIM_RE.search(low):
            nums = [int(g) for g in dm.groups() if g is not None]
            dimensions = "x".join(str(x) for x in sorted(nums))
        cm_found = {int(x) for x in _SINGLE_CM_RE.findall(f"{low} {raw_low}") if 40 <= int(x) <= 320}
        if cm_found:
            cm_values = frozenset(cm_found)

    # Size tier for toys / baby / furniture (e.g. Lego Medium vs Large Creative Brick Box)
    size_tier: Optional[str] = None
    if coarse_domain in ("baby_kids", "home_furniture"):
        if "large" in token_set:
            size_tier = "large"
        elif "medium" in token_set:
            size_tier = "medium"
        elif "small" in token_set:
            size_tier = "small"

    # Cookers & Washers
    burners: Optional[int] = None
    width_cm: Optional[int] = None
    washer_kg: Optional[str] = None
    washer_load: Optional[str] = None
    if coarse_domain == "tech_appliances":
        if bm := _COOKER_BURNERS_RE.search(low):
            burners = int(bm.group(1))
        if cm := _COOKER_CM_RE.search(low):
            width_cm = int(cm.group(1))
        if "washing" in token_set or "washer" in token_set or record.sub_category == "washing_machines":
            if km := _WASHER_KG_RE.search(low):
                washer_kg = f"{float(km.group(1)):g}kg"
            if "top" in token_set:
                washer_load = "top"
            elif "front" in token_set:
                washer_load = "front"

    # Health & Beauty concentration, form & day/night
    perfume_conc: Optional[str] = None
    hb_form: Optional[str] = None
    hb_time: Optional[str] = None
    if coarse_domain == "health_beauty":
        for conc_name, pat in _PERFUME_CONC_PATTERNS:
            if pat.search(low):
                perfume_conc = conc_name
                break
        hb_form = extract_hb_form(low)
        if re.search(r"\b(?:night|overnight|pm)\b|ليلي", f"{low} {raw_low}", re.I):
            hb_time = "night"
        elif re.search(r"\b(?:day|daytime)\b|نهاري", f"{low} {raw_low}", re.I):
            hb_time = "day"

    # Gender (fashion / sports / footwear — includes `variant_label` and shorthand `2 W RUNNING SHOES`!)
    gender: Optional[str] = None
    if coarse_domain == "fashion_sports":
        gender_text = f"{low} {normalize_arabic_text(vlabel or '')}"
        if _KIDS_RE.search(gender_text):
            gender = "kids"
        else:
            has_w = (
                bool(_WOMEN_RE.search(gender_text))
                or bool(re.search(r"(?:\b\d+\s+w\b|\bw\s+(?:running|training|walking|lifestyle|shoes?|sneakers?)\b)", gender_text))
                or record.store_name.lower() in _WOMEN_ONLY_STORES
            )
            has_m = (
                bool(_MEN_RE.search(gender_text))
                or bool(re.search(r"(?:\b\d+\s+m\b|\bm\s+(?:running|training|walking|lifestyle|shoes?|sneakers?)\b)", gender_text))
            )
            if has_w and not has_m:
                gender = "women"
            elif has_m and not has_w:
                gender = "men"

    # Grocery flavor/scent/shape/cut distinguishers (normalize compound sugar-free / half-cream / whole-wheat)
    grocery_dist: frozenset[str] = frozenset()
    if eff_cat == "groceries":
        g_norm = re.sub(r"\b(?:sugar|suger)[\s\-]?free\b|\bzero\s+sugar\b|\bno\s+(?:added\s+)?sugar\b", " sugarfree ", low)
        g_norm = re.sub(r"\bgluten[\s\-]?free\b", " glutenfree ", g_norm)
        g_norm = re.sub(r"\bwhole[\s\-]?wheat\b", " wholewheat ", g_norm)
        g_norm = re.sub(r"\bhalf[\s\-]?cream\b|\bsemi[\s\-]?skimmed\b", " halfcream ", g_norm)
        g_norm = re.sub(r"\bfull[\s\-]?cream\b", " fullcream ", g_norm)
        g_toks = set(re.findall(r"[a-z0-9]+", g_norm))
        grocery_dist = frozenset(t for t in g_toks if t in _GROCERY_DISTINGUISHERS)

    # Pet Care clumping vs non-clumping
    pet_clumping: Optional[str] = None
    if eff_cat == "pet_care":
        if re.search(r"\bnon[\s\-]?clumping\b", low):
            pet_clumping = "non_clumping"
        elif re.search(r"\bclumping\b", low):
            pet_clumping = "clumping"

    # Discriminative model/version numbers (exclude capacities/years/units/PSU standards)
    # Note: only strip bare `w` (Watts) in `tech_appliances`, NEVER in `fashion_sports` where `2 W` = Version 2 Women!
    disc_nums: set[str] = set()
    unit_suffixes = (
        r"gb|tb|mb|ml|l|ltr|kg|kgs|g|gm|gms|mg|mcg|iu|oz|lb|lbs|"
        r"hp|btu|w|watt|watts|kw|v|hz|khz|mhz|ghz|mah|wh|mp|mm|cm|ft|inch|inches|fps|dpi|ms|bar|rpm|pcs|caps|tabs|serv|servings"
        if coarse_domain == "tech_appliances"
        else r"gb|tb|mb|ml|l|ltr|kg|kgs|g|gm|gms|mg|mcg|iu|oz|lb|lbs|mm|cm|ft|inch|inches|pcs|caps|tabs|serv|servings"
    )
    cleaned_no_units = re.sub(
        rf"\b(?:\d+(?:\.\d+)?[\s\-]*(?:{unit_suffixes})|atx\s*3(?:\.[01])?|pcie\s*[45](?:\.[01])?|80\s*(?:\+|plus))\b",
        " ",
        low,
        flags=re.I,
    )
    for tok in re.findall(r"[a-z0-9]+", cleaned_no_units):
        if any(c.isdigit() for c in tok):
            if re.fullmatch(r"20[12]\d", tok):
                continue
            if _GENERIC_SPEC_CODE_RE.fullmatch(tok):
                continue
            if tok.isdigit() and int(tok) in {ram_gb, storage_gb, screen_inch, wattage_w, refresh_hz, ram_mhz, battery_mah}:
                continue
            disc_nums.add(_normalize_code_str(tok) if any(c.isalpha() for c in tok) else tok)

    return HardSpecs(
        storage_gb=storage_gb,
        ram_gb=ram_gb,
        screen_inch=screen_inch,
        hp=hp,
        unit_spec=unit_spec,
        tiers=tiers,
        network_gen=network_gen,
        cpu=cpu,
        gpu=gpu,
        dimensions=dimensions,
        cm_values=cm_values,
        burners=burners,
        width_cm=width_cm,
        washer_kg=washer_kg,
        washer_load=washer_load,
        perfume_conc=perfume_conc,
        hb_form=hb_form,
        hb_time=hb_time,
        gender=gender,
        grocery_distinguishers=grocery_dist,
        discriminative_numbers=frozenset(disc_nums),
        device_type=device_type,
        wattage_w=wattage_w,
        psu_efficiency=psu_efficiency,
        refresh_hz=refresh_hz,
        ram_mhz=ram_mhz,
        ddr_gen=ddr_gen,
        battery_mah=battery_mah,
        appliance_liters=appliance_liters,
        frost_type=frost_type,
        generation_tag=generation_tag,
        chipset=chipset,
        form_factor=form_factor,
        board_trims=board_trims,
        sub_code_suffixes=sub_code_suffixes,
        size_tier=size_tier,
        pet_clumping=pet_clumping,
    )


def _model_codes_compatible(codes_a: tuple[str, ...], codes_b: tuple[str, ...]) -> bool:
    """Return True if two non-empty model-code lists share an exact or prefix-aligned code."""
    for ca in codes_a:
        for cb in codes_b:
            if ca == cb:
                return True
            # Allow regional suffix prefix match (e.g. `ls27bg402e` vs `ls27bg402emxue`, `hfs50b20` vs `hfs50b20gr`)
            shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
            if len(shorter) >= 5 and longer.startswith(shorter):
                return True
    return False


def specs_conflict(
    a: SkuProfile,
    b: SkuProfile,
    *,
    strict_pass3: bool = False,
    exact_ean: bool = False,
) -> bool:
    """Hard spec conflict blocker (Pass 4) preventing any invalid cross-store merge."""
    # 1. Accessory vs. Main Product isolation
    if a.is_accessory != b.is_accessory:
        return True

    # 2. Bundle / Promo vs. Single SKU isolation
    if a.is_bundle != b.is_bundle:
        return True

    # 3. Brand conflict blocker (never merge two distinct non-unknown brands)
    if a.brand != "unknown" and b.brand != "unknown" and a.brand != b.brand:
        return True

    sa, sb = a.specs, b.specs

    # 3b. Cross-device-type isolation (mouse != headset, extender != router, pc_build != motherboard, etc.)
    if not exact_ean and sa.device_type is not None and sb.device_type is not None and sa.device_type != sb.device_type:
        return True

    # 4. Storage (GB/TB) & RAM conflict (including single-GB RAM-vs-Storage classification safety!)
    if sa.storage_gb is not None and sb.storage_gb is not None and sa.storage_gb != sb.storage_gb:
        return True
    if sa.ram_gb is not None and sb.ram_gb is not None and sa.ram_gb != sb.ram_gb:
        return True
    if (
        sa.ram_gb is not None and sa.storage_gb is None
        and sb.storage_gb is not None and sb.ram_gb is None
        and sa.ram_gb != sb.storage_gb
    ) or (
        sb.ram_gb is not None and sb.storage_gb is None
        and sa.storage_gb is not None and sa.ram_gb is None
        and sb.ram_gb != sa.storage_gb
    ):
        return True
    # In Pass 3 on smartphones/tablets/laptops/storage, don't merge sized vs sizeless storage
    if strict_pass3 and a.coarse_domain == "tech_appliances":
        if (sa.storage_gb is None) != (sb.storage_gb is None):
            if any(k in a.canon_text or k in b.canon_text for k in ("iphone", "galaxy", "redmi", "poco", "laptop", "macbook", "ipad", "ssd", "nvme")):
                return True

    # 5. Screen size (inch) conflict
    if sa.screen_inch is not None and sb.screen_inch is not None and sa.screen_inch != sb.screen_inch:
        return True
    if strict_pass3 and ((sa.screen_inch is None) != (sb.screen_inch is None)):
        if a.has_big_appliance_tv_cue or b.has_big_appliance_tv_cue:
            return True

    # 6. AC Horsepower / BTU conflict
    if sa.hp is not None and sb.hp is not None and sa.hp != sb.hp:
        return True

    # 7. Washer kg / load type, Cooker burners / width, Fridge liters & frost type conflict
    if sa.washer_kg is not None and sb.washer_kg is not None and sa.washer_kg != sb.washer_kg:
        return True
    if sa.washer_load is not None and sb.washer_load is not None and sa.washer_load != sb.washer_load:
        return True
    if sa.burners is not None and sb.burners is not None and sa.burners != sb.burners:
        return True
    if sa.width_cm is not None and sb.width_cm is not None and sa.width_cm != sb.width_cm:
        return True
    if sa.frost_type is not None and sb.frost_type is not None and sa.frost_type != sb.frost_type:
        return True
    if sa.appliance_liters is not None and sb.appliance_liters is not None:
        lo_l, hi_l = min(sa.appliance_liters, sb.appliance_liters), max(sa.appliance_liters, sb.appliance_liters)
        if lo_l > 0 and (hi_l / lo_l) > 1.15:
            return True

    # 7b. Hardware electrical / speed / architecture specs (PSU wattage & 80+, Hz, RAM MHz, DDR gen, mAh)
    if not exact_ean:
        if sa.wattage_w is not None and sb.wattage_w is not None and sa.wattage_w != sb.wattage_w:
            is_psu_or_pwr = (
                sa.device_type in ("psu",)
                or sb.device_type in ("psu",)
                or "power supply" in a.canon_text.lower()
                or "power supply" in b.canon_text.lower()
                or sa.psu_efficiency is not None
                or sb.psu_efficiency is not None
            )
            lo_w, hi_w = min(sa.wattage_w, sb.wattage_w), max(sa.wattage_w, sb.wattage_w)
            if is_psu_or_pwr or (lo_w > 0 and (hi_w / lo_w) > 1.35):
                return True
        if sa.psu_efficiency is not None and sb.psu_efficiency is not None and sa.psu_efficiency != sb.psu_efficiency:
            return True
        if sa.refresh_hz is not None and sb.refresh_hz is not None and sa.refresh_hz != sb.refresh_hz:
            return True
        if sa.ram_mhz is not None and sb.ram_mhz is not None and sa.ram_mhz != sb.ram_mhz:
            return True
        if sa.ddr_gen is not None and sb.ddr_gen is not None and sa.ddr_gen != sb.ddr_gen:
            return True
        if sa.battery_mah is not None and sb.battery_mah is not None and sa.battery_mah != sb.battery_mah:
            return True

    # 7c. Generation / Revision tag conflict (`GX II` != `GX III`, `v2` != `v3`, `2.0` != `3.0`)
    if not exact_ean:
        if sa.generation_tag is not None and sb.generation_tag is not None and sa.generation_tag != sb.generation_tag:
            return True
        if (sa.generation_tag in ("ii", "iii", "iv")) != (sb.generation_tag in ("ii", "iii", "iv")):
            if a.coarse_domain == "tech_appliances":
                return True

    # 7d. Motherboard chipset, form factor & series/trim conflict (`B850M D3HP` != `B850 A Stealth`, `MPG Carbon` != `MEG Godlike`, `B650M P` != `B650M A WiFi`)
    if not exact_ean:
        if sa.chipset is not None and sb.chipset is not None and sa.chipset != sb.chipset:
            return True
        if sa.form_factor is not None and sb.form_factor is not None and sa.form_factor != sb.form_factor:
            return True
        if sa.chipset is not None or sb.chipset is not None or sa.device_type == "motherboard" or sb.device_type == "motherboard":
            if ("wifi" in sa.board_trims) != ("wifi" in sb.board_trims):
                return True
            sfx_a = {t for t in sa.board_trims if t.startswith("sfx_")}
            sfx_b = {t for t in sb.board_trims if t.startswith("sfx_")}
            if sfx_a and sfx_b and sfx_a != sfx_b:
                return True
            line_a = sa.board_trims - {"wifi"} - sfx_a
            line_b = sb.board_trims - {"wifi"} - sfx_b
            # If one board specifies a distinct series/trim not on the other (e.g. `d3hp` vs `stealth`, `carbon` vs `godlike`, `a520m k` vs `a520m s2h`)
            if (line_a and line_b and line_a != line_b) or (bool(line_a) != bool(line_b) and (sfx_a != sfx_b or not (sfx_a & sfx_b))):
                return True

    # 7e. Conflicting manufacturer model codes or sub-model suffixes across ALL non-EAN passes!
    if not exact_ean:
        if a.model_codes and b.model_codes and not _model_codes_compatible(a.model_codes, b.model_codes):
            return True
        if sa.sub_code_suffixes and sb.sub_code_suffixes and not (sa.sub_code_suffixes & sb.sub_code_suffixes):
            return True

    # 8. Laptop CPU / GPU conflict (never merge integrated-GPU laptop with dedicated-GPU variant)
    if sa.cpu is not None and sb.cpu is not None and sa.cpu != sb.cpu:
        return True
    if sa.gpu is not None and sb.gpu is not None and sa.gpu != sb.gpu:
        return True
    if (sa.cpu is not None or sb.cpu is not None) and ((sa.gpu is None) != (sb.gpu is None)):
        return True

    # 9. Model Tier Modifiers (`pro`, `max`, `plus`, `ultra`, `mini`, `lite`, `fe`, `se`, `air`, `neo`, `ti`, `super`, `suffix_s`, ...)
    if not exact_ean:
        if sa.tiers != sb.tiers:
            return True
        # 4G vs 5G conflict (and `5g` vs unstated on phones!)
        if sa.network_gen and sb.network_gen and sa.network_gen != sb.network_gen:
            return True
        if (sa.network_gen == "5g") != (sb.network_gen == "5g"):
            # Don't merge `Galaxy A15 5G` with `Galaxy A15`
            if a.coarse_domain == "tech_appliances":
                return True

    # 10. Weight / Volume / Pack Count / Dosage (`UnitSpec`) conflict
    if a.coarse_domain in ("groceries_pet", "health_beauty", "baby_kids") or sa.unit_spec.has_package_size() or sb.unit_spec.has_package_size():
        if units_conflict(sa.unit_spec, sb.unit_spec):
            return True
        # For groceries, require BOTH to have a package size unless exact EAN match
        if not exact_ean and (a.eff_cat == "groceries" or b.eff_cat == "groceries"):
            if not (sa.unit_spec.has_package_size() and sb.unit_spec.has_package_size()):
                return True

    # 11. Dimensions, single-width cm & size tier conflict (rugs, mattresses, furniture, toys)
    if sa.dimensions is not None and sb.dimensions is not None and sa.dimensions != sb.dimensions:
        return True
    if sa.cm_values and sb.cm_values and not (sa.cm_values & sb.cm_values):
        return True
    if sa.size_tier is not None and sb.size_tier is not None and sa.size_tier != sb.size_tier:
        return True
    if strict_pass3 and a.coarse_domain == "home_furniture" and ((sa.dimensions is None) != (sb.dimensions is None)):
        return True

    # 12. Beauty/Health concentration, product form & day/night conflict
    if sa.perfume_conc is not None and sb.perfume_conc is not None and sa.perfume_conc != sb.perfume_conc:
        return True
    if sa.hb_form is not None and sb.hb_form is not None and sa.hb_form != sb.hb_form:
        return True
    if sa.hb_time is not None and sb.hb_time is not None and sa.hb_time != sb.hb_time:
        return True

    # 12b. Pet Care clumping vs non-clumping conflict
    if sa.pet_clumping is not None and sb.pet_clumping is not None and sa.pet_clumping != sb.pet_clumping:
        return True

    # 13. Fashion/Footwear gender/age conflict
    if sa.gender is not None and sb.gender is not None and sa.gender != sb.gender:
        return True
    if (sa.gender == "kids") != (sb.gender == "kids"):
        return True

    # 14. Grocery flavor/scent/shape/cut/variety/sugar-free conflict across ALL non-EAN passes
    if (a.eff_cat == "groceries" or b.eff_cat == "groceries") and not exact_ean:
        da, db = sa.grocery_distinguishers, sb.grocery_distinguishers
        for side_x, side_y in _GROCERY_EXCLUSIVE_PAIRS:
            if (da & side_x and db & side_y) or (da & side_y and db & side_x):
                return True
        # Sugar-free / Zero / Diet must match on both sides
        if bool(da & _SUGAR_FREE_TOKENS) != bool(db & _SUGAR_FREE_TOKENS):
            return True
        # Distinct cheese varieties (Gouda != Parmesan != Grana Padano != Parmigiano Reggiano)
        ca, cb = da & _CHEESE_VARIETIES, db & _CHEESE_VARIETIES
        if ca and cb and not (ca & cb):
            return True
        # Distinct grain / plant-milk bases (Quinoa != Almond != Half-Cream Milk)
        ga, gb = da & _GRAIN_PLANT_BASES, db & _GRAIN_PLANT_BASES
        if ga != gb:
            return True
        # Distinct coffee origins (Brazilian != Turkish+Cardamom)
        coa, cob = da & _COFFEE_ORIGIN_TOKENS, db & _COFFEE_ORIGIN_TOKENS
        if coa != cob:
            return True
        # Multi-flavor additions like "Orange & Carrot" vs plain "Orange"
        if ("carrot" in da) != ("carrot" in db):
            return True
        if strict_pass3 and da != db:
            return True

    # 15. Pass-3 extra precision guards
    if strict_pass3:
        # Conflicting high-entropy model codes -> NEVER merge via TF-IDF!
        if a.model_codes and b.model_codes and not _model_codes_compatible(a.model_codes, b.model_codes):
            return True
        # One-sided model code on big appliances/TVs (`55M70H` vs generic `Samsung 55-inch Mini LED 4K TV`)
        if (a.has_big_appliance_tv_cue or b.has_big_appliance_tv_cue) and (bool(a.model_codes) != bool(b.model_codes)):
            return True
        # Conflicting discriminative version/series numbers (`iPhone 15` vs `16`, `Pegasus 40` vs `41`, `SPF 30` vs `50`)
        if sa.discriminative_numbers != sb.discriminative_numbers:
            if sa.discriminative_numbers and sb.discriminative_numbers:
                return True
            if a.coarse_domain in ("tech_appliances", "fashion_sports"):
                return True

    return False


# ---------------------------------------------------------------------------
# Pass 4: Diameter-Checked Guarded Union-Find
# ---------------------------------------------------------------------------

@dataclass
class ClusterState:
    members: list[int]
    stores: set[str]
    min_price: float
    max_price: float
    brand: str
    origin_pass: str  # "pass1_id" | "pass2_det" | "pass2_code" | "pass3_tfidf"
    preferred_key: Optional[str] = None
    centroid: Optional[dict[str, float]] = None
    max_allowed_ratio: float = 2.5


class GuardedUnionFind:
    """Cluster-validated Union-Find preventing impure merges & transitive chaining drift."""

    def __init__(self, profiles: list[SkuProfile]) -> None:
        self.profiles = profiles
        n = len(profiles)
        self.parent = list(range(n))
        self.clusters: dict[int, ClusterState] = {}
        for i, p in enumerate(profiles):
            price = float(p.record.current_price or 0.0)
            self.clusters[i] = ClusterState(
                members=[i],
                stores={p.record.store_name},
                min_price=price,
                max_price=price,
                brand=p.brand,
                origin_pass="",
                max_allowed_ratio=99.0,
            )

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def _centroid_sim(self, c1: dict[str, float], c2: dict[str, float]) -> float:
        if not c1 or not c2:
            return 0.0
        if len(c1) > len(c2):
            c1, c2 = c2, c1
        dot = sum(w * c2[t] for t, w in c1.items() if t in c2)
        if dot <= 0.0:
            return 0.0
        n1 = math.sqrt(sum(w * w for w in c1.values()))
        n2 = math.sqrt(sum(w * w for w in c2.values()))
        if n1 <= 0.0 or n2 <= 0.0:
            return 0.0
        return dot / (n1 * n2)

    def try_union(
        self,
        u: int,
        v: int,
        *,
        price_ratio_cap: float = 2.5,
        origin_pass: str = "pass2_code",
        preferred_key: Optional[str] = None,
        strict_pass3: bool = False,
        exact_ean: bool = False,
        vectors: Optional[dict[int, dict[str, float]]] = None,
        min_cluster_centroid_sim: float = 0.74,
        max_cluster_size: int = 25,
    ) -> bool:
        ru, rv = self.find(u), self.find(v)
        if ru == rv:
            return True

        cu, cv = self.clusters[ru], self.clusters[rv]

        # Bound cluster size to prevent accidental mega-clusters
        if len(cu.members) + len(cv.members) > max_cluster_size:
            return False

        # Cluster-level price sanity guard (prevents transitive price drift & never widens a tighter cluster cap!)
        new_min = min(cu.min_price, cv.min_price)
        new_max = max(cu.max_price, cv.max_price)
        effective_pair_cap = min(price_ratio_cap, cu.max_allowed_ratio, cv.max_allowed_ratio)
        if new_min <= 0.0 or (new_max / new_min) > effective_pair_cap:
            return False

        # Cluster-level brand consistency
        if cu.brand != "unknown" and cv.brand != "unknown" and cu.brand != cv.brand:
            return False

        # Diameter check for Pass 3: require centroid cosine similarity >= 0.74 when merging clusters
        if strict_pass3 and vectors is not None:
            vec_u = cu.centroid if cu.centroid is not None else vectors.get(ru)
            vec_v = cv.centroid if cv.centroid is not None else vectors.get(rv)
            if vec_u is not None and vec_v is not None:
                if self._centroid_sim(vec_u, vec_v) < min_cluster_centroid_sim:
                    return False

        # Full cross-member hard spec validation (guarantees zero transitive spec contamination!)
        # Because max_cluster_size <= 25, checking all cross pairs between small clusters is ultra fast.
        for mi in cu.members:
            pi = self.profiles[mi]
            for mj in cv.members:
                pj = self.profiles[mj]
                if specs_conflict(pi, pj, strict_pass3=strict_pass3, exact_ean=exact_ean):
                    return False

        # Merge smaller cluster into larger
        if len(cu.members) < len(cv.members):
            ru, rv = rv, ru
            cu, cv = cv, cu

        self.parent[rv] = ru
        cu.members.extend(cv.members)
        cu.stores.update(cv.stores)
        cu.min_price = new_min
        cu.max_price = new_max
        cu.max_allowed_ratio = effective_pair_cap
        if cu.brand == "unknown" and cv.brand != "unknown":
            cu.brand = cv.brand
        if not cu.origin_pass:
            cu.origin_pass = cv.origin_pass or origin_pass
        if not cu.preferred_key:
            cu.preferred_key = cv.preferred_key or preferred_key

        # Maintain running L2-normalized centroid for Pass 3 diameter checking
        if vectors is not None:
            base_c = dict(cu.centroid) if cu.centroid is not None else dict(vectors.get(ru, {}))
            add_c = cv.centroid if cv.centroid is not None else vectors.get(rv, {})
            if base_c or add_c:
                for tok, w in add_c.items():
                    base_c[tok] = base_c.get(tok, 0.0) + w
                norm = math.sqrt(sum(w * w for w in base_c.values()))
                if norm > 0.0:
                    cu.centroid = {tok: w / norm for tok, w in base_c.items()}

        del self.clusters[rv]
        return True


# ---------------------------------------------------------------------------
# Pass 0: Unified Brand Vocabulary & Profile Builder
# ---------------------------------------------------------------------------

def _build_unified_brand_vocab(
    records: list[RawProductSnapshot],
    base_brand_aliases: dict[str, str],
) -> tuple[dict[tuple[str, ...], str], dict[str, str], CatalogPhoneticIndex]:
    """Build unified AR+EN brand lookup tables and an in-memory CatalogPhoneticIndex from loaded rows."""
    alias_by_norm: dict[str, str] = {}

    # 1. Seed from all curated electronics/appliance, health/beauty, footwear, and extra brands
    for k, v in base_brand_aliases.items():
        nk = normalize_arabic_text(k)
        if nk and v not in _PLACEHOLDER_BRANDS:
            alias_by_norm[nk] = v
    for k, v in _EXTRA_CURATED_BRANDS.items():
        nk = normalize_arabic_text(k)
        if nk and v not in _PLACEHOLDER_BRANDS:
            alias_by_norm.setdefault(nk, v)
    for k, v in _HB_BRAND_ALIASES:
        nk = normalize_arabic_text(k)
        if nk and v not in _PLACEHOLDER_BRANDS:
            alias_by_norm.setdefault(nk, v)
    for k, v in _FOOTWEAR_BRANDS:
        nk = normalize_arabic_text(k)
        if nk and v not in _PLACEHOLDER_BRANDS:
            alias_by_norm.setdefault(nk, v)

    # 2. Auto-discover clean catalog brands appearing across >= 3 distinct stores & >= 10 SKUs
    #    (strictly excluding all retailer store slugs and generic English material/room words!)
    store_set = {r.store_name.strip().lower() for r in records if r.store_name}
    single_brand_values = set(_SINGLE_BRAND_STORE_MAP.values())
    curated_keys = set(alias_by_norm.keys())
    brand_stores: dict[str, set[str]] = defaultdict(set)
    brand_counts: Counter[str] = Counter()
    latin_tok_counts: Counter[str] = Counter()

    for r in records:
        st = (r.store_name or "").strip().lower()
        raw_b = normalize_arabic_text(r.brand or "")
        if raw_b and not has_arabic(raw_b):
            slug = normalize_snake_slug(raw_b, fallback="unknown", max_len=32)
            if (
                slug != "unknown"
                and len(slug) >= 3
                and slug not in _PLACEHOLDER_BRANDS
                and raw_b not in _PLACEHOLDER_BRANDS
                and slug not in _NON_BRAND_WORDS
                and raw_b not in _NON_BRAND_WORDS
                and (slug not in store_set or slug in single_brand_values)
            ):
                canon = alias_by_norm.get(raw_b) or alias_by_norm.get(slug) or slug
                brand_stores[canon].add(st)
                brand_counts[canon] += 1
                alias_by_norm.setdefault(raw_b, canon)
        for tok in re.findall(r"[a-z]{3,20}", (r.product_title or "").lower())[:8]:
            latin_tok_counts[tok] += 1

    # Build fast token-tuple dictionary (1-3 words) for O(title_len) brand inference
    brand_by_tokens: dict[tuple[str, ...], str] = {}
    for nk, canon in alias_by_norm.items():
        toks = tuple(re.findall(r"[^\W_]+", nk))
        if not toks or len(toks) > 3:
            continue
        if len(toks) == 1 and len(toks[0]) <= 2 and nk not in base_brand_aliases:
            continue
        if len(toks) == 1 and (toks[0] in _TFIDF_STOPWORDS or toks[0] in _NON_BRAND_WORDS):
            # Allow explicitly curated brands like "fresh" (Egyptian appliance brand) only if curated
            if nk not in curated_keys:
                continue
        # Only add non-curated brands into title-scan dict if confirmed across >= 3 stores & >= 10 SKUs
        if nk not in curated_keys and (len(brand_stores.get(canon, ())) < 3 or brand_counts.get(canon, 0) < 10):
            continue
        brand_by_tokens.setdefault(toks, canon)

    # Also register strongly confirmed multi-store brands (>= 3 stores & >= 10 listings)
    for canon, stores in brand_stores.items():
        if len(stores) >= 3 and brand_counts.get(canon, 0) >= 10 and len(canon) >= 4:
            words = tuple(canon.split("_"))
            if len(words) <= 3 and not (len(words) == 1 and (words[0] in _TFIDF_STOPWORDS or words[0] in _NON_BRAND_WORDS)):
                brand_by_tokens.setdefault(words, canon)

    # Populate CatalogPhoneticIndex for automatic Arabic -> Latin brand resolution
    vocab_entries: list[tuple[str, int, bool]] = []
    for canon, cnt in brand_counts.items():
        vocab_entries.append((canon.replace("_", " "), max(cnt, 10), True))
    for k, canon in alias_by_norm.items():
        if not has_arabic(k) and len(k) >= 3:
            vocab_entries.append((k, 50, True))
    for tok, cnt in latin_tok_counts.most_common(4000):
        if cnt >= 10:
            vocab_entries.append((tok, cnt, False))

    phonetic_index = CatalogPhoneticIndex()
    phonetic_index.build_from_vocab(vocab_entries)

    return brand_by_tokens, alias_by_norm, phonetic_index


def _infer_brand(
    record: RawProductSnapshot,
    eff_cat: str,
    norm_title: str,
    alias_by_norm: dict[str, str],
    brand_by_tokens: dict[tuple[str, ...], str],
    phonetic_index: CatalogPhoneticIndex,
) -> str:
    """Pass 0 brand inference: structured brand -> O(1) unified AR/EN title vocab -> phonetic AR -> vertical fallback."""
    store_low = (record.store_name or "").strip().lower()
    raw_b = normalize_arabic_text(record.brand or "")

    # 1. Explicit non-placeholder brand column (O(1) dict lookup)
    if raw_b and raw_b not in _PLACEHOLDER_BRANDS:
        if raw_b in alias_by_norm:
            return alias_by_norm[raw_b]
        slug = normalize_snake_slug(raw_b, fallback="unknown", max_len=32)
        if slug in alias_by_norm:
            return alias_by_norm[slug]
        if (
            not has_arabic(raw_b)
            and slug != "unknown"
            and slug not in _PLACEHOLDER_BRANDS
            and slug not in _NON_BRAND_WORDS
            and slug != store_low
        ):
            return slug

    # 2. Fast O(title_tokens) n-gram lookup via unified AR+EN brand dictionary (covers ALL curated electronics,
    #    appliance, health/beauty, footwear, and auto-discovered multi-store brands!)
    toks = re.findall(r"[^\W_]+", norm_title)
    n_toks = min(len(toks), 14)  # Brand almost always appears in first 14 tokens
    for n in (3, 2, 1):
        for i in range(n_toks - n + 1):
            gram = tuple(toks[i : i + n])
            if gram in brand_by_tokens:
                return brand_by_tokens[gram]
            if n == 1 and gram[0].startswith("ال") and len(gram[0]) >= 5:
                stripped = (gram[0][2:],)
                if stripped in brand_by_tokens:
                    return brand_by_tokens[stripped]

    # 3. Grocery brand extractor fallback (handles grocery-only Egyptian brands)
    if eff_cat == "groceries":
        gb = normalize_snake_slug(extract_grocery_brand(record.product_title, record.brand), fallback="unknown", max_len=32)
        if gb and gb != "unknown" and gb not in _PLACEHOLDER_BRANDS:
            return gb

    # 4. Automatic O(1) exact phonetic skeleton resolution on Arabic brand column or leading Arabic title tokens
    ar_candidates: list[str] = []
    if raw_b and has_arabic(raw_b):
        ar_candidates.extend(re.findall(r"[\u0621-\u064A]+", raw_b)[:2])
    if has_arabic(norm_title):
        ar_candidates.extend([t for t in toks[:6] if has_arabic(t)])
    for ar_tok in ar_candidates:
        hits = phonetic_index.resolve_arabic_token(ar_tok, max_results=1, brands_only=True, allow_fuzzy=False)
        if hits:
            hit_norm = normalize_arabic_text(hits[0])
            if hit_norm in alias_by_norm:
                return alias_by_norm[hit_norm]
            hit_slug = normalize_snake_slug(hit_norm, fallback="unknown", max_len=32)
            if hit_slug != "unknown" and hit_slug not in _PLACEHOLDER_BRANDS:
                return hit_slug

    # 5. Official single-brand store fallback (e.g. `adidas_eg`, `zanussi_eg`, `ikea_eg`)
    if store_low in _SINGLE_BRAND_STORE_MAP:
        return _SINGLE_BRAND_STORE_MAP[store_low]

    return "unknown"


def _extract_exact_identifiers(record: RawProductSnapshot) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract checksum-verified EAN-13/GTIN-14 barcodes and high-entropy manufacturer MPNs."""
    attrs = record.attributes_json or {}
    eans: list[str] = []
    for k in ("ean", "gtin13", "gtin14", "gtin", "barcode"):
        val = attrs.get(k)
        if val is not None:
            digits = re.sub(r"\D", "", str(val))
            valid = _valid_ean13(digits)
            if valid and valid not in eans:
                eans.append(valid)
    for m in _EAN13_RE.finditer(record.product_title or ""):
        valid = _valid_ean13(m.group(1))
        if valid and valid not in eans:
            eans.append(valid)

    mpns: list[str] = []
    raw_mpn = attrs.get("mpn")
    if isinstance(raw_mpn, str) and raw_mpn.strip():
        norm = _normalize_code_str(raw_mpn)
        if 5 <= len(norm) <= 22 and any(c.isalpha() for c in norm) and any(c.isdigit() for c in norm):
            if not _GENERIC_SPEC_CODE_RE.fullmatch(norm):
                mpns.append(norm)
    return tuple(eans), tuple(mpns)


def _extract_core_tokens(canon_text: str, brand: str) -> tuple[str, ...]:
    brand_parts = set(brand.split("_")) if brand != "unknown" else set()
    # Strip trailing "| ..." marketing fluff
    head = canon_text.split("|", 1)[0] if ("|" in canon_text and len(canon_text.split("|", 1)[0].strip()) >= 12) else canon_text
    # Remove unit tokens like `256gb`, `500ml`, `1.5hp`
    head = re.sub(
        r"\b\d+(?:\.\d+)?[\s\-]*(?:gb|tb|mb|ml|l|ltr|kg|kgs|g|gm|gms|mg|mcg|iu|oz|lb|lbs|"
        r"hp|btu|w|watt|watts|kw|v|hz|khz|mhz|ghz|mah|wh|mp|mm|cm|ft|inch|inches|fps|dpi|ms|bar|rpm)\b",
        " ",
        head,
        flags=re.I,
    )
    out: list[str] = []
    seen: set[str] = set()
    for tok in re.findall(r"[a-z0-9\u0621-\u064a]+", head.lower()):
        if len(tok) < 2:
            continue
        if tok in _TFIDF_STOPWORDS or tok in brand_parts:
            continue
        if tok.isdigit() and len(tok) == 4 and tok.startswith("20"):
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return tuple(out)


# ---------------------------------------------------------------------------
# Main Entity Resolution Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class EntityResolutionStats:
    total_records: int
    matched_groups: int
    matched_products: int
    pass1_groups: int = 0
    pass2_det_groups: int = 0
    pass2_code_groups: int = 0
    pass3_tfidf_groups: int = 0
    brands_inferred_from_title: int = 0
    category_group_counts: dict[str, int] = field(default_factory=dict)
    group_details: dict[str, list[tuple[str, float, str]]] = field(default_factory=dict)


def run_entity_resolution(
    records: list[RawProductSnapshot],
    *,
    base_brand_aliases: dict[str, str],
    compute_deterministic_key_fn: Any,
    max_price_ratio: float = 2.5,
    tfidf_threshold: float = 0.78,
    tfidf_max_price_ratio: float = 2.0,
) -> EntityResolutionStats:
    """Run the 4-pass local RAM cross-store entity resolution pipeline in-place on `records`."""
    for rec in records:
        rec.canonical_product_key = None

    if not records:
        return EntityResolutionStats(total_records=0, matched_groups=0, matched_products=0)

    import time as _t
    _log_progress = len(records) >= 1000
    _t0 = _t.perf_counter()

    # ------------------------------------------------------------------
    # PASS 0: Unified Brand Inference, Bilingual Canonicalization & Specs
    # ------------------------------------------------------------------
    brand_by_tokens, alias_by_norm, phonetic_index = _build_unified_brand_vocab(records, base_brand_aliases)
    if _log_progress:
        print(f"  [ER Pass 0a] Built brand vocab ({len(brand_by_tokens):,} aliases) + phonetic index in {_t.perf_counter() - _t0:.1f}s", flush=True)

    profiles: list[SkuProfile] = []
    brands_inferred = 0

    for idx, rec in enumerate(records):
        eff_cat = effective_category(rec)
        domain = _COARSE_DOMAIN_BY_CAT.get(eff_cat, "other")
        raw_title = rec.product_title or ""
        norm_title = split_glued_units(raw_title)
        raw_b_norm = normalize_arabic_text(rec.brand or "")
        was_missing_brand = (
            not raw_b_norm
            or raw_b_norm in _PLACEHOLDER_BRANDS
            or normalize_snake_slug(raw_b_norm, fallback="unknown", max_len=32) in _PLACEHOLDER_BRANDS
            or has_arabic(raw_b_norm)
        )
        brand = _infer_brand(rec, eff_cat, norm_title, alias_by_norm, brand_by_tokens, phonetic_index)
        if was_missing_brand and brand != "unknown":
            brands_inferred += 1

        is_acc = False if eff_cat in ("groceries", "pet_care") else is_accessory_listing(rec)
        is_collapsed = is_collapsed_multiprice_variant(rec)
        canon_text = (
            canonicalize_bilingual_text(
                norm_title,
                phonetic_index=phonetic_index,
                brands_only_phonetic=True,
                allow_fuzzy_phonetic=False,
            )
            if has_arabic(norm_title)
            else norm_title
        )
        is_bundle = _is_bundle_or_promo(canon_text)
        eans, mpns = _extract_exact_identifiers(rec)
        model_codes = _extract_high_entropy_model_codes(canon_text, raw_title) if any(ch.isdigit() for ch in raw_title) else ()
        core_tokens = _extract_core_tokens(canon_text, brand)
        specs = _extract_hard_specs(rec, eff_cat, domain, brand, canon_text, model_codes)
        big_app_tv = bool(_BIG_APPLIANCE_TV_RE.search(canon_text)) if domain == "tech_appliances" else False

        profiles.append(
            SkuProfile(
                idx=idx,
                record=rec,
                eff_cat=eff_cat,
                coarse_domain=domain,
                brand=brand,
                is_accessory=is_acc,
                is_bundle=is_bundle,
                is_collapsed_variant=is_collapsed,
                canon_text=canon_text,
                core_tokens=core_tokens,
                exact_eans=eans,
                exact_mpns=mpns,
                model_codes=model_codes,
                specs=specs,
                has_big_appliance_tv_cue=big_app_tv,
            )
        )
        if _log_progress and (idx + 1) % 100000 == 0:
            print(f"    ... Pass 0b profiled {idx + 1:,}/{len(records):,} SKUs ({_t.perf_counter() - _t0:.1f}s)", flush=True)

    uf = GuardedUnionFind(profiles)
    if _log_progress:
        print(f"  [ER Pass 0b] Profiled {len(profiles):,} SKUs ({brands_inferred:,} brands inferred) in {_t.perf_counter() - _t0:.1f}s", flush=True)
    effective_cap = max_price_ratio
    # Confidence-tiered price ratio caps (Precision >> Recall):
    # - Pass 1 (EAN-13): up to `effective_cap` (2.5x); MPN up to 2.2x
    # - Pass 2a (deterministic keys): <= 2.0x for Electronics/Appliances/Groceries, <= 2.1x Health/Beauty/Footwear, <= 1.60x sizeless `hbl_*`
    # - Pass 2b (model code without EAN/MPN): <= 2.0x
    # - Pass 3 (TF-IDF): <= 1.75x (and <= 1.60x in tech_appliances & groceries_pet)
    mpn_cap = min(max_price_ratio, 2.2) if max_price_ratio <= 2.5 else max_price_ratio
    det_tech_groc_cap = min(max_price_ratio, 2.0) if max_price_ratio <= 2.5 else max_price_ratio
    det_other_cap = min(max_price_ratio, 2.1) if max_price_ratio <= 2.5 else max_price_ratio
    hbl_cap = min(max_price_ratio, 1.60) if max_price_ratio <= 2.5 else max_price_ratio
    p2_code_cap = min(max_price_ratio, 2.0) if max_price_ratio <= 2.5 else max_price_ratio
    p3_cap = min(max_price_ratio, tfidf_max_price_ratio, 1.75) if max_price_ratio <= 2.5 else max_price_ratio
    p3_strict_cap = min(p3_cap, 1.60) if max_price_ratio <= 2.5 else max_price_ratio

    # ------------------------------------------------------------------
    # PASS 1: Exact Identifier Graph (EAN-13 / GTIN-14 / MPN)
    # ------------------------------------------------------------------
    ean_buckets: dict[str, list[int]] = defaultdict(list)
    mpn_buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for p in profiles:
        if p.is_collapsed_variant:
            continue
        for ean in p.exact_eans:
            ean_buckets[ean].append(p.idx)
        if p.brand != "unknown":
            for mpn in p.exact_mpns:
                mpn_buckets[(p.brand, mpn)].append(p.idx)

    for ean, idxs in ean_buckets.items():
        if len(idxs) < 2 or len({profiles[i].record.store_name for i in idxs}) < 2:
            continue
        is_groc = any(profiles[i].eff_cat == "groceries" for i in idxs)
        pref = f"grocery_gtin_{ean}" if is_groc else f"ean_{ean}"
        anchor = idxs[0]
        for other in idxs[1:]:
            uf.try_union(
                anchor,
                other,
                price_ratio_cap=effective_cap,
                origin_pass="pass1_id",
                preferred_key=pref,
                exact_ean=True,
            )

    for (brand, mpn), idxs in mpn_buckets.items():
        if len(idxs) < 2 or len({profiles[i].record.store_name for i in idxs}) < 2:
            continue
        pref = normalize_snake_slug(f"mpn_{brand}_{mpn}", max_len=150)
        anchor = idxs[0]
        for other in idxs[1:]:
            uf.try_union(
                anchor,
                other,
                price_ratio_cap=mpn_cap,
                origin_pass="pass1_id",
                preferred_key=pref,
            )

    # ------------------------------------------------------------------
    # PASS 2a: Deterministic Vertical Fingerprints (preserves all battle-tested keys)
    # ------------------------------------------------------------------
    # Run sequential deterministic stages so e.g. grocery barcode -> exact size -> bilingual type
    # all get a chance to link without a store-specific size key short-circuiting type matching!
    det_stage_buckets: list[dict[str, list[int]]] = [
        defaultdict(list),  # Stage 0: Core electronics/appliances, grocery barcode, HB exact, Footwear style
        defaultdict(list),  # Stage 1: Grocery exact size, Footwear exact gender+model
        defaultdict(list),  # Stage 2: Grocery bilingual type, Footwear neutral, HB high-specificity sizeless
    ]
    for p in profiles:
        if p.is_collapsed_variant:
            continue
        if p.eff_cat == "groceries":
            if bk := compute_grocery_barcode_key(p.record):
                det_stage_buckets[0][bk].append(p.idx)
            if sk := compute_grocery_size_key(p.record):
                det_stage_buckets[1][sk].append(p.idx)
            if tk := compute_grocery_type_key(p.record):
                det_stage_buckets[2][tk].append(p.idx)
        elif p.eff_cat in ("health", "beauty"):
            feats = extract_health_beauty_features(p.record)
            if feats:
                if feats[0]:
                    det_stage_buckets[0][feats[0]].append(p.idx)
                if feats[1]:
                    det_stage_buckets[2][feats[1]].append(p.idx)
        elif p.eff_cat in ("fashion", "sports") and is_footwear_record(p.record):
            fw = extract_footwear_features(p.record)
            if fw:
                if fw[0]:
                    det_stage_buckets[0][fw[0]].append(p.idx)
                if fw[1]:
                    det_stage_buckets[1][fw[1]].append(p.idx)
                if fw[2]:
                    det_stage_buckets[2][fw[2]].append(p.idx)
        elif p.eff_cat in ("electronics", "home_appliances"):
            if ck := compute_deterministic_key_fn(p.record):
                det_stage_buckets[0][ck].append(p.idx)

    for stage_idx, det_buckets in enumerate(det_stage_buckets):
        for key, idxs in sorted(det_buckets.items()):
            if len(idxs) < 2 or len({profiles[i].record.store_name for i in idxs}) < 2:
                continue
            if key.startswith("grocery_gtin_"):
                key_cap = effective_cap
            elif key.startswith("hbl_"):
                key_cap = hbl_cap
            elif key.startswith(("hb_", "fw_")):
                key_cap = det_other_cap
            else:
                key_cap = det_tech_groc_cap
            idxs_sorted = sorted(idxs, key=lambda i: (float(profiles[i].record.current_price), i))
            for i_pos in range(len(idxs_sorted)):
                for j_pos in range(i_pos + 1, min(len(idxs_sorted), i_pos + 12)):
                    u_i, v_i = idxs_sorted[i_pos], idxs_sorted[j_pos]
                    if profiles[u_i].record.store_name == profiles[v_i].record.store_name:
                        continue
                    uf.try_union(
                        u_i,
                        v_i,
                        price_ratio_cap=key_cap,
                        origin_pass="pass2_det",
                        preferred_key=key,
                        exact_ean=key.startswith("grocery_gtin_"),
                    )

    # ------------------------------------------------------------------
    # PASS 2b: Cross-Subcategory Alphanumeric Model-Code Matching
    # ------------------------------------------------------------------
    code_buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for p in profiles:
        if p.brand == "unknown" or p.is_collapsed_variant or p.is_bundle:
            continue
        if not p.model_codes:
            continue
        for code in p.model_codes:
            # Skip short 4-char codes on non-tech items (prone to fashion/color code collisions like `s100`)
            if len(code) < 5 and p.coarse_domain != "tech_appliances":
                continue
            code_buckets[(p.brand, code)].append(p.idx)

    # Prioritize longest/highest-entropy model codes first
    for (brand, code), idxs in sorted(code_buckets.items(), key=lambda kv: (-len(kv[0][1]), kv[0])):
        if len(idxs) < 2 or len(idxs) > 80:
            continue
        if len({profiles[i].record.store_name for i in idxs}) < 2:
            continue
        # Reject model codes that appear on >15 distinct SKUs inside a single store (series/family prefix, not SKU code)
        per_store = Counter(profiles[i].record.store_name for i in idxs)
        if per_store.most_common(1)[0][1] > 15:
            continue

        pref = normalize_snake_slug(f"mc_{brand}_{code}", max_len=140)
        idxs_sorted = sorted(idxs, key=lambda i: (float(profiles[i].record.current_price), i))
        for i_pos in range(len(idxs_sorted)):
            u_i = idxs_sorted[i_pos]
            pu = profiles[u_i]
            for j_pos in range(i_pos + 1, len(idxs_sorted)):
                v_i = idxs_sorted[j_pos]
                pv = profiles[v_i]
                if pu.record.store_name == pv.record.store_name:
                    continue
                # Don't cross radically unrelated domains (e.g. a Samsung TV code vs a Samsung fashion/pet fluke)
                if pu.coarse_domain != pv.coarse_domain:
                    continue
                # On laptops/motherboards with shared chassis/chipset code (e.g. `15irx10`, `a520m`),
                # require core token overlap >= 1 beyond the code OR matching CPU/GPU/storage
                if len(idxs) > 8:
                    shared_toks = set(pu.core_tokens) & set(pv.core_tokens)
                    if len(shared_toks) < 2:
                        continue
                uf.try_union(
                    u_i,
                    v_i,
                    price_ratio_cap=p2_code_cap,
                    origin_pass="pass2_code",
                    preferred_key=pref,
                )

    # ------------------------------------------------------------------
    # PASS 3: TF-IDF Weighted Sparse Cosine Similarity per (brand, domain, acc)
    # ------------------------------------------------------------------
    if _log_progress:
        print(f"  [ER Pass 1+2] Completed Exact ID + Det + Model-Code passes in {_t.perf_counter() - _t0:.1f}s", flush=True)
    # Global document frequency across all core tokens
    global_df: Counter[str] = Counter()
    for p in profiles:
        for tok in p.core_tokens:
            global_df[tok] += 1
    n_global = max(1, len(profiles))

    # Group eligible SKUs into `(inferred_brand, coarse_domain, is_accessory)` blocks
    blocks: dict[tuple[str, str, bool], list[int]] = defaultdict(list)
    for p in profiles:
        if p.brand == "unknown" or p.is_collapsed_variant or p.is_bundle:
            continue
        if len(p.core_tokens) < 2:
            continue
        if p.eff_cat == "groceries" and not p.specs.unit_spec.has_package_size():
            continue
        blocks[(p.brand, p.coarse_domain, p.is_accessory)].append(p.idx)

    # Build L2-normalized sparse TF-IDF vectors & run inverted-index similarity per block
    all_vectors: dict[int, dict[str, float]] = {}

    for (brand, domain, is_acc), block_idxs in blocks.items():
        if len(block_idxs) < 2:
            continue
        if len({profiles[i].record.store_name for i in block_idxs}) < 2:
            continue

        # Domain-specific threshold & price cap (Precision >> Recall)
        dom_threshold = (
            max(tfidf_threshold, 0.85)
            if domain in ("groceries_pet", "fashion_sports", "home_furniture", "baby_kids")
            else max(tfidf_threshold, 0.80)
        )
        dom_p3_cap = p3_strict_cap if domain in ("tech_appliances", "groceries_pet") else p3_cap

        # Compute block document frequency
        block_df: Counter[str] = Counter()
        for idx in block_idxs:
            for tok in profiles[idx].core_tokens:
                block_df[tok] += 1
        n_block = len(block_idxs)

        # Build normalized sparse TF-IDF vector per SKU in block & inverted posting list
        postings: dict[str, list[int]] = defaultdict(list)
        block_vecs: dict[int, dict[str, float]] = {}

        for idx in block_idxs:
            toks = profiles[idx].core_tokens
            vec: dict[str, float] = {}
            norm_sq = 0.0
            for tok in toks:
                idf_b = math.log((n_block + 1.0) / (block_df[tok] + 1.0)) + 1.0
                idf_g = math.log((n_global + 1.0) / (global_df[tok] + 1.0)) + 1.0
                w = 0.60 * idf_b + 0.40 * idf_g
                # Boost alphanumeric / discriminative tokens slightly over plain words
                if any(c.isdigit() for c in tok):
                    w *= 1.35
                vec[tok] = w
                norm_sq += w * w
            if norm_sq <= 0.0:
                continue
            inv_norm = 1.0 / math.sqrt(norm_sq)
            norm_vec = {t: w * inv_norm for t, w in vec.items()}
            block_vecs[idx] = norm_vec
            all_vectors[idx] = norm_vec
            for tok in norm_vec:
                postings[tok].append(idx)

        # Accumulate candidate pairs via sparse inverted index (skip ultra-high-DF boilerplate postings)
        max_posting = min(200, max(40, int(n_block * 0.40))) if n_block > 60 else 200
        candidate_edges: list[tuple[float, int, int]] = []

        for idx in block_idxs:
            v_i = block_vecs.get(idx)
            if not v_i:
                continue
            p_i = profiles[idx]
            store_i = p_i.record.store_name
            price_i = float(p_i.record.current_price or 0.0)
            if price_i <= 0.0:
                continue

            dots: dict[int, float] = {}
            shared_cnt: dict[int, int] = {}

            for tok, wi in v_i.items():
                plist = postings.get(tok)
                if not plist or len(plist) > max_posting:
                    continue
                for jdx in plist:
                    if jdx <= idx:
                        continue
                    dots[jdx] = dots.get(jdx, 0.0) + wi * block_vecs[jdx][tok]
                    shared_cnt[jdx] = shared_cnt.get(jdx, 0) + 1

            for jdx, sim in dots.items():
                if sim < dom_threshold:
                    continue
                if shared_cnt.get(jdx, 0) < 2:
                    continue
                p_j = profiles[jdx]
                if p_j.record.store_name == store_i:
                    continue
                # Skip if already linked by Pass 1 / Pass 2
                if uf.find(idx) == uf.find(jdx):
                    continue
                price_j = float(p_j.record.current_price or 0.0)
                if price_j <= 0.0:
                    continue
                ratio_ij = max(price_i, price_j) / min(price_i, price_j)
                if ratio_ij > dom_p3_cap:
                    continue
                # Pet care: block sized vs sizeless litter/food when price gap > 1.35x (e.g. 5L vs 10L)
                if p_i.eff_cat == "pet_care" or p_j.eff_cat == "pet_care":
                    if (p_i.specs.unit_spec.has_package_size() != p_j.specs.unit_spec.has_package_size()) and ratio_ij > 1.35:
                        continue
                # Fashion/Sports: require at least 1 genuine non-generic model/line token in shared tokens
                if domain == "fashion_sports":
                    shared_non_generic = (set(p_i.core_tokens) & set(p_j.core_tokens)) - _GENERIC_FASHION_SPORTS_TOKENS
                    if not shared_non_generic:
                        continue
                if specs_conflict(p_i, p_j, strict_pass3=True):
                    continue
                candidate_edges.append((sim, idx, jdx))

        # Apply highest-similarity edges first through Diameter-Checked GuardedUnionFind
        candidate_edges.sort(key=lambda e: (-e[0], e[1], e[2]))
        for sim, u_i, v_i in candidate_edges:
            uf.try_union(
                u_i,
                v_i,
                price_ratio_cap=dom_p3_cap,
                origin_pass="pass3_tfidf",
                strict_pass3=True,
                vectors=all_vectors,
                min_cluster_centroid_sim=0.74,
            )

    # ------------------------------------------------------------------
    # PASS 4 Finalization: Emit Verified Multi-Store Clusters & Clean Keys
    # ------------------------------------------------------------------
    matched_groups = 0
    matched_products = 0
    pass1_groups = 0
    pass2_det_groups = 0
    pass2_code_groups = 0
    pass3_tfidf_groups = 0
    cat_group_counts: Counter[str] = Counter()
    group_details: dict[str, list[tuple[str, float, str]]] = {}
    used_keys: set[str] = set()

    for root, cluster in sorted(uf.clusters.items(), key=lambda kv: kv[0]):
        if len(cluster.stores) < 2:
            continue
        if cluster.min_price <= 0.0 or (cluster.max_price / cluster.min_price) > effective_cap:
            continue

        members = [profiles[m] for m in cluster.members]
        is_grocery_cluster = any(m.eff_cat == "groceries" for m in members)

        # Build deterministic canonical_product_key
        key = cluster.preferred_key
        if not key:
            brand_part = cluster.brand if cluster.brand != "unknown" else "item"
            rep = min(members, key=lambda m: (float(m.record.current_price), m.idx))
            anchor_toks = [t for t in rep.core_tokens if not has_arabic(t)][:4] or list(rep.core_tokens[:4])
            anchor = "_".join(anchor_toks) or "match"
            prefix = "er"
            if cluster.origin_pass == "pass2_code" and rep.model_codes:
                prefix = "mc"
                anchor = rep.model_codes[0]
            spec_bits: list[str] = []
            if rep.specs.storage_gb:
                spec_bits.append(f"{rep.specs.storage_gb}gb")
            if rep.specs.ram_gb:
                spec_bits.append(f"{rep.specs.ram_gb}r")
            if rep.specs.screen_inch:
                spec_bits.append(f"{rep.specs.screen_inch}in")
            if rep.specs.hp:
                spec_bits.append(rep.specs.hp)
            if rep.specs.dimensions:
                spec_bits.append(rep.specs.dimensions)
            suffix = f"_{'_'.join(spec_bits)}" if spec_bits else ""
            key = normalize_snake_slug(f"{prefix}_{brand_part}_{anchor}{suffix}", max_len=145)

        # Guarantee `mart_cross_store_matches.sql` grocery size suffix invariant
        if is_grocery_cluster and not key.startswith("grocery_gtin_"):
            if not re.search(r"_(w[0-9]+g|v[0-9]+ml|c[0-9]+[a-z]*)_x[0-9]+$", key):
                # Pull canonical size token from member with package size
                size_suffix = None
                for m in members:
                    st = m.specs.unit_spec.canonical_size_token()
                    if st:
                        # Ensure explicit `_x{pack}` suffix
                        if not re.search(r"_x\d+$", st):
                            st = f"{st}_x{m.specs.unit_spec.pack_count}"
                        size_suffix = st
                        break
                if size_suffix:
                    base_k = normalize_snake_slug(key, max_len=130)
                    key = f"{base_k}_{size_suffix}"
                else:
                    # Grocery cluster without EAN or package size -> skip to preserve 100% grocery precision
                    continue

        # Ensure uniqueness across distinct clusters
        if key in used_keys:
            digest = hashlib.md5(
                "|".join(sorted(f"{m.record.store_name}:{m.record.external_id}" for m in members)).encode("utf-8")
            ).hexdigest()[:6]
            if is_grocery_cluster and (sm := re.search(r"(_(?:w[0-9]+g|v[0-9]+ml|c[0-9]+[a-z]*)_x[0-9]+)$", key)):
                stem = key[: sm.start()]
                key = f"{stem[:120]}_{digest}{sm.group(1)}"
            else:
                key = f"{key[:148]}_{digest}"
        used_keys.add(key)

        for m in members:
            m.record.canonical_product_key = key

        matched_groups += 1
        matched_products += len(members)
        if cluster.origin_pass == "pass1_id":
            pass1_groups += 1
        elif cluster.origin_pass == "pass2_det":
            pass2_det_groups += 1
        elif cluster.origin_pass == "pass2_code":
            pass2_code_groups += 1
        else:
            pass3_tfidf_groups += 1

        dom_cat = Counter(m.eff_cat for m in members).most_common(1)[0][0]
        cat_group_counts[dom_cat] += 1
        group_details[key] = sorted(
            [(m.record.store_name, float(m.record.current_price), m.record.product_title) for m in members],
            key=lambda x: (x[1], x[0]),
        )

    return EntityResolutionStats(
        total_records=len(records),
        matched_groups=matched_groups,
        matched_products=matched_products,
        pass1_groups=pass1_groups,
        pass2_det_groups=pass2_det_groups,
        pass2_code_groups=pass2_code_groups,
        pass3_tfidf_groups=pass3_tfidf_groups,
        brands_inferred_from_title=brands_inferred,
        category_group_counts=dict(cat_group_counts),
        group_details=group_details,
    )
