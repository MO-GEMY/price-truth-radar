"""Reusable read-only live probe for staged stores in `stores_registry.yaml`.

Concurrently probes `enabled: false` stores (polite concurrency, 15s timeout,
`limit=5`, ZERO Neon writes), auto-detecting Shopify (`/products.json`),
WooCommerce (`/wp-json/wc/store/v1/products`), and Magento 2 GraphQL (`/graphql`),
verifying EGP currency and `validate_price_floor()` / `RawProductSnapshot`
validity, and classifying every store into:

  - READY_CLOUD   : >= 3 valid EGP products returned cleanly via plain HTTP
  - BLOCKED_OR_CF : 403 / 429 / Cloudflare / WAF challenge
  - FAILED        : dead domain, no public store API, empty catalog, or non-EGP currency

Usage:
    python data_platform/ingestion/scrapers/verify_registry.py
    python data_platform/ingestion/scrapers/verify_registry.py --workers 8 --json-out probe.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlparse

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_platform.ingestion.scrapers.base import (  # noqa: E402
    DEFAULT_HEADERS,
    PoliteHttpClient,
    is_throttled_html,
)
from data_platform.ingestion.scrapers.registry_loader import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    StoreRegistryEntry,
    build_platform_scraper_class,
    load_stores_registry,
)

logger = logging.getLogger("verify_registry")

ProbeStatus = Literal["READY_CLOUD", "BLOCKED_OR_CF", "FAILED"]

_SHOPIFY_CURRENCY_RE = re.compile(
    r'"active"\s*:\s*"([A-Z]{3})"|Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Z]{3})"|'
    r'<meta[^>]+property=["\'](?:og|product):price:currency["\'][^>]+content=["\']([A-Z]{3})["\']|'
    r'<meta[^>]+content=["\']([A-Z]{3})["\'][^>]+property=["\'](?:og|product):price:currency["\']|'
    r'"currency"\s*:\s*"([A-Z]{3})"',
    re.I,
)

_CF_CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
    "cf-browser-verification",
    "challenge-platform",
    "datadome",
    "incapsula",
    "access denied",
)

_PARKED_DOMAIN_HOSTS = (
    "hugedomains.com",
    "sedoparking.com",
    "dan.com",
    "afternic.com",
    "bodis.com",
)

_MAGENTO_PROBE_QUERY = """
query ProbeProducts($search: String!, $pageSize: Int!) {
  products(search: $search, pageSize: $pageSize, currentPage: 1) {
    total_count
    items {
      name
      sku
      url_key
      stock_status
      small_image { url }
      thumbnail { url }
      price_range {
        minimum_price {
          final_price { value currency }
          regular_price { value }
        }
      }
    }
  }
}
""".strip()


@dataclass
class StoreProbeResult:
    store_key: str
    display_name: str
    category: str
    vertical: str
    configured_platform: str
    detected_platform: Optional[str]
    base_url: str
    final_base_url: str
    status: ProbeStatus
    valid_count: int
    currency: Optional[str]
    reason: str
    sample_title: Optional[str] = None
    sample_price: Optional[float] = None
    suggested_config: Optional[dict[str, Any]] = None


def _is_cf_or_waf_response(resp: httpx.Response) -> Optional[str]:
    status = resp.status_code
    hdrs = {k.lower(): v.lower() for k, v in resp.headers.items()}
    server = hdrs.get("server", "")
    cf_mitigated = hdrs.get("cf-mitigated", "")
    body_head = (resp.text or "")[:6000].lower()

    if cf_mitigated == "challenge":
        return f"{status} Cloudflare challenge"
    if status == 429:
        return "429 rate-limited"
    if status in (403, 503):
        if "cloudflare" in server or "cf-ray" in hdrs or "just a moment" in body_head or "cloudflare" in body_head:
            return f"{status} Cloudflare"
        if any(m in body_head for m in _CF_CHALLENGE_MARKERS):
            return f"{status} WAF/anti-bot"
        if status == 403:
            return "403 Forbidden/WAF"
    if status == 200 and "text/html" in hdrs.get("content-type", ""):
        reason = is_throttled_html(resp.text or "", min_bytes=0)
        if reason is not None and any(m in body_head for m in _CF_CHALLENGE_MARKERS):
            return f"200 WAF challenge ({reason})"
    return None


def _filter_clean_records(records: list[Any]) -> list[Any]:
    """Keep only records with clean price, title, product_url, and image_url."""
    clean: list[Any] = []
    for r in records:
        try:
            price = float(r.current_price)
        except Exception:
            continue
        title = str(getattr(r, "product_title", "") or "").strip()
        purl = str(getattr(r, "product_url", "") or "").strip()
        img = str(getattr(r, "image_url", "") or "").strip()
        if (
            price >= 1.0
            and len(title) >= 3
            and purl.startswith(("http://", "https://"))
            and img.startswith(("http://", "https://"))
        ):
            clean.append(r)
    return clean


def _detect_shopify_currency(client: httpx.Client, base_url: str) -> Optional[str]:
    """Inspect Shopify storefront HTML or cart.js to confirm active currency (EGP vs USD/SAR/etc)."""
    for path in ("/cart.js", "/"):
        try:
            r = client.get(f"{base_url}{path}")
            if r.status_code != 200:
                continue
            if path == "/cart.js":
                try:
                    data = r.json()
                    cur = str(data.get("currency") or "").strip().upper()
                    if len(cur) == 3 and cur.isalpha():
                        return cur
                except Exception:
                    pass
            else:
                m = _SHOPIFY_CURRENCY_RE.search(r.text[:150000])
                if m:
                    for grp in m.groups():
                        if grp:
                            return grp.upper()
                if "ج.م" in r.text[:80000] or "EGP" in r.text[:80000] or "LE " in r.text[:80000]:
                    return "EGP"
        except Exception:
            continue
    return None


def _probe_shopify(
    client: httpx.Client,
    entry: StoreRegistryEntry,
    base_url: str,
    limit: int,
) -> tuple[Optional[StoreProbeResult], Optional[str]]:
    url = f"{base_url}/products.json"
    try:
        resp = client.get(url, params={"limit": 15, "page": 1})
    except Exception as exc:
        return None, f"shopify error: {type(exc).__name__}"

    blocked = _is_cf_or_waf_response(resp)
    if blocked:
        return None, f"BLOCKED:{blocked}"
    if resp.status_code != 200:
        return None, f"shopify HTTP {resp.status_code}"

    try:
        payload = resp.json()
    except Exception:
        return None, "shopify non-JSON"

    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list) or not products:
        return None, "shopify empty products"

    final_origin = f"{resp.url.scheme}://{resp.url.host}"
    currency = _detect_shopify_currency(client, final_origin)
    if currency and currency != "EGP":
        return (
            StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform="shopify",
                base_url=entry.base_url,
                final_base_url=final_origin,
                status="FAILED",
                valid_count=0,
                currency=currency,
                reason=f"non-EGP currency ({currency})",
            ),
            None,
        )

    probe_entry = StoreRegistryEntry(
        store_key=entry.store_key,
        display_name=entry.display_name,
        platform="shopify",
        base_url=final_origin,
        category=entry.category,
        vertical=entry.vertical,
        enabled=True,
        config=entry.config,
    )
    scraper_cls = build_platform_scraper_class(probe_entry)
    assert scraper_cls is not None
    with PoliteHttpClient(timeout=15.0, max_retries=1, min_delay_seconds=0.1) as hc:
        scraper = scraper_cls(hc, mode="daily", vertical=entry.vertical)
        records = scraper.scrape(limit=limit)

    # Require clean EGP price, title, product_url, and image_url
    records = _filter_clean_records(records)

    if len(records) >= 3:
        r0 = records[0]
        return (
            StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform="shopify",
                base_url=entry.base_url,
                final_base_url=final_origin,
                status="READY_CLOUD",
                valid_count=len(records),
                currency=currency or "EGP",
                reason="OK (Shopify /products.json)",
                sample_title=r0.product_title[:70],
                sample_price=float(r0.current_price),
            ),
            None,
        )
    return None, f"shopify only {len(records)} valid products"


def _probe_woocommerce(
    client: httpx.Client,
    entry: StoreRegistryEntry,
    base_url: str,
    limit: int,
) -> tuple[Optional[StoreProbeResult], Optional[str]]:
    url = f"{base_url}/wp-json/wc/store/v1/products"
    try:
        resp = client.get(url, params={"per_page": 15, "page": 1})
    except Exception as exc:
        return None, f"woo error: {type(exc).__name__}"

    blocked = _is_cf_or_waf_response(resp)
    if blocked:
        return None, f"BLOCKED:{blocked}"
    if resp.status_code != 200:
        return None, f"woo HTTP {resp.status_code}"

    try:
        payload = resp.json()
    except Exception:
        return None, "woo non-JSON"

    if not isinstance(payload, list) or not payload:
        return None, "woo empty products"

    final_origin = f"{resp.url.scheme}://{resp.url.host}"
    currencies = {
        str((item.get("prices") or {}).get("currency_code") or "").strip().upper()
        for item in payload
        if isinstance(item, dict)
    }
    currencies.discard("")
    currency = next(iter(currencies), None)
    if currency and currency != "EGP":
        return (
            StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform="woocommerce",
                base_url=entry.base_url,
                final_base_url=final_origin,
                status="FAILED",
                valid_count=0,
                currency=currency,
                reason=f"non-EGP currency ({currency})",
            ),
            None,
        )

    probe_entry = StoreRegistryEntry(
        store_key=entry.store_key,
        display_name=entry.display_name,
        platform="woocommerce",
        base_url=final_origin,
        category=entry.category,
        vertical=entry.vertical,
        enabled=True,
        config=entry.config,
    )
    scraper_cls = build_platform_scraper_class(probe_entry)
    assert scraper_cls is not None
    with PoliteHttpClient(timeout=15.0, max_retries=1, min_delay_seconds=0.1) as hc:
        scraper = scraper_cls(hc, mode="daily", vertical=entry.vertical)
        records = scraper.scrape(limit=limit)

    # Require clean EGP price, title, product_url, and image_url
    records = _filter_clean_records(records)

    if len(records) >= 3:
        r0 = records[0]
        return (
            StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform="woocommerce",
                base_url=entry.base_url,
                final_base_url=final_origin,
                status="READY_CLOUD",
                valid_count=len(records),
                currency=currency or "EGP",
                reason="OK (WooCommerce Store API)",
                sample_title=r0.product_title[:70],
                sample_price=float(r0.current_price),
            ),
            None,
        )
    return None, f"woo only {len(records)} valid products"


def _probe_magento_graphql(
    client: httpx.Client,
    entry: StoreRegistryEntry,
    base_url: str,
    limit: int,
) -> tuple[Optional[StoreProbeResult], Optional[str]]:
    gql_url = str((entry.config or {}).get("graphql_url") or f"{base_url}/graphql")
    use_post = True
    payload: Optional[dict[str, Any]] = None
    last_reason = "magento_graphql unavailable"
    final_origin = base_url

    for method in ("POST", "GET"):
        try:
            if method == "POST":
                resp = client.post(
                    gql_url,
                    json={"query": _MAGENTO_PROBE_QUERY, "variables": {"search": "a", "pageSize": 15}},
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
            else:
                resp = client.get(
                    gql_url,
                    params={
                        "query": _MAGENTO_PROBE_QUERY,
                        "variables": json.dumps({"search": "a", "pageSize": 15}),
                    },
                    headers={"Accept": "application/json"},
                )
        except Exception as exc:
            last_reason = f"magento error: {type(exc).__name__}"
            continue

        blocked = _is_cf_or_waf_response(resp)
        if blocked:
            return None, f"BLOCKED:{blocked}"
        if resp.status_code != 200:
            last_reason = f"magento HTTP {resp.status_code}"
            continue

        try:
            data = resp.json()
        except Exception:
            last_reason = "magento non-JSON"
            continue

        items = (((data or {}).get("data") or {}).get("products") or {}).get("items")
        if isinstance(items, list) and items:
            payload = data
            use_post = method == "POST"
            final_origin = f"{resp.url.scheme}://{resp.url.host}"
            break
        last_reason = "magento empty items"

    if not payload:
        return None, last_reason

    raw_items = (((payload.get("data") or {}).get("products") or {}).get("items") or [])
    currencies = {
        str((((it.get("price_range") or {}).get("minimum_price") or {}).get("final_price") or {}).get("currency") or "")
        .strip()
        .upper()
        for it in raw_items
        if isinstance(it, dict)
    }
    currencies.discard("")
    currency = next(iter(currencies), None)
    if currency and currency != "EGP":
        return (
            StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform="magento_graphql",
                base_url=entry.base_url,
                final_base_url=final_origin,
                status="FAILED",
                valid_count=0,
                currency=currency,
                reason=f"non-EGP currency ({currency})",
            ),
            None,
        )

    suggested_cfg = dict(entry.config or {})
    suggested_cfg["use_post"] = use_post
    probe_entry = StoreRegistryEntry(
        store_key=entry.store_key,
        display_name=entry.display_name,
        platform="magento_graphql",
        base_url=final_origin,
        category=entry.category,
        vertical=entry.vertical,
        enabled=True,
        config=suggested_cfg,
    )
    scraper_cls = build_platform_scraper_class(probe_entry)
    assert scraper_cls is not None
    with PoliteHttpClient(timeout=15.0, max_retries=1, min_delay_seconds=0.1) as hc:
        scraper = scraper_cls(hc, mode="daily", vertical=entry.vertical)
        records = scraper.scrape(limit=limit)

    # Require clean EGP price, title, product_url, and image_url
    records = _filter_clean_records(records)

    if len(records) >= 3:
        r0 = records[0]
        return (
            StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform="magento_graphql",
                base_url=entry.base_url,
                final_base_url=final_origin,
                status="READY_CLOUD",
                valid_count=len(records),
                currency=currency or "EGP",
                reason=f"OK (Magento GraphQL {'POST' if use_post else 'GET'})",
                sample_title=r0.product_title[:70],
                sample_price=float(r0.current_price),
                suggested_config={"use_post": use_post},
            ),
            None,
        )
    return None, f"magento only {len(records)} valid products"


def probe_store(
    entry: StoreRegistryEntry,
    *,
    timeout: float = 15.0,
    limit: int = 5,
) -> StoreProbeResult:
    """Probe one registry store cleanly with platform auto-detection (read-only)."""
    parsed = urlparse(entry.base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else entry.base_url.rstrip("/")

    headers = {
        **DEFAULT_HEADERS,
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=min(8.0, timeout)),
    ) as client:
        # Quick reachability check on homepage to catch dead DNS / Cloudflare root blocks
        root_block: Optional[str] = None
        final_origin = origin
        try:
            home_resp = client.get(entry.base_url)
            final_origin = f"{home_resp.url.scheme}://{home_resp.url.host}"
            if any(park in home_resp.url.host.lower() for park in _PARKED_DOMAIN_HOSTS):
                return StoreProbeResult(
                    store_key=entry.store_key,
                    display_name=entry.display_name,
                    category=entry.category,
                    vertical=entry.vertical,
                    configured_platform=entry.platform,
                    detected_platform=None,
                    base_url=entry.base_url,
                    final_base_url=final_origin,
                    status="FAILED",
                    valid_count=0,
                    currency=None,
                    reason=f"parked domain ({home_resp.url.host})",
                )
            root_block = _is_cf_or_waf_response(home_resp)
        except httpx.ConnectError as exc:
            return StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform=None,
                base_url=entry.base_url,
                final_base_url=origin,
                status="FAILED",
                valid_count=0,
                currency=None,
                reason=f"DNS/ConnectError ({str(exc)[:60]})",
            )
        except httpx.TimeoutException:
            return StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform=None,
                base_url=entry.base_url,
                final_base_url=origin,
                status="FAILED",
                valid_count=0,
                currency=None,
                reason="timeout (15s)",
            )
        except Exception as exc:
            return StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform=None,
                base_url=entry.base_url,
                final_base_url=origin,
                status="FAILED",
                valid_count=0,
                currency=None,
                reason=f"HTTP error ({type(exc).__name__})",
            )

        # Build probe order: configured platform first, then Shopify & WooCommerce auto-detect
        probe_order: list[str] = []
        if entry.platform in ("shopify", "woocommerce", "magento_graphql"):
            probe_order.append(entry.platform)
        for fallback in ("shopify", "woocommerce"):
            if fallback not in probe_order:
                probe_order.append(fallback)
        if entry.platform == "custom" and "magento_graphql" not in probe_order:
            probe_order.append("magento_graphql")

        probe_fns = {
            "shopify": _probe_shopify,
            "woocommerce": _probe_woocommerce,
            "magento_graphql": _probe_magento_graphql,
        }

        errors: list[str] = []
        blocked_reason: Optional[str] = root_block

        for plat in probe_order:
            res, err = probe_fns[plat](client, entry, final_origin, limit)
            if res is not None:
                return res
            if err:
                if err.startswith("BLOCKED:"):
                    blocked_reason = err.removeprefix("BLOCKED:")
                else:
                    errors.append(err)

        if blocked_reason:
            return StoreProbeResult(
                store_key=entry.store_key,
                display_name=entry.display_name,
                category=entry.category,
                vertical=entry.vertical,
                configured_platform=entry.platform,
                detected_platform=None,
                base_url=entry.base_url,
                final_base_url=final_origin,
                status="BLOCKED_OR_CF",
                valid_count=0,
                currency=None,
                reason=blocked_reason,
            )

        summary_err = "; ".join(errors[:2]) if errors else "no public store API"
        return StoreProbeResult(
            store_key=entry.store_key,
            display_name=entry.display_name,
            category=entry.category,
            vertical=entry.vertical,
            configured_platform=entry.platform,
            detected_platform=None,
            base_url=entry.base_url,
            final_base_url=final_origin,
            status="FAILED",
            valid_count=0,
            currency=None,
            reason=summary_err[:90],
        )


def run_registry_probe(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    workers: int = 8,
    timeout: float = 15.0,
    limit: int = 5,
    only_disabled: bool = True,
) -> list[StoreProbeResult]:
    entries = load_stores_registry(path=registry_path, enabled_only=False)
    targets = [e for e in entries if (not only_disabled or not e.enabled)]
    results: list[StoreProbeResult] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as pool:
        fut_map = {
            pool.submit(probe_store, entry, timeout=timeout, limit=limit): entry.store_key
            for entry in targets
        }
        for fut in concurrent.futures.as_completed(fut_map):
            key = fut_map[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                logger.warning("Unexpected probe crash for %s: %s", key, exc)

    results.sort(key=lambda r: ({"READY_CLOUD": 0, "BLOCKED_OR_CF": 1, "FAILED": 2}[r.status], r.store_key))
    return results


def _print_report(results: list[StoreProbeResult]) -> None:
    counts = Counter(r.status for r in results)
    print("=" * 96)
    print(
        f"REGISTRY PROBE SUMMARY | total_probed={len(results)} "
        f"| READY_CLOUD={counts['READY_CLOUD']} "
        f"| BLOCKED_OR_CF={counts['BLOCKED_OR_CF']} "
        f"| FAILED={counts['FAILED']}"
    )
    print("=" * 96)

    for status_label in ("READY_CLOUD", "BLOCKED_OR_CF", "FAILED"):
        bucket = [r for r in results if r.status == status_label]
        if not bucket:
            continue
        print(f"\n--- {status_label} ({len(bucket)}) ---")
        for r in bucket:
            plat = r.detected_platform or r.configured_platform
            extra = (
                f" | valid={r.valid_count} | {r.sample_price:,.2f} EGP | {r.sample_title}"
                if r.status == "READY_CLOUD" and r.sample_price is not None
                else f" | {r.reason}"
            )
            print(f"  {r.store_key:22s} [{r.category:15s}] {plat:15s} {r.final_base_url:36s}{extra}")


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Read-only live probe for staged stores in stores_registry.yaml.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent worker threads (default: 8).")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout seconds (default: 15).")
    parser.add_argument("--limit", type=int, default=5, help="Sample products per store (default: 5).")
    parser.add_argument("--all", action="store_true", help="Probe enabled stores too (default: only enabled: false).")
    parser.add_argument("--registry", type=str, default=None, help="Optional alternate registry YAML path.")
    parser.add_argument("--json-out", type=str, default=None, help="Optional path to save JSON probe results.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    results = run_registry_probe(
        registry_path=Path(args.registry) if args.registry else DEFAULT_REGISTRY_PATH,
        workers=args.workers,
        timeout=args.timeout,
        limit=args.limit,
        only_disabled=not args.all,
    )
    _print_report(results)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nSaved JSON probe results to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
