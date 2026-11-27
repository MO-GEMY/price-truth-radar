"""Zero-Neon cached FX rate helper for Global-to-Egypt estimated pricing (`pricing_mode: fx_estimated`).

Supports USD, AED, SAR, EUR, and GBP -> EGP conversion with:
  1. In-memory process cache + 12-hour local disk cache (`data/.fx_rates_cache.json`).
  2. Public ExchangeRate-API (`https://open.er-api.com/v6/latest/USD`) when online.
  3. Safe conservative fallback rates if offline or API is unreachable.
  4. ZERO Neon database connections (0 CU during scraping).
"""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
FX_CACHE_FILE = REPO_ROOT / "data" / ".fx_rates_cache.json"
FX_CACHE_TTL_SECONDS = 12 * 3600  # 12 hours
FX_API_URL = "https://open.er-api.com/v6/latest/USD"

# Safe fallback rates (1 unit of currency -> EGP) when network is unavailable
FALLBACK_TO_EGP: dict[str, float] = {
    "EGP": 1.0,
    "USD": 49.50,
    "EUR": 53.50,
    "AED": 13.48,
    "SAR": 13.20,
    "GBP": 62.50,
}

_MEM_RATES: Optional[dict[str, float]] = None
_MEM_LOADED_AT: float = 0.0
_TWO_PLACES = Decimal("0.01")


def _load_disk_cache() -> Optional[dict[str, float]]:
    if not FX_CACHE_FILE.is_file():
        return None
    try:
        doc = json.loads(FX_CACHE_FILE.read_text(encoding="utf-8"))
        ts = float(doc.get("fetched_at") or 0)
        rates = doc.get("to_egp")
        if (time.time() - ts) < FX_CACHE_TTL_SECONDS and isinstance(rates, dict) and rates.get("USD"):
            return {str(k).upper(): float(v) for k, v in rates.items() if float(v) > 0}
    except Exception:
        return None
    return None


def _save_disk_cache(to_egp: dict[str, float]) -> None:
    try:
        FX_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FX_CACHE_FILE.write_text(
            json.dumps({"fetched_at": time.time(), "to_egp": to_egp}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Could not write FX disk cache: %s", exc)


def get_fx_rates_to_egp(*, force_refresh: bool = False) -> dict[str, float]:
    """Return `{currency_code: egp_per_unit}` mapping for USD/EUR/AED/SAR/GBP/EGP."""
    global _MEM_RATES, _MEM_LOADED_AT

    if not force_refresh and _MEM_RATES is not None and (time.monotonic() - _MEM_LOADED_AT) < FX_CACHE_TTL_SECONDS:
        return dict(_MEM_RATES)

    if not force_refresh:
        disk = _load_disk_cache()
        if disk is not None:
            _MEM_RATES = disk
            _MEM_LOADED_AT = time.monotonic()
            return dict(disk)

    try:
        resp = httpx.get(FX_API_URL, timeout=6.0)
        if resp.status_code == 200:
            payload = resp.json()
            usd_rates = payload.get("rates") if isinstance(payload, dict) else None
            if isinstance(usd_rates, dict) and usd_rates.get("EGP"):
                egp_per_usd = float(usd_rates["EGP"])
                if 20.0 <= egp_per_usd <= 150.0:
                    computed: dict[str, float] = {"EGP": 1.0, "USD": round(egp_per_usd, 4)}
                    for code in ("EUR", "AED", "SAR", "GBP"):
                        per_usd = float(usd_rates.get(code) or 0)
                        if per_usd > 0:
                            computed[code] = round(egp_per_usd / per_usd, 4)
                    for k, v in FALLBACK_TO_EGP.items():
                        computed.setdefault(k, v)
                    _save_disk_cache(computed)
                    _MEM_RATES = computed
                    _MEM_LOADED_AT = time.monotonic()
                    return dict(computed)
    except Exception as exc:
        logger.warning("[fx_rates] Live FX fetch failed (%s); using safe fallback rates.", exc)

    _MEM_RATES = dict(FALLBACK_TO_EGP)
    _MEM_LOADED_AT = time.monotonic()
    return dict(FALLBACK_TO_EGP)


def convert_to_egp(amount: float | Decimal, source_currency: str) -> tuple[Decimal, float]:
    """Convert `amount` in `source_currency` (USD/AED/SAR/EUR/GBP) to raw FX EGP `(egp_decimal, rate)`."""
    code = str(source_currency or "USD").strip().upper()
    rates = get_fx_rates_to_egp()
    rate = rates.get(code) or FALLBACK_TO_EGP.get(code)
    if rate is None:
        raise ValueError(f"Unsupported FX source currency: {source_currency!r}")
    converted = (Decimal(str(amount)) * Decimal(str(rate))).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return converted, float(rate)
