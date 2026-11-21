# Price Truth Radar — QA & Smoke Test Checklist

**Status: ✅ PASS — re-run against production on 2026-11-21 after commit `79c31fe` (fix(qa): resolve URL search matching, B.TECH/Sigma URLs, image fallback, and store filter). All 4 previous findings verified resolved live. Remaining items are cosmetic (P3).**

**Targets**
- Frontend: <https://price-truth-radar.vercel.app>
- API: <https://price-truth-radar-api.onrender.com> (free tier → expect ~30–60 s cold starts; occasional connection resets between idle periods are environmental, not app bugs)

**Conventions**
- ✅ = verified pass in the 2026-11-21 re-run · ☐ = optional manual check · ⚠️ = known cosmetic issue (non-blocking)
- Viewports: Desktop 1280×720 · Mobile 390×844 (DSC/iPhone-class)

---

## 0. Preconditions

| # | Check | Status |
|---|-------|--------|
| 0.1 | `NEXT_PUBLIC_API_URL=https://price-truth-radar-api.onrender.com` set on Vercel; **no** amber "mock data" banner on any page | ✅ |
| 0.2 | `GET /api/v1/stats/overview` returns 200 with `total_tracked: 100`, `avg_fake_inflation_pct: 22.7` | ✅ |
| 0.3 | Neon raw + dbt gold rebuilt on the fixed seed (feed `product_url`s use `btech.com/en/s?q=`, `sigma-computer.com/en/search?controller=search&s=` templates) | ✅ |
| 0.4 | Deployed backend matches `main` commit `79c31fe` (exact-URL + `(host, ref)` matching) | ✅ |

## 1. API smoke

| # | Request | Expected | Status |
|---|---------|----------|--------|
| 1.1 | `GET /api/v1/stats/overview` | 200, all 5 verdict counts present | ✅ |
| 1.2 | `GET /api/v1/radar/feed?limit=50&page=1&sort=price_asc` (+ page 2) | 200; all 7 stores represented across the sweep | ✅ |
| 1.3 | Same `product_sk` from feed → `GET /api/v1/products/{sk}` | Product fields identical to feed item; `history` has 60 daily rows | ✅ |
| 1.4 | `GET /api/v1/products/search?q=samsung&limit=6` | `match_type: "text_search"` | ✅ |
| 1.5 | `search?url=<exact stored product_url>` for btech / sigma / cairo_street | **exactly 1 item — the correct product**, `url_exact` | ✅ |
| 1.6 | Same URL + `&utm_source=qa&fbclid=xyz123` | correct product via deterministic `(host, ref)` match, `url_exact` | ✅ |
| 1.7 | Same URL with `http://` + `www.` scheme/host variants | still `url_exact` (normalization) | ✅ |
| 1.8 | `search?url=<search-page URL without query>` (e.g. `https://btech.com/en/s`) | `url_not_found`, total 0 — no loose path-only fallback | ✅ |
| 1.9 | `GET /api/v1/compare?limit=10` | Electronics-only canonical groups, `stores_count ≥ 2`, spread math consistent | ✅ |
| 1.10 | `GET /api/v1/compare?category=fashion` | Empty result (fashion has no canonical keys) — UI shows empty state | ✅ (API) / ☐ (UI state) |

## 2. Home `/`

| # | Check | Status |
|---|-------|--------|
| 2.1 | Hero, KPI bar (6 tiles), filters, 12-card feed, pagination render; zero console errors / zero failed network requests | ✅ |
| 2.2 | Every card image loads (Unsplash); graceful fallback path exists (`ProductImage` component) | ✅ |
| 2.3 | Verdict badges color-coded correctly | ✅ |
| 2.4 | Category buttons filter the feed (Electronics clicked during test) and reset to page 1 | ✅ |
| 2.5 | **Store dropdown lists all 7 stores** — `2b, btech, cairo_street, dubai_phone, nile_threads, sigma, urban_eg` (P2-1 fixed via all-page sweep) | ✅ |
| 2.6 | Pagination: ellipsis window, page count matches `total_pages` (9 pages × 12/page = 100) | ✅ |
| 2.7 | Out-of-stock card shows greyed image + "Out of stock"; low-stock shows flame chip | ✅ |

## 3. Search / direct-link checker (home hero)

| # | Check | Status |
|---|-------|--------|
| 3.1 | Paste exact stored URL (btech Anker Q45) with extra tracking params → **single** correct "DIRECT LINK MATCH" result in UI | ✅ |
| 3.2 | Paste query-less URL (`https://btech.com/en/s`) → "No matching products found." — no misleading matches | ✅ |
| 3.3 | Paste untracked URL (`https://example.com/x`) → "No results" state, no mock-data leak | ☐ |
| 3.4 | Text query `"Galaxy S24"` → text-match dropdown, click navigates to detail page | ☐ |
| 3.5 | Esc/click-outside closes dropdown; clear (×) resets state | ☐ |

## 4. Product detail `/products/[product_sk]`

Verified with `1f2c4cfab383c496371ca1a8cc2ab435` (FAKE_DISCOUNT, btech Anker Q45).

| # | Check | Status |
|---|-------|--------|
| 4.1 | Image, store badge, verdict badge, "Matched across stores" chip render | ✅ |
| 4.2 | 7 price tiles populated (current 6,850 / median 6,800 / ATL 6,600 / ATH 6,850 / claimed 9,100 / +24.7% / −0.7%) | ✅ |
| 4.3 | Chart: 3 lines (price cyan / claimed dashed amber / median dotted violet), 60 daily points, axes render | ✅ |
| 4.4 | Verdict explainer matches the badge verdict; inflation callout shows 24.7% | ✅ |
| 4.5 | Specs panel (electronics): ANC/Warranty/Battery rows | ✅ |
| 4.6 | Cross-store alternatives: dubai_phone cheapest (EGP 6,250) crowned, "View listing" + external-link buttons | ✅ |
| 4.7 | **"Open at store"** lands on a live page — btech `/en/s?q=…` → 200 with real results | ✅ |
| 4.8 | Unknown SK (`/products/abc123`) → friendly not-found card | ☐ |

