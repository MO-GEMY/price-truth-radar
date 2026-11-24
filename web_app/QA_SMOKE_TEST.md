# Asarak (أسعارك) — QA & Smoke Test Checklist

**Status: ✅ PASS — LIVE-DATA SIGN-OFF (updated for production `asarak.com` / `api.asarak.com`).**

**Targets**
- Frontend: <https://asarak.com> (Cloudflare Workers)
- API: <https://api.asarak.com> (Railway + Neon PostgreSQL)

**Conventions**
- ✅ = verified pass in the 2026-11-21 live-data run · ☐ = optional manual check · ⚠️ = cosmetic (non-blocking)
- Viewports: Desktop 1280×720 · Mobile 390×844

---

## 1. Zero Mock Stores & Live KPIs — ✅ PASS

| # | Check | Result |
|---|-------|--------|
| 1.1 | `GET /api/v1/stats/overview` → `total_tracked: 300` | ✅ |
| 1.2 | Full feed sweep (6 pages × 50) → exactly 300 items: **sigma 100, 2b 100, btech 100** | ✅ |
| 1.3 | **Zero fictional stores** — `cairo_street`, `nile_threads`, `urban_eg` absent everywhere (feed, dropdown, detail, compare) | ✅ |
| 1.4 | Store dropdown on `/` = exactly `All stores / 2b / btech / sigma` | ✅ |
| 1.5 | KPI bar: 300 tracked · 137 Fake Discounts · 0 Genuine · 0 ATL · 0 Hikes · 27.1% Avg Fake Inflation | ✅ (0s are correct Day-1 semantics: no 60-day median history yet → real discount 0%, so any claimed ≥10% classifies FAKE_DISCOUNT) |
| 1.6 | Product images load from **real store CDNs**: `media.btech.com`, `api.sigma-computer.com`, `2b.com.eg` — 12/12 rendered, **0 broken**, **0 failed (≥400) network requests** | ✅ |
| 1.7 | Live product URLs in feed: `btech.com/en/p/<slug>?offering_id=…`, `2b.com.eg/en/<slug>.html`, `sigma-computer.com/en/item?id=…` | ✅ |

## 2. Live URL Search — ✅ PASS (API 8/8 + UI)

Backend matcher (`products.py`) now strips tracking params (`utm_*`, `fbclid`, `gclid`, …) and builds per-store deterministic keys (`sigma /en/item?id=`, `btech /en/p/<slug>` + `offering_id`, generic `ref`).

| # | Case | Result |
|---|------|--------|
| 2.1 | Clean live URL → `url_exact`, exactly 1 item, correct `product_sk` — verified for **sigma**, **2b**, **btech** | ✅ 3/3 |
| 2.2 | Same URL + `&utm_source=qa&fbclid=123` → `url_exact`, correct product — verified for all 3 stores | ✅ 3/3 |
| 2.3 | Unknown URL (`jumia.com.eg/catalog/?q=nonexistent…`) → `url_not_found`, total 0 | ✅ |
| 2.4 | Query-less/stripped URL → `url_not_found` (no loose fallback) | ✅ |
| 2.5 | UI: paste 2b URL with `?utm_source=qa&fbclid=123` → **single** correct "DIRECT LINK MATCH" (Tecno Spark Go 3, 2b, EGP 6,999) | ✅ |
| 2.6 | UI: unknown URL → "No matching products found." | ✅ |

## 3. Day-1 Product Detail & Chart — ✅ PASS

Verified on live products: 2b Tecno Spark Go 3 (`e5fe0433…`), sigma MEETION M360 (`a908cbbe…`), btech Sony MDR-ZX110AP (`9577a272…`).

