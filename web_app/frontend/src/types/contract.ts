/**
 * Asarak (أسعارك) — Frozen API Contract types.
 *
 * Mirrors Section 5 of CONTRACTS.md 100% verbatim (field names, types, enums).
 * Field names MUST NOT be renamed — they map 1:1 to the FastAPI responses
 * and the `gold` schema serving tables.
 */

/* ------------------------------------------------------------------ */
/* Enums (CONTRACTS.md §3.1, §5.3, §5.6)                               */
/* ------------------------------------------------------------------ */

export type Category =
  | "electronics"
  | "home_appliances"
  | "home_furniture"
  | "fashion"
  | "beauty"
  | "groceries"
  | "health"
  | "sports"
  | "pet_care"
  | "baby_kids";

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
 * - Groceries:   { "pack_size": "1L", "net_weight_g": 500, "net_volume_ml": 1000 }
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
  /** Unit price for groceries (shrinkflation transparency) — optional until the backend emits it. */
  unit_price_egp?: number | null;
  unit_price_unit?: "kg" | "L" | string | null;
  /** Multi-variant rollup fields from gold.mart_product_verdicts. */
  parent_product_key?: string | null;
  variant_label?: string | null;
  variant_count?: number;
  has_multiple_variants?: boolean;
  min_variant_price?: number | null;
  max_variant_price?: number | null;
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
  category_counts?: Record<string, number>;
}

export interface CategoryFacetItem {
  slug: Category;
  label_en: string;
  label_ar: string;
  product_count: number;
  compare_count: number;
}

export interface CategoriesResponse {
  items: CategoryFacetItem[];
  total_products: number;
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
  /** Optional groceries unit price (shrinkflation transparency). */
  unit_price_egp?: number | null;
  unit_price_unit?: "kg" | "L" | string | null;
}

export interface ProductVariant {
  product_sk: string;
  variant_label: string | null;
  title: string;
  current_price: number;
  claimed_original_price: number | null;
  verdict: DiscountVerdict;
  in_stock: boolean;
  product_url: string;
}

export interface SimilarAlternative {
  product_sk: string;
  title: string;
  store_name: string;
  current_price: number;
  price_diff_egp: number;
  price_diff_pct: number;
  verdict: DiscountVerdict;
  in_stock: boolean;
  image_url: string | null;
  product_url: string;
  similarity_reason: string;
  is_exact_match: false;
}

export interface ProductDetailResponse {
  product: Product;
  history: PriceHistoryPoint[];
  alternatives: AlternativeListing[];
  similar_alternatives?: SimilarAlternative[];
  variants?: ProductVariant[];
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
  /** Optional groceries unit price (shrinkflation transparency). */
  unit_price_egp?: number | null;
  unit_price_unit?: "kg" | "L" | string | null;
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

/* ------------------------------------------------------------------ */
/* Scandals vs Real Deals radar (launch page)                          */
/* ------------------------------------------------------------------ */

/** The native highlights payload and the feed fields accepted by its adapter. */
export interface HighlightItem {
  id?: string;
  title?: string;
  product_key?: string;
  baseline_price?: number | null;
  rolling_60d_median?: number | null;
  claimed_old_price?: number | null;
  real_drop_pct?: number;
  verdict?: string;
  last_updated_at?: string;
  product_sk?: string;
  canonical_product_key?: string | null;
  product_title?: string;
  store_name?: string;
  category?: string;
  sub_category?: string;
  brand?: string;
  image_url?: string | null;
  current_price?: number;
  claimed_original_price?: number | null;
  claimed_discount_pct?: number;
  real_discount_pct?: number;
  discount_verdict?: string;
  in_stock?: boolean;
  parent_product_key?: string | null;
  variant_label?: string | null;
  variant_count?: number;
  has_multiple_variants?: boolean;
  min_variant_price?: number | null;
  max_variant_price?: number | null;
}

export interface RadarHighlights {
  updated_at?: string | null;
  biggest_scandals: HighlightItem[];
  best_real_deals: HighlightItem[];
}

/* ------------------------------------------------------------------ */
/* Price-drop alerts ("نبّهني لما السعر ينزل")                          */
/* ------------------------------------------------------------------ */

export type AlertChannel = "telegram" | "email";

export interface PriceAlertRequest {
  product_key: string;
  product_title: string;
  store_name: string;
  target_price: number;
  channel: AlertChannel;
  destination: string;
}

export interface PriceAlertResponse {
  id: string;
  status: string;
  message: string;
}
