# Price Truth Radar — Frozen Architecture & API Contracts

> **STRICT RULE FOR ALL AI AGENTS (Antigravity & Z.ai):**
> This file is the Single Source of Truth. Do NOT rename any table, column, enum value, endpoint path, or JSON field defined here without explicit owner approval.

---

## 1. Agent Ownership & Git Branching Rules

| Track | Owner | Branch | Allowed Directories | Strictly Forbidden |
| :--- | :--- | :--- | :--- | :--- |
| **Data Platform & Backend** | Antigravity | `feat/data-platform` | `data_platform/`, `web_app/backend/`, `.github/workflows/` | Modifying `web_app/frontend/` or altering this contract |
| **Frontend UI/UX** | Z.ai | `feat/frontend-ui` | `web_app/frontend/` | Writing SQL, connecting directly to DB, or altering API response shapes |
| **Frozen Contracts** | Repo Owner | `main` | `CONTRACTS.md` | Unapproved modifications by any agent |

---

## 2. Cloud Infrastructure & Security Boundaries

* **Database:** Neon PostgreSQL (`neondb`), schemas: `raw`, `silver`, `gold`.
* **Write Role (Data Platform / dbt / GitHub Actions):** `neondb_owner` via `DATABASE_URL_ADMIN` (direct non-pooled connection).
* **Read-Only Role (FastAPI Backend on Render):** `add_readonly` via `DATABASE_URL_READONLY` (has `SELECT` privilege on `gold` schema ONLY).
* **Backend Host:** Render (`web_app/backend`) with `GET /health` keep-alive ping.
* **Frontend Host:** Vercel (`web_app/frontend`), configured with `NEXT_PUBLIC_API_URL`.

---

## 3. Gold Layer Database Contract (PostgreSQL `gold` schema)

FastAPI must ONLY query tables in the `gold` schema. No heavy analytical calculations are allowed in the FastAPI layer.

### 3.1 `gold.mart_product_verdicts`
Primary serving table for search, radar feed, and product headers.

| Column | Type | Constraints / Notes |
| :--- | :--- | :--- |
| `product_sk` | `VARCHAR` | Primary Key (MD5 surrogate key of `store_name` + `external_id`) |
| `canonical_product_key` | `VARCHAR` | Nullable. Normalized match key across stores (e.g., `samsung_s24_ultra_256gb_12gb`) |
| `store_name` | `VARCHAR` | Not Null. Lowercase slug (e.g., `btech`, `sigma`, `local_brand_x`) |
| `category` | `VARCHAR` | Enum: `'electronics'`, `'fashion'` |
| `sub_category` | `VARCHAR` | e.g., `'smartphones'`, `'laptops'`, `'monitors'`, `'hoodies'`, `'sneakers'` |
| `brand` | `VARCHAR` | Normalized brand name |
| `product_title` | `TEXT` | Cleaned display title |
| `product_url` | `TEXT` | Direct store URL |
| `image_url` | `TEXT` | Nullable product thumbnail URL |
| `attributes_json` | `JSONB` | Electronics: `{"ram_gb": 12, "storage_gb": 256, "warranty": "local"}` / Fashion: `{"available_sizes": ["M","L"], "total_sizes": 5}` |
| `current_price` | `NUMERIC(12,2)` | Current price in EGP |
| `claimed_original_price` | `NUMERIC(12,2)` | Nullable strikethrough price claimed by store |
| `rolling_60d_median` | `NUMERIC(12,2)` | Median historical price over last 60 days |
| `min_historical_price` | `NUMERIC(12,2)` | Minimum observed historical price |
| `max_historical_price` | `NUMERIC(12,2)` | Maximum observed historical price |
| `claimed_discount_pct` | `NUMERIC(5,2)` | Store's advertised discount percentage (0 if none) |
| `real_discount_pct` | `NUMERIC(5,2)` | Actual discount vs `rolling_60d_median` (can be negative if inflated) |
| `discount_verdict` | `VARCHAR` | Enum: `'ALL_TIME_LOW'`, `'GENUINE_DEAL'`, `'FAKE_DISCOUNT'`, `'PRESALE_HIKE'`, `'NORMAL_PRICE'` |
| `scarcity_flag` | `BOOLEAN` | `TRUE` if fashion item has less than 25% of sizes in stock, else `FALSE` |
| `in_stock` | `BOOLEAN` | Current availability |
| `last_updated_at` | `TIMESTAMP` | UTC timestamp of latest snapshot |

