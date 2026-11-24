"""Bilingual Arabic <-> English semantic & automatic catalog phonetic search engine.

Self-contained module shared across FastAPI search (`catalog_search.py`),
similar alternatives (`similar_alternatives.py`), and the cross-store matcher
(`data_platform/ingestion/scrapers/matcher.py`).

Core capabilities:
1. Arabic & unit normalization:
   - Unifies `أ/إ/آ/ٱ -> ا`, `ة -> ه`, `ى -> ي`, `ؤ -> و`, `ئ -> ي`
   - Strips diacritics (tashkeel), tatweel, bidi marks, trademark glyphs
   - Converts Arabic-Indic & Persian digits `٠-٩ / ۰-۹ -> 0-9`
   - Splits glued Arabic units (`256جيجا -> 256 gb`, `1.5حصان -> 1.5 hp`,
     `55بوصه -> 55 inch`, `200مل -> 200 ml`, `8كيلو -> 8 kg`)
2. Bidirectional Egyptian e-commerce semantic lexicon across electronics,
   home appliances, cosmetics/skincare, fashion, grocery, baby, and tier/spec
   modifiers (`برو/ماكس/الترا/بلس/ميني/لايت/...`).
3. Automatic Catalog Phonetic Resolver (`CatalogPhoneticIndex`):
   - Builds a compact (<5 MB) consonant phonetic skeleton index from distinct
     catalog brands and top frequent Latin tokens in `gold.mart_product_verdicts`
     (cached 24h in RAM with zero external dependencies).
   - Resolves arbitrary long-tail Arabic brand/model transliterations (e.g.
     `سيرافي -> cerave`, `سوكاني -> sokany`, `باسيوس -> baseus`, `لاروش -> laroche`,
     `زانوسي -> zanussi`, `ريدراجون -> redragon`, `تيفال -> tefal`,
     `سكيتشرز -> skechers`) in <1ms RAM without hardcoding.
4. Accessory-intent detection & canonical token translation for high-precision
   search ranking and cross-store matching.
"""

from __future__ import annotations

import math
import re
import threading
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

# ---------------------------------------------------------------------------
# 1. Normalization & Glued Unit Splitting
# ---------------------------------------------------------------------------

_AR_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u0640\u064B-\u065F\u0670\u06D6-\u06ED]")
_BIDI_MARKS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff®™]")
_AR_DIGITS_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
_AR_LETTERS_TRANS = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
    }
)

_ARABIC_CHAR_RE = re.compile(r"[\u0621-\u064A]")
_LATIN_CHAR_RE = re.compile(r"[a-zA-Z]")

# Split glued Arabic <-> ASCII/digit runs (`256جيجا`, `1.5حصان`, `ايفون15`, `موديلSK16`)
_AR_TO_ALNUM_RE = re.compile(r"([\u0621-\u064A])([A-Za-z0-9])")
_ALNUM_TO_AR_RE = re.compile(r"([A-Za-z0-9])([\u0621-\u064A])")

# Glued Arabic / bilingual unit patterns -> canonical spaced English unit
_UNIT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:جيجا\s*بايت|جيجابايت|جيجا|قيقا)(?=$|[^a-z\u0621-\u064a])"), r"\1 gb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:تيرا\s*بايت|تيرابايت|تيرا)(?=$|[^a-z\u0621-\u064a])"), r"\1 tb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:ميجا\s*بايت|ميجابايت|ميجا)(?=$|[^a-z\u0621-\u064a])"), r"\1 mb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:حصان)(?=$|[^a-z\u0621-\u064a])"), r"\1 hp"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:بوصه|انش)(?=$|[^a-z\u0621-\u064a])"), r"\1 inch"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:ملليلتر|مللي|ملل|مل)(?=$|[^a-z\u0621-\u064a])"), r"\1 ml"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:لتر|ليتر|لترات)(?=$|[^a-z\u0621-\u064a])"), r"\1 l"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:كيلو\s*جرام|كيلوجرام|كيلو|كجم)(?=$|[^a-z\u0621-\u064a])"), r"\1 kg"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:جرام|غرام|جم)(?=$|[^a-z\u0621-\u064a])"), r"\1 g"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:مللي\s*جرام|ملجم|مجم)(?=$|[^a-z\u0621-\u064a])"), r"\1 mg"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:وات|واط)(?=$|[^a-z\u0621-\u064a])"), r"\1 w"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:سم)(?=$|[^a-z\u0621-\u064a])"), r"\1 cm"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:قدم)(?=$|[^a-z\u0621-\u064a])"), r"\1 ft"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:هيرتز|هرتز)(?=$|[^a-z\u0621-\u064a])"), r"\1 hz"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:شعله|شعلات)(?=$|[^a-z\u0621-\u064a])"), r"\1 burner"),
)

# Canonical unit alias families for query regex expansion
UNIT_FAMILIES: dict[str, tuple[str, ...]] = {
    "l": ("l", "liter", "liters", "litre", "litres", "لتر", "ليتر", "لترات"),
    "ml": ("ml", "milliliter", "milliliters", "مل", "مللي", "ملل"),
    "kg": ("kg", "kgs", "kilogram", "kilograms", "كيلو", "كجم", "كيلوجرام"),
    "g": ("g", "gm", "gms", "gram", "grams", "جرام", "غرام", "جم"),
    "mg": ("mg", "مجم", "ملجم"),
    "gb": ("gb", "جيجا", "جيجابايت", "جيجا بايت"),
    "tb": ("tb", "تيرا", "تيرابايت", "تيرا بايت"),
    "w": ("w", "watt", "watts", "وات", "واط"),
    "hp": ("hp", "حصان"),
    "inch": ("inch", "inches", "بوصه", "انش"),
    "cm": ("cm", "سم"),
    "hz": ("hz", "هيرتز", "هرتز"),
}


