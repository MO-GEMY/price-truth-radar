"""Bilingual Arabic <-> English catalog search planner, phonetic expander, and SQL ranker.

Combines:
1. Semantic concept & unit normalization from `app.bilingual_search`.
2. Automatic catalog phonetic transliteration (`CatalogPhoneticIndex`, 24h RAM cached)
   for unresolved Arabic brand/model queries (`سيرافي -> cerave`, `باسيوس -> baseus`,
   `سوكاني -> sokany`, `لاروش -> la roche`, `ريدراجون -> redragon`, `سكيتشرز -> skechers`).
3. Precision ranking:
   - Strong accessory demotion when searching for main devices (disabled automatically
     if the query explicitly asks for an accessory/part).
   - Exact model-number/code anchor boost (`15`, `s24`, `a55`, `ps5`, `xm5`, etc.).
   - Multi-token coverage ranking (full AND match > high-coverage match > bounded pg_trgm).
   - In-stock listings prioritized cleanly above out-of-stock listings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.bilingual_search import (
    ACCESSORY_TITLE_SQL_RE,
    CONCEPT_ALIASES_NORM,
    CONCEPT_BY_TOKENS,
    MAIN_DEVICE_EXEMPT_SQL_RE,
    MAX_CONCEPT_PHRASE_LEN,
    UNIT_FAMILIES,
    CatalogPhoneticIndex,
    get_catalog_phonetic_index,
    has_arabic,
    is_model_anchor_token,
    normalize_arabic_text,
    query_requests_accessory,
    split_glued_units,
)
from app.routers.radar import PRODUCT_SELECT_COLS


_TOKEN = re.compile(r"\d+\.\d+[^\W_]*|[^\W_]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?\Z")
_COMPACT_MEASUREMENT = re.compile(r"(\d+(?:\.\d+)?)([^\W\d_]+)\Z")
_ARABIC_LETTER = re.compile(r"[ء-ي]")
_WORD_START = r"(?:^|[^[:alnum:]ء-ي])"
_WORD_END = r"(?:$|[^[:alnum:]ء-ي])"
_BETWEEN_WORDS = r"[[:space:][:punct:]]+"
_MAX_QUERY_TERMS = 16
_RELATED_MODEL_LIMIT = 40

_UNIT_BY_ALIAS: dict[str, str] = {
    normalize_arabic_text(alias): unit
    for unit, aliases in UNIT_FAMILIES.items()
    for alias in aliases
}

_NORMALIZE_TARGET = "'ااااهيوي01234567890123456789'"
_NORMALIZE_SOURCE = "'أإآٱةىؤئ٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹'"
_ARABIC_MARK_RANGE = r"[\u0610-\u061A\u0640\u064B-\u065F\u0670\u06D6-\u06ED]"
_SEARCH_SPACES = r"[[:space:]\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF®™]+"

_ACCESSORY_SUBCATEGORIES_SQL = (
    "('accessories', 'cables', 'chargers', 'cases', 'bags', 'spare_parts', 'playstation_accessories')"
)

# Major appliances/TVs where any listing below 1,500 EGP is guaranteed to be a spare part
# (e.g., Elaraby "Meat Tipper", "Ice Pack", "Eggs Pocket", "LED Lamp" for Sharp refrigerators)
_MAJOR_APPLIANCE_CONCEPTS = frozenset(
    {
        "refrigerator",
        "freezer",
        "washing machine",
        "dishwasher",
        "air conditioner",
        "cooker",
        "oven",
        "microwave",
        "television",
    }
)


@dataclass(frozen=True)
class SearchTerm:
    pattern: str
    fuzzy_word: str | None = None
    concept: str | None = None
    is_anchor: bool = False
    phonetic_expansions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogQuery:
    normalized: str
    phrase: str
    terms: tuple[SearchTerm, ...]
    prefer_arabic_titles: bool
    demote_accessories: bool
    demote_microwave_parts: bool  # Retained for backwards compatibility with existing callers/tests
    min_main_price: float = 0.0


def _alternatives(expressions: list[str]) -> str:
    return _WORD_START + "(?:" + "|".join(expressions) + ")" + _WORD_END


def _token_pattern(token: str) -> str:
    article = "(?:ال)?" if _ARABIC_LETTER.match(token) and not token.startswith("ال") else ""
    return article + re.escape(token)


def _phrase_body(tokens: list[str] | tuple[str, ...]) -> str:
    return _BETWEEN_WORDS.join(map(_token_pattern, tokens))


def _find_concept(tokens: list[str], start: int) -> tuple[str | None, int]:
    for end in range(min(len(tokens), start + MAX_CONCEPT_PHRASE_LEN), start, -1):
        words = tuple(tokens[start:end])
        concept = CONCEPT_BY_TOKENS.get(words)
        if concept is None and words[0].startswith("ال") and len(words[0]) > 3:
            concept = CONCEPT_BY_TOKENS.get((words[0][2:], *words[1:]))
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


def build_catalog_query(
    query: str,
    *,
    phonetic_index: Optional[CatalogPhoneticIndex] = None,
    db: Optional[Connection] = None,
) -> CatalogQuery:
    """Parse and expand an Arabic/English search query into structured SearchTerms."""
    normalized_raw = normalize_arabic_text(query)
    # Split glued Arabic units (`256جيجا`, `1.5حصان`, `55بوصه`, `200مل`, `8كيلو`)
    prepared = split_glued_units(query)
    tokens = _TOKEN.findall(prepared)

    terms: list[SearchTerm] = []
    idx_cache: Optional[CatalogPhoneticIndex] = phonetic_index
    index = 0

    while index < len(tokens):
        token = tokens[index]
        measurement = _find_measurement(tokens, index)
        if measurement:
            value, unit, end = measurement
            number = r"(?<![0-9][.٫])" + re.escape(value).replace(r"\.", "[.٫]")
            variants = [
                number + r"[[:space:]]*" + _phrase_body(_TOKEN.findall(alias))
                for alias in UNIT_FAMILIES[unit]
            ]
            terms.append(SearchTerm(_alternatives(variants), is_anchor=True))
            index = end
            continue

        concept, end = _find_concept(tokens, index)
        if concept:
            variants = [_phrase_body(_TOKEN.findall(alias)) for alias in CONCEPT_ALIASES_NORM[concept]]
            terms.append(SearchTerm(_alternatives(variants), concept=concept))
            index = end
            continue

        # Unresolved Arabic token -> automatic phonetic transliteration against catalog vocabulary
        if has_arabic(token):
            if idx_cache is None and db is not None:
                idx_cache = get_catalog_phonetic_index(db)
            phonetic_hits: list[str] = []
            if idx_cache is not None and idx_cache.is_populated:
                phonetic_hits = idx_cache.resolve_arabic_token(token, max_results=3)

            if phonetic_hits:
                exprs = [_token_pattern(token)] + [
                    _phrase_body(_TOKEN.findall(hit)) for hit in phonetic_hits
                ]
                # Deduplicate preserving order
                exprs = list(dict.fromkeys(exprs))
                terms.append(
                    SearchTerm(
                        _alternatives(exprs),
                        fuzzy_word=None,
                        phonetic_expansions=tuple(phonetic_hits),
                    )
                )
            else:
                fuzzy = token if len(token) >= 4 and token.isalpha() else None
                terms.append(SearchTerm(_alternatives([_token_pattern(token)]), fuzzy_word=fuzzy))
            index += 1
            continue

        # Latin or alphanumeric token
        anchor = is_model_anchor_token(token)
        # Never fuzz short tokens or model/numeric anchors (`15`, `s24`, `a17`, `770ar`)
        fuzzy = token if (not anchor and len(token) >= 4 and token.isalpha()) else None
        terms.append(SearchTerm(_alternatives([_token_pattern(token)]), fuzzy_word=fuzzy, is_anchor=anchor))
        index += 1

    terms = list(dict.fromkeys(terms))
    if len(terms) > _MAX_QUERY_TERMS:
        terms = terms[:12] + terms[-4:]

    # Accessory demotion: active for main-device/product queries unless the user
    # explicitly asked for an accessory/spare part (e.g., case, cover, charger, dish, جراب, كفر, شاحن, غطاء).
    explicit_acc = query_requests_accessory(tokens) or any(
        term.concept in ("case", "charger", "cable", "screen protector", "bag")
        for term in terms
    )
    demote_acc = bool(terms) and not explicit_acc
    demote_mw = any(term.concept == "microwave" for term in terms) and not explicit_acc
    min_main_price = (
        1500.0
        if (demote_acc and any(term.concept in _MAJOR_APPLIANCE_CONCEPTS for term in terms))
        else 0.0
    )

    return CatalogQuery(
        normalized=normalized_raw,
        phrase=_alternatives([_phrase_body(tokens)]) if tokens else "",
        terms=tuple(terms),
        prefer_arabic_titles=has_arabic(normalized_raw),
        demote_accessories=demote_acc,
        demote_microwave_parts=demote_mw,
        min_main_price=min_main_price,
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

_ACCESSORY_ORDER = (
    f"CASE WHEN :demote_parts AND ("
    f"LOWER(COALESCE(p.sub_category, '')) IN {_ACCESSORY_SUBCATEGORIES_SQL} "
    f"OR ({_TITLE} ~ :acc_title_re AND NOT ({_TITLE} ~ :main_exempt_re)) "
    f"OR (:min_main_price > 0 AND p.current_price < :min_main_price)"
    f") THEN 1 ELSE 0 END"
)
_SCRIPT_ORDER = "CASE WHEN :prefer_arabic AND p.product_title ~ '[ء-ي]' THEN 0 ELSE 1 END"


def _anchor_title_order_sql(query: CatalogQuery) -> str:
    anchor_idxs = [i for i, term in enumerate(query.terms) if term.is_anchor]
    if not anchor_idxs:
        return "0"
    cond = " AND ".join(f"{_TITLE} ~ :term_{i}" for i in anchor_idxs)
    return f"CASE WHEN {cond} THEN 0 ELSE 1 END"


def _term_parameters(query: CatalogQuery, limit: int) -> dict[str, Any]:
    return {
        **{f"term_{index}": term.pattern for index, term in enumerate(query.terms)},
        "limit": limit,
        "prefer_arabic": query.prefer_arabic_titles,
        "demote_parts": query.demote_accessories,
        "acc_title_re": ACCESSORY_TITLE_SQL_RE,
        "main_exempt_re": MAIN_DEVICE_EXEMPT_SQL_RE,
        "min_main_price": query.min_main_price,
    }


def exact_catalog_sql(query: CatalogQuery, limit: int, *, indexed: bool = True) -> tuple[str, dict[str, Any]]:
    document = "p.search_document" if indexed else _LEGACY_DOCUMENT
    matches = " AND ".join(f"{document} ~ :term_{index}" for index in range(len(query.terms)))
    title_matches = " AND ".join(f"{_TITLE_AND_BRAND} ~ :term_{index}" for index in range(len(query.terms)))
    anchor_order = _anchor_title_order_sql(query)

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
    ),
    deduped AS (
        SELECT
            {PRODUCT_SELECT_COLS},
            {_ACCESSORY_ORDER} AS part_order,
            {anchor_order} AS anchor_order,
            r.relevance AS relevance,
            {_SCRIPT_ORDER} AS script_order,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(p.parent_product_key, p.store_name || '::' || p.product_sk)
                ORDER BY {_ACCESSORY_ORDER}, {anchor_order}, r.relevance, p.in_stock DESC, p.current_price ASC, p.product_sk
            ) AS variant_rn
        FROM gold.mart_product_verdicts p
        JOIN ranked r ON r.matched_sk = p.product_sk
    )
    SELECT {PRODUCT_SELECT_COLS}, COUNT(*) OVER () AS search_total
    FROM deduped
    WHERE variant_rn = 1
    ORDER BY part_order, anchor_order, relevance, in_stock DESC, script_order, real_discount_pct DESC, product_sk
    LIMIT :limit
    """
    return sql, {
        **_term_parameters(query, limit),
        "normalized": query.normalized,
        "phrase": query.phrase,
        "related_model_limit": _RELATED_MODEL_LIMIT,
    }


