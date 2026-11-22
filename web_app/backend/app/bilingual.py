"""Bilingual Arabic <-> English normalization and search expansion for FastAPI backend.

Standalone module (zero dependency on `data_platform/`) so Render deployments
of `web_app/backend` work self-contained while staying 1:1 with the ingestion
synonym vocabulary.
"""

from __future__ import annotations

import re

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

AR_TO_EN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "تلاجه": ("refrigerator", "fridge"),
    "ثلاجه": ("refrigerator", "fridge"),
    "غساله اطباق": ("dishwasher",),
    "غساله": ("washing machine", "washer"),
    "تكييف": ("air conditioner", "ac"),
    "مكيف": ("air conditioner", "ac"),
    "شاشه": ("tv", "smart tv"),
    "تلفزيون": ("tv", "smart tv"),
    "تليفزيون": ("tv", "smart tv"),
    "بوتاجاز": ("cooker", "gas cooker"),
    "بوتجاز": ("cooker", "gas cooker"),
    "ميكروويف": ("microwave",),
    "ديب فريزر": ("freezer",),
    "فريزر": ("freezer",),
    "سخان": ("water heater", "heater"),
    "مكنسه": ("vacuum",),
    "مروحه": ("fan",),
    "خلاط": ("blender",),
    "كاتل": ("kettle",),
    "قلايه هوائيه": ("air fryer",),
    "مكواه": ("iron",),
    "فرن": ("oven",),
    "ايفون": ("iphone", "apple"),
    "ابل": ("apple",),
    "ماك بوك": ("macbook",),
    "سامسونج": ("samsung",),
    "جالاكسي": ("galaxy",),
    "شاومي": ("xiaomi",),
    "ريدمي": ("redmi",),
    "اوبو": ("oppo",),
    "ريلمي": ("realme",),
    "انفينكس": ("infinix",),
    "هواوي": ("huawei",),
    "هونر": ("honor",),
    "لينوفو": ("lenovo",),
    "ديل": ("dell",),
    "اتش بي": ("hp",),
    "اسوس": ("asus",),
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
    "لابتوب": ("laptop",),
    "لاب توب": ("laptop",),
    "موبايل": ("smartphone", "mobile"),
    "هاتف": ("smartphone", "mobile"),
    "تابلت": ("tablet",),
    "سماعه": ("headphones", "earbuds"),
    "سماعات": ("headphones", "earbuds"),
    "بلايستيشن": ("playstation", "ps5"),
    "بوصه": ("inch",),
    "حصان": ("hp",),
    "جيجا": ("gb",),
    "جيجابايت": ("gb",),
    "تيرا": ("tb",),
    "كيلو": ("kg",),
    "كجم": ("kg",),
    "لتر": ("l", "liter"),
    "وات": ("w", "watt"),
    "زيت": ("oil",),
    "سمن": ("ghee",),
    "سمنه": ("ghee",),
    "رز": ("rice",),
    "ارز": ("rice",),
    "مكرونه": ("pasta",),
    "لبن": ("milk",),
    "حليب": ("milk",),
    "جبنه": ("cheese",),
    "سكر": ("sugar",),
    "شاي": ("tea",),
    "قهوه": ("coffee",),
    "عسل": ("honey",),
    "مسحوق": ("detergent",),
    "جاكيت": ("jacket",),
    "بنطلون": ("pants",),
    "قميص": ("shirt",),
    "حذاء": ("shoes",),
    "فستان": ("dress",),
}

EN_TO_AR_SYNONYMS: dict[str, tuple[str, ...]] = {}
for _ar, _ens in AR_TO_EN_SYNONYMS.items():
    for _en in _ens:
        prev = EN_TO_AR_SYNONYMS.get(_en, ())
        if _ar not in prev:
            EN_TO_AR_SYNONYMS[_en] = (*prev, _ar)

_AR_KEYS_SORTED: tuple[str, ...] = tuple(sorted(AR_TO_EN_SYNONYMS.keys(), key=len, reverse=True))
_EN_KEYS_SORTED: tuple[str, ...] = tuple(sorted(EN_TO_AR_SYNONYMS.keys(), key=len, reverse=True))

_AR_UNIT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d+(?:\.\d+)?)\s*بوصه\b"), r"\1 inch"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*حصان\b"), r"\1 hp"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:جيجابايت|جيجا)\b"), r"\1 gb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:تيرابايت|تيرا)\b"), r"\1 tb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:كيلو|كجم)\b"), r"\1 kg"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*لتر\b"), r"\1 l"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*وات\b"), r"\1 w"),
)


def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    cleaned = _AR_DIACRITICS_RE.sub("", text)
    cleaned = cleaned.translate(_AR_DIGITS_TRANS)
    cleaned = cleaned.translate(_AR_LETTERS_TRANS)
    cleaned = re.sub(r"[\u200b\u200c\u200d\ufeff®™]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def translate_arabic_retail_terms(text: str) -> str:
    if not text:
        return ""
    out = normalize_arabic(text).lower()
    for pat, repl in _AR_UNIT_REPLACEMENTS:
        out = pat.sub(repl, out)
    for ar_key in _AR_KEYS_SORTED:
        if ar_key in out:
            out = re.sub(
                rf"(?<![\u0600-\u06FF])(?:ال)?{re.escape(ar_key)}(?![\u0600-\u06FF])",
                f" {AR_TO_EN_SYNONYMS[ar_key][0]} ",
                out,
            )
    return re.sub(r"\s+", " ", out).strip()


def expand_search_query(query: str) -> list[str]:
    """Expand an Arabic or English query into bilingual variants for fuzzy/ILIKE search."""
    raw = (query or "").strip()
    if not raw:
        return []

    norm = normalize_arabic(raw).lower()
    variants: list[str] = []
    for cand in (raw.lower(), norm, translate_arabic_retail_terms(norm)):
        if cand and cand not in variants:
            variants.append(cand)

    # Secondary English synonym (e.g. "fridge" alongside "refrigerator", "ac" alongside "air conditioner")
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

    # English -> Arabic translation so EN queries match Arabic-only listings
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

    return variants[:5]
