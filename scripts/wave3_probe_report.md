# Wave 3 / Core 2 Probe — Egyptian Supermarket + Electronics/Appliances Retailers

**Probe:** `scripts/probe_wave3_stores.py` (read-only, GET + read-only Magento GraphQL listing queries, ≤ ~8 requests/store, no challenge bypass)
**Run from:** residential Windows IP · curl_cffi 0.17.0 · 2026-11-22
**Purpose:** feasibility verdict for Groceries Wave 3 (Seoudi) and Core Wave 2 electronics (Jumia, Raneen, Raya Shop, Dream 2000).

## TL;DR Summary

| Rank | Store | Vertical | Fetch tier | Data source | Field coverage | GHA readiness |
|------|-------|----------|-----------|-------------|----------------|---------------|
| **1** | **Seoudi Supermarket** | Groceries W3 | ✅ **Plain HTTP** on the API host (storefront pages = Cloudflare, but not needed) | **Magento Cloud GraphQL, wide open** at `mcprod.seoudisupermarket.com/graphql` | title ✅ sku=**EAN** ✅ price ✅ strikethrough ✅ stock ✅ image (media_gallery) | 🟢 **Ready now** |
| **2** | **Raneen** | Electronics/Appliances | ✅ **Plain HTTP** (no WAF; a "captcha" word in the login modal false-positived the challenge detector) | SSR Magento HTML (1.6 MB home with prices/strikethrough/stock) | title ✅ brand ✅ price ✅ strikethrough ✅ stock ✅ image ✅ | 🟢 Ready (URL patterns need work — sitemap stale) |
| **3** | **Raya Shop** | Electronics/Phones | ⚠️ **curl_cffi `impersonate="chrome"`** (plain = Cloudflare 403) | SSR Magento/Nuxt HTML + **JSON-LD `Product` on category pages** | title ✅ price ✅ strikethrough ✅ stock ✅ image ✅ | 🟡 Canary-run from GHA first |
| **4** | **Jumia Egypt** | Electronics/Appliances/Groceries | ⚠️ Plain HTTP **works but intermittently challenged** (1 of 2 probes challenged this run; both challenged 2 days ago) | SSR HTML + **JSON-LD `Product` on product pages**; DOM selectors (`article.prd`, `.prc`, `.old`, `a.core`) verified | title ✅ price ✅ strikethrough ✅ stock ✅ image ✅ (no EAN) | 🔴 **Local residential runner (alongside 2b)** — CF is IP-reputation sensitive |
| **5** | **Dream 2000** | Electronics/Phones | ❌ Plain = 403 "Access denied" (WAF); curl_cffi = 200 but **4.6 MB JS-rendered page with zero detectable fields**; `/graphql` + `/rest/V1` → 404 | Unknown — client-rendered; needs reverse-engineering or Playwright | none verified | 🔴 Defer (lowest effort/value ratio) |

**Build-order recommendation:**
- **Groceries Wave 3: Seoudi is ready for immediate build on plain HTTP — GHA-friendly.** Its `mcprod` GraphQL host answers open, unauthenticated catalog queries with EGP prices, EAN SKUs, and strikethroughs (identical pattern to Spinneys, rank 1 of the Wave 2 probe).
- **Core Wave 2: build Raneen first** (plain HTTP, zero WAF, full SSR fields — but fix product-URL discovery first), **then Raya Shop** (curl_cffi + JSON-LD, bigger phone catalog). 
- **Jumia: defer to the local residential runner alongside 2b** — highest catalog value of the four, but its Cloudflare behaviour is IP-reputation sensitive (today: 1 of 2 plain probes challenged; two days ago: all challenged), which makes datacenter-IP runs unreliable.
- **Dream 2000: defer** — no structured data path found within the probe budget.

---

## 1. Seoudi Supermarket — `https://seoudisupermarket.com` ✅ READY (Groceries Wave 3)

