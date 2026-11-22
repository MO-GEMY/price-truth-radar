"""
Wave 2 feasibility probe — Egyptian supermarket e-commerce platforms.

READ-ONLY reconnaissance: a handful of GET requests per store to answer four
questions before committing scraper effort:
  1. Anti-bot / WAF tier  (plain HTTP vs TLS-impersonated HTTP vs JS required)
  2. Data accessibility   (Shopify/JSON endpoints, JSON-LD, SSR markup)
  3. Location coupling    (are Cairo branch cookies needed for price/stock?)
  4. Field coverage       (price, strikethrough, stock, image, EAN, pack size)

Targets (Wave 2 candidates):
  - Carrefour Egypt   https://carrefouregypt.com
  - Spinneys Egypt    https://spinneys-egypt.com
  - HyperOne          https://hyperone.com.eg

Usage:
  python scripts/probe_supermarkets.py            # human-readable summary
  python scripts/probe_supermarkets.py --json     # raw machine output

Requires: curl_cffi  (plain HTTP = curl_cffi without impersonation,
TLS-impersonated = curl_cffi impersonate="chrome").

Ethics: strictly GET, <= 6 requests per store, no challenge bypassing, no
auth, no concurrency. Robots.txt is fetched and recorded, not violated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin

from curl_cffi import requests as http

TIMEOUT = 30
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CHALLENGE_MARKERS = [
    "just a moment",
    "cf-chl",
    "challenge-platform",
    "captcha",
    "access denied",
    "request rejected",
    "attention required",
    "verify you are",
]

PLATFORM_FINGERPRINTS = {
    "shopify": ["cdn.shopify.com", "Shopify.theme", "/cdn/shop/", "X-ShopId"],
    "magento": ["Magento", "mage/", "catalog/product", "customer-data"],
    "woocommerce": ["wp-content", "woocommerce"],
    "sfcc": ["demandware", "sfcc"],
    "odoo": ["/web/static/", "odoo"],
    "nextjs": ["__NEXT_DATA__", "self.__next_f", "/_next/static"],
    "nuxt": ["__NUXT__", "/_nuxt/"],
    "salla_zid": ["salla", "zid"],
}

# Field-sniffing regexes run against HTML / embedded JSON.
PRICE_PATTERNS = [
    r'(?:EGP|ج\.م|ج\.م\.|LE)\s?:?\s?[\d,.]+',
    r'"price"\s*:\s*[\d.]+',
    r'"price"\s*:\s*"[^"]+"',
    r'class="[^"]*(?:price|prc)[^"]*"',
]
STRIKETHROUGH_PATTERNS = [
    r'class="[^"]*(?:old-price|was-price|compare-at|a-text-price|line-through|oldPrice)[^"]*"',
    r'"compare_at_price"\s*:\s*[\d.]+',
    r'(?:List:|Was:|بدلاً من)',
]
STOCK_PATTERNS = [
    r'"available"\s*:\s*true',
    r'"available":\s*"[\w]+"',
    r'(?:in stock|instock|add to cart|أضف إلى السلة|أضف للسلة|OUT OF STOCK|sold out|نفذت الكمية|غير متوفر)',
    r'id="availability"',
]
EAN_PATTERNS = [
    r'"(?:ean|barcode|gtin|gtin13|barcode_s)\s*"\s*:\s*"?(\d{8,14})"?',
    r'(?:ean|barcode|gtin)["\']?\s*[:=]\s*["\']?(\d{8,14})',
]
WEIGHT_PATTERNS = [
    r'\b\d+(?:[.,]\d+)?\s?(?:kg|g|gram|grams|مل|جرام|كيلو|لتر|ml|ltr|liter|litre|L)\b',
    r'"(?:net_weight|weight|net_content|size|pack_size|volume)"\s*:\s*"[^"]{1,30}"',
]
LOCATION_PATTERNS = [
    r'(?:select.{0,20}(?:store|branch|area|location)|branch selector|choose.{0,15}(?:branch|area)|فرع|اختر الفرع|متاجرنا|delivery (?:location|area))',
]


@dataclass
class TierResult:
    tier: str
    status: int | None = None
    bytes: int = 0
    title: str = ""
    challenge: bool = False
    final_url: str = ""
    body_sample: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and not self.challenge

    @property
    def real_content(self) -> bool:
        """A 200 whose body is big enough to be a real page (not a stub/redirect)."""
        return self.ok and self.bytes >= 500


@dataclass
class PageProbe:
    url: str
    tiers: list[TierResult] = field(default_factory=list)
    platform: str = "unknown"
    fields: dict = field(default_factory=dict)
    location_coupling: bool = False
    structured_endpoints: dict = field(default_factory=dict)


def _pick_text(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return m.group(1).strip()[:80] if m else ""


def _challenge(html: str) -> bool:
    low = html.lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


def fetch(url: str, impersonate: str | None) -> tuple[TierResult, str]:
    """One GET via curl_cffi. impersonate=None -> plain HTTP, 'chrome' -> TLS spoof."""
    result = TierResult(tier=impersonate or "plain")
    try:
        r = http.get(
            url,
            impersonate=impersonate,
            timeout=TIMEOUT,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            },
            allow_redirects=True,
        )
        result.status = r.status_code
        result.bytes = len(r.content)
        result.final_url = str(r.url)
        text = r.text
        result.body_sample = re.sub(r"\s+", " ", text)[:120]
        result.title = _pick_text(text)
        result.challenge = _challenge(text) or r.status_code in (403, 503, 429, 202)
        result.error = ""
        return result, text
    except Exception as exc:  # noqa: BLE001 — probe must never crash
        result.error = f"{type(exc).__name__}: {str(exc)[:110]}"
        return result, ""


def sniff_platform(html: str) -> list[str]:
    low = html.lower()
    found = [name for name, needles in PLATFORM_FINGERPRINTS.items() if any(n.lower() in low for n in needles)]
    return found


def sniff_fields(html: str) -> dict:
    return {
        "price": any(re.search(p, html, re.I) for p in PRICE_PATTERNS),
        "claimed_original_price": any(re.search(p, html, re.I) for p in STRIKETHROUGH_PATTERNS),
        "in_stock": any(re.search(p, html, re.I) for p in STOCK_PATTERNS),
        "image_url": bool(re.search(r'<img[^>]+src="https?://[^"]+"', html)),
        "ean_barcode": bool(re.search(EAN_PATTERNS[0], html) or re.search(EAN_PATTERNS[1], html, re.I)),
        "weight_size": bool(re.search(WEIGHT_PATTERNS[0], html, re.I) or re.search(WEIGHT_PATTERNS[1], html, re.I)),
        "json_ld_blocks": len(re.findall(r'application/ld\+json', html)),
        "json_ld_product": bool(re.search(r'"@type"\s*:\s*"(?:Product|ItemList)"', html)),
    }


def sniff_location(html: str) -> bool:
    return any(re.search(p, html, re.I) for p in LOCATION_PATTERNS)


def first_product_url(html: str, base: str) -> str | None:
    """Cheap product-link discovery from a listing/home page."""
    candidates = [
        r'href="(/[^"]*?/p/[^"]+)"',
        r'href="(/products/[^"#?]+)"',
        r'href="(/[^"]*?/product/[^"#?]+)"',
        r'href="(https?://[^"]*?/products/[^"#?]+)"',
        r'href="(/[^"]*?\d{5,}[^"]*?\.html)"',
    ]
    for pattern in candidates:
        m = re.search(pattern, html)
        if m:
            return urljoin(base, m.group(1))
    return None


def sitemap_urls(base: str) -> dict:
    """Fetch sitemap.xml and classify a few URLs (never fetches more than 2)."""
    out: dict = {"fetch": "n/a"}
    tier, body = fetch(base + "/sitemap.xml", impersonate=None)
    out["fetch"] = f"HTTP {tier.status}, {tier.bytes}B"
    if not (tier.ok and body):
        return out
    locs = re.findall(r"<loc>\s*(\S+?)\s*</loc>", body)
    out["entries"] = len(locs)
    # Prefer an sitemap-index -> single child
    if any(loc.endswith(".xml") for loc in locs) and len(locs) <= 12:
        child = next((l for l in locs if l.endswith(".xml")), None)
        if child:
            t2, b2 = fetch(child, impersonate=None)
            if t2.ok and b2:
                locs = re.findall(r"<loc>\s*(\S+?)\s*</loc>", b2)
                out["entries_after_index"] = len(locs)
    product_like = [u for u in locs if re.search(r"(/p/|/products?/|\d{6,})", u) and not u.rstrip("/").endswith((".xml", ".jpg", ".png"))]
    category_like = [u for u in locs if u not in product_like and not u.rstrip("/").endswith(".xml")]
    if product_like:
        out["product_sample"] = product_like[0][:130]
        out["product_count_estimate"] = len(product_like)
    if category_like:
        out["category_sample"] = category_like[1][:130] if len(category_like) > 1 else category_like[0][:130]
    out["_product_list"] = product_like[:2]
    out["_category_list"] = category_like[:2]
    return out


def probe_page(url: str, allow_product_discovery: bool = False) -> PageProbe:
    probe = PageProbe(url=url)

    # Tier 1: plain HTTP
    tier, html = fetch(url, impersonate=None)
    probe.tiers.append(tier)
    if not tier.ok:
        # Tier 2: TLS-impersonated Chrome
        tier2, html2 = fetch(url, impersonate="chrome")
        probe.tiers.append(tier2)
        if tier2.ok:
            html = html2
    if not html:
        return probe

    probe.platform = ", ".join(sniff_platform(html)) or "unknown"
    probe.fields = sniff_fields(html)
    probe.location_coupling = sniff_location(html)

    # Structured-endpoint pokes (cheap, only for platforms that support them)
    if "shopify" in probe.platform:
        for ep in ("/products.json?limit=3", "/collections/all/products.json?limit=3"):
            t, body = fetch(url.split("?")[0].rstrip("/") + ep, impersonate=None)
            if t.ok and body and body.lstrip().startswith("{"):
                probe.structured_endpoints[ep] = "JSON OK"
                try:
                    payload = json.loads(body)
                    products = payload.get("products") or []
                    if products:
                        first = products[0]
                        probe.structured_endpoints["shopify_sample"] = {
                            "title": first.get("title", "")[:60],
                            "variants_have_price": any("price" in v for v in first.get("variants", [])),
                            "variants_have_barcode": any(bool(v.get("barcode")) for v in first.get("variants", [])),
                            "images": bool(first.get("images")),
                        }
                except Exception:
                    probe.structured_endpoints[ep] = "JSON parse failed"
                break
            probe.structured_endpoints[ep] = f"HTTP {t.status}" + (" (challenge)" if t.challenge else "")

    if allow_product_discovery:
        product_url = first_product_url(html, url.rstrip("/").rsplit("/", 1)[0] + "/")
        if product_url:
            ptier, phtml = fetch(product_url, impersonate="chrome" if not tier.ok else None)
            probe.tiers.append(TierResult(
                tier=f"product:{ptier.tier}",
                status=ptier.status,
                bytes=ptier.bytes,
                title=ptier.title,
                challenge=ptier.challenge,
                error=ptier.error,
            ))
            if phtml:
                probe.fields = {**sniff_fields(phtml), "discovered_product_url": product_url[:120]}
                probe.location_coupling = sniff_location(phtml)

    return probe


def probe_store(name: str, base: str, paths: list[str], alt_bases: list[str] | None = None) -> dict:
    report: dict = {"store": name, "base": base, "pages": []}

    # robots.txt — record, never violate
    robots_tier, robots_body = fetch(base + "/robots.txt", impersonate=None)
    robots_note = f"HTTP {robots_tier.status}, {robots_tier.bytes}B"
    if robots_tier.ok and robots_body:
        sitemaps = re.findall(r"^Sitemap:\s*(\S+)", robots_body, re.M)
        robots_note += f", sitemaps={sitemaps[:2] if sitemaps else 0}"
        disallow_all = bool(re.search(r"User-agent:\s*\*\s*\nDisallow:\s*/\s*$", robots_body))
        robots_note += ", disallow-all-for-*" if disallow_all else ""
    report["robots"] = robots_note

    # Homepage (try alternate bases when the primary is unreachable / stub-only)
    home = probe_page(base + "/", allow_product_discovery=True)
    home_reachable = any(t.real_content for t in home.tiers)
    if not home_reachable and alt_bases:
        for alt in alt_bases:
            home = probe_page(alt + "/", allow_product_discovery=True)
            if any(t.real_content for t in home.tiers):
                base = alt  # subsequent paths hang off the working host
                report["base"] = alt
                break
    report["pages"].append(asdict(home))

    # Category / search guesses
    for path in paths[:2]:
        report["pages"].append(asdict(probe_page(base + path, allow_product_discovery=True)))

    # Sitemap-driven discovery: probe one real category page and one product page
    sitemap = sitemap_urls(base)
    report["sitemap"] = {k: v for k, v in sitemap.items() if not k.startswith("_")}
    for label, key in (("sitemap_category", "_category_list"), ("sitemap_product", "_product_list")):
        urls = sitemap.get(key) or []
        if urls:
            page = probe_page(urls[0], allow_product_discovery=False)
            report["pages"].append(asdict(page))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Wave 2 supermarket feasibility probe (read-only).")
    parser.add_argument("--json", action="store_true", help="emit raw JSON instead of a summary")
    args = parser.parse_args()

    stores = [
        ("carrefour_egypt", "https://carrefouregypt.com",
         ["/groceries.html", "/search?q=rice%201kg", "/fresh-food"],
         ["https://www.carrefouregypt.com", "https://carrefouregypt.com/eg/en"]),
        ("spinneys_egypt", "https://spinneys-egypt.com",
         ["/grocery-canned-food-dry-goods.html", "/grocery.html", "/catalogsearch/result/?q=rice"],
         ["https://www.spinneys-egypt.com"]),
        ("hyperone", "https://hyperone.com.eg",
         ["/groceries", "/product-category/groceries/", "/search?q=rice"],
         ["https://www.hyperone.com.eg", "https://hyperoneegypt.com", "https://www.hyperone.com",
          "https://hyper1one.com.eg", "https://hyperone.store"]),
    ]

    results = [probe_store(name, base, paths, alt_bases) for name, base, paths, alt_bases in stores]

    if args.json:
        print(json.dumps(results, indent=1, ensure_ascii=False))
        return

    for store in results:
        print(f"\n{'=' * 70}\n{store['store']}  ({store['base']})\nrobots: {store['robots']}")
        for page in store["pages"]:
            print(f"\n  URL: {page['url']}")
            for tier in page["tiers"]:
                status = tier["status"] if isinstance(tier, dict) else tier.status
                challenge = tier["challenge"] if isinstance(tier, dict) else tier.challenge
                tier_name = tier["tier"] if isinstance(tier, dict) else tier.tier
                nbytes = tier["bytes"] if isinstance(tier, dict) else tier.bytes
                title = tier["title"] if isinstance(tier, dict) else tier.title
                error = tier["error"] if isinstance(tier, dict) else tier.error
                final_url = tier["final_url"] if isinstance(tier, dict) else tier.final_url
                ok = status is not None and 200 <= status < 300 and not challenge
                flag = "OK " if ok else ("CHALLENGE" if challenge else "FAIL")
                print(f"    [{tier_name:16s}] {flag:9s} status={status} bytes={nbytes} title={title[:45]!r} {error}")
                if final_url and final_url.rstrip("/") != page["url"].rstrip("/"):
                    print(f"      -> redirected to: {final_url[:120]}")
            print(f"    platform     : {page['platform']}")
            if page.get("structured_endpoints"):
                print(f"    endpoints    : {json.dumps(page['structured_endpoints'], ensure_ascii=False)[:300]}")
            print(f"    location     : {'branch/area coupling detected' if page['location_coupling'] else 'none detected'}")
            for k, v in page.get("fields", {}).items():
                print(f"    field {k:22s}: {v}")


if __name__ == "__main__":
    sys.exit(main())