| # | Check | Result |
|---|-------|--------|
| 3.1 | **Day-1 chart renders visible dots** (cyan current + violet median at EGP 6,999; amber claimed at 10,349) plotted at "21 Nov"; tooltip shows all three values | ✅ |
| 3.2 | **Day-1 tracking notice** chip: "Tracking started on 21 Nov — trend lines will build as daily snapshots accumulate." (desktop + mobile) | ✅ |
| 3.3 | **Specs clean — no raw internal UUIDs** anywhere (page text scanned for UUID regex: none). Values are store data: `Sku: M360` / `Sku: 59FA752552DA2C9D2A25`, `Fulfillment: Delivery, Pickup`, `Is best seller: Yes` | ✅ |
| 3.4 | **"Open at store"** links to the exact live store URL, `target="_blank"` + `rel="noopener noreferrer"` (2b → `2b.com.eg/en/tecno-spark-go-3….html`, sigma → `sigma-computer.com/en/item?id=…`, btech → `btech.com/en/p/…?offering_id=…`) | ✅ |
| 3.5 | Price tiles: current 6,999 = median 6,999 = ATL = ATH (Day-1 correct); claimed 10,349; claimed +32.4% vs real 0.0%; inflation callout 32.4% | ✅ |
| 3.6 | Alternatives panel: correct "No matched alternatives in other stores yet." for non-canonical products | ✅ |

## 4. Live Cross-Store Compare — ✅ PASS

| # | Check | Result |
|---|-------|--------|
| 4.1 | Exactly **6 live cross-store matches** rendered ("6 products") | ✅ |
| 4.2 | **Spread math verified for all 6** from API `listings_json`: `highest − lowest = price_spread_egp` and `pct = spread/lowest·100` — 6/6 exact (e.g. Galaxy A27: 19,610 btech → 22,449 2b, spread 2,839 = 14.5%; UI DOM text matches API digit-for-digit) | ✅ |
| 4.3 | **Deduplicated store listings** — no store appears twice within a match (6/6); one row per store, cheapest crowned, per-listing verdict + stock state correct | ✅ |
| 4.4 | Match discovery is sane: btech↔2b Samsung Galaxy A17/A27/A57 + Oppo Reno 16F ×2, sigma↔2b Lenovo IdeaPad — plausible same-SKU pairs across stores | ✅ |

## 5. RTL/AR, Mobile & Console Audit — ✅ PASS

| # | Check | Result |
|---|-------|--------|
| 5.1 | AR toggle flips `dir="rtl" lang="ar"` (verified in DOM); layouts mirror on home/detail/compare; Arabic font + Latin-digit prices; no missing-translation keys observed | ✅ |
| 5.2 | Mobile 390×844: **0 px horizontal overflow** on home EN, compare AR, product detail | ✅ |
| 5.3 | Mobile detail: price tiles stack, Day-1 notice + dot visible, chart fits | ✅ |
| 5.4 | **Console/network audit: 0 console errors, 0 failed (≥400) resources** across home EN desktop (incl. filter interaction), 3 product details, compare EN+AR, mobile AR compare, mobile EN home, mobile detail | ✅ |

## 6. Known cosmetic notes (P3, non-blocking)

1. **Spec-panel labels leak prettified internal attribute keys**: "Two b category" (2b), "Btech category" (btech), "Sigma category" (sigma). Values are clean store data; consider renaming to a neutral "Store category" or filtering in `AttributesPanel`.
2. **Day-1 KPI semantics**: Genuine/ATL/Presale = 0 by design until the second daily snapshot builds 60-day history — communicate so nobody files it as a bug.
3. Search dropdown glass background remains slightly translucent over bright content (pre-existing).
4. Render free-tier cold starts cause occasional connection resets between idle requests — environmental; the 8 s timeout + mock fallback absorbs it.

## 7. Historical sign-offs

| Date | Commit | Scope | Result |
|------|--------|-------|--------|
| 2026-11-21 (run 3) | `683555e` + `f68c8a1` | **Live scraped data (sigma/2b/btech, 300 products)** — full battery above | ✅ PASS |
| 2026-11-21 (run 2) | `79c31fe` | Mock-store smoke after URL/store-filter fixes | ✅ PASS (all 4 findings resolved) |
| 2026-11-21 (run 1) | `79c31fe` review | Initial QA — found P1-1/P1-2/P1-3/P2-1 (all subsequently fixed) | ⚠️ → fixed |

**Verdict: production is clean on 100% live data. No blockers for continued scraper/pipeline work.**