### 3.2 `gold.fct_price_history`
Daily time-series built from dbt Snapshots (SCD Type 2) to render price charts.

| Column | Type | Notes |
| :--- | :--- | :--- |
| `product_sk` | `VARCHAR` | Foreign key to `gold.mart_product_verdicts.product_sk` |
| `snapshot_date` | `DATE` | Daily date grain |
| `price` | `NUMERIC(12,2)` | Effective price on that date |
| `claimed_original_price` | `NUMERIC(12,2)` | Nullable strikethrough price on that date |
| `rolling_60d_median` | `NUMERIC(12,2)` | Rolling 60-day median as of that date |
| `in_stock` | `BOOLEAN` | Stock status |
| `available_sizes_count` | `INTEGER` | Nullable (used for fashion items) |

### 3.3 `gold.mart_cross_store_matches`
Cross-store arbitrage comparison for matched electronics products (`stores_count >= 2`).

| Column | Type | Notes |
| :--- | :--- | :--- |
| `canonical_product_key` | `VARCHAR` | Primary Key |
| `product_title_clean` | `TEXT` | Clean unified title |
| `category` | `VARCHAR` | `'electronics'` or `'fashion'` |
| `brand` | `VARCHAR` | Normalized brand |
| `stores_count` | `INTEGER` | Number of stores carrying this item |
| `lowest_price` | `NUMERIC(12,2)` | Lowest current price in EGP |
| `lowest_price_store` | `VARCHAR` | Store offering the lowest price |
| `highest_price` | `NUMERIC(12,2)` | Highest current price in EGP |
| `price_spread_egp` | `NUMERIC(12,2)` | `highest_price - lowest_price` |
| `price_spread_pct` | `NUMERIC(5,2)` | `((highest_price - lowest_price) / lowest_price) * 100` |
| `listings_json` | `JSONB` | Array of `{"product_sk", "store_name", "price", "in_stock", "product_url", "discount_verdict"}` |

---

## 4. Verdict Classification Logic (Implemented in dbt)

Evaluate in strict priority order:
1. **`FAKE_DISCOUNT`**: `claimed_discount_pct >= 10` AND `real_discount_pct < 3`
2. **`ALL_TIME_LOW`**: `current_price <= min_historical_price` AND `history_days >= 14` AND `real_discount_pct >= 5`
3. **`GENUINE_DEAL`**: `real_discount_pct >= 10`
4. **`PRESALE_HIKE`**: Recent 14-day price increased `>= 12%` compared to prior 45-day median
5. **`NORMAL_PRICE`**: All other cases

---

## 5. REST API Contract (FastAPI Serving Layer)

Base path: `/api/v1` (except `/health`). CORS must allow frontend origins (`*` in dev, Vercel domain in prod).

### 5.1 Health Check (UptimeRobot Keep-Alive)
* `GET /health`
* Response `200 OK`:
```json
{ "status": "ok", "database": "connected" }
```

### 5.2 Overview Stats
* `GET /api/v1/stats/overview`
* Response `200 OK`:
```json
{
  "total_tracked": 100,
  "fake_discounts_today": 24,
  "genuine_deals_today": 18,
  "all_time_lows_today": 9,
  "presale_hikes_today": 11,
  "avg_fake_inflation_pct": 16.4,
  "last_pipeline_run_at": "2026-11-21T03:00:00Z"
}
```

