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


class RawProductSnapshot(BaseModel):
    """Strict schema matching `raw.raw_product_snapshots` and `CONTRACTS.md`."""

    store_name: str = Field(..., min_length=1, max_length=100)
    external_id: str = Field(..., min_length=1, max_length=120)
    canonical_product_key: Optional[str] = Field(default=None, max_length=160)
    category: Literal["electronics", "fashion"]
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
        min_delay_seconds: Optional[float] = None,
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._wait_rate_limit(min_delay_override=min_delay_seconds)
            try:
                resp = self._client.get(url, params=params)
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


class BaseScraper(ABC):
    """Abstract base class for all Egyptian e-commerce store scrapers."""

    store_name: str
    category: Literal["electronics", "fashion"]
    base_url: str
    min_delay_seconds: float = 1.0

    def __init__(self, http_client: PoliteHttpClient) -> None:
        self.http = http_client
        self.skipped_count: int = 0
        self.pages_fetched: int = 0

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


def upsert_snapshots_to_neon(snapshots: list[RawProductSnapshot]) -> int:
    """Non-destructively upsert scraped snapshots into `raw.raw_product_snapshots`."""
    if not snapshots:
        return 0

    db_url = os.getenv("DATABASE_URL_ADMIN")
    if not db_url:
        raise RuntimeError("DATABASE_URL_ADMIN is not set in environment / .env")

    rows = [s.to_db_tuple() for s in snapshots]
    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, UPSERT_SQL, rows, page_size=500)
    finally:
        conn.close()

    return len(rows)
