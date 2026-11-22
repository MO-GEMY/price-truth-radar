"""Bilingual Arabic <-> English normalization and Egyptian retail synonym engine.

Used by:
- The 3-tier hybrid cross-store matcher (`matcher.py`) so Arabic titles
  (e.g. `تلفزيون سامسونج 65 بوصة`) match English titles (`Samsung 65 Inch TV`).
- Search document enrichment & query expansion across Arabic and English terms.
"""

from __future__ import annotations

import re

# Arabic diacritics (tashkeel) and tatweel
_AR_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_AR_DIGITS_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
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

# Normalized Arabic phrase/token -> canonical English equivalents (Egyptian retail vocabulary)
AR_TO_EN_SYNONYMS: dict[str, tuple[str, ...]] = {
    # Home appliances
    "تلاجه": ("refrigerator", "fridge"),
    "ثلاجه": ("refrigerator", "fridge"),
    "ثلاجات": ("refrigerator", "fridge"),
    "تلاجات": ("refrigerator", "fridge"),
    "غساله اطباق": ("dishwasher",),
    "غساله صحون": ("dishwasher",),
    "غساله": ("washing machine", "washer"),
    "غسالات": ("washing machine", "washer"),
    "مجفف": ("dryer",),
    "تكييف": ("air conditioner", "ac"),
    "مكيف": ("air conditioner", "ac"),
    "تكييفات": ("air conditioner", "ac"),
    "شاشه": ("tv", "smart tv", "screen"),
    "شاشات": ("tv", "screen", "monitor"),
    "تلفزيون": ("tv", "smart tv"),
    "تليفزيون": ("tv", "smart tv"),
    "بوتاجاز": ("cooker", "gas cooker", "stove"),
    "بوتجاز": ("cooker", "gas cooker", "stove"),
    "موقد": ("cooker", "stove"),
    "ميكروويف": ("microwave",),
    "مايكروويف": ("microwave",),
    "ديب فريزر": ("deep freezer", "freezer"),
    "فريزر": ("freezer",),
    "سخان": ("water heater", "heater"),
    "مكنسه": ("vacuum", "vacuum cleaner"),
    "مروحه": ("fan",),
    "خلاط": ("blender",),
    "كاتل": ("kettle",),
    "غلايه": ("kettle",),
    "قلايه هوائيه": ("air fryer",),
    "اير فراير": ("air fryer",),
    "مكواه": ("iron",),
    "فرن": ("oven",),
    "شفاط": ("hood", "exhaust"),
    "نوفروست": ("no frost", "nofrost"),
    "دي فروست": ("defrost",),
    "انفرتر": ("inverter",),
    "ديجيتال": ("digital",),
    "سبليت": ("split",),
    "ستانلس": ("stainless",),
    "استانلس": ("stainless",),
    "ستيل": ("steel",),
    "بروفيشنال": ("professional",),
    "شعله": ("burner",),
    "شعلات": ("burner",),
    "بارد ساخن": ("cooling heating",),
    "بارد فقط": ("cooling only",),
    # Electronics & brands
    "ايفون": ("iphone", "apple"),
    "ابل": ("apple",),
    "ماك بوك": ("macbook", "apple"),
    "ايباد": ("ipad", "apple"),
    "سامسونج": ("samsung",),
    "جالاكسي": ("galaxy",),
    "جالكسي": ("galaxy",),
    "شاومي": ("xiaomi",),
    "ريدمي": ("redmi", "xiaomi"),
    "بوكو": ("poco", "xiaomi"),
    "اوبو": ("oppo",),
    "ريلمي": ("realme",),
    "انفينكس": ("infinix",),
    "تكنو": ("tecno",),
    "هواوي": ("huawei",),
    "هونر": ("honor",),
    "نوكيا": ("nokia",),
    "موتورولا": ("motorola",),
    "فيفو": ("vivo",),
    "لينوفو": ("lenovo",),
    "ديل": ("dell",),
    "اتش بي": ("hp",),
    "اسوس": ("asus",),
    "ايسر": ("acer",),
    "توشيبا": ("toshiba",),
    "شارب": ("sharp",),
    "تورنيدو": ("tornado",),
    "ال جي": ("lg",),
    "سوني": ("sony",),
    "بوش": ("bosch",),
    "بيكو": ("beko",),
    "زانوسي": ("zanussi",),
    "فريش": ("fresh",),
    "كاريير": ("carrier",),
    "ميديا": ("midea",),
    "يونيون اير": ("unionaire",),
    "كريازي": ("kiriazi",),
    "هوفير": ("hoover",),
    "اريستون": ("ariston",),
    "اندست": ("indesit",),
    "وايت بوينت": ("white point",),
    "وايت ويل": ("white whale",),
    "لا جيرمانيا": ("la germania",),
    "كينوود": ("kenwood",),
    "براون": ("braun",),
    "فيليبس": ("philips",),
    "تيفال": ("tefal",),
    "مولينكس": ("moulinex",),
    "بلاك اند ديكر": ("black decker",),
    "هاير": ("haier",),
    "لابتوب": ("laptop",),
    "لاب توب": ("laptop",),
    "كمبيوتر": ("pc", "computer"),
    "موبايل": ("smartphone", "mobile"),
    "هاتف": ("smartphone", "mobile"),
    "تليفون": ("smartphone", "mobile"),
    "تابلت": ("tablet",),
    "سماعه": ("headphones", "earbuds"),
    "سماعات": ("headphones", "earbuds"),
    "ساعه ذكيه": ("smartwatch",),
    "بلايستيشن": ("playstation", "ps5"),
    "ذكي": ("smart",),
    "ذكية": ("smart",),
    "الذكي": ("smart",),
    "ريموت": ("remote",),
    # Units & specs
    "بوصه": ("inch",),
    "حصان": ("hp",),
    "جيجا": ("gb",),
    "جيجابايت": ("gb",),
    "تيرا": ("tb",),
    "تيرابايت": ("tb",),
    "كيلو": ("kg",),
    "كجم": ("kg",),
    "لتر": ("l", "liter"),
    "مل": ("ml",),
    "جرام": ("g",),
    "جم": ("g",),
    "وات": ("w", "watt"),
    "قدم": ("ft",),
    "سم": ("cm",),
    "رام": ("ram",),
    "هيرتز": ("hz",),
    # Groceries & fashion
    "زيت": ("oil",),
    "سمن": ("ghee",),
    "سمنه": ("ghee",),
    "رز": ("rice",),
    "ارز": ("rice",),
    "مكرونه": ("pasta",),
    "لبن": ("milk",),
    "حليب": ("milk",),
    "جبنه": ("cheese",),
    "جبن": ("cheese",),
    "زبده": ("butter",),
    "سكر": ("sugar",),
    "دقيق": ("flour",),
    "شاي": ("tea",),
    "قهوه": ("coffee",),
    "بن": ("coffee",),
    "عسل": ("honey",),
    "عصير": ("juice",),
    "مسحوق": ("detergent",),
    "صلصه": ("sauce", "paste"),
    "تونه": ("tuna",),
    "جاكيت": ("jacket",),
    "بنطلون": ("pants", "trousers"),
    "جينز": ("jeans",),
    "قميص": ("shirt",),
    "تيشيرت": ("t-shirt", "tshirt"),
    "بولو": ("polo",),
    "فستان": ("dress",),
    "حذاء": ("shoes",),
    "كوتشي": ("sneakers", "shoes"),
    "شنطه": ("bag",),
}

