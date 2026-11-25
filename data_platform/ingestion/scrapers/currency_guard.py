"""Strict EGP currency enforcement, Shopify Egypt localization, and ingestion flip circuit breaker.

Protects `asarak.com` against Geo-IP / Shopify Markets multi-currency pollution
(e.g., US GitHub Actions runners receiving USD prices or inflated US-market prices
instead of real Egyptian EGP prices):

1. Storefront Guards:
   - `enforce_shopify_egypt_context`: forces Egypt country/currency cookies
     (`localization=EG`, `cart_currency=EGP`), posts `country_code=EG` to
     `/localization`, verifies `/cart.js?currency=EGP&country=EG` reports `EGP`,
     and rejects cross-host Geo-IP redirects (e.g. `eg.okhtein.com` -> `okhtein.com`).
   - `is_valid_egp_currency`: strict EGP validator used by Shopify, WooCommerce
     (`currency_code`), and Magento GraphQL (`final_price.currency`) adapters.
   - `is_same_store_host`: rejects cross-subdomain / cross-domain geo-redirects.

2. Ingestion Currency-Flip Circuit Breaker:
   - `detect_store_currency_flips` & `filter_currency_flip_batches`:
     compares each store's incoming batch against recent EGP prices in
     `gold.mart_product_verdicts` before committing to Neon. Quarantines an
     entire store batch with `CURRENCY_MISMATCH_SUSPECTED` if:
       a) >= 50% of >= 5 overlapping SKUs shift by >= 3.5x or <= 0.30x
          (classic USD <-> EGP flip like `shopzhivago`), OR
       b) A split-storefront geo-redirect produces 0 overlapping IDs across
          >= 20 incoming & >= 20 stored SKUs with a >= 4.0x or <= 0.25x
          catalog-median jump (like `okhtein` / `azza_fahmy`).
"""

from __future__ import annotations

import inspect
import logging
import statistics
from dataclasses import dataclass
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_CURRENCY = "EGP"
ALLOWED_COUNTRY = "EG"

FLIP_HIGH_RATIO = 3.5
FLIP_LOW_RATIO = 0.30
FLIP_MIN_OVERLAP = 5
FLIP_MAJORITY_FRACTION = 0.50

ZERO_OVERLAP_MIN_PRODUCTS = 20
ZERO_OVERLAP_HIGH_RATIO = 4.0
ZERO_OVERLAP_LOW_RATIO = 0.25

_CURRENCY_ALIASES: dict[str, str] = {
    "EGP": "EGP",
    "LE": "EGP",
    "L.E": "EGP",
    "L.E.": "EGP",
    "ج.م": "EGP",
    "ج.م.": "EGP",
    "جنيه": "EGP",
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "AED": "AED",
    "SAR": "SAR",
    "KWD": "KWD",
    "QAR": "QAR",
    "BHD": "BHD",
    "OMR": "OMR",
    "JOD": "JOD",
    "CAD": "CAD",
    "AUD": "AUD",
}


@dataclass(frozen=True)
class ShopifyLocalizationResult:
    """Outcome of enforcing and verifying Egypt (EG / EGP) context on a Shopify storefront."""

    ok: bool
    currency: Optional[str]
    country: Optional[str]
    redirected_host: Optional[str]
    reason: str


@dataclass(frozen=True)
class CurrencyFlipAlert:
    """Structured alert emitted when the ingestion circuit breaker quarantines a store batch."""

    store_name: str
    reason: str
    batch_count: int
    overlap_count: int
    median_ratio: float
    shifted_fraction: float
    ref_median_price: float
    batch_median_price: float


