"""Zero-Neon in-memory coupon & promo code service for Asarak (أسعارك).

Loads curated Egyptian store promo codes from:
  1. `COUPONS_SHEET_CSV_URL` (published Google Sheet CSV, refreshed every 30 min, 5s timeout)
  2. Local fallback `data/coupons.json` shipped in the repository

Guarantees:
  - ZERO Neon DB reads or writes.
  - On fetch/parse errors, retains the last known good in-memory snapshot (or local
    `data/coupons.json`) and logs a warning without ever failing API requests.
  - Strictly filters out inactive (`active != TRUE`) and expired coupons evaluated
    in `Africa/Cairo` timezone.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CouponDiscountType = Literal["percent", "fixed"]
CouponScope = Literal["general", "bank", "first_order", "seasonal"]

VALID_DISCOUNT_TYPES: frozenset[str] = frozenset({"percent", "fixed"})
VALID_SCOPES: frozenset[str] = frozenset({"general", "bank", "first_order", "seasonal"})
REFRESH_INTERVAL_SECONDS: float = 1800.0  # 30 minutes
FETCH_TIMEOUT_SECONDS: float = 5.0

try:
    CAIRO_TZ = ZoneInfo("Africa/Cairo")
except Exception:  # pragma: no cover - Windows without tzdata package
    CAIRO_TZ = timezone(timedelta(hours=2))


def cairo_now() -> datetime:
    """Return current timezone-aware datetime in Africa/Cairo."""
    return datetime.now(CAIRO_TZ)


def _resolve_repo_root() -> Path:
    env_root = os.getenv("REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    parents = Path(__file__).resolve().parents
    return parents[min(3, len(parents) - 1)] if parents else Path(".")


def _candidate_local_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.getenv("COUPONS_LOCAL_FILE", "").strip()
    if override:
        paths.append(Path(override))
    paths.append(_resolve_repo_root() / "data" / "coupons.json")
    paths.append(Path(__file__).resolve().parents[1] / "data" / "coupons.json")
    return paths


class CouponRecord(BaseModel):
    store_id: str
    store_name_ar: str
    code: str
    title_ar: str
    discount_type: CouponDiscountType
    value: float = Field(..., gt=0)
    max_discount: Optional[float] = None
    min_order: Optional[float] = None
    scope: CouponScope = "general"
    category: str = "all"
    affiliate_url: Optional[str] = None
    expires_at: Optional[str] = None
    active: bool = True
    notes_ar: str = ""


class ApplicableCoupon(BaseModel):
    code: str
    title_ar: str
    discount_type: CouponDiscountType
    value: float
    max_discount: Optional[float] = None
    min_order: Optional[float] = None
    scope: CouponScope
    estimated_price: float
    estimated_savings: float
    affiliate_url: Optional[str] = None
    notes_ar: str = ""


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in {"true", "1", "yes", "y", "on"}


def _parse_optional_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        val = float(raw)
        return val if val > 0 else None
    text = str(raw).strip().replace(",", "")
    if not text or text.lower() in {"none", "null", "n/a", "-"}:
        return None
    try:
        val = float(text)
        return val if val > 0 else None
    except ValueError:
        return None


def _parse_expiry_cairo(raw: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date (`YYYY-MM-DD`) or ISO datetime into an Africa/Cairo deadline."""
    if not raw:
        return None
    cleaned = str(raw).strip()
    if not cleaned or cleaned.lower() in {"none", "null", "n/a", "-"}:
        return None
    # Date-only: valid through end of day (23:59:59) Africa/Cairo time
    if len(cleaned) == 10 and cleaned[4] == "-" and cleaned[7] == "-":
        try:
            d = date.fromisoformat(cleaned)
            return datetime.combine(d, dt_time(23, 59, 59), tzinfo=CAIRO_TZ)
        except ValueError:
            return None
    try:
        iso = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=CAIRO_TZ)
        return dt.astimezone(CAIRO_TZ)
    except ValueError:
        return None


