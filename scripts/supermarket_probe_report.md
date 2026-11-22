# Wave 2 Probe — Egyptian Supermarkets (Groceries Vertical)

**Probe:** `scripts/probe_supermarkets.py` (read-only, GET-only, ≤ 8 requests/store, no challenge bypass)
**Run from:** residential Windows IP · curl_cffi 0.17.0 · 2026-11-22
**Purpose:** rank Wave 2 grocery retailers by scraper feasibility before committing build effort.

## TL;DR Ranking

| Rank | Store | Fetch tier | Data source | GHA (datacenter) verdict |
|------|-------|-----------|-------------|--------------------------|
| 1 | **Spinneys Egypt** | ✅ Plain HTTP | **Magento GraphQL on-origin** (`/graphql`) — JSON with every field | 🟢 Safe — no WAF observed |
| 2 | **HyperOne** | ⚠️ curl_cffi `impersonate="chrome"` (plain = 403) | SSR'd Nuxt payload per product page (`price`, `priceBefore`, `stock`, `sku`) + **EAN embedded in URL** | 🟡 Canary-run first — 403 is UA/TLS-level, impersonation cleared it from residential IP |
| 3 | **Carrefour Egypt** | ❌ Browser required | Next.js RSC SPA behind **Akamai bot-manager**; empty 53-byte shell to non-browsers | 🔴 Defer — needs Playwright + likely residential egress |

**Recommendation:** build **Spinneys first, HyperOne second**. Both are Magento-Cloud backends
(`mcprod.spinneys-egypt.com`, `mcprod.hyperone.com.eg`) with modern storefronts, full field
coverage, and no JS-rendering requirement. Defer Carrefour until the Playwright runner story
exists (it is the only one of the three that hard-blocks non-browser clients).

---

## 1. Spinneys Egypt — `https://spinneys-egypt.com`  ✅ RANK 1

**Anti-bot:** none observed. Plain `curl` (no impersonation) returned 200 on every page
(home 274 KB, robots 144 B, sitemap 200). No Cloudflare, no Akamai, no challenge markers.

**Data source — the jackpot:** the Nuxt storefront calls **standard Magento GraphQL on the same
origin**, and it accepts plain-HTTP GET:

```
GET https://spinneys-egypt.com/graphql?query={products(search:"rice",pageSize:3){
  total_count items{name sku url_key stock_status
    price_range{minimum_price{final_price{value currency} regular_price{value}}}}}}
```

Verified live response (abbreviated):

```json
{"data":{"products":{"total_count":284,"items":[
  {"name":"- RICE BASMATI - 1KG","sku":"449441","url_key":"rice-basmati-1kg",
   "stock_status":"IN_STOCK",
   "price_range":{"minimum_price":{"final_price":{"value":76.95,"currency":"EGP"},
                                   "regular_price":{"value":79.95}}}}]}}}
```

**Field mapping to CONTRACTS.md:**
| Field | Source |
|---|---|
| `external_id` | `sku` (e.g. `449441`) |
| `product_url` | `https://spinneys-egypt.com/en/` + `url_key` |
| `title` | `name` |
| `current_price` | `price_range.minimum_price.final_price.value` (EGP) |
| `claimed_original_price` | `price_range.minimum_price.regular_price.value` when `> final_price`, else null (proven: 76.95 vs 79.95) |
| `in_stock` | `stock_status == "IN_STOCK"` |
| `image_url` | add `media_gallery { url }` / `small_image { url }` to the query |
| `ean/barcode` | not in the listing query — probe `products(items:{sku:{eq:…}})` detail fields during build |
| weight/size | in product name/attributes (`… - 1KG`) |

**Pagination:** standard Magento `page_info { current_page, total_pages }` + `page_size`.
**Categories (live):** `/en/grocery`, `/en/beverages`, `/en/cold-cuts-deli`, `/en/meat-poultry`,
`/en/fruits-vegetables`, `/en/sweets-snacks`, `/en/deals`. Filter via
`filter:{category_id:{eq:…}}` or `category(uid:…)` after introspecting the category tree.

**Location coupling:** a `FindStore(lat, lng)` GraphQL query exists (branch selector in the UI,
default "Maadi - Cairo"), **but catalog prices/stock return with no branch cookies** — treat
catalog-level prices as the baseline; branch-level price/stock variance (if any) is a later concern.

**GHA risk:** lowest of the three. Only caution: keep `pageSize` modest and add the same
politeness pacing as every other scraper.

