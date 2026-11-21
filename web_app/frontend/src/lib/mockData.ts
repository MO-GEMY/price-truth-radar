/**
 * Local mock dataset — activated ONLY when `NEXT_PUBLIC_API_URL` is empty or
 * the live FastAPI backend is unreachable. Shapes match CONTRACTS.md §5
 * responses exactly, and verdicts follow the §4 classification priority.
 *
 * Fully deterministic (seeded PRNG) so pagination/search results are stable.
 */

import type {
  AlternativeListing,
  Category,
  CompareListing,
  CompareParams,
  CompareResponse,
  DiscountVerdict,
  PriceHistoryPoint,
  Product,
  ProductAttributes,
  RadarFeedParams,
  RadarFeedResponse,
  SearchParams,
  SearchResponse,
  StatsOverview,
} from "@/types/contract";

const MOCK_NOW = "2026-11-21T03:00:00Z";
const HISTORY_DAYS = 75;

/* ------------------------------------------------------------------ */
/* Deterministic PRNG helpers                                          */
/* ------------------------------------------------------------------ */

function hashSeed(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function fakeSk(store: string, slug: string): string {
  return hashSeed(`${store}::${slug}`).toString(16).padStart(8, "0");
}

/* ------------------------------------------------------------------ */
/* Price-history pattern ratios (relative to the CURRENT final price)   */
/* ------------------------------------------------------------------ */

type Pattern = "fake" | "atl" | "genuine" | "hike" | "normal";

/**
 * CONTRACTS.md §4 classification logic, in strict priority order.
 * `history_days` = number of daily snapshots available.
 */
function classifyVerdict(input: {
  claimed_discount_pct: number;
  real_discount_pct: number;
  current_price: number;
  min_historical_price: number;
  history_days: number;
  recent_hike_pct: number;
}): DiscountVerdict {
  const {
    claimed_discount_pct,
    real_discount_pct,
    current_price,
    min_historical_price,
    history_days,
    recent_hike_pct,
  } = input;
  // 1. FAKE_DISCOUNT: claimed >= 10 AND real < 3
  if (claimed_discount_pct >= 10 && real_discount_pct < 3) return "FAKE_DISCOUNT";
  // 2. ALL_TIME_LOW: current <= min AND history >= 14 days AND real >= 5
  if (current_price <= min_historical_price && history_days >= 14 && real_discount_pct >= 5)
    return "ALL_TIME_LOW";
  // 3. GENUINE_DEAL: real >= 10
  if (real_discount_pct >= 10) return "GENUINE_DEAL";
  // 4. PRESALE_HIKE: recent 14-day price up >= 12% vs prior 45-day median
  if (recent_hike_pct >= 12) return "PRESALE_HIKE";
  // 5. Everything else
  return "NORMAL_PRICE";
}

function buildPriceRatios(pattern: Pattern, rnd: () => number, days: number): number[] {
  const ratios: number[] = [];
  const noise = (amp: number) => 1 + (rnd() * 2 - 1) * amp;
  for (let i = 0; i < days; i++) {
    let ratio: number;
    switch (pattern) {
      case "fake":
        // Price hugs its median → big claimed strike-through is cosmetic.
        ratio = noise(0.012);
        break;
      case "atl":
        // Stable for two months, then drops to an all-time low at the end.
        ratio = i >= days - 3 ? 1 : 1.09 + rnd() * 0.03;
        break;
      case "genuine":
        // Fluctuating, one historical dip, recent plateau clearly below the median.
        if (i < 16) ratio = 1.16 + rnd() * 0.02;
        else if (i < 32) ratio = 0.94 + rnd() * 0.015;
        else if (i < days - 10) ratio = 1.16 + rnd() * 0.02;
        else ratio = 1;
        break;
      case "hike": {
        // Flat baseline, then a ramp in the last 14 days. Ratios are relative
        // to the CURRENT (hiked) price, so the baseline sits ~14% below it and
        // the final-day override to 1 keeps the hike intact.
        if (i < days - 14) {
          ratio = (1 / 1.16) * noise(0.01);
        } else {
          const t = (i - (days - 14)) / 13;
          ratio = 1 / 1.16 + (1 - 1 / 1.16) * (0.3 + 0.7 * t * t);
        }
        break;
      }
      case "normal":
      default:
        // Smooth oscillation inside its normal band.
        ratio = 1 + 0.03 * Math.sin(i / 6 + rnd() * 6.28) + (rnd() - 0.5) * 0.008;
        break;
    }
    ratios.push(ratio);
  }
  ratios[days - 1] = 1; // The last snapshot IS the current price.
  return ratios;
}

/* ------------------------------------------------------------------ */
/* Product specs                                                       */
/* ------------------------------------------------------------------ */

interface ProductSpec {
  slug: string;
  store: string;
  category: Category;
  sub_category: string;
  brand: string;
  title: string;
  clean_title?: string;
  canonical: string | null;
  pattern: Pattern;
  /** Final current price in EGP (exactly what the UI/API will report). */
  price: number;
  /** Claimed strike-through price (fake-discount patterns). */
  claimed?: number;
  attributes: ProductAttributes;
  in_stock?: boolean;
}

const SPECS: ProductSpec[] = [
  // ------------------------- Electronics ------------------------- //
  {
    slug: "samsung-galaxy-s24-ultra-256gb",
    store: "btech",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Samsung",
    title: "Samsung Galaxy S24 Ultra 256GB 12GB RAM",
    clean_title: "Samsung Galaxy S24 Ultra 256GB",
    canonical: "samsung_s24_ultra_256gb_12gb",
    pattern: "fake",
    price: 54999.0,
    claimed: 65000.0,
    attributes: { ram_gb: 12, storage_gb: 256, warranty: "local" },
  },
  {
    slug: "samsung-galaxy-s24-ultra-256gb-sgm",
    store: "sigma",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Samsung",
    title: "Samsung Galaxy S24 Ultra 256GB 12GB RAM",
    clean_title: "Samsung Galaxy S24 Ultra 256GB",
    canonical: "samsung_s24_ultra_256gb_12gb",
    pattern: "genuine",
    price: 51900.0,
    attributes: { ram_gb: 12, storage_gb: 256, warranty: "local" },
  },
  {
    slug: "samsung-galaxy-s24-ultra-256gb-egc",
    store: "egycart",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Samsung",
    title: "Samsung Galaxy S24 Ultra 256GB 12GB RAM",
    clean_title: "Samsung Galaxy S24 Ultra 256GB",
    canonical: "samsung_s24_ultra_256gb_12gb",
    pattern: "normal",
    price: 56500.0,
    attributes: { ram_gb: 12, storage_gb: 256, warranty: "international" },
  },
  {
    slug: "apple-iphone-15-pro-256gb",
    store: "btech",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Apple",
    title: "Apple iPhone 15 Pro 256GB Natural Titanium",
    clean_title: "Apple iPhone 15 Pro 256GB",
    canonical: "iphone_15_pro_256gb",
    pattern: "atl",
    price: 48999.0,
    attributes: { storage_gb: 256, warranty: "international" },
  },
  {
    slug: "apple-iphone-15-pro-256gb-egc",
    store: "egycart",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Apple",
    title: "Apple iPhone 15 Pro 256GB Blue Titanium",
    clean_title: "Apple iPhone 15 Pro 256GB",
    canonical: "iphone_15_pro_256gb",
    pattern: "normal",
    price: 51500.0,
    attributes: { storage_gb: 256, warranty: "local" },
  },
  {
    slug: "xiaomi-redmi-note-13-pro-256gb",
    store: "sigma",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Xiaomi",
    title: "Xiaomi Redmi Note 13 Pro 256GB 8GB RAM",
    clean_title: "Xiaomi Redmi Note 13 Pro 256GB",
    canonical: "redmi_note_13_pro_256gb",
    pattern: "genuine",
    price: 11499.0,
    attributes: { ram_gb: 8, storage_gb: 256, warranty: "local" },
  },
  {
    slug: "xiaomi-redmi-note-13-pro-256gb-egc",
    store: "egycart",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Xiaomi",
    title: "Xiaomi Redmi Note 13 Pro 256GB 8GB RAM",
    clean_title: "Xiaomi Redmi Note 13 Pro 256GB",
    canonical: "redmi_note_13_pro_256gb",
    pattern: "normal",
    price: 12250.0,
    attributes: { ram_gb: 8, storage_gb: 256, warranty: "local" },
  },
  {
    slug: "samsung-galaxy-a55-5g-256gb",
    store: "btech",
    category: "electronics",
    sub_category: "smartphones",
    brand: "Samsung",
    title: "Samsung Galaxy A55 5G 256GB 8GB RAM",
    canonical: null,
    pattern: "normal",
    price: 16999.0,
    attributes: { ram_gb: 8, storage_gb: 256, warranty: "local" },
  },
  {
    slug: "apple-macbook-air-m3-13-256gb",
    store: "btech",
    category: "electronics",
    sub_category: "laptops",
    brand: "Apple",
    title: "Apple MacBook Air M3 13-inch 256GB",
    clean_title: "Apple MacBook Air M3 13-inch 256GB",
    canonical: "macbook_air_m3_13_256gb",
    pattern: "hike",
    price: 44999.0,
    attributes: { ram_gb: 16, storage_gb: 256, warranty: "international" },
  },
  {
    slug: "apple-macbook-air-m3-13-256gb-egc",
    store: "egycart",
    category: "electronics",
    sub_category: "laptops",
    brand: "Apple",
    title: "Apple MacBook Air M3 13-inch 256GB Midnight",
    clean_title: "Apple MacBook Air M3 13-inch 256GB",
    canonical: "macbook_air_m3_13_256gb",
    pattern: "hike",
    price: 46999.0,
    attributes: { ram_gb: 16, storage_gb: 256, warranty: "local" },
  },
  {
    slug: "lenovo-ideapad-slim-5-16gb-512gb",
    store: "sigma",
    category: "electronics",
    sub_category: "laptops",
    brand: "Lenovo",
    title: "Lenovo IdeaPad Slim 5 16GB 512GB RTX 3050",
    canonical: null,
    pattern: "fake",
    price: 27999.0,
    claimed: 32999.0,
    attributes: { ram_gb: 16, storage_gb: 512, warranty: "local" },
  },
  {
    slug: "lg-27ul500-27-4k-ips",
    store: "btech",
    category: "electronics",
    sub_category: "monitors",
    brand: "LG",
    title: "LG 27UL500 27-inch 4K IPS Monitor",
    clean_title: "LG 27UL500 27-inch 4K Monitor",
    canonical: "lg_27ul500_27_4k",
    pattern: "genuine",
    price: 8999.0,
    attributes: { screen_size_inch: 27, panel: "IPS 4K UHD" },
  },
  {
    slug: "lg-27ul500-27-4k-ips-sgm",
    store: "sigma",
    category: "electronics",
    sub_category: "monitors",
    brand: "LG",
    title: "LG 27UL500 27-inch 4K IPS Monitor",
    clean_title: "LG 27UL500 27-inch 4K Monitor",
    canonical: "lg_27ul500_27_4k",
    pattern: "normal",
    price: 9450.0,
    attributes: { screen_size_inch: 27, panel: "IPS 4K UHD" },
  },
  {
    slug: "samsung-odyssey-g5-27-165hz",
    store: "egycart",
    category: "electronics",
    sub_category: "monitors",
    brand: "Samsung",
    title: "Samsung Odyssey G5 27-inch 165Hz Curved",
    canonical: null,
    pattern: "fake",
    price: 10999.0,
    claimed: 13999.0,
    attributes: { screen_size_inch: 27, refresh_hz: 165 },
  },
  {
    slug: "apple-airpods-pro-2-usbc",
    store: "btech",
    category: "electronics",
    sub_category: "headphones",
    brand: "Apple",
    title: "Apple AirPods Pro 2nd Gen USB-C",
    clean_title: "Apple AirPods Pro 2nd Gen",
    canonical: "airpods_pro_2_usbc",
    pattern: "atl",
    price: 10499.0,
    attributes: { anc: true, battery_hours: 30 },
  },
  {
    slug: "apple-airpods-pro-2-usbc-sgm",
    store: "sigma",
    category: "electronics",
    sub_category: "headphones",
    brand: "Apple",
    title: "Apple AirPods Pro 2nd Gen USB-C",
    clean_title: "Apple AirPods Pro 2nd Gen",
    canonical: "airpods_pro_2_usbc",
    pattern: "normal",
    price: 10999.0,
    attributes: { anc: true, battery_hours: 30 },
  },
  {
    slug: "sony-wh-1000xm5",
    store: "sigma",
    category: "electronics",
    sub_category: "headphones",
    brand: "Sony",
    title: "Sony WH-1000XM5 Wireless Noise Cancelling",
    clean_title: "Sony WH-1000XM5 Headphones",
    canonical: "sony_wh1000xm5",
    pattern: "genuine",
    price: 13999.0,
    attributes: { anc: true, battery_hours: 30 },
  },
  {
    slug: "sony-wh-1000xm5-btc",
    store: "btech",
    category: "electronics",
    sub_category: "headphones",
    brand: "Sony",
    title: "Sony WH-1000XM5 Wireless Noise Cancelling",
    clean_title: "Sony WH-1000XM5 Headphones",
    canonical: "sony_wh1000xm5",
    pattern: "normal",
    price: 15499.0,
    attributes: { anc: true, battery_hours: 30 },
  },
  {
    slug: "microsoft-xbox-series-s-512gb",
    store: "egycart",
    category: "electronics",
    sub_category: "gaming_consoles",
    brand: "Microsoft",
    title: "Microsoft Xbox Series S 512GB",
    canonical: null,
    pattern: "normal",
    price: 13499.0,
    attributes: { storage_gb: 512 },
  },
  {
    slug: "sony-ps5-slim-digital",
    store: "btech",
    category: "electronics",
    sub_category: "gaming_consoles",
    brand: "Sony",
    title: "Sony PlayStation 5 Slim Digital Edition",
    canonical: null,
    pattern: "hike",
    price: 24999.0,
    attributes: { storage_gb: 1000 },
  },
  // --------------------------- Fashion --------------------------- //
  {
    slug: "nike-club-fleece-hoodie",
    store: "style_hub",
    category: "fashion",
    sub_category: "hoodies",
    brand: "Nike",
    title: "Nike Club Fleece Pullover Hoodie",
    clean_title: "Nike Club Fleece Hoodie",
    canonical: "nike_club_fleece_hoodie",
    pattern: "genuine",
    price: 1899.0,
    attributes: { available_sizes: ["M", "L", "XL"], total_sizes: 5 },
  },
  {
    slug: "nike-club-fleece-hoodie-thr",
    store: "thread_eg",
    category: "fashion",
    sub_category: "hoodies",
    brand: "Nike",
    title: "Nike Club Fleece Pullover Hoodie",
    clean_title: "Nike Club Fleece Hoodie",
    canonical: "nike_club_fleece_hoodie",
    pattern: "normal",
    price: 2150.0,
    attributes: { available_sizes: ["S", "M", "L", "XL"], total_sizes: 5 },
  },
  {
    slug: "adidas-essentials-3stripes-hoodie",
    store: "local_brand_x",
    category: "fashion",
    sub_category: "hoodies",
    brand: "Adidas",
    title: "Adidas Essentials 3-Stripes Hoodie",
    canonical: null,
    pattern: "fake",
    price: 1450.0,
    claimed: 1899.0,
    attributes: { available_sizes: ["S", "M"], total_sizes: 5 },
  },
  {
    slug: "nike-air-force-1-07",
    store: "style_hub",
    category: "fashion",
    sub_category: "sneakers",
    brand: "Nike",
    title: "Nike Air Force 1 '07 Sneakers",
    canonical: null,
    pattern: "atl",
    price: 3499.0,
    attributes: { available_sizes: ["40", "41", "42", "43", "44", "45"], total_sizes: 8 },
  },
  {
    slug: "adidas-samba-og",
    store: "thread_eg",
    category: "fashion",
    sub_category: "sneakers",
    brand: "Adidas",
    title: "Adidas Samba OG Sneakers",
    canonical: null,
    pattern: "hike",
    price: 4299.0,
    attributes: { available_sizes: ["42"], total_sizes: 8 },
  },
  {
    slug: "local-brand-oversized-hoodie",
    store: "local_brand_x",
    category: "fashion",
    sub_category: "hoodies",
    brand: "Local Brand",
    title: "Local Brand Oversized Fleece Hoodie",
    canonical: null,
    pattern: "normal",
    price: 950.0,
    attributes: { available_sizes: ["M", "L", "XL"], total_sizes: 4 },
  },
  {
    slug: "puma-rs-x-bold",
    store: "style_hub",
    category: "fashion",
    sub_category: "sneakers",
    brand: "PUMA",
    title: "PUMA RS-X Bold Sneakers",
    canonical: null,
    pattern: "normal",
    price: 2799.0,
    in_stock: false,
    attributes: { available_sizes: [], total_sizes: 8 },
  },
  {
    slug: "levis-511-slim-jeans",
    store: "thread_eg",
    category: "fashion",
    sub_category: "jeans",
    brand: "Levi's",
    title: "Levi's 511 Slim Fit Jeans",
    canonical: null,
    pattern: "genuine",
    price: 2299.0,
    attributes: { available_sizes: ["30", "32", "34"], total_sizes: 7 },
  },
  {
    slug: "calvin-klein-logo-tee",
    store: "style_hub",
    category: "fashion",
    sub_category: "t_shirts",
    brand: "Calvin Klein",
    title: "Calvin Klein Logo Cotton T-Shirt",
    canonical: null,
    pattern: "fake",
    price: 1249.0,
    claimed: 1699.0,
    attributes: { available_sizes: ["L"], total_sizes: 5 },
  },
  {
    slug: "style-hub-ribbed-knit-cardigan",
    store: "style_hub",
    category: "fashion",
    sub_category: "knitwear",
    brand: "Style Hub",
    title: "Style Hub Ribbed Knit Cardigan",
    canonical: null,
    pattern: "normal",
    price: 1699.0,
    attributes: { available_sizes: ["S", "M", "L"], total_sizes: 5 },
  },
];

/* ------------------------------------------------------------------ */
/* Dataset builders                                                    */
/* ------------------------------------------------------------------ */

function snapshotDates(days: number): string[] {
  const end = Date.UTC(2026, 10, 21); // 2026-11-21 (mock "today")
  const out: string[] = [];
  for (let i = 0; i < days; i++) {
    out.push(new Date(end - (days - 1 - i) * 86400000).toISOString().slice(0, 10));
  }
  return out;
}

const MOCK_STORE_URL_TEMPLATES: Record<string, string> = {
  btech: "https://btech.com/en/s?q={query}&ref={slug}",
  sigma: "https://www.sigma-computer.com/en/search?controller=search&s={query}&ref={slug}",
  egycart: "https://www.amazon.eg/s?k={query}&ref={slug}",
  style_hub: "https://www.jumia.com.eg/catalog/?q={query}&ref={slug}",
  thread_eg: "https://www.noon.com/egypt-en/search/?q={query}&ref={slug}",
  local_brand_x: "https://www.amazon.eg/s?k={query}&ref={slug}",
};

const MOCK_SUBCATEGORY_IMAGES: Record<string, string[]> = {
  smartphones: [
    "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1592899677977-9c10ca588bbd?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1598327105666-5b89351aff97?auto=format&fit=crop&w=800&q=80",
  ],
  laptops: [
    "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?auto=format&fit=crop&w=800&q=80",
  ],
  monitors: [
    "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1586210579191-33b45e38fa2c?auto=format&fit=crop&w=800&q=80",
  ],
  headphones: [
    "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1583394838336-acd977736f90?auto=format&fit=crop&w=800&q=80",
  ],
  gaming_consoles: [
    "https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?auto=format&fit=crop&w=800&q=80",
  ],
  hoodies: [
    "https://images.unsplash.com/photo-1556821840-3a63f95609a7?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1620799140408-edc6dcb6d633?auto=format&fit=crop&w=800&q=80",
  ],
  sneakers: [
    "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1549298916-b41d501d3772?auto=format&fit=crop&w=800&q=80",
  ],
  jeans: [
    "https://images.unsplash.com/photo-1542272604-787c3835535d?auto=format&fit=crop&w=800&q=80",
  ],
  t_shirts: [
    "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=800&q=80",
  ],
  knitwear: [
    "https://images.unsplash.com/photo-1578768079052-aa76e52ff62e?auto=format&fit=crop&w=800&q=80",
  ],
};

function buildMockProductUrl(spec: ProductSpec): string {
  const template =
    MOCK_STORE_URL_TEMPLATES[spec.store] ??
    "https://www.amazon.eg/s?k={query}&ref={slug}";
  return template
    .replace("{query}", encodeURIComponent(spec.title))
    .replace("{slug}", encodeURIComponent(spec.slug));
}

function buildMockImageUrl(spec: ProductSpec): string | null {
  const pool = MOCK_SUBCATEGORY_IMAGES[spec.sub_category];
  if (!pool || pool.length === 0) return null;
  return pool[hashSeed(spec.slug) % pool.length];
}

function buildProduct(spec: ProductSpec, dates: string[]): {
  product: Product;
  history: PriceHistoryPoint[];
} {
  const rnd = mulberry32(hashSeed(`${spec.store}::${spec.slug}`));
  const days = dates.length;
  const ratios = buildPriceRatios(spec.pattern, rnd, days);
  const prices = ratios.map((r) => round2(r * spec.price));

  const claimedFactor =
    spec.claimed !== undefined ? spec.claimed / spec.price : undefined;
  const isFashion = spec.category === "fashion";
  const inStockEverywhere = spec.in_stock !== false;
  const sizesCount = isFashion
    ? ((spec.attributes.available_sizes as string[] | undefined)?.length ?? 0)
    : 0;

  const history: PriceHistoryPoint[] = dates.map((date, i) => ({
    snapshot_date: date,
    price: prices[i],
    claimed_original_price:
      claimedFactor !== undefined ? round2(prices[i] * claimedFactor) : null,
    rolling_60d_median: round2(median(prices.slice(Math.max(0, i - 59), i + 1))),
    in_stock: inStockEverywhere || i < days - 1,
    available_sizes_count: isFashion ? (inStockEverywhere || i < days - 1 ? sizesCount : 0) : null,
  }));

  const currentPrice = prices[days - 1];
  const rollingMedian = history[days - 1].rolling_60d_median;
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const claimedFinal =
    claimedFactor !== undefined ? round2(currentPrice * claimedFactor) : null;

  const claimedDiscountPct =
    claimedFinal !== null
      ? round2(((claimedFinal - currentPrice) / claimedFinal) * 100)
      : 0;
  const realDiscountPct = round2(((rollingMedian - currentPrice) / rollingMedian) * 100);

  // Prior 45-day median before the recent 14-day window (§4 rule 4).
  const priorSlice = prices.slice(Math.max(0, days - 59), days - 14);
  const priorMedian = median(priorSlice);
  const recentHikePct =
    priorMedian > 0 ? round2(((currentPrice - priorMedian) / priorMedian) * 100) : 0;

  const verdict = classifyVerdict({
    claimed_discount_pct: claimedDiscountPct,
    real_discount_pct: realDiscountPct,
    current_price: currentPrice,
    min_historical_price: minPrice,
    history_days: days,
    recent_hike_pct: recentHikePct,
  });

  // Fashion scarcity: less than 25% of sizes still in stock (§3.1).
  const scarcityFlag = isFashion
    ? sizesCount / Math.max(1, (spec.attributes.total_sizes as number | undefined) ?? 1) < 0.25
    : false;

  const product: Product = {
    product_sk: fakeSk(spec.store, spec.slug),
    canonical_product_key: spec.canonical,
    store_name: spec.store,
    category: spec.category,
    sub_category: spec.sub_category,
    brand: spec.brand,
    product_title: spec.title,
    product_url: buildMockProductUrl(spec),
    image_url: buildMockImageUrl(spec),
    attributes_json: spec.attributes,
    current_price: currentPrice,
    claimed_original_price: claimedFinal,
    rolling_60d_median: rollingMedian,
    min_historical_price: round2(minPrice),
    max_historical_price: round2(maxPrice),
    claimed_discount_pct: claimedDiscountPct,
    real_discount_pct: realDiscountPct,
    discount_verdict: verdict,
    scarcity_flag: scarcityFlag,
    in_stock: inStockEverywhere,
    last_updated_at: MOCK_NOW,
  };

  return { product, history };
}

let cachedProducts: Product[] | null = null;
const historyCache = new Map<string, PriceHistoryPoint[]>();

function getDataset(): Product[] {
  if (cachedProducts) return cachedProducts;
  const dates = snapshotDates(HISTORY_DAYS);
  const products: Product[] = [];
  for (const spec of SPECS) {
    const { product, history } = buildProduct(spec, dates);
    products.push(product);
    historyCache.set(product.product_sk, history);
  }
  cachedProducts = products;
  return products;
}

/* ------------------------------------------------------------------ */
/* Public mock API (mirrors FastAPI responses)                         */
/* ------------------------------------------------------------------ */

export function getMockStoreNames(): string[] {
  return Array.from(new Set(getDataset().map((p) => p.store_name))).sort();
}

export function getMockStatsOverview(): StatsOverview {
  const products = getDataset();
  const count = (v: DiscountVerdict) =>
    products.filter((p) => p.discount_verdict === v).length;
  const fake = products.filter((p) => p.discount_verdict === "FAKE_DISCOUNT");
  const avgInflation =
    fake.length > 0
      ? round2(
          fake.reduce(
            (sum, p) => sum + (p.claimed_discount_pct - Math.max(p.real_discount_pct, 0)),
            0,
          ) / fake.length,
        )
      : 0;
  return {
    total_tracked: products.length,
    fake_discounts_today: count("FAKE_DISCOUNT"),
    genuine_deals_today: count("GENUINE_DEAL"),
    all_time_lows_today: count("ALL_TIME_LOW"),
    presale_hikes_today: count("PRESALE_HIKE"),
    avg_fake_inflation_pct: avgInflation,
    last_pipeline_run_at: MOCK_NOW,
    available_stores: getMockStoreNames(),
  };
}

function sortFeed(items: Product[], sort: RadarFeedParams["sort"]): Product[] {
  const sorted = [...items];
  switch (sort) {
    case "real_discount_pct_desc":
      sorted.sort((a, b) => b.real_discount_pct - a.real_discount_pct);
      break;
    case "claimed_vs_real_gap_desc":
      sorted.sort(
        (a, b) =>
          b.claimed_discount_pct - b.real_discount_pct -
          (a.claimed_discount_pct - a.real_discount_pct),
      );
      break;
    case "price_asc":
      sorted.sort((a, b) => a.current_price - b.current_price);
      break;
    case "price_desc":
      sorted.sort((a, b) => b.current_price - a.current_price);
      break;
  }
  return sorted;
}

export function mockRadarFeed(params: RadarFeedParams): RadarFeedResponse {
  const items = getDataset().filter((p) => {
    if (params.category !== "all" && p.category !== params.category) return false;
    if (params.verdict && p.discount_verdict !== params.verdict) return false;
    if (params.store && p.store_name !== params.store) return false;
    return true;
  });
  const sorted = sortFeed(items, params.sort);
  const limit = Math.max(1, params.limit);
  const total = sorted.length;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const page = Math.min(Math.max(1, params.page), totalPages);
  return {
    items: sorted.slice((page - 1) * limit, page * limit),
    total,
    page,
    limit,
    total_pages: totalPages,
  };
}

const TRACKING_QUERY_PARAMS = new Set([
  "fbclid",
  "gclid",
  "gbraid",
  "wbraid",
  "dclid",
  "msclkid",
  "yclid",
  "mc_cid",
  "mc_eid",
  "igshid",
  "ttclid",
  "si",
  "_ga",
  "_gl",
  "srsltid",
  "gad_source",
  "gad_campaignid",
  "trk",
  "spm",
  "scid",
]);

function isTrackingParam(name: string): boolean {
  const low = name.trim().toLowerCase();
  return low.startsWith("utm_") || TRACKING_QUERY_PARAMS.has(low);
}

function parseUrlParts(rawUrl: string): {
  fullKey: string;
  host: string;
  path: string;
  ref: string | null;
  sigmaId: string | null;
  btechSlug: string | null;
  noonSku: string | null;
  amazonAsin: string | null;
  jumiaSku: string | null;
} {
  const cleaned = rawUrl.trim();
  if (!cleaned) {
    return {
      fullKey: "",
      host: "",
      path: "",
      ref: null,
      sigmaId: null,
      btechSlug: null,
      noonSku: null,
      amazonAsin: null,
      jumiaSku: null,
    };
  }
  try {
    const withScheme = /^https?:\/\//i.test(cleaned) ? cleaned : `https://${cleaned}`;
    const parsed = new URL(withScheme);
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const path = parsed.pathname.replace(/\/+$/, "");
    const kept = new URLSearchParams();
    parsed.searchParams.forEach((v, k) => {
      if (!isTrackingParam(k) && v.trim() !== "") {
        kept.append(k, v);
      }
    });
    const query = kept.toString();
    const fullKey = (query ? `${host}${path}?${query}` : `${host}${path}`).toLowerCase();
    const refVal = kept.get("ref")?.trim().toLowerCase() || null;
    const sigmaId =
      host === "sigma-computer.com" && path.toLowerCase() === "/en/item"
        ? kept.get("id")?.trim().toLowerCase() || null
        : null;
    const btechSlug =
      host === "btech.com" && path.toLowerCase().startsWith("/en/p/") && path.length > "/en/p/".length
        ? path.toLowerCase()
        : null;
    const noonMatch = host === "noon.com" ? path.match(/\/([a-z0-9_-]+)\/p(?:\/|$)/i) : null;
    const noonSku = noonMatch ? noonMatch[1].toLowerCase() : null;
    const amzMatch =
      host === "amazon.eg" ? path.match(/\/(?:dp|gp\/product)\/([a-z0-9]{10})(?:\/|$)/i) : null;
    const amazonAsin = amzMatch ? amzMatch[1].toLowerCase() : null;
    const jumiaMatch = host === "jumia.com.eg" ? path.match(/-(\d{5,15})\.html$/i) : null;
    const jumiaSku = jumiaMatch ? jumiaMatch[1].toLowerCase() : null;
    return {
      fullKey,
      host,
      path: path.toLowerCase(),
      ref: refVal,
      sigmaId,
      btechSlug,
      noonSku,
      amazonAsin,
      jumiaSku,
    };
  } catch {
    const fallback = cleaned
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .replace(/#.*$/, "")
      .replace(/\/\?/, "?")
      .replace(/\/+$/, "");
    return {
      fullKey: fallback,
      host: "",
      path: "",
      ref: null,
      sigmaId: null,
      btechSlug: null,
      noonSku: null,
      amazonAsin: null,
      jumiaSku: null,
    };
  }
}

export function mockSearch(params: SearchParams): SearchResponse {
  const limit = params.limit ?? 20;
  const products = getDataset();

  if (params.url) {
    const target = parseUrlParts(params.url);
    if (target.fullKey.length > 0) {
      const exact = products.find(
        (p) => parseUrlParts(p.product_url).fullKey === target.fullKey,
      );
      if (exact) {
        return { match_type: "url_exact", items: [exact], total: 1 };
      }
      if (target.sigmaId) {
        const sigmaMatch = products.find(
          (p) => parseUrlParts(p.product_url).sigmaId === target.sigmaId,
        );
        if (sigmaMatch) {
          return { match_type: "url_exact", items: [sigmaMatch], total: 1 };
        }
      }
      if (target.btechSlug) {
        const btechMatch = products.find(
          (p) => parseUrlParts(p.product_url).btechSlug === target.btechSlug,
        );
        if (btechMatch) {
          return { match_type: "url_exact", items: [btechMatch], total: 1 };
        }
      }
      if (target.noonSku) {
        const noonMatch = products.find(
          (p) => parseUrlParts(p.product_url).noonSku === target.noonSku,
        );
        if (noonMatch) {
          return { match_type: "url_exact", items: [noonMatch], total: 1 };
        }
      }
      if (target.amazonAsin) {
        const amzMatch = products.find(
          (p) => parseUrlParts(p.product_url).amazonAsin === target.amazonAsin,
        );
        if (amzMatch) {
          return { match_type: "url_exact", items: [amzMatch], total: 1 };
        }
      }
      if (target.jumiaSku) {
        const jumiaMatch = products.find(
          (p) => parseUrlParts(p.product_url).jumiaSku === target.jumiaSku,
        );
        if (jumiaMatch) {
          return { match_type: "url_exact", items: [jumiaMatch], total: 1 };
        }
      }
      if (target.host && target.ref) {
        const refMatch = products.find((p) => {
          const cand = parseUrlParts(p.product_url);
          return cand.host === target.host && cand.ref === target.ref;
        });
        if (refMatch) {
          return { match_type: "url_exact", items: [refMatch], total: 1 };
        }
      }
      if (!params.q?.trim()) {
        return { match_type: "url_not_found", items: [], total: 0 };
      }
    }
  }

  const q = (params.q ?? "").trim().toLowerCase();
  if (q.length === 0) {
    return { match_type: "none", items: [], total: 0 };
  }
  const matched = products.filter(
    (p) =>
      p.product_title.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q),
  );
  return { match_type: "text_search", items: matched.slice(0, limit), total: matched.length };
}

export function mockProductDetail(productSk: string): {
  product: Product;
  history: PriceHistoryPoint[];
  alternatives: AlternativeListing[];
} | null {
  const products = getDataset();
  const product = products.find((p) => p.product_sk === productSk);
  if (!product) return null;
  const history = historyCache.get(product.product_sk) ?? [];
  const alternatives: AlternativeListing[] = products
    .filter(
      (p) =>
        p.canonical_product_key !== null &&
        p.canonical_product_key === product.canonical_product_key &&
        p.product_sk !== product.product_sk,
    )
    .sort((a, b) => a.current_price - b.current_price)
    .map((p) => ({
      product_sk: p.product_sk,
      store_name: p.store_name,
      price: p.current_price,
      in_stock: p.in_stock,
      product_url: p.product_url,
      discount_verdict: p.discount_verdict,
    }));
  return { product, history, alternatives };
}

export function mockCompare(params: CompareParams): CompareResponse {
  const products = getDataset();
  const groups = new Map<string, Product[]>();
  for (const p of products) {
    if (!p.canonical_product_key) continue;
    const bucket = groups.get(p.canonical_product_key) ?? [];
    bucket.push(p);
    groups.set(p.canonical_product_key, bucket);
  }

  let items = Array.from(groups.values())
    .filter((members) => members.length >= 2)
    .map((members): import("@/types/contract").CrossStoreMatch => {
      const listings: CompareListing[] = members
        .sort((a, b) => a.current_price - b.current_price)
        .map((p) => ({
          product_sk: p.product_sk,
          store_name: p.store_name,
          price: p.current_price,
          in_stock: p.in_stock,
          product_url: p.product_url,
          discount_verdict: p.discount_verdict,
        }));
      const lowest = listings[0];
      const highest = listings[listings.length - 1];
      const spreadEgp = round2(highest.price - lowest.price);
      const spreadPct = round2(((highest.price - lowest.price) / lowest.price) * 100);
      return {
        canonical_product_key: members[0].canonical_product_key as string,
        product_title_clean:
          SPECS.find((s) => s.canonical === members[0].canonical_product_key)
            ?.clean_title ?? members[0].product_title,
        category: members[0].category,
        brand: members[0].brand,
        stores_count: listings.length,
        lowest_price: lowest.price,
        lowest_price_store: lowest.store_name,
        highest_price: highest.price,
        price_spread_egp: spreadEgp,
        price_spread_pct: spreadPct,
        listings_json: listings,
      };
    })
    .sort((a, b) => b.price_spread_pct - a.price_spread_pct);

  if (params.category && params.category !== "all") {
    items = items.filter((m) => m.category === params.category);
  }
  if (params.min_spread_pct !== undefined && params.min_spread_pct > 0) {
    items = items.filter((m) => m.price_spread_pct >= (params.min_spread_pct as number));
  }

  const limit = Math.max(1, params.limit);
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const page = Math.min(Math.max(1, params.page), totalPages);
  return {
    items: items.slice((page - 1) * limit, page * limit),
    total,
    page,
    limit,
  };
}
