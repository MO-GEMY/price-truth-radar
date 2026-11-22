"""
Shared scraper foundation for Price Truth Radar.

Provides:
- `PoliteHttpClient`: timeouts, exponential-backoff retries, polite per-request
  rate limiting, and clean browser-like headers.
- `parse_egp_price`: resilient EGP price parser (numbers, EGP/LE/ج.م strings,
  commas, Arabic-Indic numerals).
- `RawProductSnapshot`: strict Pydantic validation matching the Neon
  `raw.raw_product_snapshots` table and `CONTRACTS.md`.
- `BaseScraper`: abstract interface for store scrapers.
- `upsert_snapshots_to_neon`: non-destructive upsert into `raw.raw_product_snapshots`.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
import psycopg2
from dotenv import load_dotenv
from psycopg2 import errors as pg_errors
from psycopg2.extras import execute_values
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
IMPERSONATED_RETRYABLE_CODES: frozenset[int] = frozenset({403, 429, 500, 502, 503, 504})

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_THROTTLE_TITLE_MARKERS: tuple[str, ...] = (
    "robot check",
    "captcha",
    "sorry! something went wrong",
    "access denied",
    "attention required",
    "just a moment",
    "service unavailable",
)


class ThrottledResponseError(RuntimeError):
    """Raised when an upstream storefront returns a throttle/challenge/empty page."""


def is_throttled_html(html: str, *, min_bytes: int = 5120) -> Optional[str]:
    """Return a reason string if `html` looks like a throttle/empty/challenge page."""
    if not html or len(html) < min_bytes:
        return f"tiny HTML body ({len(html)} bytes < {min_bytes})"
    m = _TITLE_RE.search(html[:16384])
    if m is not None:
        title_text = re.sub(r"\s+", " ", m.group(1)).strip()
        if not title_text:
            return "blank <title> tag"
        low_title = title_text.lower()
        for marker in _THROTTLE_TITLE_MARKERS:
            if marker in low_title:
                return f"bot-wall/throttle title ({title_text!r})"
    return None

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_PRICE_NUMBER_RE = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)")
_MAX_NUMERIC_12_2 = Decimal("9999999999.99")
_TWO_PLACES = Decimal("0.01")


def parse_egp_price(raw: Any) -> Optional[Decimal]:
    """Parse an EGP price from int/float/Decimal or messy formatted text.

    Returns a positive `Decimal` rounded to 2 decimal places, or `None` if the
    input cannot be parsed as a valid positive price.
    """
    if raw is None or isinstance(raw, bool):
        return None

    if isinstance(raw, (int, float, Decimal)):
        try:
            dec = Decimal(str(raw)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None
        return dec if (dec > 0 and dec <= _MAX_NUMERIC_12_2) else None

    text = str(raw).strip().translate(_ARABIC_DIGITS)
    if not text:
        return None

    match = _PRICE_NUMBER_RE.search(text)
    if not match:
        return None

    cleaned = match.group(1).replace(",", "")
    try:
        dec = Decimal(cleaned).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None

    return dec if (dec > 0 and dec <= _MAX_NUMERIC_12_2) else None


def normalize_snake_slug(raw: str, fallback: str = "other", max_len: int = 80) -> str:
    """Normalize an arbitrary category/slug label into lowercase snake_case."""
    cleaned = re.sub(r"['’]", "", raw.strip().lower())
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return (cleaned or fallback)[:max_len]


def utc_now_naive() -> datetime:
    """UTC timestamp stripped of tzinfo to match PostgreSQL `TIMESTAMP`."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


Category = Literal["electronics", "fashion", "home_appliances", "groceries"]
ScrapeMode = Literal["daily", "discover"]
ScrapeVertical = Literal["core", "groceries", "fashion"]