def is_coupon_expired(expires_at: Optional[str], now: Optional[datetime] = None) -> bool:
    """Return True if `expires_at` is a valid timestamp strictly in the past (Africa/Cairo)."""
    if not expires_at or not str(expires_at).strip():
        return False
    deadline = _parse_expiry_cairo(expires_at)
    if deadline is None:
        # Unparseable non-empty expiry string: fail closed so stale/corrupt rows are not published
        return True
    ref_now = now.astimezone(CAIRO_TZ) if (now and now.tzinfo) else (now.replace(tzinfo=CAIRO_TZ) if now else cairo_now())
    return ref_now > deadline


def _normalize_row(raw: dict[str, Any], *, now: Optional[datetime] = None) -> Optional[CouponRecord]:
    if not isinstance(raw, dict):
        return None
    cleaned = {str(k).strip().lower(): v for k, v in raw.items() if k is not None}

    if not _parse_bool(cleaned.get("active")):
        return None

    store_id = str(cleaned.get("store_id") or "").strip().lower()
    code = str(cleaned.get("code") or "").strip().upper()
    store_name_ar = str(cleaned.get("store_name_ar") or "").strip()
    title_ar = str(cleaned.get("title_ar") or "").strip()
    discount_type = str(cleaned.get("discount_type") or "").strip().lower()
    scope = str(cleaned.get("scope") or "general").strip().lower()
    category = str(cleaned.get("category") or "all").strip().lower() or "all"
    value = _parse_optional_float(cleaned.get("value"))

    if not store_id or not code or value is None:
        return None
    if discount_type not in VALID_DISCOUNT_TYPES:
        return None
    if discount_type == "percent" and value > 100.0:
        return None
    if scope not in VALID_SCOPES:
        return None

    expires_raw = cleaned.get("expires_at")
    expires_at = str(expires_raw).strip() if expires_raw is not None and str(expires_raw).strip() else None
    if is_coupon_expired(expires_at, now=now):
        return None

    affiliate_raw = cleaned.get("affiliate_url")
    affiliate_url: Optional[str] = None
    if affiliate_raw is not None:
        cand = str(affiliate_raw).strip()
        if cand.startswith(("https://", "http://")):
            affiliate_url = cand

    return CouponRecord(
        store_id=store_id,
        store_name_ar=store_name_ar or store_id,
        code=code,
        title_ar=title_ar or f"كود خصم {code}",
        discount_type=discount_type,  # type: ignore[arg-type]
        value=round(value, 2),
        max_discount=_parse_optional_float(cleaned.get("max_discount")),
        min_order=_parse_optional_float(cleaned.get("min_order")),
        scope=scope,  # type: ignore[arg-type]
        category=category,
        affiliate_url=affiliate_url,
        expires_at=expires_at,
        active=True,
        notes_ar=str(cleaned.get("notes_ar") or "").strip(),
    )


def parse_coupons_csv(csv_text: str, *, now: Optional[datetime] = None) -> list[CouponRecord]:
    """Parse a Google Sheet CSV export into validated, active, non-expired coupons."""
    cleaned_text = csv_text.lstrip("\ufeff")
    if not cleaned_text.strip():
        raise ValueError("Coupons CSV payload is empty")
    reader = csv.DictReader(io.StringIO(cleaned_text))
    if not reader.fieldnames:
        raise ValueError("Coupons CSV missing header row")
    headers = {str(h).strip().lower() for h in reader.fieldnames if h}
    required = {"store_id", "code", "discount_type", "value", "active"}
    if not required.issubset(headers):
        missing = sorted(required - headers)
        raise ValueError(f"Coupons CSV missing required columns: {', '.join(missing)}")

    coupons: list[CouponRecord] = []
    seen: set[tuple[str, str]] = set()
    for row in reader:
        rec = _normalize_row(row, now=now)
        if rec is None:
            continue
        key = (rec.store_id, rec.code)
        if key in seen:
            continue
        seen.add(key)
        coupons.append(rec)
    return coupons