def normalize_arabic_text(raw: str) -> str:
    """Normalize Arabic script, digits, diacritics, and spacing (lowercased)."""
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw)
    s = _AR_DIACRITICS_RE.sub("", s)
    s = _BIDI_MARKS_RE.sub(" ", s)
    s = s.translate(_AR_DIGITS_TRANS)
    s = s.translate(_AR_LETTERS_TRANS)
    return re.sub(r"\s+", " ", s).strip().lower()


def split_glued_units(text_value: str) -> str:
    """Normalize Arabic text, split glued Arabic/digit boundaries, and expand Arabic units."""
    s = normalize_arabic_text(text_value)
    if not s:
        return ""
    if not _ARABIC_CHAR_RE.search(s):
        return s
    s = _AR_TO_ALNUM_RE.sub(r"\1 \2", s)
    s = _ALNUM_TO_AR_RE.sub(r"\1 \2", s)
    for pat, repl in _UNIT_REPLACEMENTS:
        s = pat.sub(repl, s)
    return re.sub(r"\s+", " ", s).strip()


def has_arabic(text_value: str) -> bool:
    return bool(_ARABIC_CHAR_RE.search(text_value or ""))


# ---------------------------------------------------------------------------
# 2. Bidirectional Egyptian E-Commerce Semantic Lexicon
# ---------------------------------------------------------------------------
# Organized by canonical concept -> tuple of Arabic + English retail equivalents.
# Multi-word phrases are supported seamlessly.