## 2. HyperOne — `https://www.hyperone.com.eg`  ⚠️ RANK 2

**Anti-bot:** server-level 403 ("403 Forbidden", 118 B, Apache-style) for **plain HTTP**;
`curl_cffi impersonate="chrome"` → **200** (628 KB storefront, redirects to `/en`). No Cloudflare
challenge page, no CAPTCHA — the 403 is a simple UA/TLS gate that impersonation defeats.
Note: apex `hyperone.com.eg` does **not resolve** — use `www.hyperone.com.eg`.

**Data source:** Magento Cloud backend (`mcprod.hyperone.com.eg`) behind a **Nuxt** storefront.
- **Product pages are SSR'd** with the full record in the Nuxt payload: `id`, `stock`, `price`,
  **`priceBefore`** (= strikethrough/claimed price), `sku`, `thumbnail`, `media_gallery`,
  `categories`, `attributes`. Verified live on `/en/product/200-6624000275011`
  (title "Orouba Medium Plain Coffee - 200g", strikethrough `176.95` visible in markup via
  `slope-line-through` class).
- **`external_id` + EAN in one shot:** product URLs are `/en/product/<seq>-<EAN13>` —
  `200-6624000275011` embeds a 13-digit Egypt GS1 barcode (622-prefix). So `external_id` can be
  the EAN itself.
- Category pages (`/en/category/food-cupboard`, `/en/category/beverages`, …) hydrate client-side —
  listing data must come from the sitemap, Nuxt payload discovery, or their internal API
  (not yet reverse-engineered; sitemap.xml did not respond on plain HTTP this probe).

**Field mapping:** `price` ✅ (payload + HTML), `claimed_original_price` ✅ (`priceBefore` /
`slope-line-through`), `in_stock` ✅ (`stock`), `image_url` ✅ (`thumbnail`/`media_gallery`),
`ean_barcode` ✅ (URL), weight/size ✅ (title + `attributes`). No location cookies required for
catalog prices (no branch selector detected).

**GHA risk:** medium — impersonated requests worked from a residential IP; datacenter IPs may
face the same 403 unless the gate is purely UA-based (likely). Canary-run from Actions before
committing; the curl_cffi dependency is required either way.

## 3. Carrefour Egypt — `https://carrefouregypt.com`  🔴 RANK 3 (defer)

**Anti-bot:** **Akamai bot-manager**. Every non-browser request (plain and TLS-impersonated)
receives a **200 with a 53-byte empty HTML shell** (`Server: AkamaiGHost`, `<p></p>`) —
technically "200 OK" but zero content. Only a real browser passes (verified: in-app browser
renders the full store, 50,000+ items claimed).

**Site anatomy (from the browser):**
- Real app: `https://www.carrefouregypt.com/mafegy/{ar|en}` — a **Next.js App Router SPA**
  (RSC flight requests `…?_rsc=…` visible; data is streamed, no classic JSON API observed).
- **Akamai sensor** (`/akam/13/pixel_…`) + Securiti cookie-consent gate.
- **Branch-coupled pricing**: UI pins a branch ("Maadi - Cairo") with three fulfilment modes
  (scheduled / express / instant) — price and stock depend on the selected branch/area.

**Extraction path (if pursued later):** Playwright with stealth, load `/mafegy/en`, wait for
hydration, then either (a) read product data from the RSC flight payload in-page, or (b) drive
the category UI and parse the hydrated DOM. Requires residential/sticky egress; Akamai is
sensitive to datacenter IPs, so **not GHA-friendly**.

**Fields seen in UI:** prices, strikethroughs, stock nudges — extractable, but only behind the
browser tier above.

## Probe Limitations & Caveats

- All probes ran from a **residential Egyptian IP**. GHA runners (Azure datacenter) may see
  different WAF behaviour — Spinneys is the only store with no WAF at all; HyperOne's 403 gate
  is the main unknown; Carrefour is presumed blocked on GHA.
- Request budget was deliberately tiny (~8 GETs/store); Spinneys GraphQL schema was only
  spot-checked (one corrected query) — introspect properly during implementation.
- HyperOne category/listing pagination is not yet mapped (client-hydrated grid) — the
  sitemap/API reverse-engineering is Wave 2 build work.
- No CAPTCHAs were solved, bypassed, or otherwise interacted with; blocked paths are reported
  as blocked.