# Build reverse EN -> AR synonym map for bilingual query expansion
EN_TO_AR_SYNONYMS: dict[str, tuple[str, ...]] = {}
for _ar_term, _en_terms in AR_TO_EN_SYNONYMS.items():
    for _en in _en_terms:
        existing = EN_TO_AR_SYNONYMS.get(_en, ())
        if _ar_term not in existing:
            EN_TO_AR_SYNONYMS[_en] = (*existing, _ar_term)

# Sorted longest-first so multi-word phrases ("غساله اطباق", "قلايه هوائيه", "ال جي") match before single words
_AR_KEYS_SORTED: tuple[str, ...] = tuple(
    sorted(AR_TO_EN_SYNONYMS.keys(), key=len, reverse=True)
)
_EN_KEYS_SORTED: tuple[str, ...] = tuple(
    sorted(EN_TO_AR_SYNONYMS.keys(), key=len, reverse=True)
)

# Unit normalization regexes (after normalize_arabic)
_AR_UNIT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d+(?:\.\d+)?)\s*بوصه\b"), r"\1 inch"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*حصان\b"), r"\1 hp"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:جيجابايت|جيجا)\b"), r"\1 gb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:تيرابايت|تيرا)\b"), r"\1 tb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:كيلو|كجم)\b"), r"\1 kg"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*لتر\b"), r"\1 l"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*وات\b"), r"\1 w"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*سم\b"), r"\1 cm"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*هيرتز\b"), r"\1 hz"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:شعله|شعلات)\b"), r"\1 burner"),
)