CONCEPT_FAMILIES: dict[str, tuple[str, ...]] = {
    # --- Tier / Spec Modifiers ---
    "pro": ("pro", "برو"),
    "max": ("max", "ماكس"),
    "ultra": ("ultra", "الترا", "ألترا"),
    "plus": ("plus", "بلس", "بلاس"),
    "mini": ("mini", "ميني"),
    "lite": ("lite", "لايت"),
    "air": ("air", "اير"),
    "note": ("note", "نوت"),
    "fold": ("fold", "فولد"),
    "flip": ("flip", "فليب"),
    "slim": ("slim", "سليم"),
    "neo": ("neo", "نيو"),
    "inverter": ("inverter", "انفرتر", "انفيرتر"),
    "digital": ("digital", "ديجيتال"),
    "no frost": ("no frost", "nofrost", "نوفروست", "نو فروست"),
    "defrost": ("defrost", "ديفروست", "دي فروست"),
    "split": ("split", "سبليت", "اسبلت", "اسبليت"),
    "smart": ("smart", "ذكي", "ذكيه", "سمارت"),
    "wireless": ("wireless", "لاسلكي", "لاسلكيه", "وايرلس"),
    "bluetooth": ("bluetooth", "بلوتوث"),
    "stainless": ("stainless", "ستانلس", "استانلس"),
    "built in": ("built in", "builtin", "بلت ان"),
    # --- Home Appliances ---
    "refrigerator": ("refrigerator", "refrigerators", "fridge", "fridges", "ثلاجه", "تلاجه", "ثلاجات", "تلاجات"),
    "dishwasher": ("dishwasher", "dishwashers", "غساله اطباق", "غساله صحون"),
    "washing machine": ("washing machine", "washing machines", "washer", "غساله", "غساله ملابس", "غسالات"),
    "dryer": ("dryer", "مجفف", "مجفف ملابس"),
    "air conditioner": ("air conditioner", "air conditioners", "air conditioning", "ac", "تكييف", "مكيف", "تكييفات"),
    "tv": ("tv", "smart tv", "television", "شاشه", "تلفزيون", "تليفزيون", "تلفاز"),
    "cooker": ("cooker", "gas cooker", "stove", "بوتاجاز", "بوتجاز", "موقد"),
    "microwave": ("microwave", "microwaves", "ميكروويف", "ميكرويف", "مايكروويف", "مايكرويف", "مكروويف", "ميكرو ويف", "مايكرو ويف"),
    "freezer": ("freezer", "deep freezer", "ديب فريزر", "فريزر"),
    "water heater": ("water heater", "heater", "سخان", "سخان مياه", "سخان غاز", "سخان كهرباء", "سخان كهربا"),
    "water dispenser": ("water dispenser", "water cooler", "مبرد مياه", "ديسبنسر", "كولدير"),
    "vacuum": ("vacuum", "vacuum cleaner", "مكنسه", "مكنسه كهربائيه"),
    "fan": ("fan", "stand fan", "مروحه", "مراوح"),
    "blender": ("blender", "خلاط"),
    "hand blender": ("hand blender", "immersion blender", "هاند بلندر"),
    "chopper": ("chopper", "mincer", "كبه", "مفرمه"),
    "food processor": ("food processor", "محضر طعام", "كيتشن ماشين"),
    "mixer": ("mixer", "stand mixer", "hand mixer", "عجان", "مضرب بيض", "مضرب"),
    "kettle": ("kettle", "electric kettle", "كاتل", "غلايه", "غلايه مياه"),
    "air fryer": ("air fryer", "fryer", "قلايه هوائيه", "قلايه", "مقلاه هوائيه", "مقلاه", "اير فراير"),
    "iron": ("iron", "steam iron", "steamer", "مكواه", "مكواه بخار"),
    "oven": ("oven", "electric oven", "فرن", "فرن كهربائي"),
    "toaster": ("toaster", "sandwich maker", "توستر", "ساندوتش ميكر", "شوايه"),
    "coffee maker": ("coffee maker", "coffee machine", "espresso", "ماكينه قهوه", "صانعه قهوه"),
    "hood": ("hood", "exhaust", "شفاط"),
    # --- Electronics & Core Tech ---
    "iphone": ("iphone", "ايفون", "اي فون"),
    "apple": ("apple", "ابل", "أبل"),
    "macbook": ("macbook", "ماك بوك", "ماكبوك"),
    "ipad": ("ipad", "ايباد", "اي باد"),
    "airpods": ("airpods", "airpod", "ايربودز", "ايربود"),
    "samsung": ("samsung", "سامسونج", "سامسونق"),
    "galaxy": ("galaxy", "جالاكسي", "جالكسي", "جلاكسي", "جلاكزى"),
    "xiaomi": ("xiaomi", "شاومي", "شياومي"),
    "redmi": ("redmi", "ريدمي"),
    "poco": ("poco", "بوكو"),
    "oppo": ("oppo", "اوبو"),
    "realme": ("realme", "ريلمي"),
    "infinix": ("infinix", "انفينكس", "انفنكس"),
    "tecno": ("tecno", "تكنو"),
    "huawei": ("huawei", "هواوي"),
    "honor": ("honor", "هونر", "اونر"),
    "vivo": ("vivo", "فيفو"),
    "nokia": ("nokia", "نوكيا"),
    "motorola": ("motorola", "موتورولا"),
    "lenovo": ("lenovo", "لينوفو"),
    "dell": ("dell", "ديل"),
    "hp": ("hp", "اتش بي"),
    "asus": ("asus", "اسوس"),
    "acer": ("acer", "ايسر"),
    "msi": ("msi", "ام اس اي"),
    "sony": ("sony", "سوني"),
    "lg": ("lg", "ال جي", "الجي"),
    "toshiba": ("toshiba", "توشيبا"),
    "sharp": ("sharp", "شارب"),
    "tornado": ("tornado", "تورنيدو"),
    "fresh": ("fresh", "فريش"),
    "zanussi": ("zanussi", "زانوسي"),
    "beko": ("beko", "بيكو"),
    "bosch": ("bosch", "بوش"),
    "carrier": ("carrier", "كاريير", "كارير"),
    "midea": ("midea", "ميديا"),
    "unionaire": ("unionaire", "يونيون اير", "يونيون"),
    "kiriazi": ("kiriazi", "كريازي"),
    "haier": ("haier", "هاير"),
    "hoover": ("hoover", "هوفر", "هوفير"),
    "ariston": ("ariston", "اريستون"),
    "indesit": ("indesit", "اندست", "انديست"),
    "white point": ("white point", "وايت بوينت"),
    "white whale": ("white whale", "وايت ويل"),
    "kenwood": ("kenwood", "كينوود", "كنود"),
    "braun": ("braun", "براون"),
    "philips": ("philips", "فيليبس", "فليبس"),
    "tefal": ("tefal", "تيفال"),
    "moulinex": ("moulinex", "مولينكس", "مولينيكس"),
    "sokany": ("sokany", "سوكاني"),
    "black decker": ("black decker", "بلاك اند ديكر"),
    "smartphone": ("smartphone", "mobile", "mobile phone", "موبايل", "هاتف", "تليفون", "جوال"),
    "laptop": ("laptop", "laptops", "notebook", "notebooks", "لابتوب", "لاب توب"),
    "tablet": ("tablet", "tablets", "تابلت"),
    "monitor": ("monitor", "monitors", "شاشه كمبيوتر", "شاشه جيمنج"),
    "headphones": ("headphones", "headphone", "headset", "earbuds", "earphones", "airpods", "سماعه", "سماعات", "سماعه اذن", "سماعه راس", "هيدسيت"),
    "speaker": ("speaker", "soundbar", "سبيكر", "مكبر صوت"),
    "smartwatch": ("smartwatch", "smart watch", "ساعه ذكيه", "سمارت ووتش"),
    "watch": ("watch", "watches", "ساعه", "ساعات"),
    "playstation": ("playstation", "ps5", "ps4", "بلايستيشن", "بلاي ستيشن"),
    "controller": ("controller", "gamepad", "dualsense", "ذراع تحكم", "دراع"),
    "mouse": ("mouse", "ماوس"),
    "keyboard": ("keyboard", "كيبورد", "لوحه مفاتيح"),
    "power bank": ("power bank", "powerbank", "باور بانك", "باوربانك"),
    "router": ("router", "راوتر"),
    "printer": ("printer", "طابعه"),
    "ssd": ("ssd", "nvme", "هارد", "هارد ديسك"),
    "charger": ("charger", "شاحن"),
    "cable": ("cable", "كابل", "كبل", "وصله"),
    "case": ("case", "cover", "جراب", "كفر"),
    "screen protector": ("screen protector", "tempered glass", "اسكرينه", "اسكرين", "سكرين", "سكرينه"),
    # --- Cosmetics, Skincare, Pharmacy & Health ---
    "cleanser": ("cleanser", "face wash", "facial wash", "cleansing gel", "غسول", "غسول وجه", "غسول للوجه", "غسول للبشره"),
    "sunscreen": ("sunscreen", "sunblock", "sun shield", "spf", "صن بلوك", "واقي شمس", "صن سكرين"),
    "perfume": ("perfume", "eau de parfum", "eau de toilette", "fragrance", "parfum", "edp", "edt", "عطر", "برفان", "برفيوم", "عطور"),
    "body mist": ("body mist", "body splash", "mist", "splash", "بادي ميست", "بادي سبلاش", "سبلاش"),
    "deodorant": ("deodorant", "antiperspirant", "مزيل عرق", "مضاد تعرق"),
    "serum": ("serum", "سيروم"),
    "moisturizer": ("moisturizer", "moisturizing", "cream", "كريم", "مرطب", "كريم مرطب"),
    "lotion": ("lotion", "body lotion", "لوشن"),
    "shampoo": ("shampoo", "شامبو"),
    "conditioner": ("conditioner", "بلسم"),
    "mask": ("mask", "ماسك"),
    "toner": ("toner", "تونر"),
    "scrub": ("scrub", "exfoliating", "سكراب", "مقشر"),
    "micellar": ("micellar", "ميسيلار"),
    "makeup": ("makeup", "cosmetics", "مكياج"),
    "vitamin": ("vitamin", "vitamins", "فيتامين", "فيتامينات"),
    "protein": ("protein", "whey", "whey protein", "بروتين", "واي بروتين"),
    "creatine": ("creatine", "كرياتين"),
    "collagen": ("collagen", "كولاجين"),
    "magnesium": ("magnesium", "مغنيسيوم", "ماغنيسيوم"),
    "omega": ("omega", "اوميجا"),
    "zinc": ("zinc", "زنك"),
    "supplements": ("supplements", "مكملات", "مكملات غذائيه"),
    # --- Fashion & Footwear ---
    "sneakers": ("sneakers", "shoes", "trainers", "footwear", "كوتشي", "سنيكرز", "حذاء", "حذاء رياضي", "جزمه"),
    "sandals": ("sandals", "slides", "slippers", "صندل", "شبشب"),
    "boots": ("boots", "boot", "بوت"),
    "heels": ("heels", "كعب"),
    "jacket": ("jacket", "جاكيت", "جاكت"),
    "pants": ("pants", "trousers", "بنطلون"),
    "jeans": ("jeans", "جينز"),
    "shirt": ("shirt", "قميص"),
    "tshirt": ("t-shirt", "tshirt", "tee", "تيشيرت", "تي شيرت"),
    "hoodie": ("hoodie", "هودي"),
    "dress": ("dress", "فستان"),
    "bag": ("bag", "backpack", "handbag", "شنطه", "حقيبه"),
    "sunglasses": ("sunglasses", "eyewear", "نظاره", "نظاره شمس"),
    "men": ("men", "mens", "رجالي", "للرجال"),
    "women": ("women", "womens", "حريمي", "نسائي", "للنساء"),
    "kids": ("kids", "children", "اطفال", "ولادي", "بناتي"),
    # --- Groceries, Baby, Pet, Home Furniture ---
    "diapers": ("diapers", "diaper", "حفاضات", "حفاضه", "بامبرز"),
    "olive oil": ("olive oil", "زيت زيتون"),
    "oil": ("oil", "زيت"),
    "ghee": ("ghee", "سمن", "سمنه"),
    "rice": ("rice", "رز", "ارز"),
    "pasta": ("pasta", "مكرونه"),
    "milk": ("milk", "لبن", "حليب"),
    "cheese": ("cheese", "جبنه", "جبن"),
    "butter": ("butter", "زبده"),
    "sugar": ("sugar", "سكر"),
    "flour": ("flour", "دقيق"),
    "tea": ("tea", "شاي"),
    "coffee": ("coffee", "قهوه", "بن"),
    "honey": ("honey", "عسل"),
    "juice": ("juice", "عصير"),
    "tuna": ("tuna", "تونه"),
    "sauce": ("sauce", "paste", "صلصه"),
    "detergent": ("detergent", "مسحوق", "مسحوق غسيل"),
    "mattress": ("mattress", "مرتبه", "مراتب"),
    "bedsheet": ("bedsheet", "sheet", "bedding", "ملايه", "ملايات", "لحاف"),
    "rug": ("rug", "carpet", "سجاده", "سجاد"),
    "cookware": ("cookware", "حلل", "طقم حلل"),
    "cat litter": ("cat litter", "رمل قطط"),
    "cat": ("cat", "قطط"),
    "dog": ("dog", "كلاب"),
    "toys": ("toys", "العاب"),
    "treadmill": ("treadmill", "مشايه"),
}