def load_local_coupons(*, now: Optional[datetime] = None) -> list[CouponRecord]:
    """Load fallback coupons from `data/coupons.json`."""
    for path in _candidate_local_paths():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[coupons] Failed reading fallback file %s: %s", path, exc)
            continue
        if not isinstance(payload, list):
            logger.warning("[coupons] Expected JSON list in %s", path)
            continue
        coupons: list[CouponRecord] = []
        seen: set[tuple[str, str]] = set()
        for row in payload:
            rec = _normalize_row(row, now=now)
            if rec is None:
                continue
            key = (rec.store_id, rec.code)
            if key in seen:
                continue
            seen.add(key)
            coupons.append(rec)
        return coupons
    return []


def compute_coupon_price(price: float, coupon: CouponRecord) -> Optional[float]:
    """Compute final EGP price after applying `coupon`, respecting `min_order` & `max_discount`.

    Returns `None` when the coupon is not applicable (e.g., `price <= 0`, `price < min_order`,
    or yields zero discount).
    """
    if price <= 0:
        return None
    if coupon.min_order is not None and price < coupon.min_order:
        return None

    if coupon.discount_type == "percent":
        discount = price * (coupon.value / 100.0)
        if coupon.max_discount is not None and coupon.max_discount > 0:
            discount = min(discount, coupon.max_discount)
    else:
        discount = coupon.value
        if coupon.max_discount is not None and coupon.max_discount > 0:
            discount = min(discount, coupon.max_discount)

    if discount <= 0:
        return None
    final_price = max(0.0, round(price - discount, 2))
    if final_price >= price:
        return None
    return final_price


