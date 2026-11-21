/**
 * Price Truth Radar — Frozen API Contract types.
 *
 * Mirrors Section 5 of CONTRACTS.md 100% verbatim (field names, types, enums).
 * Field names MUST NOT be renamed — they map 1:1 to the FastAPI responses
 * and the `gold` schema serving tables.
 */

/* ------------------------------------------------------------------ */
/* Enums (CONTRACTS.md §3.1, §5.3, §5.6)                               */
/* ------------------------------------------------------------------ */

export type Category = "electronics" | "fashion" | "home_appliances";

export type DiscountVerdict =
  | "ALL_TIME_LOW"
  | "GENUINE_DEAL"
  | "FAKE_DISCOUNT"
  | "PRESALE_HIKE"
  | "NORMAL_PRICE";

export type FeedCategoryFilter = "all" | Category;

export type FeedSort =
  | "real_discount_pct_desc"
  | "claimed_vs_real_gap_desc"
  | "price_asc"
  | "price_desc";

/**
 * `attributes_json` is a JSONB payload whose shape differs by category:
 * - Electronics: { "ram_gb": 12, "storage_gb": 256, "warranty": "local" }
 * - Fashion:     { "available_sizes": ["M","L"], "total_sizes": 5 }
 */
export type ProductAttributes = Record<string, unknown>;

/* ------------------------------------------------------------------ */
/* Core product object (§5.3 feed item, reused in §5.4 and §5.5)       */
/* ------------------------------------------------------------------ */

export interface Product {
  product_sk: string;
  canonical_product_key: string | null;
  store_name: string;
  category: Category;
  sub_category: string;
  brand: string;
  product_title: string;
  product_url: string;
  image_url: string | null;
  attributes_json: ProductAttributes;
  current_price: number;
  claimed_original_price: number | null;
  rolling_60d_median: number;
  min_historical_price: number;
  max_historical_price: number;
  claimed_discount_pct: number;
  real_discount_pct: number;
  discount_verdict: DiscountVerdict;
  scarcity_flag: boolean;
  in_stock: boolean;
  last_updated_at: string;
}

/* ------------------------------------------------------------------ */
/* §5.1 Health Check                                                   */
/* ------------------------------------------------------------------ */

export interface HealthResponse {
  status: string;
  database: string;
}

/* ------------------------------------------------------------------ */
/* §5.2 Overview Stats                                                 */
/* ------------------------------------------------------------------ */

export interface StatsOverview {
  total_tracked: number;
  fake_discounts_today: number;
  genuine_deals_today: number;
  all_time_lows_today: number;
  presale_hikes_today: number;
  avg_fake_inflation_pct: number;
  last_pipeline_run_at: string;
  available_stores: string[];
}

/* ------------------------------------------------------------------ */
/* §5.3 Radar Feed                                                     */
/* ------------------------------------------------------------------ */

export interface RadarFeedParams {
  category: FeedCategoryFilter;
  verdict?: DiscountVerdict;
  store?: string;
  sort: FeedSort;
  page: number;
  limit: number;
}

export interface RadarFeedResponse {
  items: Product[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

/* ------------------------------------------------------------------ */
/* §5.4 Search & Direct Link Checker                                   */
/* ------------------------------------------------------------------ */

export interface SearchParams {
  q?: string;
  url?: string;
  limit?: number;
}

export interface SearchResponse {
  /** e.g. "url_exact" when matched by direct store link, text-search otherwise */
  match_type: string;
  items: Product[];
  total: number;
}

/* ------------------------------------------------------------------ */
/* §5.5 Product Detail, History & Alternatives                         */
/* ------------------------------------------------------------------ */

export interface PriceHistoryPoint {
  snapshot_date: string;
  price: number;
  claimed_original_price: number | null;
  rolling_60d_median: number;
  in_stock: boolean;
  available_sizes_count: number | null;
}

export interface AlternativeListing {
  product_sk: string;
  store_name: string;
  price: number;
  in_stock: boolean;
  product_url: string;
  discount_verdict: DiscountVerdict;
}

export interface ProductDetailResponse {
  product: Product;
  history: PriceHistoryPoint[];
  alternatives: AlternativeListing[];
}

/* ------------------------------------------------------------------ */
/* §5.6 Cross-Store Arbitrage Comparison                               */
/* ------------------------------------------------------------------ */

export interface CompareParams {
  category?: FeedCategoryFilter;
  min_spread_pct?: number;
  page: number;
  limit: number;
}

export interface CompareListing {
  product_sk: string;
  store_name: string;
  price: number;
  in_stock: boolean;
  product_url: string;
  discount_verdict: DiscountVerdict;
}

export interface CrossStoreMatch {
  canonical_product_key: string;
  product_title_clean: string;
  category: Category;
  brand: string;
  stores_count: number;
  lowest_price: number;
  lowest_price_store: string;
  highest_price: number;
  price_spread_egp: number;
  price_spread_pct: number;
  listings_json: CompareListing[];
}

export interface CompareResponse {
  items: CrossStoreMatch[];
  total: number;
  page: number;
  limit: number;
}
