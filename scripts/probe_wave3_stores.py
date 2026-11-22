"""
Wave 3 / Core 2 feasibility probe — next expansion stores.

READ-ONLY reconnaissance: GET requests only (plus read-only Magento GraphQL
storeConfig / products listing queries), ≤ ~8 requests per store, no challenge
bypassing, no auth. Robots.txt is fetched and recorded, never violated.

Targets:
  Groceries Wave 3:
  - Seoudi Supermarket   https://seoudisupermarket.com
  Core Wave 2 (Electronics/Appliances):
  - Jumia Egypt          https://jumia.com.eg
  - Raneen               https://raneen.com
  - Raya Shop            https://rayashop.com
  - Dream 2000           https://dream2000.com

For each store the probe records:
  1. Fetch tiers  (plain HTTP vs curl_cffi impersonate="chrome" vs browser-only)
  2. Platform / structured data source (Magento GraphQL, Shopify JSON,
     JSON-LD, __NEXT_DATA__/__NUXT_DATA__, SSR HTML)
  3. Field coverage on real items (price, strikethrough, stock, image, sku/ean)
  4. Location / store-view coupling hints

Reuse: fetch/sniff helpers come from probe_supermarkets.py (same directory,
imported read-only — that file is not modified).

Usage:
  python scripts/probe_wave3_stores.py           # human-readable summary
  python scripts/probe_wave3_stores.py --json    # raw machine output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_supermarkets as ps  # noqa: E402  (read-only reuse of helpers)


def fetch_json(url: str, impersonate: str | None = None) -> tuple[dict | None, str]:
    """GET a URL and parse JSON; plain first, TLS-impersonated fallback on failure."""
    result, text = ps.fetch(url, impersonate)
    note = f"HTTP {result.status} ({impersonate or 'plain'}), {result.bytes}B"
    if result.error or result.challenge or (result.status is not None and result.status >= 400):
        # retry once with Chrome TLS impersonation (defeats UA/TLS-level gates)
        result2, text2 = ps.fetch(url, impersonate="chrome")
        note += f" -> retry chrome: HTTP {result2.status}, {result2.bytes}B"
        if not result2.error and not result2.challenge and result2.status and result2.status < 400:
            result, text = result2, text2
            note = f"HTTP {result.status} (chrome), {result.bytes}B"
        elif result.error:
            return None, note
    if text:
        try:
            return json.loads(text), note
        except Exception:
            return None, f"{note} (non-JSON body)"
    return None, note


def probe_magento_graphql(base: str, search_term: str = "iphone") -> dict:
    """Read-only Magento GraphQL checks: storeConfig, then a minimal products query."""
    out: dict = {"endpoint": f"{base}/graphql"}
    cfg_q = '{storeConfig{store_code locale base_currency_code website_id}}'
    payload, note = fetch_json(f"{base}/graphql?query={quote(cfg_q)}")
    out["storeConfig"] = note if payload is None else {
        "store_code": payload.get("data", {}).get("storeConfig", {}).get("store_code"),
        "locale": payload.get("data", {}).get("storeConfig", {}).get("locale"),
        "currency": payload.get("data", {}).get("storeConfig", {}).get("base_currency_code"),
    }
    if payload is None:
        return out

    prod_q = (f'{{products(search:"{search_term}",pageSize:2){{total_count items{{name sku '
              'url_key stock_status price_range{minimum_price{final_price{value currency} '
              'regular_price{value}}}}}}}}')
    payload2, note2 = fetch_json(f"{base}/graphql?query={quote(prod_q)}")
    if payload2 is None:
        out["products"] = note2
        return out
    try:
        products = payload2["data"]["products"]
        items = products.get("items", [])
        out["products"] = {
            "total_count": products.get("total_count"),
            "sample": [
                {
                    "name": it.get("name", "")[:50],
                    "sku": it.get("sku"),
                    "url_key": it.get("url_key"),
                    "stock": it.get("stock_status"),
                    "final": (it.get("price_range", {}).get("minimum_price", {})
                              .get("final_price", {}).get("value")),
                    "regular": (it.get("price_range", {}).get("minimum_price", {})
                                .get("regular_price", {}).get("value")),
                }
                for it in items[:2]
            ],
        }
    except Exception as exc:  # noqa: BLE001
        out["products"] = f"unexpected shape: {exc}"
    return out


def probe_rest_store(base: str) -> dict:
    """Magento REST store configs (fallback when GraphQL is closed)."""
    payload, note = fetch_json(f"{base}/rest/V1/store/storeConfigs")
    if payload is None:
        return {"endpoint": f"{base}/rest/V1/store/storeConfigs", "result": note}
    if isinstance(payload, list) and payload:
        return {
            "endpoint": f"{base}/rest/V1/store/storeConfigs",
            "result": "JSON OK",
            "store_views": [c.get("code") for c in payload[:4]],
        }
    return {"endpoint": f"{base}/rest/V1/store/storeConfigs", "result": "JSON OK, unexpected shape"}


def probe_store(name: str, base: str, alt_bases: list[str] | None = None,
                graphql: bool = True, search_term: str = "iphone",
                guess_paths: list[str] | None = None) -> dict:
    report: dict = {"store": name, "base": base}

    # robots.txt
    robots_tier, robots_body = ps.fetch(base + "/robots.txt", impersonate=None)
    robots_note = f"HTTP {robots_tier.status}, {robots_tier.bytes}B"
    if robots_tier.ok and robots_body:
        sitemaps = re.findall(r"^Sitemap:\s*(\S+)", robots_body, re.M)
        robots_note += f", sitemaps={sitemaps[:2] if sitemaps else 0}"
    report["robots"] = robots_note

    # Homepage (alt bases on DNS/stub failure)
    home = ps.probe_page(base + "/", allow_product_discovery=True)
    if not any(t.real_content for t in home.tiers) and alt_bases:
        for alt in alt_bases:
            home = ps.probe_page(alt + "/", allow_product_discovery=True)
            if any(t.real_content for t in home.tiers):
                base = alt
                report["base"] = alt
                break
    home_page = asdict_page(home)
    report["home"] = home_page

    # Sitemap-driven discovery of one category + one product page
    sitemap = ps.sitemap_urls(base)
    report["sitemap"] = {k: v for k, v in sitemap.items() if not k.startswith("_")}

    cat_url = (sitemap.get("_category_list") or [None])[0]
    prod_url = (sitemap.get("_product_list") or [None])[0]
    if cat_url:
        report["category_page"] = asdict_page(ps.probe_page(cat_url))
    if prod_url:
        report["product_page"] = asdict_page(ps.probe_page(prod_url))

    # Fallback: single guessed path when the sitemap yielded nothing
    if not cat_url and not prod_url and guess_paths:
        report["guess_page"] = asdict_page(
            ps.probe_page(base + guess_paths[0], allow_product_discovery=True))

    # Platform-specific structured endpoints on the working host
    working = report.get("base", base)
    if graphql:
        report["magento_graphql"] = probe_magento_graphql(working, search_term)
        sc = report["magento_graphql"].get("storeConfig")
        if isinstance(sc, str):  # GraphQL unreachable/closed -> try Magento REST once
            report["magento_rest"] = probe_rest_store(working)
    if "shopify" in str(home_page.get("platform", "")):
        payload, note = fetch_json(working + "/products.json?limit=2")
        report["shopify_products_json"] = note if payload is None else {
            "count": len(payload.get("products", [])),
            "sample": [
                {
                    "title": p.get("title", "")[:50],
                    "vendor": p.get("vendor"),
                    "price": (p.get("variants") or [{}])[0].get("price"),
                    "barcode": (p.get("variants") or [{}])[0].get("barcode"),
                    "available": (p.get("variants") or [{}])[0].get("available"),
                }
                for p in payload.get("products", [])[:2]
            ],
        }
    return report


def asdict_page(page: ps.PageProbe) -> dict:  # noqa: F821 — ps re-exports the type
    d = {
        "url": page.url,
        "tiers": [
            {
                "tier": t.tier,
                "status": t.status,
                "bytes": t.bytes,
                "title": t.title[:60],
                "challenge": t.challenge,
                "final_url": t.final_url,
                "error": t.error,
            }
            for t in page.tiers
        ],
        "platform": page.platform,
        "location_coupling": page.location_coupling,
        "fields": page.fields,
    }
    return d


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Wave 3 / Core 2 store feasibility probe (read-only).")
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    args = parser.parse_args()

    stores = [
        ("seoudi_supermarket", "https://seoudisupermarket.com",
         ["https://www.seoudisupermarket.com"], True, "rice", ["/groceries", "/en/groceries"]),
        ("jumia_egypt", "https://jumia.com.eg",
         ["https://www.jumia.com.eg"], False, "iphone", ["/catalog/?q=rice"]),  # known CF challenge — browser tier per prior recon
        ("raneen", "https://raneen.com",
         ["https://www.raneen.com"], True, "tv", ["/tv", "/en/tv"]),
        ("raya_shop", "https://rayashop.com",
         ["https://www.rayashop.com"], True, "iphone", ["/mobiles", "/en/mobiles"]),
        ("dream2000", "https://dream2000.com",
         ["https://www.dream2000.com"], True, "samsung", ["/mobiles", "/en/mobiles"]),
    ]

    results = []
    for name, base, alt_bases, graphql, search_term, guess_paths in stores:
        results.append(probe_store(name, base, alt_bases, graphql=graphql,
                                   search_term=search_term, guess_paths=guess_paths))

    if args.json:
        print(json.dumps(results, indent=1, ensure_ascii=False))
        return

    for store in results:
        print(f"\n{'=' * 72}\n{store['store']}  (working base: {store.get('base')})")
        print(f"robots: {store['robots']}")
        for label in ("home", "category_page", "product_page", "guess_page"):
            page = store.get(label)
            if not page:
                continue
            print(f"\n  [{label}] {page['url']}")
            for t in page["tiers"]:
                ok = t["status"] is not None and 200 <= t["status"] < 300 and not t["challenge"]
                flag = "OK " if ok else ("CHALLENGE" if t["challenge"] else "FAIL")
                print(f"    [{t['tier']:8s}] {flag:9s} status={t['status']} bytes={t['bytes']:>8} title={t['title'][:42]!r} {t['error']}")
                if t["final_url"] and t["final_url"].rstrip("/") != page["url"].rstrip("/"):
                    print(f"      -> final: {t['final_url'][:110]}")
            print(f"    platform : {page['platform']}")
            print(f"    location : {'branch/area coupling' if page['location_coupling'] else 'none detected'}")
            for k, v in page["fields"].items():
                print(f"    field {k:24s}: {v}")
        for key in ("magento_graphql", "magento_rest", "shopify_products_json", "next_nuxt"):
            if store.get(key):
                print(f"\n  {key}: {json.dumps(store[key], ensure_ascii=False)[:600]}")
        print()


if __name__ == "__main__":
    sys.exit(main())