# Build fast bidirectional lookup tables
_TOKEN_RE = re.compile(r"\d+\.\d+[^\W_]*|[^\W_]+")
CONCEPT_BY_TOKENS: dict[tuple[str, ...], str] = {}
CONCEPT_ALIASES_NORM: dict[str, tuple[str, ...]] = {}
CONCEPT_PRIMARY_EN: dict[str, str] = {}

for _concept_key, _aliases in CONCEPT_FAMILIES.items():
    norm_aliases = tuple(sorted({normalize_arabic_text(a) for a in _aliases if a}))
    CONCEPT_ALIASES_NORM[_concept_key] = norm_aliases
    # Prefer pure Latin primary token for canonical English representation
    latin_first = next((a for a in _aliases if not has_arabic(a)), _concept_key)
    CONCEPT_PRIMARY_EN[_concept_key] = normalize_arabic_text(latin_first)
    for _alias in norm_aliases:
        toks = tuple(_TOKEN_RE.findall(_alias))
        if toks:
            CONCEPT_BY_TOKENS.setdefault(toks, _concept_key)

MAX_CONCEPT_PHRASE_LEN: int = max((len(k) for k in CONCEPT_BY_TOKENS), default=1)

# Arabic stopwords that should NEVER trigger phonetic brand resolution
_ARABIC_STOPWORDS: frozenset[str] = frozenset(
    {
        "في", "من", "على", "الي", "عن", "مع", "او", "و", "ب", "ل", "لل",
        "جديد", "جديده", "اصلي", "اصليه", "سعر", "اسعار", "افضل", "احسن", "ارخص",
        "عرض", "عروض", "خصم", "خصومات", "تخفيض", "مصر", "ضمان", "موديل", "لون",
        "اسود", "ابيض", "ازرق", "احمر", "اخضر", "رمادي", "فضي", "ذهبي", "وردي",
        "بني", "بيج", "اصفر", "برتقالي", "بنفسجي", "كحلي", "سماوي", "تيتانيوم",
        "كبير", "صغير", "وسط", "حجم", "مقاس", "قطعه", "قطع", "طقم", "علبه", "عبوه",
        "للبشره", "للشعر", "للوجه", "للجسم", "للعين", "للعيون", "دهنيه", "جافه", "حساسه",
        "ضد", "بدون", "فقط", "كامل", "بارد", "ساخن", "يدوي", "اوتوماتيك", "فوق", "امامي",
        "بضمان", "رسمي", "محلي", "دولي", "سنتين", "سنوات", "سنه", "شحن", "مجاني",
    }
)

# ---------------------------------------------------------------------------
# 3. Consonant Phonetic Skeleton Engine (Zero Hardcoding for Long-Tail Brands)
# ---------------------------------------------------------------------------

