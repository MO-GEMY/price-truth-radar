# Asarak (أسعارك) — Frontend UI

Bilingual (Arabic RTL / English LTR) Egypt price tracking and cross-store comparison platform (`https://asarak.com`).
Built with **Next.js 15 (App Router) + TypeScript + Tailwind CSS v4 + Recharts + Lucide React**, deployed on **Cloudflare Workers** via `@opennextjs/cloudflare`.

> **Frozen contract:** every API type mirrors Section 5 of the root `CONTRACTS.md` verbatim
> (field names, enums, response shapes). Do not rename fields. See `src/types/contract.ts`.

## Quick start

```bash
npm install
npm run dev        # http://localhost:3000
npm run build      # production Next.js build
npm run lint       # ESLint (next/core-web-vitals + next/typescript)
npm run cf:build   # OpenNext Cloudflare Workers build
npm run cf:deploy  # Deploy to Cloudflare Workers
```

## Connecting the backend

Production builds automatically use `.env.production` and `wrangler.jsonc`:

```
NEXT_PUBLIC_SITE_URL=https://asarak.com
NEXT_PUBLIC_API_URL=https://api.asarak.com
```

- **Configured** → every request hits the live endpoints directly:
  - `GET /api/v1/stats/overview` — KPI bar
  - `GET /api/v1/radar/feed` — filterable/sortable/paginated feed
  - `GET /api/v1/products/search` — text search **and** direct store-URL checker
  - `GET /api/v1/products/{product_sk}` — detail, daily history, alternatives
  - `GET /api/v1/compare` — cross-store arbitrage
- **Empty or unreachable** → the UI transparently serves the deterministic,
  contract-matching mock dataset (`src/lib/mockData.ts`) and shows a subtle
  amber **demo-mode banner**. Network errors/timeouts/5xx fall back to mock;
  4xx (e.g. unknown product → 404 page) are surfaced as-is.

## Pages

| Route | Description |
| :--- | :--- |
| `/` | Radar feed: KPI overview bar, search + direct-link checker, category/verdict/store/sort filters, pagination, product cards with verdict badges, claimed-vs-real discount chips, scarcity & out-of-stock warnings |
| `/products/[product_sk]` | Price truth page: full price breakdown, verdict explainer, interactive Recharts time series (`price` solid, `claimed_original_price` dashed, `rolling_60d_median` dotted), attributes (electronics specs / fashion size pills), cross-store alternatives table |
| `/compare` | Cross-store arbitrage: lowest/highest store per matched product, savings (`price_spread_egp`, `price_spread_pct`), expandable store listings |

## Design system

- Dark-first fintech/radar aesthetic, glass surfaces, radar-ring hero glow.
- Verdict badge colors: `FAKE_DISCOUNT` red · `PRESALE_HIKE` amber ·
  `ALL_TIME_LOW` emerald · `GENUINE_DEAL` teal · `NORMAL_PRICE` slate.
- Language toggle in the header (persisted in `localStorage`); `<html lang/dir>`
  flips to `rtl` with the IBM Plex Sans Arabic font; prices use EGP formatting
  with Latin digits (`ar-EG-u-nu-latn`) for readability.

## Layout

```
src/
├── app/                    # App Router pages + layout + icon
│   ├── page.tsx            # Radar feed
│   ├── products/[product_sk]/page.tsx
│   └── compare/page.tsx
├── components/             # Header, KPI bar, search, filters, cards, chart, tables…
├── lib/
│   ├── api.ts              # Typed client + mock fallback (reads NEXT_PUBLIC_API_URL)
│   ├── mockData.ts         # Deterministic contract-exact mock dataset
│   ├── i18n.tsx            # Language provider (EN/AR, RTL)
│   ├── translations.ts     # UI dictionary
│   └── format.ts           # EGP price / % / date formatters
└── types/
    └── contract.ts         # CONTRACTS.md §5 types (verbatim)
```

**Boundary:** this app only writes inside `web_app/frontend/`; it never touches the
database, the backend, or the contracts.
