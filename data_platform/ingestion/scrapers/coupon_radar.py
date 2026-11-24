"""Passive scraper promo-code radar (draft queue ONLY — NEVER auto-published).

Extracts potential Arabic/English coupon codes from scraped product descriptions,
promo badges, or tags, applies strict false-positive filtering, and appends unique
`(store_id, code)` candidates into `data/pending_coupons.json` for manual review.

Optional non-blocking Telegram alert fires on newly discovered candidates when
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (or `TELEGRAM_NOTIFY_CHAT_ID`) are set.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PENDING_PATH = _REPO_ROOT / "data" / "pending_coupons.json"

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Match Arabic & English promo-code triggers followed by a plausible promo code token.
# Intentionally case-sensitive on the code capture (or uppercased & filtered) to minimize noise.
_PROMO_CODE_RE = re.compile(
    r"(?i)(?:"
    r"استخدم\s+(?:ال)?كود(?:\s+الخصم)?|"
    r"كود\s+(?:ال)?خصم|"
    r"كوبون(?:\s+(?:ال)?خصم)?|"
    r"(?:ال)?رمز\s+(?:ال)?ترويجي|"
    r"use\s+(?:promo\s+|coupon\s+|discount\s+)?code|"
    r"enter\s+(?:promo\s+|coupon\s+|discount\s+)?code|"
    r"apply\s+(?:promo\s+|coupon\s+|discount\s+)?code|"
    r"(?:promo|coupon|discount|voucher)\s+code"
    r")\s*[:\-–—=،,\s\"'«(\[]+\s*([A-Za-z0-9][A-Za-z0-9_-]{3,19})(?=[\s\"'»)\]\.,!؟?،;:/|]|$)"
)

# Common English/store/technical words that often appear after "use code" in prose or HTML
_FALSE_POSITIVE_WORDS: frozenset[str] = frozenset(
    {
        "CODE", "CODES", "PROMO", "COUPON", "COUPONS", "DISCOUNT", "DISCOUNTS",
        "VOUCHER", "OFFER", "OFFERS", "SALE", "SALES", "DEAL", "DEALS",
        "FREE", "SHIPPING", "DELIVERY", "CHECKOUT", "CART", "ORDER", "ORDERS",
        "SHOP", "STORE", "ONLINE", "TODAY", "HERE", "BELOW", "ABOVE", "ONLY",
        "VALID", "UNTIL", "FROM", "WITH", "YOUR", "THIS", "THAT", "WHEN",
        "SAVE", "EXTRA", "MORE", "LESS", "PRICE", "PRICES", "CASH", "CARD",
        "BANK", "EGYPT", "CAIRO", "MOBILE", "PHONE", "APPLE", "IPHONE",
        "SAMSUNG", "XIAOMI", "BLACK", "WHITE", "BLUE", "GREEN", "GOLD", "SILVER",
        "SIZE", "COLOR", "COLOUR", "MODEL", "SERIES", "EDITION", "VERSION",
        "ORIGINAL", "WARRANTY", "INSTALLMENT", "PRODUCT", "BRAND", "ITEM",
        "HTML", "HTTP", "HTTPS", "JSON", "NULL", "TRUE", "FALSE", "NONE",
        "TEST", "DEMO", "DEFAULT", "TEXT", "VALUE", "NAME", "LINK", "PAGE",
        "CLICK", "COPY", "ENTER", "APPLY", "CHECK", "START", "FIRST", "NEXT",
        "BEST", "GOOD", "GREAT", "SUPER", "MEGA", "ULTRA", "PLUS", "MINI",
        "LITE", "PRO", "MAX", "NEW", "HOT", "TOP", "ALL", "ANY", "FOR",
    }
)

# Technical spec tokens / measurements / resolutions / model prefixes that are never promo codes
_SPEC_TOKEN_RE = re.compile(
    r"^(?:"
    r"\d+(?:GB|TB|MB|ML|KG|GM|MG|CM|MM|HZ|KHZ|MHZ|GHZ|MAH|RPM|BTU|FPS|MP|HP|W|V|A|L|G|K|P)|"
    r"SPF\d+|UV\d+|IP\d{2}|DDR\d|USB[C0-9]?|HDMI\d?|WIFI\d?|BT\d|5G|4G|3G|UHD|FHD|QHD|OLED|QLED|AMOLED|"
    r"[0-9A-F]{6}|[0-9A-F]{8}|"  # Hex color / hash fragments
    r"\d{4,20}"  # Pure digits (barcodes, years, phone numbers)
    r")$"
)

_WRITE_LOCK = threading.Lock()
_SEEN_SESSION: set[tuple[str, str]] = set()


def _strip_html(raw_text: str) -> str:
    if not raw_text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", raw_text)
    return _WHITESPACE_RE.sub(" ", no_tags).strip()


def is_plausible_promo_code(
    candidate: str,
    *,
    excluded_tokens: Optional[set[str]] = None,
) -> bool:
    """Strict false-positive filter for extracted promo code candidates."""
    code = (candidate or "").strip().upper()
    if len(code) < 4 or len(code) > 20:
        return False
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{3,19}", code):
        return False
    # Must contain at least one ASCII letter (blocks pure barcodes/years/prices)
    if not any("A" <= ch <= "Z" for ch in code):
        return False
    # Reject leading/trailing punctuation or repeated punctuation
    if code.endswith(("-", "_")) or "--" in code or "__" in code:
        return False
    if code in _FALSE_POSITIVE_WORDS:
        return False
    if _SPEC_TOKEN_RE.fullmatch(code):
        return False
    # Reject single repeated char ("AAAA")
    if len(set(code.replace("-", "").replace("_", ""))) < 2:
        return False
    # Reject product SKU / external_id echoes
    if excluded_tokens and code in excluded_tokens:
        return False
    return True


def extract_coupon_candidates(
    text: str,
    *,
    excluded_tokens: Optional[set[str]] = None,
) -> list[tuple[str, str]]:
    """Extract deduplicated `(code, context_snippet)` pairs from raw text or HTML."""
    clean = _strip_html(text)
    if not clean or len(clean) < 8:
        return []

    found: list[tuple[str, str]] = []
    seen_codes: set[str] = set()
    for match in _PROMO_CODE_RE.finditer(clean):
        raw_code = match.group(1).strip()
        # Extra precision guard for English prose: if code is purely lowercase letters
        # with no digits (e.g. "use code below" / "enter code checkout" / "use code automatically"),
        # reject unless it contains at least one digit or uppercase letter.
        if raw_code.isalpha() and raw_code.islower():
            continue
        code = raw_code.upper()
        if code in seen_codes:
            continue
        if not is_plausible_promo_code(code, excluded_tokens=excluded_tokens):
            continue
        seen_codes.add(code)
        start = max(0, match.start() - 30)
        end = min(len(clean), match.end() + 45)
        snippet = clean[start:end].strip()
        found.append((code, snippet))
    return found


def _notify_telegram_draft(store_id: str, code: str, snippet: str, source_url: str) -> None:
    """Optional best-effort Telegram ping for newly detected draft coupon candidates."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_NOTIFY_CHAT_ID", "")).strip()
    if not token or not chat_id:
        return
    msg = (
        f"🎟️ Coupon Radar Draft (Pending Review)\n"
        f"Store: {store_id}\n"
        f"Code: {code}\n"
        f"Snippet: {snippet[:160]}\n"
        f"URL: {source_url or '-'}\n"
        f"Saved to data/pending_coupons.json (NOT published)."
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "disable_web_page_preview": True},
            timeout=4.0,
        )
    except Exception as exc:
        logger.debug("[coupon_radar] Telegram draft alert skipped: %s", exc)