def normalize_arabic(text: str) -> str:
    """Normalize Arabic letters, strip tashkeel/tatweel, and map Arabic-Indic digits to ASCII."""
    if not text:
        return ""
    cleaned = _AR_DIACRITICS_RE.sub("", text)
    cleaned = cleaned.translate(_AR_DIGITS_TRANS)
    cleaned = cleaned.translate(_AR_LETTERS_TRANS)
    # Strip invisible zero-width marks & trademark glyphs
    cleaned = re.sub(r"[\u200b\u200c\u200d\ufeff®™]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def translate_arabic_retail_terms(text: str) -> str:
    """Normalize Arabic text and translate known Egyptian retail terms/units to canonical English.

    Preserves all Latin model numbers, numbers, and already-English tokens so
    Arabic titles like `تلفزيون سامسونج S85H مقاس 65 بوصة` become
    `tv samsung s85h 65 inch ...` for deterministic + hybrid matching.
    """
    if not text:
        return ""
    norm = normalize_arabic(text).lower()
    # Strip common Arabic definite prefix "ال" on known retail nouns/brands when attached
    for pat, repl in _AR_UNIT_REPLACEMENTS:
        norm = pat.sub(repl, norm)

    out = norm
    for ar_key in _AR_KEYS_SORTED:
        en_primary = AR_TO_EN_SYNONYMS[ar_key][0]
        # Match standalone or with leading "ال"
        if ar_key in out:
            out = re.sub(
                rf"(?<![\u0600-\u06FF])(?:ال)?{re.escape(ar_key)}(?![\u0600-\u06FF])",
                f" {en_primary} ",
                out,
            )
    return re.sub(r"\s+", " ", out).strip()


def expand_search_query(query: str) -> list[str]:
    """Return bilingual query expansions (normalized original + AR<->EN translations).

    Examples:
      - "تلاجة سامسونج" -> ["تلاجه سامسونج", "refrigerator samsung", "fridge samsung"]
      - "iphone 16"      -> ["iphone 16", "ايفون 16"]
      - "شاشة 55 بوصة"   -> ["شاشه 55 بوصه", "tv 55 inch", "smart tv 55 inch"]
    """
    norm = normalize_arabic(query).lower()
    if not norm:
        return []

    variants: list[str] = [norm]
    translated = translate_arabic_retail_terms(norm)
    if translated and translated not in variants:
        variants.append(translated)

    # Also generate secondary English synonym (e.g., "fridge" alongside "refrigerator")
    alt_en = norm
    for pat, repl in _AR_UNIT_REPLACEMENTS:
        alt_en = pat.sub(repl, alt_en)
    for ar_key in _AR_KEYS_SORTED:
        syns = AR_TO_EN_SYNONYMS[ar_key]
        if ar_key in alt_en:
            chosen = syns[1] if len(syns) > 1 else syns[0]
            alt_en = re.sub(
                rf"(?<![\u0600-\u06FF])(?:ال)?{re.escape(ar_key)}(?![\u0600-\u06FF])",
                f" {chosen} ",
                alt_en,
            )
    alt_en = re.sub(r"\s+", " ", alt_en).strip()
    if alt_en and alt_en not in variants:
        variants.append(alt_en)

    # EN -> AR expansion (so English search also hits Arabic-only titles like DubaiPhone/ElAraby)
    ar_ver = norm
    for en_key in _EN_KEYS_SORTED:
        if re.search(rf"\b{re.escape(en_key)}\b", ar_ver):
            ar_ver = re.sub(
                rf"\b{re.escape(en_key)}\b",
                f" {EN_TO_AR_SYNONYMS[en_key][0]} ",
                ar_ver,
            )
    ar_ver = re.sub(r"\s+", " ", ar_ver).strip()
    if ar_ver and ar_ver not in variants:
        variants.append(ar_ver)

    return variants[:4]


def build_search_document(
    *,
    product_title: str,
    brand: str = "",
    category: str = "",
    sub_category: str = "",
    store_name: str = "",
) -> str:
    """Build a normalized bilingual search document combining AR + EN tokens."""
    base = normalize_arabic(f"{product_title} {brand} {sub_category.replace('_', ' ')} {category.replace('_', ' ')} {store_name}").lower()
    extras: list[str] = []
    translated = translate_arabic_retail_terms(base)
    if translated and translated != base:
        extras.append(translated)
    for en_key, ar_vals in EN_TO_AR_SYNONYMS.items():
        if re.search(rf"\b{re.escape(en_key)}\b", base):
            extras.append(ar_vals[0])
    combined = " ".join([base, *extras])
    # Deduplicate tokens while preserving order
    seen: set[str] = set()
    tokens: list[str] = []
    for tok in combined.split():
        if tok not in seen:
            seen.add(tok)
            tokens.append(tok)
    return " ".join(tokens)