**Two-host architecture** (identical pattern to Spinneys/HyperOne from the Wave 2 probe):
- Storefront `seoudisupermarket.com` → **Cloudflare**: plain HTTP = 403 "Attention Required!"; `curl_cffi impersonate="chrome"` = 200 (1 MB pages). Pages are Magento-Cloud + Nuxt-style and **branch/location-coupled** (`FindStore(lat,lng)` seen in browser network log; default branch "Maadi"-style selection required before product grids populate).
- **Data API `mcprod.seoudisupermarket.com/graphql` → OPEN via plain HTTP, no auth, no cookies** (verified live):

```
GET https://mcprod.seoudisupermarket.com/graphql?query={storeConfig{store_code locale base_currency_code website_id}}
→ {"data":{"storeConfig":{"store_code":"default","locale":"en_US","base_currency_code":"EGP","website_id":1}}}

GET https://mcprod.seoudisupermarket.com/graphql?query={products(search:"rice",pageSize:2){total_count items{name sku stock_status price_range{minimum_price{final_price{value} regular_price{value}}}}}}
→ {"data":{"products":{"total_count":251,"items":[
     {"name":"Seoudi Rice Kofta","sku":"2000722000000","stock_status":"IN_STOCK",
      "price_range":{"minimum_price":{"final_price":{"value":434.95},"regular_price":{"value":445}}}},
     {"name":"Al Doha Beyti Rice, Easy Rice Edition - 320 g","sku":"6223000660140",
      "stock_status":"IN_STOCK","final_price":{"value":25.75},"regular_price":{"value":25.75}}]}}}
```

**Field mapping to CONTRACTS.md:**
| Field | Source |
|---|---|
| `external_id` | `sku` — **13-digit EAN barcodes** (`2000722000000`, `6223000660140` 622 = Egypt GS1) |
| `product_url` | storefront URL derived from `url_key` (add `url_key` to the query) |
| `title` | `name` (weights inline: "… - 320 g") |
| `current_price` | `price_range.minimum_price.final_price.value` (EGP) |
| `claimed_original_price` | `regular_price.value` when `> final_price` (proven: 445 vs 434.95) |
| `in_stock` | `stock_status == "IN_STOCK"` |
| `image_url` | add `media_gallery { url }` / `small_image { url }` to the query |
| weight/size | in names ("320 g"); extend query with attributes if needed |

**Pagination:** standard Magento `page_info` + `page_size`. **Location:** `FindStore(lat,lng)` exists on the storefront, but catalog GraphQL returns prices with **no branch cookies required**. **Category context:** add `filter:{category_id:{eq:…}}` after a `categories(filters:{url_key:{eq:"groceries"}})` tree query during build.

## 2. Raneen — `https://www.raneen.com` ✅ (Core Wave 2, rank 1)

