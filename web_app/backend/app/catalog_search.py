"""Rank Arabic and English listing matches without changing the search API."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.bilingual import AR_TO_EN_SYNONYMS, normalize_arabic
from app.routers.radar import PRODUCT_SELECT_COLS


_TOKEN = re.compile(r"\d+\.\d+[^\W_]*|[^\W_]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?\Z")
_COMPACT_MEASUREMENT = re.compile(r"(\d+(?:\.\d+)?)([^\W\d_]+)\Z")
_ARABIC_LETTER = re.compile(r"[ء-ي]")
_BIDI_MARKS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_WORD_START = r"(?:^|[^[:alnum:]ء-ي])"
_WORD_END = r"(?:$|[^[:alnum:]ء-ي])"
_BETWEEN_WORDS = r"[[:space:][:punct:]]+"
_MAX_QUERY_TERMS = 16
_RELATED_MODEL_LIMIT = 40

_UNITS: dict[str, tuple[str, ...]] = {
    "l": ("l", "liter", "liters", "litre", "litres", "لتر", "ليتر", "لترات"),
    "ml": ("ml", "milliliter", "milliliters", "مل", "مللي"),
    "kg": ("kg", "kgs", "kilogram", "kilograms", "كيلو", "كجم", "كيلوجرام"),
    "g": ("g", "gram", "grams", "جرام", "غرام"),
    "gb": ("gb", "جيجا", "جيجابايت", "جيجا بايت"),
    "tb": ("tb", "تيرا", "تيرابايت", "تيرا بايت"),
    "w": ("w", "watt", "watts", "وات", "واط"),
    "hp": ("hp", "حصان"),
    "inch": ("inch", "inches", "بوصه", "انش"),
}
_UNIT_BY_ALIAS = {alias: unit for unit, aliases in _UNITS.items() for alias in aliases}
_ARABIC_UNIT_TERMS = frozenset(alias for alias in _UNIT_BY_ALIAS if _ARABIC_LETTER.match(alias))

# Add common retail spellings without merging a product type into a brand,
# broader category, model number, or ambiguously translated unit.
_CATALOG_ALIASES: dict[str, tuple[str, ...]] = {
    "microwave": ("microwaves", "ميكرويف", "مايكروويف", "مايكرويف", "مكروويف", "ميكرو ويف", "مايكرو ويف"),
    "refrigerator": ("fridge", "fridges", "refrigerators"),
    "washing machine": ("washer", "washing machines"),
    "dishwasher": ("dishwashers", "غساله صحون"),
    "air conditioner": ("air conditioners", "air conditioning"),
    "tv": ("smart tv", "television", "تلفاز"),
    "laptop": ("laptops", "notebook", "notebooks"),
    "iphone": ("اي فون",),
    "galaxy": ("جلاكسي", "جالكسي", "جلاكزى"),
    "lg": ("الجي",),
    "headphones": ("headphone",),
}

_MICROWAVE_PARTS = ("dish", "dishes", "plate", "plates", "tray", "trays", "cover", "covers", "طبق", "غطاء", "صحن", "رف")

_NORMALIZE_TARGET = "'ااااهيوي01234567890123456789'"
_NORMALIZE_SOURCE = "'أإآٱةىؤئ٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹'"
_ARABIC_MARK_RANGE = r"[\u0610-\u061A\u0640\u064B-\u065F\u0670\u06D6-\u06ED]"
_SEARCH_SPACES = r"[[:space:]\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF®™]+"


def _normalize(text_value: str) -> str:
    clean = _BIDI_MARKS.sub(" ", unicodedata.normalize("NFKC", text_value))
    return normalize_arabic(clean).lower().replace("٫", ".")


def _alias_families() -> tuple[dict[str, tuple[str, ...]], dict[tuple[str, ...], str]]:
    families: dict[str, set[str]] = {}
    for arabic, english in AR_TO_EN_SYNONYMS.items():
        if arabic in _ARABIC_UNIT_TERMS:
            continue
        families.setdefault(english[0], {english[0]}).add(arabic)
    for name, aliases in _CATALOG_ALIASES.items():
        families.setdefault(name, {name}).update(aliases)
    aliases_by_name = {
        name: tuple(sorted({_normalize(alias) for alias in aliases}))
        for name, aliases in families.items()
    }
    name_by_tokens = {
        tuple(_TOKEN.findall(alias)): name
        for name, aliases in aliases_by_name.items()
        for alias in aliases
    }
    return aliases_by_name, name_by_tokens


_ALIASES, _CONCEPT_BY_TOKENS = _alias_families()
_MAX_PHRASE = max(map(len, _CONCEPT_BY_TOKENS))


@dataclass(frozen=True)
class SearchTerm:
    pattern: str
    fuzzy_word: str | None = None
    concept: str | None = None


@dataclass(frozen=True)
class CatalogQuery:
    normalized: str
    phrase: str
    terms: tuple[SearchTerm, ...]
    prefer_arabic_titles: bool
    demote_microwave_parts: bool


def _alternatives(expressions: list[str]) -> str:
    return _WORD_START + "(?:" + "|".join(expressions) + ")" + _WORD_END


def _token_pattern(token: str) -> str:
    article = "(?:ال)?" if _ARABIC_LETTER.match(token) and not token.startswith("ال") else ""
    return article + re.escape(token)


def _phrase_body(tokens: list[str] | tuple[str, ...]) -> str:
    return _BETWEEN_WORDS.join(map(_token_pattern, tokens))


def _find_concept(tokens: list[str], start: int) -> tuple[str | None, int]:
    for end in range(min(len(tokens), start + _MAX_PHRASE), start, -1):
        words = tuple(tokens[start:end])
        concept = _CONCEPT_BY_TOKENS.get(words)
        if concept is None and words[0].startswith("ال") and len(words[0]) > 3:
            concept = _CONCEPT_BY_TOKENS.get((words[0][2:], *words[1:]))
        if concept is not None:
            return concept, end
    return None, start + 1


def _find_measurement(tokens: list[str], start: int) -> tuple[str, str, int] | None:
    token = tokens[start]
    compact = _COMPACT_MEASUREMENT.fullmatch(token)
    if compact and compact[2] in _UNIT_BY_ALIAS:
        return compact[1], _UNIT_BY_ALIAS[compact[2]], start + 1
    if _NUMBER.fullmatch(token):
        for end in range(min(len(tokens), start + 3), start + 1, -1):
            unit = _UNIT_BY_ALIAS.get(" ".join(tokens[start + 1:end]))
            if unit:
                return token, unit, end
    return None


def build_catalog_query(query: str) -> CatalogQuery:
    normalized = _normalize(query)
    tokens = _TOKEN.findall(normalized)
    terms: list[SearchTerm] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        measurement = _find_measurement(tokens, index)
        if measurement:
            value, unit, end = measurement
            number = r"(?<![0-9][.٫])" + re.escape(value).replace(r"\.", "[.٫]")
            variants = [number + r"[[:space:]]*" + _phrase_body(_TOKEN.findall(alias)) for alias in _UNITS[unit]]
            terms.append(SearchTerm(_alternatives(variants)))
            index = end
            continue
        concept, end = _find_concept(tokens, index)
        if concept:
            variants = [_phrase_body(_TOKEN.findall(alias)) for alias in _ALIASES[concept]]
            terms.append(SearchTerm(_alternatives(variants), concept=concept))
            index = end
            continue
        # Do not allow typo matching to substitute SKU letters, serial
        # numbers, or capacity values with a similar-looking variant.
        fuzzy = token if len(token) >= 4 and token.isalpha() else None
        terms.append(SearchTerm(_alternatives([_token_pattern(token)]), fuzzy_word=fuzzy))
        index += 1

    terms = list(dict.fromkeys(terms))
    if len(terms) > _MAX_QUERY_TERMS:
        terms = terms[:12] + terms[-4:]
    return CatalogQuery(
        normalized=normalized,
        phrase=_alternatives([_phrase_body(tokens)]) if tokens else "",
        terms=tuple(terms),
        prefer_arabic_titles=bool(_ARABIC_LETTER.search(normalized)),
        demote_microwave_parts=any(term.concept == "microwave" for term in terms)
        and not set(tokens).intersection(_MICROWAVE_PARTS),
    )


def _normalize_sql(expression: str) -> str:
    return (
        f"LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(TRANSLATE({expression}, "
        f"{_NORMALIZE_SOURCE}, {_NORMALIZE_TARGET}), '{_ARABIC_MARK_RANGE}', '', 'g'), "
        f"'{_SEARCH_SPACES}', ' ', 'g')))"
    )


_TITLE = _normalize_sql("COALESCE(p.product_title, '')")
_TITLE_AND_BRAND = _normalize_sql("COALESCE(p.product_title, '') || ' ' || COALESCE(p.brand, '')")
_LEGACY_DOCUMENT = _normalize_sql(
    "COALESCE(p.product_title, '') || ' ' || COALESCE(p.brand, '') || ' ' || "
    "REPLACE(COALESCE(p.sub_category, ''), '_', ' ') || ' ' || "
    "REPLACE(COALESCE(p.canonical_product_key, ''), '_', ' ')"
)
_MICROWAVE_WORDS = "(?:" + "|".join(_phrase_body(_TOKEN.findall(alias)) for alias in _ALIASES["microwave"]) + ")"
_PART_WORDS = "(?:" + "|".join(_token_pattern(part) for part in _MICROWAVE_PARTS) + ")"
_PART_TITLE = (
    _WORD_START + _MICROWAVE_WORDS + r"[[:space:]-]+" + _PART_WORDS + _WORD_END +
    r"|^[[:space:]]*" + _PART_WORDS + "(?=" + _WORD_END + ").*" + _WORD_START + _MICROWAVE_WORDS + _WORD_END
)
_PART_ORDER = f"CASE WHEN :demote_parts AND {_TITLE} ~ :part_title THEN 1 ELSE 0 END"
_SCRIPT_ORDER = "CASE WHEN :prefer_arabic AND p.product_title ~ '[ء-ي]' THEN 0 ELSE 1 END"


def _term_parameters(query: CatalogQuery, limit: int) -> dict[str, Any]:
    return {
        **{f"term_{index}": term.pattern for index, term in enumerate(query.terms)},
        "limit": limit,
        "prefer_arabic": query.prefer_arabic_titles,
        "demote_parts": query.demote_microwave_parts,
        "part_title": _PART_TITLE,
    }


def exact_catalog_sql(query: CatalogQuery, limit: int, *, indexed: bool = True) -> tuple[str, dict[str, Any]]:
    document = "p.search_document" if indexed else _LEGACY_DOCUMENT
    matches = " AND ".join(f"{document} ~ :term_{index}" for index in range(len(query.terms)))
    title_matches = " AND ".join(f"{_TITLE_AND_BRAND} ~ :term_{index}" for index in range(len(query.terms)))
    sql = f"""
    WITH direct_matches AS MATERIALIZED (
        SELECT p.product_sk, p.canonical_product_key,
            CASE
                WHEN {_TITLE} = :normalized THEN 0
                WHEN {_TITLE} ~ :phrase THEN 1
                WHEN {title_matches} THEN 2
                ELSE 3
            END AS relevance
        FROM gold.mart_product_verdicts p
        WHERE {matches}
    ),
    verified_models AS (
        SELECT d.canonical_product_key
        FROM direct_matches d
        JOIN gold.mart_cross_store_matches m USING (canonical_product_key)
        WHERE d.relevance <= 2
          AND m.listings_json @> jsonb_build_array(jsonb_build_object('product_sk', d.product_sk))
        GROUP BY d.canonical_product_key
        ORDER BY MIN(d.relevance), d.canonical_product_key
        LIMIT :related_model_limit
    ),
    candidates AS (
        SELECT product_sk AS matched_sk, relevance FROM direct_matches
        UNION ALL
        SELECT offer.value->>'product_sk', 4
        FROM verified_models v
        JOIN gold.mart_cross_store_matches m USING (canonical_product_key)
        CROSS JOIN LATERAL jsonb_array_elements(m.listings_json) AS offer(value)
    ),
    ranked AS (
        SELECT matched_sk, MIN(relevance) AS relevance
        FROM candidates
        GROUP BY matched_sk
    )
    SELECT {PRODUCT_SELECT_COLS}, COUNT(*) OVER () AS search_total
    FROM gold.mart_product_verdicts p
    JOIN ranked r ON r.matched_sk = p.product_sk
    ORDER BY {_PART_ORDER}, r.relevance, {_SCRIPT_ORDER}, p.in_stock DESC, p.real_discount_pct DESC, p.product_sk
    LIMIT :limit
    """
    return sql, {
        **_term_parameters(query, limit),
        "normalized": query.normalized,
        "phrase": query.phrase,
        "related_model_limit": _RELATED_MODEL_LIMIT,
    }


def fuzzy_catalog_sql(query: CatalogQuery, limit: int, *, indexed: bool = True) -> tuple[str, dict[str, Any]] | None:
    if not any(term.fuzzy_word for term in query.terms):
        return None
    document = "p.search_document" if indexed else _LEGACY_DOCUMENT
    params = _term_parameters(query, limit)
    matches, misses, scores = [], [], []
    for index, term in enumerate(query.terms):
        exact = f"{document} ~ :term_{index}"
        if not term.fuzzy_word:
            matches.append(exact)
            continue
        word = f"word_{index}"
        params[word] = term.fuzzy_word
        matches.append(f"({exact} OR {document} %>> :{word})")
        misses.append(f"CASE WHEN {exact} THEN 0 ELSE 1 END")
        scores.append(f"strict_word_similarity(:{word}, {document})")

    missed = " + ".join(misses)
    return f"""
        SELECT {PRODUCT_SELECT_COLS}, COUNT(*) OVER () AS search_total
        FROM gold.mart_product_verdicts p
        WHERE {' AND '.join(matches)} AND ({missed}) <= 2
        ORDER BY {_PART_ORDER}, ({missed}), ({' + '.join(scores)}) DESC,
            {_SCRIPT_ORDER}, p.in_stock DESC, p.real_discount_pct DESC, p.product_sk
        LIMIT :limit
    """, params


def _database_code(error: DBAPIError) -> str | None:
    return getattr(error.orig, "pgcode", None) or getattr(error.orig, "sqlstate", None)


def search_catalog(db: Connection, query: CatalogQuery, limit: int) -> tuple[list[dict[str, Any]], int, str]:
    indexed = True
    sql, params = exact_catalog_sql(query, limit)
    try:
        rows = db.execute(text(sql), params).mappings().all()
    except DBAPIError as error:
        if _database_code(error) != "42703" or "search_document" not in str(error.orig):
            raise
        # A serving snapshot from before search_document can still search its
        # existing listing fields during a warehouse rollout.
        db.rollback()
        indexed = False
        sql, params = exact_catalog_sql(query, limit, indexed=indexed)
        rows = db.execute(text(sql), params).mappings().all()

    if rows:
        return [dict(row) for row in rows], int(rows[0]["search_total"]), "text_search"
    fuzzy = fuzzy_catalog_sql(query, limit, indexed=indexed)
    if fuzzy is not None:
        sql, params = fuzzy
        try:
            rows = db.execute(text(sql), params).mappings().all()
        except DBAPIError as error:
            if _database_code(error) != "42883":
                raise
            # This compatibility path allows literal search before pg_trgm is enabled.
            db.rollback()
        if rows:
            return [dict(row) for row in rows], int(rows[0]["search_total"]), "fuzzy_trgm"
    return [], 0, "text_search"