class CouponStore:
    """Thread-safe 30-minute in-memory coupon registry with resilient fallback."""

    def __init__(self, refresh_interval_seconds: float = REFRESH_INTERVAL_SECONDS) -> None:
        self._refresh_interval = refresh_interval_seconds
        self._lock = threading.RLock()
        self._coupons: list[CouponRecord] = []
        self._loaded_at: float = 0.0
        self._has_loaded: bool = False
        self._source: str = "uninitialized"
        self._last_refreshed_utc: Optional[str] = None

    def reset(self) -> None:
        with self._lock:
            self._coupons = []
            self._loaded_at = 0.0
            self._has_loaded = False
            self._source = "uninitialized"
            self._last_refreshed_utc = None

    def _fetch_remote_csv(self, url: str) -> list[CouponRecord]:
        resp = httpx.get(url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        resp.raise_for_status()
        return parse_coupons_csv(resp.text)

    def refresh(self, *, force: bool = True) -> dict[str, Any]:
        """Attempt reload from `COUPONS_SHEET_CSV_URL` (or local fallback).

        Never raises: on network or parse error, keeps the previous good snapshot
        (or falls back to `data/coupons.json` on cold start) and logs a warning.
        """
        sheet_url = os.getenv("COUPONS_SHEET_CSV_URL", "").strip()
        now_mono = time.monotonic()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._lock:
            if not force and self._has_loaded and (now_mono - self._loaded_at) < self._refresh_interval:
                return {
                    "ok": True,
                    "source": self._source,
                    "count": len(self._coupons),
                    "refreshed_at": self._last_refreshed_utc,
                }

        if sheet_url:
            try:
                loaded = self._fetch_remote_csv(sheet_url)
                with self._lock:
                    self._coupons = loaded
                    self._loaded_at = time.monotonic()
                    self._has_loaded = True
                    self._source = "sheet_csv"
                    self._last_refreshed_utc = now_iso
                return {
                    "ok": True,
                    "source": "sheet_csv",
                    "count": len(loaded),
                    "refreshed_at": now_iso,
                }
            except Exception as exc:
                logger.warning(
                    "[coupons] Failed to refresh from COUPONS_SHEET_CSV_URL (%s); keeping last good snapshot.",
                    exc,
                )
                with self._lock:
                    if self._has_loaded:
                        # Back off for 30 minutes before hammering a failing upstream again
                        self._loaded_at = time.monotonic()
                        return {
                            "ok": False,
                            "source": self._source,
                            "count": len(self._coupons),
                            "refreshed_at": self._last_refreshed_utc,
                            "error": str(exc)[:200],
                        }
                    # Cold start failure -> fall back to bundled data/coupons.json
                    fallback = load_local_coupons()
                    self._coupons = fallback
                    self._loaded_at = time.monotonic()
                    self._has_loaded = True
                    self._source = "local_fallback"
                    self._last_refreshed_utc = now_iso
                    return {
                        "ok": False,
                        "source": "local_fallback",
                        "count": len(fallback),
                        "refreshed_at": now_iso,
                        "error": str(exc)[:200],
                    }

        fallback = load_local_coupons()
        with self._lock:
            self._coupons = fallback
            self._loaded_at = time.monotonic()
            self._has_loaded = True
            self._source = "local_fallback"
            self._last_refreshed_utc = now_iso
        return {
            "ok": True,
            "source": "local_fallback",
            "count": len(fallback),
            "refreshed_at": now_iso,
        }

    def _ensure_loaded(self) -> None:
        now_mono = time.monotonic()
        with self._lock:
            fresh = self._has_loaded and (now_mono - self._loaded_at) < self._refresh_interval
        if not fresh:
            self.refresh(force=False)

    def get_coupons(
        self,
        *,
        store_id: Optional[str] = None,
        scope: Optional[str] = None,
        category: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> tuple[list[CouponRecord], str, Optional[str]]:
        self._ensure_loaded()
        ref_now = now or cairo_now()
        target_store = store_id.strip().lower() if store_id else None
        target_scope = scope.strip().lower() if scope else None
        target_cat = category.strip().lower() if category else None

        with self._lock:
            snapshot = list(self._coupons)
            source = self._source
            refreshed_at = self._last_refreshed_utc

        filtered: list[CouponRecord] = []
        for c in snapshot:
            if not c.active or is_coupon_expired(c.expires_at, now=ref_now):
                continue
            if target_store and c.store_id != target_store:
                continue
            if target_scope and c.scope != target_scope:
                continue
            if target_cat and target_cat != "all" and c.category not in ("all", target_cat):
                continue
            filtered.append(c)

        return filtered, source, refreshed_at

    def match_for_offer(
        self,
        *,
        store_id: str,
        price: float,
        category: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> tuple[list[ApplicableCoupon], Optional[float]]:
        """Match active coupons for a single store offer and return sorted savings."""
        if not store_id or price <= 0:
            return [], None

        coupons, _, _ = self.get_coupons(store_id=store_id, category=category, now=now)
        applicable: list[ApplicableCoupon] = []
        for coupon in coupons:
            est = compute_coupon_price(price, coupon)
            if est is None or est >= price:
                continue
            applicable.append(
                ApplicableCoupon(
                    code=coupon.code,
                    title_ar=coupon.title_ar,
                    discount_type=coupon.discount_type,
                    value=coupon.value,
                    max_discount=coupon.max_discount,
                    min_order=coupon.min_order,
                    scope=coupon.scope,
                    estimated_price=est,
                    estimated_savings=round(price - est, 2),
                    affiliate_url=coupon.affiliate_url,
                    notes_ar=coupon.notes_ar,
                )
            )

        if not applicable:
            return [], None

        # Prefer general/seasonal broad coupons when savings tie, and highest savings first
        scope_rank = {"general": 0, "seasonal": 1, "first_order": 2, "bank": 3}
        applicable.sort(key=lambda c: (c.estimated_price, scope_rank.get(c.scope, 9), c.code))
        return applicable, applicable[0].estimated_price


coupon_store = CouponStore()