def coverage_catalog_sql(query: CatalogQuery, limit: int, *, indexed: bool = True) -> tuple[str, dict[str, Any]] | None:
    """High-coverage fallback for 3+ token queries when 1 descriptive token misses.

    Requires ALL model-number/unit anchors to match and at least `len(terms) - 1`
    total intent tokens, strictly ranking higher coverage above partial matches.
    """
    if len(query.terms) < 3:
        return None
    document = "p.search_document" if indexed else _LEGACY_DOCUMENT
    anchor_idxs = [i for i, t in enumerate(query.terms) if t.is_anchor]
    non_anchor_idxs = [i for i, t in enumerate(query.terms) if not t.is_anchor]
    if len(non_anchor_idxs) < 2:
        return None

    min_hits = len(query.terms) - 1
    hit_sum = " + ".join(f"CASE WHEN {document} ~ :term_{i} THEN 1 ELSE 0 END" for i in range(len(query.terms)))
    required_clauses = [f"{document} ~ :term_{i}" for i in anchor_idxs]
    any_non_anchor = "(" + " OR ".join(f"{document} ~ :term_{i}" for i in non_anchor_idxs) + ")"
    required_clauses.append(any_non_anchor)
    where_sql = " AND ".join(required_clauses)
    anchor_order = _anchor_title_order_sql(query)

    params = {**_term_parameters(query, limit), "min_hits": min_hits}
    sql = f"""
    WITH scored AS (
        SELECT
            {PRODUCT_SELECT_COLS},
            {_ACCESSORY_ORDER} AS part_order,
            {anchor_order} AS anchor_order,
            ({hit_sum}) AS matched_terms,
            {_SCRIPT_ORDER} AS script_order
        FROM gold.mart_product_verdicts p
        WHERE {where_sql}
          AND ({hit_sum}) >= :min_hits
    ),
    deduped AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(parent_product_key, store_name || '::' || product_sk)
                ORDER BY part_order, matched_terms DESC, anchor_order, in_stock DESC, current_price ASC, product_sk
            ) AS variant_rn
        FROM scored
    )
    SELECT {PRODUCT_SELECT_COLS}, COUNT(*) OVER () AS search_total
    FROM deduped
    WHERE variant_rn = 1
    ORDER BY part_order, matched_terms DESC, anchor_order, in_stock DESC, script_order, real_discount_pct DESC, product_sk
    LIMIT :limit
    """
    return sql, params


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
    score_expr = " + ".join(scores)
    anchor_order = _anchor_title_order_sql(query)
    return f"""
        WITH deduped AS (
            SELECT
                {PRODUCT_SELECT_COLS},
                {_ACCESSORY_ORDER} AS part_order,
                {anchor_order} AS anchor_order,
                ({missed}) AS miss_count,
                ({score_expr}) AS fuzzy_score,
                {_SCRIPT_ORDER} AS script_order,
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(p.parent_product_key, p.store_name || '::' || p.product_sk)
                    ORDER BY {_ACCESSORY_ORDER}, {anchor_order}, ({missed}), ({score_expr}) DESC, p.in_stock DESC, p.current_price ASC, p.product_sk
                ) AS variant_rn
            FROM gold.mart_product_verdicts p
            WHERE {' AND '.join(matches)} AND ({missed}) <= 2
        )
        SELECT {PRODUCT_SELECT_COLS}, COUNT(*) OVER () AS search_total
        FROM deduped
        WHERE variant_rn = 1
        ORDER BY part_order, anchor_order, miss_count, fuzzy_score DESC,
            in_stock DESC, script_order, real_discount_pct DESC, product_sk
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
        db.rollback()
        indexed = False
        sql, params = exact_catalog_sql(query, limit, indexed=indexed)
        rows = db.execute(text(sql), params).mappings().all()

    if rows:
        return [dict(row) for row in rows], int(rows[0]["search_total"]), "text_search"

    # Multi-token coverage fallback (for 3+ term queries where 1 descriptive word is absent)
    cov = coverage_catalog_sql(query, limit, indexed=indexed)
    if cov is not None:
        cov_sql, cov_params = cov
        try:
            cov_rows = db.execute(text(cov_sql), cov_params).mappings().all()
            if cov_rows:
                return [dict(row) for row in cov_rows], int(cov_rows[0]["search_total"]), "text_search"
        except DBAPIError:
            db.rollback()

    fuzzy = fuzzy_catalog_sql(query, limit, indexed=indexed)
    if fuzzy is not None:
        sql, params = fuzzy
        try:
            rows = db.execute(text(sql), params).mappings().all()
        except DBAPIError as error:
            if _database_code(error) != "42883":
                raise
            db.rollback()
        if rows:
            return [dict(row) for row in rows], int(rows[0]["search_total"]), "fuzzy_trgm"
    return [], 0, "text_search"