def normalize_currency_code(raw: Any) -> Optional[str]:
    """Normalize a raw currency token (e.g. 'egp', 'L.E.', 'USD', '$') to ISO code."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    upper = text.upper()
    if upper in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[upper]
    if text in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[text]
    return upper


def is_valid_egp_currency(raw: Any, *, allow_missing: bool = False) -> bool:
    """Return True strictly when `raw` normalizes to `EGP` (or is absent when `allow_missing=True`)."""
    norm = normalize_currency_code(raw)
    if norm is None:
        return allow_missing
    return norm == ALLOWED_CURRENCY


def normalize_host(url: str) -> str:
    """Extract lowercase hostname stripping only a leading `www.` (preserving regional subdomains)."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_same_store_host(actual_url: Optional[str], expected_base_url: str) -> bool:
    """Return False if a storefront redirected to a different host/subdomain (e.g. eg.okhtein.com -> okhtein.com)."""
    if not actual_url:
        return True
    expected = normalize_host(expected_base_url)
    actual = normalize_host(str(actual_url))
    if not expected or not actual:
        return True
    return actual == expected


def _apply_cookies_to_fetcher(fetcher: Any, cookies: dict[str, str], host: str) -> None:
    """Set cookies on `PoliteHttpClient`, `ImpersonatedHttpClient`, or compatible test doubles."""
    set_cookies_fn = getattr(fetcher, "set_cookies", None)
    if callable(set_cookies_fn):
        try:
            set_cookies_fn(cookies, domain=host or None)
        except TypeError:
            set_cookies_fn(cookies)
        return

    session = getattr(fetcher, "_session", None)
    if session is not None and getattr(session, "cookies", None) is not None:
        for k, v in cookies.items():
            try:
                if host:
                    session.cookies.set(k, v, domain=host)
                else:
                    session.cookies.set(k, v)
            except Exception:
                pass
        return

    client = getattr(fetcher, "_client", None)
    if client is not None and getattr(client, "cookies", None) is not None:
        for k, v in cookies.items():
            try:
                if host:
                    client.cookies.set(k, v, domain=host)
                else:
                    client.cookies.set(k, v)
            except Exception:
                pass


def _supports_kwarg(fn: Any, kwarg: str) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return kwarg in sig.parameters