### 5.3 Radar Feed (Paginated & Filterable)
* `GET /api/v1/radar/feed`
* Query Params:
  * `category`: `all` | `electronics` | `fashion` (default `all`)
  * `verdict`: optional (`ALL_TIME_LOW`, `GENUINE_DEAL`, `FAKE_DISCOUNT`, `PRESALE_HIKE`, `NORMAL_PRICE`)
  * `store`: optional store slug
  * `sort`: `real_discount_pct_desc` | `claimed_vs_real_gap_desc` | `price_asc` | `price_desc` (default `claimed_vs_real_gap_desc`)
  * `page`: integer >= 1 (default `1`)
  * `limit`: integer 1..50 (default `20`)
* Response `200 OK`:
```json
{
  "items": [
    {
      "product_sk": "a1b2c3d4",
      "canonical_product_key": "samsung_s24_ultra_256gb_12gb",
      "store_name": "btech",
      "category": "electronics",
      "sub_category": "smartphones",
      "brand": "Samsung",
      "product_title": "Samsung Galaxy S24 Ultra 256GB 12GB RAM",
      "product_url": "[https://example.com/p/1](https://example.com/p/1)",
      "image_url": "[https://example.com/img/1.jpg](https://example.com/img/1.jpg)",
      "attributes_json": { "ram_gb": 12, "storage_gb": 256 },
      "current_price": 54999.0,
      "claimed_original_price": 65000.0,
      "rolling_60d_median": 53500.0,
      "min_historical_price": 51000.0,
      "max_historical_price": 65000.0,
      "claimed_discount_pct": 15.39,
      "real_discount_pct": -2.80,
      "discount_verdict": "FAKE_DISCOUNT",
      "scarcity_flag": false,
      "in_stock": true,
      "last_updated_at": "2026-11-21T03:00:00Z"
    }
  ],
  "total": 100,
  "page": 1,
  "limit": 20,
  "total_pages": 5
}
```

### 5.4 Search & Direct Link Checker
* `GET /api/v1/products/search?q={query}&url={optional_url}&limit=20`
* Behavior: If `url` is provided, attempt exact/normalized URL match first; otherwise perform case-insensitive search on `product_title` and `brand`.
* Response `200 OK`:
```json
{
  "match_type": "url_exact",
  "items": [ /* Same product object schema as /radar/feed items */ ],
  "total": 1
}
```

### 5.5 Product Detail, History & Alternatives
* `GET /api/v1/products/{product_sk}`
* Response `200 OK`:
```json
{
  "product": { /* Same product object schema as /radar/feed item */ },
  "history": [
    {
      "snapshot_date": "2026-10-01",
      "price": 53500.0,
      "claimed_original_price": 53500.0,
      "rolling_60d_median": 53500.0,
      "in_stock": true,
      "available_sizes_count": null
    }
  ],
  "alternatives": [
    {
      "product_sk": "e5f6g7h8",
      "store_name": "sigma",
      "price": 51900.0,
      "in_stock": true,
      "product_url": "[https://example.com/p/2](https://example.com/p/2)",
      "discount_verdict": "GENUINE_DEAL"
    }
  ]
}
```
* Returns `404 Not Found` if `product_sk` does not exist.

### 5.6 Cross-Store Arbitrage Comparison
* `GET /api/v1/compare?category=electronics&min_spread_pct=5&page=1&limit=20`
* Response `200 OK`:
```json
{
  "items": [
    {
      "canonical_product_key": "samsung_s24_ultra_256gb_12gb",
      "product_title_clean": "Samsung Galaxy S24 Ultra 256GB 12GB",
      "category": "electronics",
      "brand": "Samsung",
      "stores_count": 3,
      "lowest_price": 51900.0,
      "lowest_price_store": "sigma",
      "highest_price": 56500.0,
      "price_spread_egp": 4600.0,
      "price_spread_pct": 8.86,
      "listings_json": [
        {
          "product_sk": "e5f6g7h8",
          "store_name": "sigma",
          "price": 51900.0,
          "in_stock": true,
          "product_url": "[https://example.com/p/2](https://example.com/p/2)",
          "discount_verdict": "GENUINE_DEAL"
        }
      ]
    }
  ],
  "total": 15,
  "page": 1,
  "limit": 20
}
```
