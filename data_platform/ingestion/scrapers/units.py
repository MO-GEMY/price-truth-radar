"""Shared bilingual (AR/EN) weight, volume, count, and pack-size parser.

Used across both Phase A (price/unit integrity audits & grocery normalization)
and Phase B (cross-store matching unit/quantity conflict blocking across
groceries, health, beauty, pet_care, and household items).

Key invariants:
- Converts all weights to canonical grams (`weight_g`):
    1kg / 1 كيلو / 1 كجم = 1000g
    نص كيلو / نصف كيلو = 500g
    ربع كيلو = 250g
    ثمن كيلو / تمن كيلو = 125g
    1 lb / 1 باوند = 454g (exact rounded integer: 2 lb = 907g, 5 lb = 2268g)
- Converts all volumes to canonical milliliters (`volume_ml`):
    1L / 1 لتر = 1000ml
    نص لتر / نصف لتر = 500ml
    ربع لتر = 250ml
- Never confuses potency/dosage (`mg`, `mcg`, `iu`, `مجم`) with package weight (`g`).
- Decodes URL-encoded Arabic variant labels (e.g. `100%d9%85%d9%84` -> `100مل`).
- Detects multi-size ambiguous titles (e.g. `100 مل / 250 مل`) when no single-size
  `variant_label` disambiguates the SKU.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import unquote

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")


def normalize_unit_text(text: str) -> str:
    """Decode percent-encoding, normalize Arabic digits/diacritics, lowercase."""
    if not text:
        return ""
    s = text
    if "%" in s:
        try:
            s = unquote(s)
        except Exception:
            pass
    s = s.translate(_ARABIC_DIGITS)
    s = _DIACRITICS_RE.sub("", s)
    # Normalize alef & teh marbuta variants for reliable Arabic unit matching
    s = (
        s.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ة", "ه")
        .replace("ى", "ي")
    )
    return s.lower()


# ---------------------------------------------------------------------------
# Weight patterns -> canonical grams
# ---------------------------------------------------------------------------
_AR_FRAC_WEIGHT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:كيلو\s*و\s*نصف|كيلو\s*و\s*نص)(?:$|[\s\-–—,/|)])"), 1500),
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:نصف\s*كيلو|نص\s*كيلو)(?:$|[\s\-–—,/|)])"), 500),
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:ربع\s*كيلو)(?:$|[\s\-–—,/|)])"), 250),
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:ثمن\s*كيلو|تمن\s*كيلو)(?:$|[\s\-–—,/|)])"), 125),
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:2\s*كيلو|اتنين\s*كيلو|اثنين\s*كيلو)(?:$|[\s\-–—,/|)])"), 2000),
)

_WEIGHT_KG_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:kgs?|kilos?|kilograms?|كيلوجرام|كيلو\s*جرام|كيلو|كجم)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)
_WEIGHT_G_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:grams?|gms?|gm|g|جرام|غرام|جم)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)
_WEIGHT_LB_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?|باوند|رطل)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)
_WEIGHT_OZ_RE = re.compile(
    r"(?<!fl\s)(?<!fl.\s)(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:oz|ounces?|اونصه)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)

# ---------------------------------------------------------------------------
# Volume patterns -> canonical milliliters
# ---------------------------------------------------------------------------
_AR_FRAC_VOL_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:لتر\s*و\s*نصف|لتر\s*و\s*نص)(?:$|[\s\-–—,/|)])"), 1500),
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:نصف\s*لتر|نص\s*لتر)(?:$|[\s\-–—,/|)])"), 500),
    (re.compile(r"(?:^|[\s\-–—,/|(])(?:ربع\s*لتر)(?:$|[\s\-–—,/|)])"), 250),
)

_VOL_L_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:liters?|litres?|ltrs?|ltr|l|لتر|ليتر)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)
_VOL_ML_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:milliliters?|millilitres?|mls?|ml|ملليلتر|مللي|ملل|مل)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)
_VOL_FLOZ_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:fl\.?\s*oz)(?=$|[^a-z])",
    re.I,
)

# ---------------------------------------------------------------------------
# Count / dosage-unit patterns (tablets, capsules, sachets, servings, pcs)
# ---------------------------------------------------------------------------
_COUNT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "caps",
        re.compile(
            r"(?:^|[^0-9a-z.])(\d{1,4})\s*(?:vegcaps?|veg\s*caps?|softgels?|gelcaps?|capsules?|caps?|كبسولات|كبسوله)(?=$|[^a-z\u0621-\u064a])",
            re.I,
        ),
    ),
    (
        "tabs",
        re.compile(
            r"(?:^|[^0-9a-z.])(\d{1,4})\s*(?:tablets?|tabs?|caplets?|lozenges?|chewables?|gummies?|اقراص|قرص)(?=$|[^a-z\u0621-\u064a])",
            re.I,
        ),
    ),
    (
        "sachets",
        re.compile(
            r"(?:^|[^0-9a-z.])(\d{1,3})\s*(?:sachets?|tea\s*bags?|teabags?|bags?|envelopes?|sticks?|اكياس|كيس|فتله|باكيت)(?=$|[^a-z\u0621-\u064a])",
            re.I,
        ),
    ),
    (
        "servings",
        re.compile(
            r"(?:^|[^0-9a-z.])(\d{1,3})\s*(?:servings?|serv\.?|scoops?|حصص|حصه|سكوب)(?=$|[^a-z\u0621-\u064a])",
            re.I,
        ),
    ),
    (
        "pcs",
        re.compile(
            r"(?:^|[^0-9a-z.])(\d{1,3})\s*(?:pieces?|pcs?|sheets?|wipes?|pads?|patches?|strips?|ampoules?|vials?|قطع|قطعه|امبول|منديل|شريط)(?=$|[^a-z\u0621-\u064a])",
            re.I,
        ),
    ),
)

# ---------------------------------------------------------------------------
# Pack multiplier patterns (e.g. `6 x 1.5L`, `x6`, `pack of 12`, `دستة`)
# ---------------------------------------------------------------------------
_PACK_MULTI_RE = re.compile(
    r"(?:(?:pack\s+of|set\s+of|box\s+of|bundle\s+of|عبوه|علبه|كرتونه|عرض)\s*(\d{1,2})\b"
    r"|\b(\d{1,2})\s*(?:pack|packs|pk|عبوات|علب)\b"
    r"|\b[x×]\s*(\d{1,2})\b"
    r"|\b(\d{1,2})\s*[x×]\s*(?=\d{2,}))",
    re.I,
)
_DOZEN_RE = re.compile(r"(?:^|[\s\-–—,/|(])(?:دسته|dozen)(?:$|[\s\-–—,/|)])", re.I)
_IN_ONE_RE = re.compile(r"\b[2345]\s*[x×]\s*1\b", re.I)

# Potency/dosage (mg / mcg / iu) — used for health supplements so 500mg != 1000mg
_DOSAGE_MG_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:mg|مجم|ملجم|مللي\s*جرام)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)
_DOSAGE_MCG_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d+(?:\.\d+)?)\s*(?:mcg|ug|ميكروجرام)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)
_DOSAGE_IU_RE = re.compile(
    r"(?:^|[^0-9a-z.])(\d{3,6})\s*(?:iu|وحده\s*دوليه)(?=$|[^a-z\u0621-\u064a])",
    re.I,
)


@dataclass(frozen=True)
class UnitSpec:
    weight_g: Optional[int] = None
    volume_ml: Optional[int] = None
    unit_count: Optional[int] = None
    unit_kind: Optional[str] = None
    pack_count: int = 1
    dosage_tag: Optional[str] = None
    has_ambiguous_multi_size: bool = False

    def has_package_size(self) -> bool:
        return (
            self.weight_g is not None
            or self.volume_ml is not None
            or self.unit_count is not None
        )

    def canonical_size_token(self) -> Optional[str]:
        """Return deterministic canonical size token for matching keys."""
        parts: list[str] = []
        if self.weight_g is not None and self.weight_g > 0:
            parts.append(f"w{self.weight_g}g")
        elif self.volume_ml is not None and self.volume_ml > 0:
            parts.append(f"v{self.volume_ml}ml")
        elif self.unit_count is not None and self.unit_count > 0:
            kind = self.unit_kind or "cnt"
            parts.append(f"c{self.unit_count}{kind}")
        else:
            return None
        if self.pack_count > 1:
            parts.append(f"x{self.pack_count}")
        return "_".join(parts)


def _extract_all_weights(norm: str) -> list[int]:
    found: list[int] = []
    for pat, grams in _AR_FRAC_WEIGHT_PATTERNS:
        if pat.search(norm):
            found.append(grams)
    for m in _WEIGHT_KG_RE.finditer(norm):
        val = float(m.group(1))
        if 0.05 <= val <= 100.0:
            g = int(round(val * 1000))
            if g not in found:
                found.append(g)
    for m in _WEIGHT_LB_RE.finditer(norm):
        val = float(m.group(1))
        if 0.25 <= val <= 50.0:
            g = int(round(val * 453.592))
            if g not in found:
                found.append(g)
    for m in _WEIGHT_G_RE.finditer(norm):
        # Guard against matching `mg` (already excluded by lookbehind, double-check)
        start = m.start(1)
        if start > 0 and norm[start - 1].isalpha():
            continue
        val = float(m.group(1))
        if 5.0 <= val <= 50000.0:
            g = int(round(val))
            if g not in found:
                found.append(g)
    for m in _WEIGHT_OZ_RE.finditer(norm):
        val = float(m.group(1))
        if 0.5 <= val <= 200.0:
            g = int(round(val * 28.3495))
            if g not in found:
                found.append(g)
    return found


def _extract_all_volumes(norm: str) -> list[int]:
    found: list[int] = []
    for pat, ml in _AR_FRAC_VOL_PATTERNS:
        if pat.search(norm):
            found.append(ml)
    for m in _VOL_L_RE.finditer(norm):
        val = float(m.group(1))
        if 0.1 <= val <= 50.0:
            ml = int(round(val * 1000))
            if ml not in found:
                found.append(ml)
    for m in _VOL_ML_RE.finditer(norm):
        val = float(m.group(1))
        if 2.0 <= val <= 25000.0:
            ml = int(round(val))
            if ml not in found:
                found.append(ml)
    for m in _VOL_FLOZ_RE.finditer(norm):
        val = float(m.group(1))
        if 0.2 <= val <= 128.0:
            ml = int(round(val * 29.5735))
            if ml not in found:
                found.append(ml)
    return found


def _extract_count(norm: str) -> tuple[Optional[int], Optional[str]]:
    for kind, pat in _COUNT_PATTERNS:
        m = pat.search(norm)
        if m:
            cnt = int(m.group(1))
            if 2 <= cnt <= 2000:
                return cnt, kind
    return None, None


def _extract_pack_count(norm: str) -> int:
    if _DOZEN_RE.search(norm):
        return 12
    # Ignore "3x1" / "2x1" (3-in-1 / 2-in-1 coffee or shampoo)
    cleaned = _IN_ONE_RE.sub(" ", norm)
    m = _PACK_MULTI_RE.search(cleaned)
    if m:
        for grp in m.groups():
            if grp:
                n = int(grp)
                if 2 <= n <= 48:
                    return n
    return 1


def _extract_dosage_tag(norm: str) -> Optional[str]:
    if m := _DOSAGE_IU_RE.search(norm):
        return f"{int(m.group(1))}iu"
    if m := _DOSAGE_MCG_RE.search(norm):
        return f"{m.group(1).rstrip('0').rstrip('.')}mcg"
    if m := _DOSAGE_MG_RE.search(norm):
        val = float(m.group(1))
        if 0.5 <= val <= 10000:
            num = str(int(val)) if val.is_integer() else f"{val:g}"
            return f"{num}mg"
    return None


def parse_unit_spec(
    title: str,
    variant_label: Optional[str] = None,
    attributes: Optional[Mapping[str, Any]] = None,
) -> UnitSpec:
    """Extract normalized weight, volume, count, pack, and dosage specs.

    Priority:
    1. Explicit `variant_label` size wins over multi-size title ranges (e.g.
       title `"Lotion 100 ml / 250 ml"` + variant_label `"100%d9%85%d9%84"` -> `100ml`).
    2. Title parsed with Arabic+English regexes.
    3. Fallback to structured `attributes_json` (`net_weight_g`, `net_volume_ml`, `pack_count`).
    """
    attrs = attributes or {}
    vlabel = variant_label or (str(attrs.get("variant_label")) if attrs.get("variant_label") else None)

    norm_var = normalize_unit_text(vlabel) if vlabel else ""
    norm_title = normalize_unit_text(title or "")

    var_weights = _extract_all_weights(norm_var) if norm_var else []
    var_vols = _extract_all_volumes(norm_var) if norm_var else []
    title_weights = _extract_all_weights(norm_title)
    title_vols = _extract_all_volumes(norm_title)

    ambiguous = False
    weight_g: Optional[int] = None
    volume_ml: Optional[int] = None

    if var_weights:
        weight_g = var_weights[0]
    elif len(title_weights) == 1:
        weight_g = title_weights[0]
    elif len(title_weights) > 1:
        # Check if dual-unit same measurement (e.g. "2 lbs / 907g" or "5lb 2.27kg")
        w_min, w_max = min(title_weights), max(title_weights)
        if w_min > 0 and (w_max / w_min) <= 1.12:
            weight_g = w_max
        else:
            ambiguous = True

    if var_vols:
        volume_ml = var_vols[0]
    elif len(title_vols) == 1:
        volume_ml = title_vols[0]
    elif len(title_vols) > 1:
        v_min, v_max = min(title_vols), max(title_vols)
        if v_min > 0 and (v_max / v_min) <= 1.12:
            volume_ml = v_max
        else:
            ambiguous = True

    # Fallback to attributes_json if still missing and not ambiguous
    if weight_g is None and not ambiguous:
        raw_wg = attrs.get("net_weight_g")
        if raw_wg is not None and str(raw_wg).isdigit() and int(raw_wg) > 0:
            weight_g = int(raw_wg)
    if volume_ml is None and not ambiguous:
        raw_vl = attrs.get("net_volume_ml")
        if raw_vl is not None and str(raw_vl).isdigit() and int(raw_vl) > 0:
            volume_ml = int(raw_vl)

    # Count (prefer variant_label, then title)
    unit_count, unit_kind = _extract_count(norm_var) if norm_var else (None, None)
    if unit_count is None:
        unit_count, unit_kind = _extract_count(norm_title)

    # Pack count
    pack_count = _extract_pack_count(norm_var) if norm_var else 1
    if pack_count == 1:
        pack_count = _extract_pack_count(norm_title)
    if pack_count == 1:
        raw_pk = attrs.get("pack_count")
        if raw_pk is not None and str(raw_pk).isdigit() and 2 <= int(raw_pk) <= 48:
            pack_count = int(raw_pk)

    dosage_tag = _extract_dosage_tag(norm_var) if norm_var else None
    if dosage_tag is None:
        dosage_tag = _extract_dosage_tag(norm_title)

    return UnitSpec(
        weight_g=weight_g,
        volume_ml=volume_ml,
        unit_count=unit_count,
        unit_kind=unit_kind,
        pack_count=pack_count,
        dosage_tag=dosage_tag,
        has_ambiguous_multi_size=ambiguous,
    )


def units_conflict(a: UnitSpec, b: UnitSpec, *, tolerance: float = 0.06) -> bool:
    """Return True if two UnitSpecs have incompatible weight, volume, count, pack, or dosage.

    Used as a mandatory hard blocker across all matcher tiers so:
    - 250g vs 1000g NEVER match
    - 50ml vs 100ml NEVER match
    - 60 caps vs 120 caps NEVER match
    - 500g powder vs 500ml liquid NEVER match
    - Pack of 1 vs Pack of 6 NEVER match
    - 500mg vs 1000mg NEVER match
    """
    if a.has_ambiguous_multi_size or b.has_ambiguous_multi_size:
        return True

    # Pack count mismatch (e.g. single vs 6-pack)
    if a.pack_count != b.pack_count:
        return True

    # Weight vs Volume cross-type conflict (e.g. 500g powder vs 500ml gel)
    if (a.weight_g and not a.volume_ml) and (b.volume_ml and not b.weight_g):
        return True
    if (a.volume_ml and not a.weight_g) and (b.weight_g and not b.volume_ml):
        return True

    # Weight mismatch beyond small rounding tolerance (e.g. 2lb=907g vs 900g is ok; 250g vs 500g blocked)
    if a.weight_g and b.weight_g:
        lo, hi = min(a.weight_g, b.weight_g), max(a.weight_g, b.weight_g)
        if lo > 0 and (hi - lo) / lo > tolerance:
            return True

    # Volume mismatch
    if a.volume_ml and b.volume_ml:
        lo, hi = min(a.volume_ml, b.volume_ml), max(a.volume_ml, b.volume_ml)
        if lo > 0 and (hi - lo) / lo > tolerance:
            return True

    # Unit count mismatch (tablets / capsules / sachets / servings / pcs)
    if a.unit_count and b.unit_count:
        if a.unit_kind == b.unit_kind or not a.unit_kind or not b.unit_kind:
            if a.unit_count != b.unit_count:
                return True

    # Dosage / potency mismatch (e.g. Vitamin D3 1000IU vs 5000IU, Magnesium 250mg vs 500mg)
    if a.dosage_tag and b.dosage_tag and a.dosage_tag != b.dosage_tag:
        return True

    return False