def enforce_shopify_egypt_context(
    fetcher: Any,
    base_url: str,
    store_name: str,
    *,
    timeout: float = 15.0,
) -> ShopifyLocalizationResult:
    """Force Egypt (EG / EGP) Shopify Markets localization and verify active currency via `/cart.js`.

    Hard rules:
    - If `/localization` or `/cart.js` redirects to another host/subdomain (Geo-IP storefront
      redirect such as `eg.okhtein.com` -> `okhtein.com`), returns `ok=False`.
    - If `/cart.js` returns a currency other than `EGP` (e.g. `USD`, `EUR`, `AED`),
      returns `ok=False`.
    - Minimal test doubles exposing only `.get()` (without `.post()`, `.set_cookies()`, or
      `supports_currency_probe=True`) pass through without making extra network calls.
    """
    base = base_url.rstrip("/")
    expected_host = normalize_host(base)
    eg_cookies = {"localization": ALLOWED_COUNTRY, "cart_currency": ALLOWED_CURRENCY}

    has_post = callable(getattr(fetcher, "post", None))
    has_set_cookies = callable(getattr(fetcher, "set_cookies", None))
    has_cookie_jar = (
        getattr(fetcher, "_session", None) is not None
        or getattr(fetcher, "_client", None) is not None
    )
    wants_probe = (
        has_post
        or has_set_cookies
        or has_cookie_jar
        or bool(getattr(fetcher, "supports_currency_probe", False))
    )
    if not wants_probe:
        return ShopifyLocalizationResult(
            ok=True,
            currency=ALLOWED_CURRENCY,
            country=ALLOWED_COUNTRY,
            redirected_host=None,
            reason="skipped_minimal_mock_fetcher",
        )

    _apply_cookies_to_fetcher(fetcher, eg_cookies, expected_host)

    # Step 1: POST /localization to force Shopify Markets country_code=EG on server session.
    if has_post:
        post_fn = fetcher.post
        post_kwargs: dict[str, Any] = {
            "data": {"_method": "put", "country_code": ALLOWED_COUNTRY, "return_to": "/"},
        }
        if _supports_kwarg(post_fn, "min_delay_seconds"):
            post_kwargs["min_delay_seconds"] = 0.0
        if _supports_kwarg(post_fn, "timeout"):
            post_kwargs["timeout"] = min(timeout, 12.0)
        if _supports_kwarg(post_fn, "check_throttle"):
            post_kwargs["check_throttle"] = False
        try:
            loc_resp = post_fn(f"{base}/localization", **post_kwargs)
            loc_url = str(getattr(loc_resp, "url", "") or "")
            if loc_url and not is_same_store_host(loc_url, base):
                act_host = normalize_host(loc_url)
                return ShopifyLocalizationResult(
                    ok=False,
                    currency=None,
                    country=None,
                    redirected_host=act_host,
                    reason=f"GEO_REDIRECT_HOST_MISMATCH on /localization: expected {expected_host}, got {act_host}",
                )
        except Exception as exc:
            # Many single-market Shopify stores do not enable /localization (404/405/422).
            resp_obj = getattr(exc, "response", None)
            resp_url = str(getattr(resp_obj, "url", "") or "")
            if resp_url and not is_same_store_host(resp_url, base):
                act_host = normalize_host(resp_url)
                return ShopifyLocalizationResult(
                    ok=False,
                    currency=None,
                    country=None,
                    redirected_host=act_host,
                    reason=f"GEO_REDIRECT_HOST_MISMATCH on /localization: expected {expected_host}, got {act_host}",
                )
            logger.debug("[%s] /localization POST ignored (%s); continuing to /cart.js verification.", store_name, exc)

        # Re-assert EG/EGP cookies in case /localization was unavailable or reset them.
        _apply_cookies_to_fetcher(fetcher, eg_cookies, expected_host)

    # Step 2: Verify active storefront currency via /cart.js?currency=EGP&country=EG.
    get_fn = fetcher.get
    get_kwargs: dict[str, Any] = {
        "params": {"currency": ALLOWED_CURRENCY, "country": ALLOWED_COUNTRY},
    }
    if _supports_kwarg(get_fn, "min_delay_seconds"):
        get_kwargs["min_delay_seconds"] = 0.0
    if _supports_kwarg(get_fn, "timeout"):
        get_kwargs["timeout"] = min(timeout, 12.0)
    if _supports_kwarg(get_fn, "check_throttle"):
        get_kwargs["check_throttle"] = False

    try:
        cart_resp = get_fn(f"{base}/cart.js", **get_kwargs)
    except Exception as exc:
        resp_obj = getattr(exc, "response", None)
        resp_url = str(getattr(resp_obj, "url", "") or "")
        if resp_url and not is_same_store_host(resp_url, base):
            act_host = normalize_host(resp_url)
            return ShopifyLocalizationResult(
                ok=False,
                currency=None,
                country=None,
                redirected_host=act_host,
                reason=f"GEO_REDIRECT_HOST_MISMATCH on /cart.js: expected {expected_host}, got {act_host}",
            )
        logger.warning(
            "[%s] Could not verify /cart.js currency (%s); proceeding with EG localization cookies + params.",
            store_name,
            exc,
        )
        return ShopifyLocalizationResult(
            ok=True,
            currency=None,
            country=ALLOWED_COUNTRY,
            redirected_host=None,
            reason=f"cart_js_unavailable:{type(exc).__name__}",
        )

    cart_url = str(getattr(cart_resp, "url", "") or "")
    if cart_url and not is_same_store_host(cart_url, base):
        act_host = normalize_host(cart_url)
        return ShopifyLocalizationResult(
            ok=False,
            currency=None,
            country=None,
            redirected_host=act_host,
            reason=f"GEO_REDIRECT_HOST_MISMATCH on /cart.js: expected {expected_host}, got {act_host}",
        )

    try:
        payload = cart_resp.json()
    except Exception as exc:
        logger.warning("[%s] Non-JSON /cart.js response (%s); proceeding with EG params.", store_name, exc)
        return ShopifyLocalizationResult(
            ok=True,
            currency=None,
            country=ALLOWED_COUNTRY,
            redirected_host=None,
            reason="cart_js_non_json",
        )

    if not isinstance(payload, dict):
        return ShopifyLocalizationResult(
            ok=True,
            currency=None,
            country=ALLOWED_COUNTRY,
            redirected_host=None,
            reason="cart_js_non_dict",
        )

    raw_currency = payload.get("currency")
    norm_currency = normalize_currency_code(raw_currency)
    raw_country = str(payload.get("country") or "").strip().upper() or None

    if norm_currency is not None and norm_currency != ALLOWED_CURRENCY:
        return ShopifyLocalizationResult(
            ok=False,
            currency=norm_currency,
            country=raw_country,
            redirected_host=None,
            reason=f"NON_EGP_CURRENCY: /cart.js returned currency={norm_currency!r} (expected 'EGP')",
        )

    return ShopifyLocalizationResult(
        ok=True,
        currency=norm_currency or ALLOWED_CURRENCY,
        country=raw_country or ALLOWED_COUNTRY,
        redirected_host=None,
        reason="verified_egp_cart_js" if norm_currency == ALLOWED_CURRENCY else "cart_js_missing_currency",
    )