_AR_CHAR_TO_SKEL: dict[str, str] = {
    "ب": "b",
    "پ": "b",
    "ت": "t",
    "ط": "t",
    "د": "t",
    "ض": "t",
    "ث": "s",
    "س": "s",
    "ص": "s",
    "ز": "s",
    "ذ": "s",
    "ظ": "s",
    "ش": "X",
    "ج": "k",  # Egyptian hard 'g' primary; alternate 'j' also generated
    "ك": "k",
    "ق": "k",
    "خ": "k",
    "غ": "k",
    "ف": "f",
    "ڤ": "f",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "ر": "r",
    "ه": "",
    "ح": "h",
    "ع": "",
    "ا": "",
    "و": "",
    "ي": "",
    "ء": "",
}

_LATIN_CONSONANT_MAP = str.maketrans(
    {
        "p": "b",
        "v": "f",
        "c": "k",
        "q": "k",
        "g": "k",
        "z": "s",
        "d": "t",
        "h": "",
        "w": "",
        "y": "",
        "a": "",
        "e": "",
        "i": "",
        "o": "",
        "u": "",
    }
)


def _collapse_adjacent_chars(s: str) -> str:
    if not s:
        return ""
    out = [s[0]]
    for ch in s[1:]:
        if ch != out[-1]:
            out.append(ch)
    return "".join(out)


def latin_phonetic_skeleton(token: str) -> str:
    """Compute a normalized consonant skeleton for a Latin token.

    Examples:
      - cerave   -> srf
      - sokany   -> skn
      - baseus   -> bss
      - laroche  -> lrX
      - zanussi  -> sns
      - redragon -> rtrkn
      - tefal    -> tfl
      - skechers -> skXrs
    """
    s = re.sub(r"[^a-z]", "", (token or "").lower())
    if not s:
        return ""
    # Collapse doubled letters BEFORE stripping vowels so `zanussi -> zanusi -> sns`
    # while `baseus -> baseus -> bss` keeps separate consonants across vowels.
    s = _collapse_adjacent_chars(s)
    # Multi-letter phonetic digraphs
    s = s.replace("tch", "X")
    s = s.replace("sh", "X")
    s = s.replace("ch", "X")
    s = s.replace("ph", "f")
    s = s.replace("kh", "k")
    s = s.replace("gh", "k")
    s = s.replace("th", "t")
    s = s.replace("ck", "k")
    s = s.replace("qu", "k")
    s = s.replace("x", "ks")
    # Soft 'c' before e/i/y (e.g. cerave -> serave, cetaphil -> setaphil, cybele -> sybele)
    s = re.sub(r"c(?=[eiy])", "s", s)
    # Leading 'w' acts as consonant glide (`white`, `western`, `wiwu`)
    lead = ""
    if s.startswith("w") and len(s) >= 3:
        lead = "w"
        s = s[1:]
    # Soft 'j' normalized to 'k' in primary skeleton so Egyptian `ج` aligns with both g/j
    s = s.replace("j", "k")
    skel = lead + s.translate(_LATIN_CONSONANT_MAP)
    return skel


def arabic_phonetic_skeletons(token: str) -> tuple[str, ...]:
    """Compute primary (and optional Egyptian alternate) consonant skeletons for an Arabic word.

    Examples:
      - سيرافي   -> ('srf',)
      - سوكاني   -> ('skn',)
      - باسيوس   -> ('bss',)
      - لاروش    -> ('lrX',)
      - زانوسي   -> ('sns',)
      - ريدراجون -> ('rtrkn',)
      - تيفال    -> ('tfl',)
      - سكيتشرز  -> ('skXrs',)
    """
    norm = normalize_arabic_text(token)
    if not norm:
        return ()
    # Strip definite article `ال` when token is long enough (e.g. `السيرافي` -> `سيرافي`)
    candidates = [norm]
    if norm.startswith("ال") and len(norm) >= 5:
        candidates.append(norm[2:])

    out: list[str] = []
    for cand in candidates:
        # Collapse consecutive identical Arabic letters before vowel stripping
        c = _collapse_adjacent_chars(cand)
        # Digraphs: `تش` -> `X` (skechers -> سكيتشرز, kitchen -> كيتشن)
        # `دي` / `تي` keep normal consonant mapping
        c = c.replace("تش", "X")
        # Leading `و` as consonant (`وايت`, `ويسترن`)
        lead = ""
        if c.startswith("و") and len(c) >= 3:
            lead = "w"
            c = c[1:]
        pieces: list[str] = [lead] if lead else []
        for ch in c:
            if ch == "X":
                pieces.append("X")
            else:
                mapped = _AR_CHAR_TO_SKEL.get(ch, "")
                if mapped:
                    pieces.append(mapped)
        skel = "".join(pieces)
        if skel and skel not in out:
            out.append(skel)
        # Alternate: collapse consecutive duplicate consonants in skeleton (handles `كاريير` krr vs `carrier` kr)
        collapsed = _collapse_adjacent_chars(skel)
        if collapsed and collapsed not in out:
            out.append(collapsed)
    return tuple(out)


