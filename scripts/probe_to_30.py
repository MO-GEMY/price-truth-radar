"""
Lightweight read-only feasibility probe across 26 Egyptian e-commerce candidates
to select the Top 17 live-working, GHA-friendly stores (scaling 13 -> 30 stores).

Checks per candidate (no challenge/CAPTCHA bypass; skips blocked sites):
  1. Shopify:     GET /products.json?limit=5
  2. WooCommerce: GET /wp-json/wc/store/v1/products?per_page=5
  3. Magento GQL: GET /graphql?query={products(search:"a",pageSize:3){...}} (plus mcprod.<domain>)
  4. Homepage:    GET / (checks HTTP 200, JSON-LD Product, Cloudflare/WAF markers, platform hints)

Outputs a ranked JSON & console report to help wire the Top 17 winners cleanly.
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Any, Optional

import httpx

CANDIDATES: list[tuple[str, str, str, list[str]]] = [
    # Fashion & Footwear (11 candidates -> target ~7-8 winners)
    ("ravin", "fashion", "fashion", ["https://ravin.eg", "https://www.ravin.eg"]),
    ("activ", "fashion", "fashion", ["https://activaboualaa.com", "https://www.activaboualaa.com"]),
    ("mobaco", "fashion", "fashion", ["https://mobaco.com", "https://www.mobaco.com"]),
    ("concrete", "fashion", "fashion", ["https://concrete.com.eg", "https://www.concrete.com.eg"]),
    ("tiehouse", "fashion", "fashion", ["https://tiehouse.com", "https://www.tiehouse.com"]),
    ("khotwh", "fashion", "fashion", ["https://khotwh.com", "https://www.khotwh.com"]),
    ("carina", "fashion", "fashion", ["https://carinawear.com", "https://www.carinawear.com"]),
    ("tomato", "fashion", "fashion", ["https://tomato.com.eg", "https://www.tomato.com.eg"]),
    ("mitcha", "fashion", "fashion", ["https://mitcha.com", "https://www.mitcha.com"]),
    ("lcwaikiki", "fashion", "fashion", ["https://www.lcwaikiki.eg", "https://lcwaikiki.eg"]),
    ("defacto", "fashion", "fashion", ["https://www.defacto.com/en-eg", "https://www.defacto.com"]),
    # Groceries & Food (7 candidates -> target ~4-5 winners)
    ("gourmet", "groceries", "groceries", ["https://gourmetegypt.com", "https://www.gourmetegypt.com"]),
    ("metro_market", "groceries", "groceries", ["https://www.metro-markets.com", "https://metro-markets.com"]),
    ("oscar", "groceries", "groceries", ["https://oscarstores.com", "https://www.oscarstores.com"]),
    ("abu_auf", "groceries", "groceries", ["https://abuauf.com", "https://www.abuauf.com"]),
    ("imtenan", "groceries", "groceries", ["https://imtenan.com", "https://www.imtenan.com"]),
    ("fathalla", "groceries", "groceries", ["https://fathallamarket.com", "https://www.fathallamarket.com"]),
    ("breadfast", "groceries", "groceries", ["https://www.breadfast.com", "https://breadfast.com"]),
    # Electronics, PC Hardware & Home Appliances (8 candidates -> target ~5-6 winners)
    ("elaraby", "core", "home_appliances", ["https://www.elarabygroup.com", "https://elarabygroup.com"]),
    ("compuscience", "core", "electronics", ["https://compuscience.com.eg", "https://www.compuscience.com.eg"]),
    ("elbadr", "core", "electronics", ["https://elbadrgroupeg.store", "https://www.elbadrgroupeg.store"]),
    ("compumarts", "core", "electronics", ["https://www.compumarts.com", "https://compumarts.com"]),
    ("egyptlaptop", "core", "electronics", ["https://egyptlaptop.com", "https://www.egyptlaptop.com"]),
    ("dubaiphone", "core", "electronics", ["https://dubaiphone.net", "https://www.dubaiphone.net"]),
    ("tradeline", "core", "electronics", ["https://tradelineegypt.com", "https://www.tradelineegypt.com"]),
    ("cairosales", "core", "electronics", ["https://cairosales.com", "https://www.cairosales.com"]),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

GQL_TEST = '{products(search:"a",pageSize:3){total_count items{name sku url_key stock_status small_image{url} price_range{minimum_price{final_price{value currency}regular_price{value}}}}}}'


@dataclass
class ProbeResult:
    store_name: str
    vertical: str
    category: str
    base_url: str
    adapter: str  # shopify | woocommerce | magento_graphql | jsonld | html | blocked | failed
    score: int
    sample_count: int
    sample_title: str
    sample_price: str
    currency: str
    endpoint: str
    notes: str


def _is_cf_challenge(resp: httpx.Response) -> bool:
    if (resp.headers.get("cf-mitigated") or "").lower() == "challenge":
        return True
    txt = (resp.text or "")[:2000].lower()
    return "<title>just a moment...</title>" in txt or "attention required! | cloudflare" in txt


def _probe_one(store_name: str, vertical: str, category: str, urls: list[str]) -> ProbeResult:
    base = urls[0].rstrip("/")
    notes: list[str] = []

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=12.0, verify=True) as client:
        # Resolve working base origin
        working_base = base
        home_resp: Optional[httpx.Response] = None
        for cand in urls:
            try:
                r = client.get(cand)
                if r.status_code < 500:
                    working_base = f"{r.url.scheme}://{r.url.host}"
                    home_resp = r
                    break
            except Exception as exc:
                notes.append(f"conn({cand}):{type(exc).__name__}")

        if home_resp is None:
            return ProbeResult(
                store_name, vertical, category, base, "failed", 0, 0, "", "", "", "", "; ".join(notes)
            )

        if _is_cf_challenge(home_resp):
            return ProbeResult(
                store_name, vertical, category, working_base, "blocked", 0, 0, "", "", "", working_base,
                f"Cloudflare challenge HTTP {home_resp.status_code}"
            )

        # 1. Shopify `/products.json?limit=5`
        try:
            r_sh = client.get(f"{working_base}/products.json", params={"limit": 5})
            if r_sh.status_code == 200 and "application/json" in (r_sh.headers.get("content-type") or "").lower():
                data = r_sh.json()
                prods = data.get("products") if isinstance(data, dict) else None
                if isinstance(prods, list) and len(prods) > 0:
                    p0 = prods[0]
                    v0 = (p0.get("variants") or [{}])[0]
                    price = str(v0.get("price") or "")
                    return ProbeResult(
                        store_name, vertical, category, working_base, "shopify", 100,
                        len(prods), str(p0.get("title") or "")[:60], price, "EGP",
                        f"{working_base}/products.json", "Shopify JSON open"
                    )
        except Exception:
            pass

        # 2. WooCommerce Store API `/wp-json/wc/store/v1/products?per_page=5`
        for wc_path in ("/wp-json/wc/store/v1/products", "/en/wp-json/wc/store/v1/products"):
            try:
                r_wc = client.get(f"{working_base}{wc_path}", params={"per_page": 5})
                if r_wc.status_code == 200 and "json" in (r_wc.headers.get("content-type") or "").lower():
                    data = r_wc.json()
                    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "prices" in data[0]:
                        p0 = data[0]
                        pr = p0.get("prices") or {}
                        curr = str(pr.get("currency_code") or "")
                        minor = int(pr.get("currency_minor_unit") or 2)
                        raw_p = pr.get("price") or "0"
                        val = f"{int(raw_p) / (10 ** minor):.2f}" if str(raw_p).isdigit() else str(raw_p)
                        return ProbeResult(
                            store_name, vertical, category, working_base, "woocommerce", 95,
                            len(data), str(p0.get("name") or "")[:60], val, curr,
                            f"{working_base}{wc_path}", f"WooCommerce Store API ({curr})"
                        )
            except Exception:
                pass

        # 3. Magento 2 GraphQL (on-origin and mcprod.<apex>)
        host_apex = working_base.split("://", 1)[-1].removeprefix("www.")
        gql_candidates = [
            f"{working_base}/graphql",
            f"https://mcprod.{host_apex}/graphql",
        ]
        for gql_url in gql_candidates:
            try:
                r_gql = client.get(gql_url, params={"query": GQL_TEST})
                if r_gql.status_code == 200 and "json" in (r_gql.headers.get("content-type") or "").lower():
                    data = r_gql.json()
                    prods = ((data.get("data") or {}).get("products") or {}).get("items")
                    if isinstance(prods, list) and len(prods) > 0:
                        p0 = prods[0]
                        pr = ((p0.get("price_range") or {}).get("minimum_price") or {}).get("final_price") or {}
                        return ProbeResult(
                            store_name, vertical, category, working_base, "magento_graphql", 92,
                            len(prods), str(p0.get("name") or "")[:60], str(pr.get("value") or ""),
                            str(pr.get("currency") or "EGP"), gql_url, "Magento GraphQL open"
                        )
            except Exception:
                pass

        # 4. Inspect homepage HTML for JSON-LD Product / OpenCart / PrestaShop / Magento SSR hints
        html = home_resp.text or ""
        if home_resp.status_code == 200 and len(html) > 10_000:
            has_jsonld = '"@type":"Product"' in html or '"@type": "Product"' in html
            is_shopify = "cdn.shopify.com" in html or "Shopify.theme" in html
            is_wp = "wp-content" in html or "woocommerce" in html.lower()
            is_magento = "Magento_" in html or "product-item-info" in html
            is_opencart = "index.php?route=product" in html or "catalog/view/theme" in html
            hints = [
                h for h, ok in (
                    ("jsonld_product", has_jsonld),
                    ("shopify_theme", is_shopify),
                    ("wp", is_wp),
                    ("magento_ssr", is_magento),
                    ("opencart", is_opencart),
                ) if ok
            ]
            if has_jsonld:
                return ProbeResult(
                    store_name, vertical, category, working_base, "jsonld", 70, 1, "", "", "EGP",
                    working_base, f"HTTP 200 ({len(html)//1024}KB) hints={hints}"
                )
            return ProbeResult(
                store_name, vertical, category, working_base, "html", 40 if hints else 20, 0, "", "", "EGP",
                working_base, f"HTTP 200 ({len(html)//1024}KB) hints={hints}"
            )

        return ProbeResult(
            store_name, vertical, category, working_base, "blocked" if home_resp.status_code in (403, 429, 503) else "failed",
            0, 0, "", "", "", working_base, f"HTTP {home_resp.status_code} ({len(html)}B)"
        )


def main() -> int:
    results: list[ProbeResult] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_probe_one, s, v, c, u) for s, v, c, u in CANDIDATES]
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda r: (-r.score, r.vertical, r.store_name))
    print(f"{'STORE':14s} | {'VERT':9s} | {'CAT':15s} | {'ADAPTER':15s} | {'CNT':3s} | {'PRICE':10s} | {'CURR':4s} | NOTES")
    print("-" * 120)
    for r in results:
        print(
            f"{r.store_name:14s} | {r.vertical:9s} | {r.category:15s} | {r.adapter:15s} | "
            f"{r.sample_count:3d} | {r.sample_price[:10]:10s} | {r.currency[:4]:4s} | {r.notes[:45]} | {r.sample_title[:35]}"
        )

    out_path = "scripts/probe_to_30_results.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump([asdict(r) for r in results], fh, indent=2, ensure_ascii=False)
    print(f"\nSaved raw probe results to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