**Anti-bot:** none — plain HTTP 200 on all pages (home 1.6 MB, fully SSR'd). The word "captcha" appears 53× on the homepage (login-modal reCAPTCHA element) which false-positived challenge sniffing — **not** a WAF.

**Data source:** Magento SSR HTML. Live-verified fields on the homepage: `price` ✅, strikethrough ✅, `in_stock` ✅, images ✅, weights in titles ✅, JSON-LD present (2 blocks, non-Product). GraphQL exists but is **authorization-gated** (`{"errors":[{"message":"The GraphQL API is not available to this client.","category":"graphql-authorization"}]}`) → use SSR HTML selectors.

**Gotcha found:** sitemap URLs (`/en/<slug>` product pages) return 404 — the sitemap is stale or products need a different store-view prefix. Build must discover product URLs from category-page HTML instead of the sitemap. Sitemaps declared: `sitemap/sitemap_ar.xml`, `sitemap/sitemap_en.xml`.

**Suggested start:** fetch a real category page (discover from `/en` nav links — categories exist for appliances/electronics), extract product tiles (Magento `item product product-item` markup + `data-price-type="oldPrice|finalPrice"` spans), paginate via Magento `?p=N`.

## 3. Raya Shop — `https://www.rayashop.com` ⚠️ (Core Wave 2, rank 2)

**Anti-bot:** **Cloudflare 403** ("Attention Required!") for plain HTTP on every path incl. `robots.txt`; `curl_cffi impersonate="chrome"` → 200 (2 MB home, 1.3 MB category). The `/graphql` and `/rest/V1` endpoints return the category **HTML** instead of JSON (Cloudflare rule rewrites/locks them) → API tier unavailable.

**Data source:** SSR HTML with **JSON-LD `Product` block verified on the `/ar/mobiles` category page** — extract offers (price/currency/availability) straight from JSON-LD plus DOM fallbacks. Platform markers: Magento + Nuxt hybrid.

**Field coverage (category page):** title ✅ price ✅ strikethrough ✅ (absent on non-discounted grid pages — present in JSON-LD offers) image ✅; stock via JSON-LD `availability`; sku/ean not surfaced on cards → per-product detail fetch if needed.

**GHA risk:** medium — impersonation cleared Cloudflare from a residential IP; run one canary from Actions before relying on it. Robots.txt itself 403s (bot-gated) — respect meta robots instead.

## 4. Jumia Egypt — `https://www.jumia.com.eg` 🔴 (local residential runner, alongside 2b)

**Anti-bot:** Cloudflare behaves **intermittently**: this run — homepage plain HTTP got a 125 KB challenge body, but the `/catalog/?q=rice` page and a discovered product page returned **full 200 content (767 KB / 209 KB)** to plain HTTP; the earlier probe run (2 days ago) got challenges on everything. Conclusion: CF passes/fails per-request based on reputation — **unreliable from datacenter IPs**.

**Data source (when through):** SSR HTML with **JSON-LD `Product` on product pages** (verified: `"@type":"Product"` present), plus the previously-verified DOM selectors: `article.prd`, `.name`, `.prc` (current), `.old` (claimed strikethrough), `a.core` href `/slug-<numeric-id>.html` (numeric id = external_id), images `eg.jumia.is`, pagination `?page=N`. No EAN on cards.

**Field coverage:** title ✅ price ✅ strikethrough ✅ stock ✅ image ✅ weight/size ✅ (titles), EAN ❌.

**GHA verdict:** 🔴 run on the **local residential runner next to 2b** (commit `093d510` precedent). Add per-request challenge detection (body < ~10 KB or "Just a moment" title) with retry/backoff.

## 5. Dream 2000 — `https://www.dream2000.com` 🔴 DEFER

- Plain HTTP → 403 "Access denied" (6.9 KB WAF page); `curl_cffi chrome` → 200 but the **4.6 MB homepage contains zero detectable prices/JSON-LD** — content is client-rendered or obfuscated.
- `/graphql` and `/rest/V1/store/storeConfigs` → 404 (chrome) — no exposed Magento API; `/mobiles` → 404 (wrong URL guess).
- Within probe budget, no structured path was found. Defer until a browser-based session reverse-engineers the data calls; likely the hardest of the wave.

## Probe Limitations & Caveats

- Residential Egyptian IP; GHA datacenter results may differ — Spinneys/Seoudi-style open GraphQL hosts are the safest bets, Raya needs a canary, Jumia is presumed challenge-heavy on datacenter IPs.
- No CAPTCHAs solved or bypassed; blocked paths reported as blocked. Requests kept ≤ ~8/store.
- Seoudi storefront pages were not extractable without a branch context; the viable path is the open `mcprod` GraphQL host documented above (verified with real queries).

**Recommended wave plan:** Groceries Wave 3 = Seoudi now (GHA). Core Wave 2 = Raneen (GHA) → Raya Shop (GHA canary) → Jumia (local residential, alongside 2b). Dream 2000 deferred.