def record_pending_coupons(
    store_id: str,
    candidates: list[tuple[str, str]],
    *,
    source_url: str = "",
    pending_path: Optional[Path] = None,
    notify_telegram: bool = True,
) -> list[dict[str, Any]]:
    """Append unique `(store_id, code)` drafts to `data/pending_coupons.json`.

    Returns only the newly appended entries. Never raises to callers.
    """
    if not candidates or not store_id:
        return []

    target_path = pending_path or DEFAULT_PENDING_PATH
    store_slug = store_id.strip().lower()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    newly_added: list[dict[str, Any]] = []

    try:
        with _WRITE_LOCK:
            existing: list[dict[str, Any]] = []
            if target_path.is_file():
                try:
                    raw = json.loads(target_path.read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        existing = [item for item in raw if isinstance(item, dict)]
                except Exception as exc:
                    logger.warning("[coupon_radar] Could not parse %s (%s); starting fresh.", target_path, exc)

            known_keys: set[tuple[str, str]] = {
                (str(item.get("store_id") or "").strip().lower(), str(item.get("code") or "").strip().upper())
                for item in existing
            }

            for code, snippet in candidates:
                key = (store_slug, code)
                if key in known_keys:
                    continue
                entry = {
                    "store_id": store_slug,
                    "code": code,
                    "context_snippet": snippet[:200],
                    "source_url": source_url[:500] if source_url else "",
                    "detected_at": now_iso,
                    "status": "pending_review",
                }
                existing.append(entry)
                known_keys.add(key)
                newly_added.append(entry)

            if newly_added:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(
                    dir=str(target_path.parent),
                    prefix=".pending_coupons_",
                    suffix=".tmp",
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(existing, fh, ensure_ascii=False, indent=2)
                        fh.write("\n")
                    os.replace(tmp_name, target_path)
                except Exception:
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                    raise
    except Exception as exc:
        logger.debug("[coupon_radar] Failed persisting pending coupons: %s", exc)
        return []

    if notify_telegram:
        for entry in newly_added:
            _notify_telegram_draft(
                entry["store_id"],
                entry["code"],
                entry["context_snippet"],
                entry["source_url"],
            )
    return newly_added


def scan_and_record_coupons(
    store_id: str,
    texts: list[str],
    *,
    source_url: str = "",
    excluded_tokens: Optional[set[str]] = None,
    pending_path: Optional[Path] = None,
    notify_telegram: bool = True,
) -> list[dict[str, Any]]:
    """Non-blocking convenience hook for scrapers (fast in-process dedup + draft queue write)."""
    try:
        store_slug = (store_id or "").strip().lower()
        if not store_slug or not texts:
            return []
        combined = " | ".join(t for t in texts if t)
        if not combined:
            return []
        candidates = extract_coupon_candidates(combined, excluded_tokens=excluded_tokens)
        if not candidates:
            return []
        # Skip disk I/O for codes already seen during this process run (when using default path)
        if pending_path is None:
            fresh = [(c, s) for c, s in candidates if (store_slug, c) not in _SEEN_SESSION]
            if not fresh:
                return []
            for c, _ in fresh:
                _SEEN_SESSION.add((store_slug, c))
            candidates = fresh
        return record_pending_coupons(
            store_slug,
            candidates,
            source_url=source_url,
            pending_path=pending_path,
            notify_telegram=notify_telegram,
        )
    except Exception as exc:  # pragma: no cover - defensive non-blocking guarantee
        logger.debug("[coupon_radar] Non-blocking scan error ignored: %s", exc)
        return []