def fetch_store_reference_prices(
    conn: Any,
    store_names: Sequence[str],
) -> dict[str, dict[str, float]]:
    """Fetch latest EGP prices per `(store_name, product_sk)` from `gold.mart_product_verdicts`."""
    clean_stores = sorted({str(s).strip().lower() for s in store_names if str(s).strip()})
    if not clean_stores:
        return {}

    refs: dict[str, dict[str, float]] = {}
    in_tx = bool(getattr(conn, "status", 0) == 2)  # psycopg2.extensions.STATUS_IN_TRANSACTION == 2

    with conn.cursor() as cur:
        try:
            if in_tx:
                cur.execute("SAVEPOINT sp_currency_ref_prices;")
            cur.execute(
                """
                SELECT store_name, product_sk, current_price
                FROM gold.mart_product_verdicts
                WHERE store_name = ANY(%s)
                  AND current_price IS NOT NULL
                  AND current_price > 0;
                """,
                (clean_stores,),
            )
            for store_name, product_sk, current_price in cur.fetchall():
                if not store_name or not product_sk or current_price is None:
                    continue
                price_f = float(current_price)
                if price_f > 0:
                    refs.setdefault(str(store_name).lower(), {})[str(product_sk)] = price_f
            if in_tx:
                cur.execute("RELEASE SAVEPOINT sp_currency_ref_prices;")
        except Exception as exc:
            if in_tx:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_currency_ref_prices;")
                    cur.execute("RELEASE SAVEPOINT sp_currency_ref_prices;")
                except Exception:
                    pass
            else:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.debug("Could not load reference prices for currency circuit breaker (%s).", exc)
            return {}

    return refs