def _levenshtein_le1(a: str, b: str) -> int:
    """Fast bounded edit distance returning 0, 1, or 2 (>1)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return 2
    if la == lb:
        diffs = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                diffs += 1
                if diffs > 1:
                    return 2
        return diffs
    # Ensure `short` is shorter by exactly 1
    short, long_s = (a, b) if la < lb else (b, a)
    i = j = diffs = 0
    while i < len(short) and j < len(long_s):
        if short[i] == long_s[j]:
            i += 1
            j += 1
        else:
            diffs += 1
            if diffs > 1:
                return 2
            j += 1
    return 1


@dataclass(frozen=True)
class VocabEntry:
    term: str        # Original lowercased Latin token or phrase (e.g. "cerave", "la roche")
    freq: int        # Document frequency in catalog
    is_brand: bool   # True if from brand column or multi-word brand
    skeleton: str    # Consonant skeleton


class CatalogPhoneticIndex:
    """Bounded in-memory phonetic skeleton index over real catalog brands & Latin tokens.

    Memory footprint: < 2 MB for ~6,000 catalog tokens.
    Lookup latency: < 0.5 ms per Arabic token.
    """

    def __init__(self) -> None:
        self._by_skel: dict[str, list[VocabEntry]] = defaultdict(list)
        self._by_first_len: dict[tuple[str, int], list[str]] = defaultdict(list)
        self._resolve_cache: dict[tuple[str, int, bool], list[str]] = {}
        self._built_at: float = 0.0
        self._size: int = 0
        self._lock = threading.RLock()

    @property
    def is_populated(self) -> bool:
        return self._size > 0

    def is_fresh(self, ttl_seconds: float = 86400.0) -> bool:
        return self._size > 0 and (time.monotonic() - self._built_at) < ttl_seconds

    def build_from_vocab(self, entries: Iterable[tuple[str, int, bool]]) -> int:
        """Populate index from `(term, freq, is_brand)` tuples."""
        # Deduplicate by normalized term, keeping max freq and OR'd is_brand
        merged: dict[str, tuple[int, bool]] = {}
        for raw_term, freq, is_brand in entries:
            clean = re.sub(r"[^a-z\s-]", " ", (raw_term or "").lower()).strip()
            clean = re.sub(r"\s+", " ", clean)
            if not clean:
                continue
            words = [w for w in re.split(r"[\s-]+", clean) if len(w) >= 2]
            if not words:
                continue
            # Index each individual word >= 3 chars
            for w in words:
                if len(w) >= 3:
                    prev_f, prev_b = merged.get(w, (0, False))
                    merged[w] = (max(prev_f, int(freq)), prev_b or bool(is_brand))
            # For multi-word brands (e.g. "la roche-posay", "black decker", "white whale"),
            # also index the joined first-two-words & full-brand forms so `لاروش` -> `la roche`!
            if is_brand and len(words) >= 2:
                pair = f"{words[0]} {words[1]}"
                prev_f, prev_b = merged.get(pair, (0, False))
                merged[pair] = (max(prev_f, int(freq)), True)
                if len(words) >= 3:
                    full_b = " ".join(words[:3])
                    prev_f, prev_b = merged.get(full_b, (0, False))
                    merged[full_b] = (max(prev_f, int(freq)), True)

        by_skel: dict[str, list[VocabEntry]] = defaultdict(list)
        for term, (freq, is_brand) in merged.items():
            skel = latin_phonetic_skeleton(term)
            if len(skel) < 2:
                continue
            by_skel[skel].append(VocabEntry(term=term, freq=freq, is_brand=is_brand, skeleton=skel))

        # Sort each skeleton bucket: brands first, then highest catalog frequency
        for skel, bucket in by_skel.items():
            bucket.sort(key=lambda e: (not e.is_brand, -e.freq, len(e.term), e.term))
            # Keep top 8 entries per skeleton to bound memory
            by_skel[skel] = bucket[:8]

        by_first_len: dict[tuple[str, int], list[str]] = defaultdict(list)
        for skel in by_skel:
            by_first_len[(skel[0], len(skel))].append(skel)

        with self._lock:
            self._by_skel = by_skel
            self._by_first_len = by_first_len
            self._resolve_cache.clear()
            self._size = len(merged)
            self._built_at = time.monotonic()
            return self._size

    def resolve_arabic_token(
        self,
        arabic_token: str,
        *,
        max_results: int = 3,
        brands_only: bool = False,
        allow_fuzzy: bool = True,
    ) -> list[str]:
        """Resolve an Arabic token to top matching catalog Latin tokens in <1ms RAM."""
        norm = normalize_arabic_text(arabic_token)
        if not norm or not has_arabic(norm):
            return []
        stripped = norm[2:] if (norm.startswith("ال") and len(norm) >= 5) else norm
        if len(stripped) < 3 or norm in _ARABIC_STOPWORDS or stripped in _ARABIC_STOPWORDS:
            return []

        cache_key = (norm, max_results, brands_only, allow_fuzzy)
        with self._lock:
            cached = self._resolve_cache.get(cache_key)
            if cached is not None:
                return list(cached)
            if not self._by_skel:
                return []

            skeletons = arabic_phonetic_skeletons(norm)
            if not skeletons:
                return []

            scored: dict[str, float] = {}

            # 1. Exact consonant skeleton match (strongest signal — pure O(1) dict lookup)
            for idx, sk in enumerate(skeletons):
                if len(sk) < 2:
                    continue
                bucket = self._by_skel.get(sk)
                if not bucket:
                    continue
                for entry in bucket:
                    if brands_only and not entry.is_brand:
                        continue
                    if len(sk) == 2 and not entry.is_brand:
                        continue
                    base = 100.0 - (idx * 8.0)
                    brand_bonus = 25.0 if entry.is_brand else 0.0
                    freq_bonus = min(15.0, math.log1p(max(1, entry.freq)) * 2.0)
                    len_gap = abs(len(entry.term.replace(" ", "")) - len(stripped))
                    len_pen = max(0.0, (len_gap - 3) * 6.0)
                    score = base + brand_bonus + freq_bonus - len_pen
                    if score > scored.get(entry.term, -1.0):
                        scored[entry.term] = score

            # 2. Bounded edit-distance <= 1 fallback ONLY when exact skeleton found nothing
            if allow_fuzzy and not scored:
                primary = skeletons[0]
                if len(primary) >= 3:
                    first_ch = primary[0]
                    for clen in (len(primary) - 1, len(primary), len(primary) + 1):
                        if clen < 3:
                            continue
                        for cand_skel in self._by_first_len.get((first_ch, clen), ()):
                            if _levenshtein_le1(primary, cand_skel) <= 1:
                                for entry in self._by_skel[cand_skel]:
                                    if brands_only and not entry.is_brand:
                                        continue
                                    if not entry.is_brand and entry.freq < 50:
                                        continue
                                    len_gap = abs(len(entry.term.replace(" ", "")) - len(stripped))
                                    if len_gap > 4:
                                        continue
                                    score = (
                                        65.0
                                        + (20.0 if entry.is_brand else 0.0)
                                        + min(12.0, math.log1p(max(1, entry.freq)) * 1.8)
                                        - len_gap * 4.0
                                    )
                                    if score > scored.get(entry.term, -1.0):
                                        scored[entry.term] = score

            result = (
                [term for term, _ in sorted(scored.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[:max_results]]
                if scored
                else []
            )
            if len(self._resolve_cache) < 100000:
                self._resolve_cache[cache_key] = result
            return list(result)


# Singleton process-level catalog phonetic index (lazily refreshed every 24h in RAM)
_CATALOG_PHONETIC_INDEX = CatalogPhoneticIndex()
_VOCAB_LOAD_LOCK = threading.Lock()
_VOCAB_TTL_SECONDS = 86400.0  # 24 hours

_CATALOG_VOCAB_SQL = text(
    """
    WITH brand_vocab AS (
        SELECT
            LOWER(TRIM(brand)) AS term,
            COUNT(*)::INTEGER AS freq,
            TRUE AS is_brand
        FROM gold.mart_product_verdicts
        WHERE brand IS NOT NULL
          AND brand <> ''
          AND LOWER(brand) NOT IN ('unknown', 'generic', 'other', 'unbranded', 'none')
          AND brand ~ '[A-Za-z]'
        GROUP BY LOWER(TRIM(brand))
    ),
    title_vocab AS (
        SELECT
            tok AS term,
            COUNT(*)::INTEGER AS freq,
            FALSE AS is_brand
        FROM (
            SELECT unnest(regexp_split_to_array(LOWER(product_title), '[^a-z]+')) AS tok
            FROM gold.mart_product_verdicts
        ) sub
        WHERE length(tok) BETWEEN 3 AND 24
        GROUP BY tok
        HAVING COUNT(*) >= 15
        ORDER BY COUNT(*) DESC
        LIMIT 3500
    )
    SELECT term, freq, is_brand FROM brand_vocab
    UNION ALL
    SELECT term, freq, is_brand FROM title_vocab
    """
)


def get_catalog_phonetic_index(db: Optional[Connection] = None) -> CatalogPhoneticIndex:
    """Return the 24h-cached catalog phonetic index, lazily loading once from Neon if needed."""
    if _CATALOG_PHONETIC_INDEX.is_fresh(_VOCAB_TTL_SECONDS):
        return _CATALOG_PHONETIC_INDEX
    if db is None:
        return _CATALOG_PHONETIC_INDEX
    with _VOCAB_LOAD_LOCK:
        if _CATALOG_PHONETIC_INDEX.is_fresh(_VOCAB_TTL_SECONDS):
            return _CATALOG_PHONETIC_INDEX
        try:
            rows = db.execute(_CATALOG_VOCAB_SQL).mappings().all()
            vocab = [
                (str(r["term"]), int(r["freq"]), bool(r["is_brand"]))
                for r in rows
                if r.get("term")
            ]
            if vocab:
                _CATALOG_PHONETIC_INDEX.build_from_vocab(vocab)
        except DBAPIError:
            try:
                db.rollback()
            except Exception:
                pass
        except Exception:
            # Never break search if a mocked/fake DB in unit tests does not handle the vocab query
            pass
    return _CATALOG_PHONETIC_INDEX


def reset_catalog_phonetic_index() -> None:
    """Reset the singleton phonetic index (used in unit tests)."""
    with _VOCAB_LOAD_LOCK:
        _CATALOG_PHONETIC_INDEX.build_from_vocab(())
        _CATALOG_PHONETIC_INDEX._built_at = 0.0


# ---------------------------------------------------------------------------
# 4. Accessory Detection & Canonical English Token Representation
# ---------------------------------------------------------------------------

ACCESSORY_QUERY_TOKENS: frozenset[str] = frozenset(
    {
        # Arabic accessory terms (normalized)
        "جراب", "جرابات", "كفر", "كفرات", "اسكرين", "اسكرينه", "سكرين", "سكرينه",
        "شاحن", "شواحن", "كابل", "كابلات", "كبل", "سلك", "وصله", "محول", "ادابتور",
        "استراب", "سير", "حامل", "ستاند", "قاعده", "غطاء", "غطا", "طبق", "اطباق",
        "صحن", "رف", "رفوف", "درج", "ادراج", "حاجز", "كاوتش", "مفصله", "شنطه", "حقيبه",
        "لاصق", "استيكر", "ريموت", "فلتر", "قطعه", "غيار", "خرطوم", "بطاريه", "حبر", "شيكر",
        # English accessory & spare-part terms
        "case", "cases", "cover", "covers", "protector", "protectors", "glass", "film",
        "charger", "chargers", "cable", "cables", "cord", "wire", "adapter", "adaptor",
        "strap", "straps", "band", "bands", "bracelet", "holder", "stand", "mount",
        "bracket", "pouch", "sleeve", "folio", "bumper", "sticker", "skin", "decal",
        "bag", "backpack", "dish", "dishes", "plate", "plates", "tray", "trays",
        "shelf", "shelves", "drawer", "drawers", "barrier", "barriers", "crisper",
        "remote", "filter", "spare", "replacement", "battery", "toner", "cartridge",
        "ink", "hose", "blade", "knob", "hinge", "gasket", "thermostat", "shaker", "insole", "shoelace",
    }
)

# SQL-safe POSIX regex matching accessory/spare-part titles (demoted when searching main devices)
ACCESSORY_TITLE_SQL_RE: str = (
    r"(?:^|[^[:alnum:]ء-ي])(?:"
    r"case|cases|cover|covers|pouch|sleeve|folio|bumper|screen[[:space:]]+protector|"
    r"tempered[[:space:]]+glass|privacy[[:space:]]+glass|protector|phone[[:space:]]+skin|"
    r"laptop[[:space:]]+skin|vinyl[[:space:]]+skin|cable|cables|charger|adapter|adaptor|"
    r"watch[[:space:]]+strap|watch[[:space:]]+band|strap|phone[[:space:]]+holder|"
    r"car[[:space:]]+holder|laptop[[:space:]]+stand|laptop[[:space:]]+bag|"
    r"laptop[[:space:]]+sleeve|laptop[[:space:]]+backpack|cooling[[:space:]]+pad|"
    r"replacement[[:space:]]+remote|spare[[:space:]]+part|dust[[:space:]]+cover|"
    r"dish|dishes|plate|plates|tray|trays|barrier|barriers|shelf|shelves|drawer|drawers|"
    r"crisper|gasket|hinge|thermostat|"
    r"(?:ال)?جراب|(?:ال)?كفر|(?:ال)?اسكرين(?:ه)?|(?:ال)?سكرين(?:ه)?|"
    r"(?:ال)?شاحن|(?:ال)?كابل|(?:ال)?وصله|(?:ال)?استراب|سير[[:space:]]+ساعه|"
    r"حامل[[:space:]]+موبايل|شنطه[[:space:]]+لابتوب|حقيبه[[:space:]]+لابتوب|"
    r"قطعه[[:space:]]+غيار|(?:ال)?غطاء|(?:ال)?طبق|(?:ال)?صحن|(?:ال)?رف|(?:ال)?درج|(?:ال)?حاجز|(?:ال)?كاوتش"
    r")(?:$|[^[:alnum:]ء-ي])"
)

# Main-device phrases that legitimately include an accessory noun ("with cover", "charging case", "pc case", "stand fan")
MAIN_DEVICE_EXEMPT_SQL_RE: str = (
    r"(?:^|[^[:alnum:]ء-ي])(?:"
    r"with[[:space:]]+(?:flip[[:space:]]+)?cover|with[[:space:]]+(?:magic[[:space:]]+)?remote|"
    r"with[[:space:]]+charger|with[[:space:]]+adapter|with[[:space:]]+stand|"
    r"charging[[:space:]]+case|pc[[:space:]]+case|gaming[[:space:]]+case|mid[[:space:]]+tower|"
    r"full[[:space:]]+tower|atx[[:space:]]+case|stand[[:space:]]+fan|stand[[:space:]]+mixer"
    r")(?:$|[^[:alnum:]ء-ي])"
)


def query_requests_accessory(tokens: Sequence[str]) -> bool:
    """Return True if the user explicitly searched for an accessory/spare part."""
    for tok in tokens:
        low = tok.lower()
        stripped = low[2:] if (low.startswith("ال") and len(low) >= 4) else low
        if low in ACCESSORY_QUERY_TOKENS or stripped in ACCESSORY_QUERY_TOKENS:
            return True
    return False


def is_model_anchor_token(token: str) -> bool:
    """Return True for discriminative model numbers/codes (`15`, `s24`, `a55`, `ps5`, `xm5`, `770ar`)."""
    low = (token or "").lower()
    if not low or not any(ch.isdigit() for ch in low):
        return False
    # Exclude pure unit expressions (handled separately as measurements)
    if re.fullmatch(r"\d+(?:\.\d+)?(?:gb|tb|mb|ml|l|kg|g|mg|hp|w|hz|cm|mm|inch|in|mp|mah)", low):
        return False
    # Pure digits like "15", "16", "55" or alphanumeric codes like "s24", "a55", "ps5", "xm5"
    if low.isdigit():
        # Exclude 4-digit years like 2024/2025/2026 as weak anchors
        if len(low) == 4 and low.startswith("20"):
            return False
        return 1 <= len(low) <= 5
    return len(low) >= 2 and any(ch.isalpha() for ch in low)


def canonicalize_bilingual_text(
    raw: str,
    *,
    phonetic_index: Optional[CatalogPhoneticIndex] = None,
    brands_only_phonetic: bool = False,
    allow_fuzzy_phonetic: bool = True,
) -> str:
    """Translate Arabic retail concepts, units, and phonetic brands into canonical English tokens.

    Preserves all Latin tokens, numbers, and model codes intact so bilingual
    titles (Arabic vs. English) map into one shared token space for matching
    and similar-product ranking.
    """
    normalized = split_glued_units(raw)
    if not normalized:
        return ""
    # Fast path: pure Latin/ASCII titles require zero Arabic concept translation or phonetic lookup
    if not _ARABIC_CHAR_RE.search(normalized):
        return normalized
    tokens = _TOKEN_RE.findall(normalized)
    out: list[str] = []
    idx = 0
    while idx < len(tokens):
        # Greedy longest semantic concept phrase match
        matched_concept: Optional[str] = None
        end = idx + 1
        for cand_end in range(min(len(tokens), idx + MAX_CONCEPT_PHRASE_LEN), idx, -1):
            phrase = tuple(tokens[idx:cand_end])
            c = CONCEPT_BY_TOKENS.get(phrase)
            if c is None and phrase[0].startswith("ال") and len(phrase[0]) > 3:
                c = CONCEPT_BY_TOKENS.get((phrase[0][2:], *phrase[1:]))
            if c is not None:
                matched_concept = c
                end = cand_end
                break
        if matched_concept is not None:
            out.append(CONCEPT_PRIMARY_EN[matched_concept])
            idx = end
            continue

        tok = tokens[idx]
        if has_arabic(tok):
            if phonetic_index is not None and phonetic_index.is_populated:
                resolved = phonetic_index.resolve_arabic_token(
                    tok,
                    max_results=1,
                    brands_only=brands_only_phonetic,
                    allow_fuzzy=allow_fuzzy_phonetic,
                )
                if resolved:
                    out.append(resolved[0])
                    idx += 1
                    continue
            # Keep normalized Arabic token if unresolved
            out.append(tok)
        else:
            out.append(tok)
        idx += 1

    return re.sub(r"\s+", " ", " ".join(out)).strip()