## 5. Compare `/compare`

| # | Check | Status |
|---|-------|--------|
| 5.1 | 18 match cards: lowest/highest/gap tiles, stores count, "Save EGP …" chip | ✅ |
| 5.2 | Expand "Store listings": cheapest crowned, verdict badges, stock state, working "View product" + external links (sigma/dubai_phone/btech rows verified) | ✅ |
| 5.3 | Category + min-spread filters render and apply | ☐ (render verified; filter clicks ☐) |

## 6. EN / AR switching

| # | Check | Status |
|---|-------|--------|
| 6.1 | Toggle flips `<html lang="ar" dir="rtl">` live; verified values `dir:"rtl" lang:"ar"` in DOM | ✅ |
| 6.2 | Arabic font applied; digits stay Latin (`ar-EG-u-nu-latn`); no missing-translation keys observed on any page | ✅ |
| 6.3 | Layout mirrors on home, detail, and compare (badges/chips/pagination flip sides) | ✅ |
| 6.4 | Choice persists across reloads and routes | ✅ |
| 6.5 | Known/accepted: price chart remains LTR in AR mode (standard for financial charts) | ✅ |

## 7. Narrow / mobile viewports (390×844)

| # | Check | Status |
|---|-------|--------|
| 7.1 | **0 px horizontal overflow** verified on home EN, compare AR/EN | ✅ |
| 7.2 | Header collapses to icons + language toggle | ✅ |
| 7.3 | Feed grid single-column; images and chips fit | ✅ |
| 7.4 | Compare filters stack vertically; match cards stack | ✅ |
| 7.5 | Detail page: price tiles 2-col, chart fits, alternatives table scrolls horizontally | ✅ |
| 7.6 | Tap targets ≥ 40 px | ☐ |

## 8. External store URL spot checks (seed templates, all 7 verified)

| Store | Live template | curl (bot UA) | Real browser |
|-------|--------------|---------------|--------------|
| btech | `https://btech.com/en/s?q={query}&ref={slug}` | **200** (search results render) | ✅ |
| sigma | `https://www.sigma-computer.com/en/search?controller=search&s={query}&ref={slug}` | **200** | ✅ |
| 2b | `https://2b.com.eg/en/catalogsearch/result/?q={query}&ref={slug}` | **200** | ✅ |
| nile_threads | `https://www.amazon.eg/s?k={query}&ref={slug}` | 503 bot-block | ✅ renders search page (0 results for fictional product — expected, no error page) |
| cairo_street | `https://www.jumia.com.eg/catalog/?q={query}&ref={slug}` | 403 bot-block | ✅ renders search page with query (newsletter popup is Jumia-standard) |
| urban_eg | `https://www.noon.com/egypt-en/search/?q={query}&ref={slug}` | TLS bot-block (curl 000) | ✅ renders search page ("We couldn't find what you were looking for" — expected, no 404) |
| dubai_phone | `https://dubaiphone.net/?s={query}&post_type=product&ref={slug}` | 429 rate-limit | ✅ renders (slow site; redirects to www host) |

> Note: `cairo_street`/`nile_threads`/`urban_eg` map fictional stores to Jumia/Amazon.eg/Noon search pages; 0-result searches are the designed behavior for mock data on real marketplaces. Store badge and linked site brand intentionally differ.

## 9. Console / network error audit

| Phase | console errors | failed resources (≥400) |
|-------|----------------|--------------------------|
| Home desktop EN (incl. filter interaction, store sweep) | 0 | 0 |
| Detail page (btech Anker Q45, chart + alternatives) | 0 | 0 |
| Compare desktop EN (listings expanded) | 0 | 0 |
| Compare AR RTL + mobile 390×844 | 0 | 0 |
| Home mobile 390×844 EN | 0 | 0 |

## 10. Findings disposition (2026-11-21 re-run)

| ID | Finding (previous run) | Disposition |
|----|------------------------|-------------|
| P1-1 | Deployed API ran old `products.py`; URL checker returned wrong products for new-format URLs | **RESOLVED** — commit `79c31fe` deployed; exact normalized match verified live (API + UI) |
| P1-2 | Stripped-URL fallback returned arbitrary same-store products | **RESOLVED** — replaced by deterministic `(host, ref)` match; query-less URLs now `url_not_found` (API) / "No matching products found." (UI) |
| P1-3 | Seed templates for btech (`/en/catalogsearch/result/`) and sigma (`/search?search=`) 404 | **RESOLVED** — templates now `btech.com/en/s?q=` and `sigma-computer.com/en/search?controller=search&s=`; DB re-seeded + gold rebuilt; both 200 |
| P2-1 | Store dropdown missing `sigma` | **RESOLVED** — store options now sweep all feed pages; all 7 stores listed |
| P3-2 | Mock search normalization diverged from backend | **RESOLVED** — mock now uses shared `parseUrlParts` (host + ref) semantics |
| P3-1 | Search dropdown glass background too transparent over bright content | **OPEN (cosmetic)** — `SearchBar.tsx:140` still uses `glass`; readable but content behind shows through |
| — | Render free-tier cold starts cause intermittent connection resets between idle requests | Environmental; the frontend's 8 s timeout + mock fallback handles it; not an app bug |

**Verdict: production is clean. No blockers remaining before scraper work.**