def detect_store_currency_flips(
    snapshots: Sequence[Any],
    reference_prices_by_store: dict[str, dict[str, float]],
    *,
    high_ratio: float = FLIP_HIGH_RATIO,
    low_ratio: float = FLIP_LOW_RATIO,
    min_overlap: int = FLIP_MIN_OVERLAP,
    majority_fraction: float = FLIP_MAJORITY_FRACTION,
    zero_overlap_min_products: int = ZERO_OVERLAP_MIN_PRODUCTS,
    zero_overlap_high_ratio: float = ZERO_OVERLAP_HIGH_RATIO,
    zero_overlap_low_ratio: float = ZERO_OVERLAP_LOW_RATIO,
) -> tuple[list[Any], list[CurrencyFlipAlert]]:
    """Quarantine any store batch showing a store-wide currency-scale price jump or drop.

    Pure function (zero DB I/O) so it can be unit-tested exhaustively and reused
    across both `bulk_copy_snapshots_to_neon` and `upsert_snapshots_to_neon`.
    """
    from .base import compute_product_sk

    by_store: dict[str, list[Any]] = {}
    for snap in snapshots:
        by_store.setdefault(str(snap.store_name).strip().lower(), []).append(snap)

    kept: list[Any] = []
    alerts: list[CurrencyFlipAlert] = []

    for store_name, store_snaps in by_store.items():
        ref_map = reference_prices_by_store.get(store_name) or {}
        if not ref_map:
            kept.extend(store_snaps)
            continue

        ratios: list[float] = []
        ref_overlap_prices: list[float] = []
        batch_overlap_prices: list[float] = []

        for snap in store_snaps:
            sk = compute_product_sk(store_name, snap.external_id)
            ref_p = ref_map.get(sk)
            cur_p = float(snap.current_price)
            if ref_p is not None and ref_p > 0 and cur_p > 0:
                ratios.append(cur_p / ref_p)
                ref_overlap_prices.append(ref_p)
                batch_overlap_prices.append(cur_p)

        if len(ratios) >= min_overlap:
            med_ratio = statistics.median(ratios)
            high_frac = sum(1 for r in ratios if r >= high_ratio) / len(ratios)
            low_frac = sum(1 for r in ratios if r <= low_ratio) / len(ratios)

            is_high_flip = med_ratio >= high_ratio and high_frac >= majority_fraction
            is_low_flip = med_ratio <= low_ratio and low_frac >= majority_fraction

            if is_high_flip or is_low_flip:
                alerts.append(
                    CurrencyFlipAlert(
                        store_name=store_name,
                        reason="overlap_price_shift",
                        batch_count=len(store_snaps),
                        overlap_count=len(ratios),
                        median_ratio=round(med_ratio, 4),
                        shifted_fraction=round(high_frac if is_high_flip else low_frac, 4),
                        ref_median_price=round(statistics.median(ref_overlap_prices), 2),
                        batch_median_price=round(statistics.median(batch_overlap_prices), 2),
                    )
                )
                continue

        elif (
            len(ratios) == 0
            and len(ref_map) >= zero_overlap_min_products
            and len(store_snaps) >= zero_overlap_min_products
        ):
            ref_med = statistics.median(ref_map.values())
            batch_prices = [float(s.current_price) for s in store_snaps if float(s.current_price) > 0]
            if ref_med > 0 and batch_prices:
                batch_med = statistics.median(batch_prices)
                cat_ratio = batch_med / ref_med
                if cat_ratio >= zero_overlap_high_ratio or cat_ratio <= zero_overlap_low_ratio:
                    alerts.append(
                        CurrencyFlipAlert(
                            store_name=store_name,
                            reason="catalog_median_shift_zero_overlap",
                            batch_count=len(store_snaps),
                            overlap_count=0,
                            median_ratio=round(cat_ratio, 4),
                            shifted_fraction=1.0,
                            ref_median_price=round(ref_med, 2),
                            batch_median_price=round(batch_med, 2),
                        )
                    )
                    continue

        kept.extend(store_snaps)

    return kept, alerts


def filter_currency_flip_batches(
    snapshots: Sequence[Any],
    conn: Any,
    *,
    high_ratio: float = FLIP_HIGH_RATIO,
    low_ratio: float = FLIP_LOW_RATIO,
    min_overlap: int = FLIP_MIN_OVERLAP,
    majority_fraction: float = FLIP_MAJORITY_FRACTION,
) -> tuple[list[Any], list[CurrencyFlipAlert]]:
    """Run the Neon-backed ingestion currency-flip circuit breaker and log quarantined stores."""
    if not snapshots:
        return [], []

    stores = sorted({str(s.store_name).strip().lower() for s in snapshots})
    refs = fetch_store_reference_prices(conn, stores)
    if not refs:
        return list(snapshots), []

    kept, alerts = detect_store_currency_flips(
        snapshots,
        refs,
        high_ratio=high_ratio,
        low_ratio=low_ratio,
        min_overlap=min_overlap,
        majority_fraction=majority_fraction,
    )

    for alert in alerts:
        msg = (
            f"CURRENCY_MISMATCH_SUSPECTED | store={alert.store_name} | reason={alert.reason} "
            f"| quarantined_rows={alert.batch_count} | overlap={alert.overlap_count} "
            f"| median_ratio={alert.median_ratio:.3f}x | shifted={alert.shifted_fraction * 100:.1f}% "
            f"| ref_median={alert.ref_median_price:.2f} | batch_median={alert.batch_median_price:.2f}"
        )
        logger.warning(msg)
        print(msg, flush=True)

    return kept, alerts