class RawProductSnapshot(BaseModel):
    """Strict schema matching `raw.raw_product_snapshots` and `CONTRACTS.md`."""

    store_name: str = Field(..., min_length=1, max_length=100)
    external_id: str = Field(..., min_length=1, max_length=120)
    canonical_product_key: Optional[str] = Field(default=None, max_length=160)
    category: Category
    sub_category: str = Field(..., min_length=1, max_length=80)
    brand: str = Field(..., min_length=1, max_length=100)
    product_title: str = Field(..., min_length=1)
    product_url: str = Field(..., min_length=1)
    image_url: Optional[str] = None
    attributes_json: dict[str, Any] = Field(default_factory=dict)
    current_price: Decimal = Field(..., gt=0, le=_MAX_NUMERIC_12_2)
    claimed_original_price: Optional[Decimal] = Field(default=None, gt=0, le=_MAX_NUMERIC_12_2)
    in_stock: bool
    snapshot_date: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())
    scraped_at: datetime = Field(default_factory=utc_now_naive)

    @field_validator("store_name", mode="before")
    @classmethod
    def _clean_store_name(cls, v: Any) -> str:
        return str(v or "").strip().lower()

    @field_validator("external_id", "brand", "product_title", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> str:
        return re.sub(r"\s+", " ", str(v or "").strip())

    @field_validator("sub_category", mode="before")
    @classmethod
    def _clean_sub_category(cls, v: Any) -> str:
        return normalize_snake_slug(str(v or ""), fallback="other", max_len=80)

    @field_validator("canonical_product_key", mode="before")
    @classmethod
    def _clean_canonical_key(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        return s or None

    @field_validator("product_url", mode="before")
    @classmethod
    def _validate_product_url(cls, v: Any) -> str:
        url = str(v or "").strip()
        if not re.match(r"^https?://[^\s]+$", url, re.I):
            raise ValueError(f"Invalid product_url: {url!r}")
        return url

    @field_validator("image_url", mode="before")
    @classmethod
    def _validate_image_url(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        url = str(v).strip()
        if not url:
            return None
        if not re.match(r"^https?://[^\s]+$", url, re.I):
            return None
        return url

    @field_validator("current_price", "claimed_original_price", mode="before")
    @classmethod
    def _quantize_price(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        parsed = parse_egp_price(v)
        if parsed is None:
            raise ValueError(f"Invalid EGP price: {v!r}")
        return parsed

    @model_validator(mode="after")
    def _normalize_claimed_price(self) -> "RawProductSnapshot":
        # A strikethrough original price is only meaningful if strictly higher than current_price.
        if (
            self.claimed_original_price is not None
            and self.claimed_original_price <= self.current_price
        ):
            self.claimed_original_price = None
        if self.scraped_at.tzinfo is not None:
            self.scraped_at = self.scraped_at.astimezone(timezone.utc).replace(tzinfo=None)
        return self

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict matching `raw.raw_product_snapshots` columns."""
        return {
            "store_name": self.store_name,
            "external_id": self.external_id,
            "canonical_product_key": self.canonical_product_key,
            "category": self.category,
            "sub_category": self.sub_category,
            "brand": self.brand,
            "product_title": self.product_title,
            "product_url": self.product_url,
            "image_url": self.image_url,
            "attributes_json": self.attributes_json,
            "current_price": float(self.current_price),
            "claimed_original_price": (
                float(self.claimed_original_price)
                if self.claimed_original_price is not None
                else None
            ),
            "in_stock": self.in_stock,
            "snapshot_date": self.snapshot_date.isoformat(),
            "scraped_at": self.scraped_at.isoformat() + "Z",
        }

    def to_db_tuple(self) -> tuple[Any, ...]:
        return (
            self.store_name,
            self.external_id,
            self.canonical_product_key,
            self.category,
            self.sub_category,
            self.brand,
            self.product_title,
            self.product_url,
            self.image_url,
            json.dumps(self.attributes_json, ensure_ascii=False),
            self.current_price,
            self.claimed_original_price,
            self.in_stock,
            self.snapshot_date,
            self.scraped_at,
        )


class PoliteHttpClient:
    """HTTP client with timeouts, exponential retries, and polite rate limiting."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 1.5,
        min_delay_seconds: float = 1.0,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.min_delay_seconds = max(0.0, min_delay_seconds)
        merged_headers = dict(DEFAULT_HEADERS)
        if headers:
            merged_headers.update(headers)
        self._client = httpx.Client(
            headers=merged_headers,
            follow_redirects=True,
            timeout=timeout,
        )
        self._last_request_ts: float = 0.0

    def __enter__(self) -> "PoliteHttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _wait_rate_limit(self, min_delay_override: Optional[float] = None) -> None:
        effective_delay = max(self.min_delay_seconds, min_delay_override or 0.0)
        if self._last_request_ts <= 0 or effective_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        jitter = random.uniform(0.0, 0.35)
        remaining = (effective_delay + jitter) - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get(
        self,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        min_delay_seconds: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        effective_timeout = timeout if timeout is not None else self.timeout
        for attempt in range(1, self.max_retries + 1):
            self._wait_rate_limit(min_delay_override=min_delay_seconds)
            try:
                resp = self._client.get(url, params=params, headers=headers, timeout=effective_timeout)
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    sleep_for = (
                        float(retry_after)
                        if retry_after and retry_after.isdigit()
                        else self.backoff_base**attempt
                    )
                    logger.warning(
                        "HTTP %s for %s (attempt %d/%d); retrying in %.1fs",
                        resp.status_code,
                        url,
                        attempt,
                        self.max_retries,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    sleep_for = self.backoff_base**attempt
                    logger.warning(
                        "Request error for %s (attempt %d/%d): %s; retrying in %.1fs",
                        url,
                        attempt,
                        self.max_retries,
                        exc,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                raise
            finally:
                self._last_request_ts = time.monotonic()
        assert last_exc is not None
        raise last_exc

    def post(
        self,
        url: str,
        *,
        json: Optional[Any] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        min_delay_seconds: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        effective_timeout = timeout if timeout is not None else self.timeout
        for attempt in range(1, self.max_retries + 1):
            self._wait_rate_limit(min_delay_override=min_delay_seconds)
            try:
                resp = self._client.post(
                    url,
                    json=json,
                    params=params,
                    headers=headers,
                    timeout=effective_timeout,
                )
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    sleep_for = (
                        float(retry_after)
                        if retry_after and retry_after.isdigit()
                        else self.backoff_base**attempt
                    )
                    logger.warning(
                        "HTTP %s for POST %s (attempt %d/%d); retrying in %.1fs",
                        resp.status_code,
                        url,
                        attempt,
                        self.max_retries,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    sleep_for = self.backoff_base**attempt
                    logger.warning(
                        "Request error for POST %s (attempt %d/%d): %s; retrying in %.1fs",
                        url,
                        attempt,
                        self.max_retries,
                        exc,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                raise
            finally:
                self._last_request_ts = time.monotonic()

        assert last_exc is not None
        raise last_exc


class ImpersonatedHttpClient:
    """TLS-impersonated HTTP client powered by `curl_cffi` with polite jitter & throttle detection."""

    def __init__(
        self,
        *,
        impersonate: str = "chrome",
        timeout: float = 25.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        min_delay_seconds: float = 3.0,
        jitter_range: tuple[float, float] = (0.3, 1.2),
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        from curl_cffi import requests as cffi_requests

        self.impersonate = impersonate
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.min_delay_seconds = max(0.0, min_delay_seconds)
        self.jitter_range = jitter_range
        self._default_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            self._default_headers.update(headers)
        self._session = cffi_requests.Session(impersonate=impersonate)
        self._last_request_ts: float = 0.0

    def __enter__(self) -> "ImpersonatedHttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def _wait_rate_limit(self, min_delay_override: Optional[float] = None) -> None:
        effective_delay = max(self.min_delay_seconds, min_delay_override or 0.0)
        if self._last_request_ts <= 0 or effective_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        jitter = random.uniform(self.jitter_range[0], self.jitter_range[1])
        remaining = (effective_delay + jitter) - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _compute_backoff(
        self,
        status: Optional[int],
        attempt: int,
        retry_after: Optional[str] = None,
    ) -> float:
        if retry_after:
            try:
                parsed = float(retry_after.strip())
                if parsed > 0:
                    return min(parsed, 60.0)
            except ValueError:
                pass
        if status == 429:
            schedule = (4.0, 8.0, 15.0, 25.0)
            base_delay = schedule[min(max(attempt - 1, 0), len(schedule) - 1)]
            return base_delay + random.uniform(0.3, 1.0)
        return (self.backoff_base**attempt) + random.uniform(0.5, 1.5)

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        min_delay_seconds: Optional[float] = None,
        timeout: Optional[float] = None,
        headers: Optional[dict[str, str]] = None,
        check_throttle: bool = True,
        min_html_bytes: int = 5120,
    ) -> Any:
        merged_headers = dict(self._default_headers)
        if headers:
            merged_headers.update(headers)
        effective_timeout = timeout if timeout is not None else self.timeout
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            self._wait_rate_limit(min_delay_override=min_delay_seconds)
            try:
                if method == "POST":
                    resp = self._session.post(
                        url,
                        params=params,
                        json=json,
                        data=data,
                        headers=merged_headers,
                        timeout=effective_timeout,
                        allow_redirects=True,
                    )
                else:
                    resp = self._session.get(
                        url,
                        params=params,
                        headers=merged_headers,
                        timeout=effective_timeout,
                        allow_redirects=True,
                    )
                status = int(resp.status_code)
                if status in IMPERSONATED_RETRYABLE_CODES:
                    msg = f"HTTP {status} for {method} {url}"
                    last_exc = ThrottledResponseError(msg)
                    if attempt < self.max_retries:
                        sleep_for = self._compute_backoff(
                            status, attempt, resp.headers.get("Retry-After")
                        )
                        logger.warning(
                            "%s (attempt %d/%d); backing off %.1fs",
                            msg,
                            attempt,
                            self.max_retries,
                            sleep_for,
                        )
                        time.sleep(sleep_for)
                        continue
                    raise last_exc

                if status >= 400:
                    resp.raise_for_status()

                if check_throttle:
                    reason = is_throttled_html(resp.text or "", min_bytes=min_html_bytes)
                    if reason is not None:
                        last_exc = ThrottledResponseError(f"Throttled response for {url}: {reason}")
                        if attempt < self.max_retries:
                            sleep_for = self._compute_backoff(None, attempt)
                            logger.warning(
                                "%s (attempt %d/%d); backing off %.1fs",
                                last_exc,
                                attempt,
                                self.max_retries,
                                sleep_for,
                            )
                            time.sleep(sleep_for)
                            continue
                        raise last_exc

                return resp
            except ThrottledResponseError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    sleep_for = self._compute_backoff(None, attempt)
                    logger.warning(
                        "Impersonated %s error for %s (attempt %d/%d): %s; retrying in %.1fs",
                        method,
                        url,
                        attempt,
                        self.max_retries,
                        exc,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                raise
            finally:
                self._last_request_ts = time.monotonic()

        assert last_exc is not None
        raise last_exc

    def get(
        self,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        min_delay_seconds: Optional[float] = None,
        timeout: Optional[float] = None,
        headers: Optional[dict[str, str]] = None,
        check_throttle: bool = True,
        min_html_bytes: int = 5120,
    ) -> Any:
        return self._request(
            "GET",
            url,
            params=params,
            min_delay_seconds=min_delay_seconds,
            timeout=timeout,
            headers=headers,
            check_throttle=check_throttle,
            min_html_bytes=min_html_bytes,
        )

    def post(
        self,
        url: str,
        *,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        params: Optional[dict[str, Any]] = None,
        min_delay_seconds: Optional[float] = None,
        timeout: Optional[float] = None,
        headers: Optional[dict[str, str]] = None,
        check_throttle: bool = False,
        min_html_bytes: int = 5120,
    ) -> Any:
        return self._request(
            "POST",
            url,
            params=params,
            json=json,
            data=data,
            min_delay_seconds=min_delay_seconds,
            timeout=timeout,
            headers=headers,
            check_throttle=check_throttle,
            min_html_bytes=min_html_bytes,
        )


class BaseScraper(ABC):
    """Abstract base class for all Egyptian e-commerce store scrapers."""

    store_name: str
    category: Category
    base_url: str
    default_limit: int = 300
    discover_limit: int = 0
    groceries_limit: int = 300
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds: float = 1.0
    request_timeout: Optional[float] = None

    def __init__(
        self,
        http_client: PoliteHttpClient,
        *,
        mode: ScrapeMode = "daily",
        vertical: ScrapeVertical = "core",
        tracked_external_ids: Optional[set[str]] = None,
    ) -> None:
        self.http = http_client
        self.mode: ScrapeMode = mode
        self.vertical: ScrapeVertical = vertical
        self.tracked_external_ids: set[str] = set(tracked_external_ids or ())
        self.skipped_count: int = 0
        self.pages_fetched: int = 0
        self.category_counts: dict[str, int] = {}

    def get_target_limit(
        self,
        mode: Optional[ScrapeMode] = None,
        vertical: Optional[ScrapeVertical] = None,
    ) -> int:
        """Return default product target for the requested scrape mode & vertical."""
        effective_mode = mode or self.mode
        effective_vertical = vertical or self.vertical
        if effective_vertical == "groceries":
            base_cap = self.groceries_limit
            return min(350, int(round(base_cap * 1.15))) if effective_mode == "discover" else base_cap
        if effective_mode == "discover":
            if self.discover_limit > 0:
                return self.discover_limit
            return max(self.default_limit + 100, int(round(self.default_limit * 1.75)))
        return self.default_limit

    def prioritize_tracked(
        self,
        items: list[Any],
        id_getter: Any,
    ) -> list[Any]:
        """In `daily` mode, order previously tracked items first so price histories stay continuous."""
        if self.mode != "daily" or not self.tracked_external_ids:
            return items
        tracked: list[Any] = []
        untracked: list[Any] = []
        for item in items:
            ext_id = id_getter(item)
            if ext_id and str(ext_id) in self.tracked_external_ids:
                tracked.append(item)
            else:
                untracked.append(item)
        return tracked + untracked

    def validate_record(self, payload: dict[str, Any]) -> Optional[RawProductSnapshot]:
        """Validate a scraped dict against `RawProductSnapshot`; skip bad rows safely."""
        try:
            return RawProductSnapshot.model_validate(payload)
        except Exception as exc:
            self.skipped_count += 1
            logger.warning(
                "[%s] Skipping invalid record (external_id=%r): %s",
                self.store_name,
                payload.get("external_id"),
                exc,
            )
            return None

    @abstractmethod
    def scrape(self, limit: int = 30) -> list[RawProductSnapshot]:
        """Scrape up to `limit` validated product snapshots from the store."""


DDL_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS raw.raw_product_snapshots (
    store_name              VARCHAR(100) NOT NULL,
    external_id             VARCHAR(120) NOT NULL,
    canonical_product_key   VARCHAR(160),
    category                VARCHAR(50)  NOT NULL,
    sub_category            VARCHAR(80)  NOT NULL,
    brand                   VARCHAR(100) NOT NULL,
    product_title           TEXT         NOT NULL,
    product_url             TEXT         NOT NULL,
    image_url               TEXT,
    attributes_json         JSONB        NOT NULL,
    current_price           NUMERIC(12,2) NOT NULL,
    claimed_original_price  NUMERIC(12,2),
    in_stock                BOOLEAN      NOT NULL,
    snapshot_date           DATE         NOT NULL,
    scraped_at              TIMESTAMP    NOT NULL,
    PRIMARY KEY (store_name, external_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_raw_snapshots_date
    ON raw.raw_product_snapshots (snapshot_date);
"""

UPSERT_SQL = """
INSERT INTO raw.raw_product_snapshots (
    store_name,
    external_id,
    canonical_product_key,
    category,
    sub_category,
    brand,
    product_title,
    product_url,
    image_url,
    attributes_json,
    current_price,
    claimed_original_price,
    in_stock,
    snapshot_date,
    scraped_at
) VALUES %s
ON CONFLICT (store_name, external_id, snapshot_date) DO UPDATE SET
    canonical_product_key  = EXCLUDED.canonical_product_key,
    category               = EXCLUDED.category,
    sub_category           = EXCLUDED.sub_category,
    brand                  = EXCLUDED.brand,
    product_title          = EXCLUDED.product_title,
    product_url            = EXCLUDED.product_url,
    image_url              = EXCLUDED.image_url,
    attributes_json        = EXCLUDED.attributes_json,
    current_price          = EXCLUDED.current_price,
    claimed_original_price = EXCLUDED.claimed_original_price,
    in_stock               = EXCLUDED.in_stock,
    scraped_at             = EXCLUDED.scraped_at;
"""


def upsert_snapshots_to_neon(
    snapshots: list[RawProductSnapshot],
    *,
    max_attempts: int = 5,
) -> int:
    """Non-destructively upsert scraped snapshots into `raw.raw_product_snapshots`.

    Uses deterministic conflict-key ordering, a transaction-scoped PostgreSQL
    advisory lock, and exponential-backoff retries on transient deadlock /
    serialization errors (SQLSTATE 40P01 / 40001) so parallel CI matrix jobs
    can commit safely without lock collisions.
    """
    if not snapshots:
        return 0

    db_url = os.getenv("DATABASE_URL_ADMIN")
    if not db_url:
        raise RuntimeError("DATABASE_URL_ADMIN is not set in environment / .env")

    # Sort deterministically by ON CONFLICT (store_name, external_id, snapshot_date)
    # to guarantee consistent row lock acquisition order.
    rows = sorted(
        (s.to_db_tuple() for s in snapshots),
        key=lambda r: (r[0], r[1], r[13]),
    )
    conn = psycopg2.connect(db_url)
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext('raw_product_snapshots_upsert'))"
                    )
                    cur.execute(DDL_SQL)
                    execute_values(cur, UPSERT_SQL, rows, page_size=500)
                conn.commit()
                return len(rows)
            except psycopg2.Error as exc:
                is_retryable = isinstance(
                    exc, (pg_errors.DeadlockDetected, pg_errors.SerializationFailure)
                ) or getattr(exc, "pgcode", None) in ("40P01", "40001")
                conn.rollback()
                if not is_retryable or attempt >= max_attempts:
                    raise
                sleep_for = 0.5 * (2**attempt) + random.uniform(0.1, 0.6)
                logger.warning(
                    "Transient PostgreSQL error during snapshot upsert "
                    "(%s, pgcode=%s, attempt %d/%d, rows=%d); rolled back and retrying in %.2fs.",
                    type(exc).__name__,
                    getattr(exc, "pgcode", None),
                    attempt,
                    max_attempts,
                    len(rows),
                    sleep_for,
                )
                time.sleep(sleep_for)
    finally:
        conn.close()

    return len(rows)


def fetch_latest_snapshots_from_neon(
    target_date: Optional[date] = None,
) -> tuple[Optional[date], list[RawProductSnapshot]]:
    """Load all rows from `raw.raw_product_snapshots` for `target_date` (or latest date)."""
    db_url = os.getenv("DATABASE_URL_ADMIN")
    if not db_url:
        raise RuntimeError("DATABASE_URL_ADMIN is not set in environment / .env")

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            if target_date is None:
                cur.execute("SELECT MAX(snapshot_date) FROM raw.raw_product_snapshots;")
                row = cur.fetchone()
                if not row or row[0] is None:
                    return None, []
                target_date = row[0]

            cur.execute(
                """
                SELECT
                    store_name,
                    external_id,
                    canonical_product_key,
                    category,
                    sub_category,
                    brand,
                    product_title,
                    product_url,
                    image_url,
                    attributes_json,
                    current_price,
                    claimed_original_price,
                    in_stock,
                    snapshot_date,
                    scraped_at
                FROM raw.raw_product_snapshots
                WHERE snapshot_date = %s
                ORDER BY store_name, external_id;
                """,
                (target_date,),
            )
            fetched = cur.fetchall()
    finally:
        conn.close()

    snapshots: list[RawProductSnapshot] = []
    for r in fetched:
        attrs = r[9] if isinstance(r[9], dict) else (json.loads(r[9]) if r[9] else {})
        snapshots.append(
            RawProductSnapshot.model_validate(
                {
                    "store_name": r[0],
                    "external_id": r[1],
                    "canonical_product_key": r[2],
                    "category": r[3],
                    "sub_category": r[4],
                    "brand": r[5],
                    "product_title": r[6],
                    "product_url": r[7],
                    "image_url": r[8],
                    "attributes_json": attrs,
                    "current_price": r[10],
                    "claimed_original_price": r[11],
                    "in_stock": r[12],
                    "snapshot_date": r[13],
                    "scraped_at": r[14],
                }
            )
        )
    return target_date, snapshots


def update_canonical_keys_in_neon(snapshots: list[RawProductSnapshot]) -> int:
    """Batch-update `canonical_product_key` for the given snapshots in Neon."""
    if not snapshots:
        return 0

    db_url = os.getenv("DATABASE_URL_ADMIN")
    if not db_url:
        raise RuntimeError("DATABASE_URL_ADMIN is not set in environment / .env")

    values = [
        (s.store_name, s.external_id, s.snapshot_date, s.canonical_product_key)
        for s in snapshots
    ]
    sql = """
    UPDATE raw.raw_product_snapshots AS t
    SET canonical_product_key = v.canonical_product_key
    FROM (VALUES %s) AS v(store_name, external_id, snapshot_date, canonical_product_key)
    WHERE t.store_name = v.store_name
      AND t.external_id = v.external_id
      AND t.snapshot_date = v.snapshot_date;
    """
    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, values, page_size=500)
    finally:
        conn.close()

    return len(values)


def fetch_tracked_store_ids_from_neon(
    store_name: str,
    *,
    category: Optional[str] = None,
) -> set[str]:
    """Fetch previously tracked `external_id`s for `store_name` so daily runs prioritize continuity."""
    db_url = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL_READONLY")
    if not db_url:
        return set()
    try:
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                if category:
                    cur.execute(
                        """
                        SELECT DISTINCT external_id
                        FROM raw.raw_product_snapshots
                        WHERE store_name = %s
                          AND category = %s;
                        """,
                        (store_name, category),
                    )
                else:
                    cur.execute(
                        """
                        SELECT DISTINCT external_id
                        FROM raw.raw_product_snapshots
                        WHERE store_name = %s;
                        """,
                        (store_name,),
                    )
                return {str(row[0]) for row in cur.fetchall() if row and row[0]}
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("[%s] Could not load tracked IDs from Neon (%s); continuing without watchlist.", store_name, exc)
        return set()
