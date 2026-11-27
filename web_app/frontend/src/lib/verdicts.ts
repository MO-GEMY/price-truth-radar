import {
  BadgeCheck,
  Clock,
  MinusCircle,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import type {
  CategoryFacetsResponse,
  DiscountVerdict,
  FeedCategoryFilter,
  HistoryMaturity,
  MarketBenchmark,
  PriceHistoryPoint,
  Product,
  StatsOverview,
} from "@/types/contract";

export const ALL_DEAL_VERDICTS: ReadonlySet<DiscountVerdict> = new Set([
  "ALL_TIME_LOW",
  "GENUINE_DEAL",
  "RECENT_DROP",
]);

export const ALL_HIKE_VERDICTS: ReadonlySet<DiscountVerdict> = new Set([
  "FAKE_DISCOUNT",
  "PRESALE_HIKE",
  "RECENT_HIKE",
]);

/** Unified catalog-wide in-stock deals count (ALL_TIME_LOW + GENUINE_DEAL + RECENT_DROP). */
export function getAllDealsCount(stats: StatsOverview): number {
  if (typeof stats.all_deals_count === "number" && Number.isFinite(stats.all_deals_count)) {
    return stats.all_deals_count;
  }
  return (
    (stats.all_time_lows_today ?? 0) +
    (stats.genuine_deals_today ?? 0) +
    (stats.recent_drops_today ?? 0)
  );
}

/** Unified catalog-wide in-stock hikes/fake discounts count (FAKE_DISCOUNT + PRESALE_HIKE + RECENT_HIKE). */
export function getAllHikesCount(stats: StatsOverview): number {
  if (typeof stats.all_hikes_count === "number" && Number.isFinite(stats.all_hikes_count)) {
    return stats.all_hikes_count;
  }
  return (
    (stats.fake_discounts_today ?? 0) +
    (stats.presale_hikes_today ?? 0) +
    (stats.recent_hikes_today ?? 0)
  );
}

/**
 * Returns the exact in-stock deals count for the active `(category, subcategory)` scope.
 * Never falls back to global totals when a category or subcategory is selected.
 */
export function getScopedDealsCount(
  stats: StatsOverview | null | undefined,
  category: FeedCategoryFilter,
  subcategory: string,
  facets?: CategoryFacetsResponse | null,
): number | null {
  if (category === "all") {
    return stats ? getAllDealsCount(stats) : null;
  }
  const normSub = subcategory.trim().toLowerCase();
  const facetsMatchScope =
    facets !== null &&
    facets !== undefined &&
    facets.category === category &&
    (facets.subcategory ?? "").trim().toLowerCase() === normSub;

  if (
    facetsMatchScope &&
    typeof facets.all_deals_count === "number" &&
    Number.isFinite(facets.all_deals_count)
  ) {
    return facets.all_deals_count;
  }
  if (!normSub) {
    const catCount = stats?.category_deals_counts?.[category];
    if (typeof catCount === "number" && Number.isFinite(catCount)) {
      return catCount;
    }
  }
  return null;
}

/**
 * Returns the exact in-stock hikes/fake discounts count for the active `(category, subcategory)` scope.
 * Never falls back to global totals when a category or subcategory is selected.
 */
export function getScopedHikesCount(
  stats: StatsOverview | null | undefined,
  category: FeedCategoryFilter,
  subcategory: string,
  facets?: CategoryFacetsResponse | null,
): number | null {
  if (category === "all") {
    return stats ? getAllHikesCount(stats) : null;
  }
  const normSub = subcategory.trim().toLowerCase();
  const facetsMatchScope =
    facets !== null &&
    facets !== undefined &&
    facets.category === category &&
    (facets.subcategory ?? "").trim().toLowerCase() === normSub;

  if (
    facetsMatchScope &&
    typeof facets.all_hikes_count === "number" &&
    Number.isFinite(facets.all_hikes_count)
  ) {
    return facets.all_hikes_count;
  }
  if (!normSub) {
    const catCount = stats?.category_hikes_counts?.[category];
    if (typeof catCount === "number" && Number.isFinite(catCount)) {
      return catCount;
    }
  }
  return null;
}

export interface VerdictTone {
  icon: LucideIcon;
  className: string;
}

export const DEFAULT_VERDICT_TONE: VerdictTone = {
  icon: MinusCircle,
  className: "",
};

export const VERDICT_TONES: Record<DiscountVerdict, VerdictTone> = {
  FAKE_DISCOUNT: { icon: ShieldAlert, className: "ptr-badge-warning" },
  ALL_TIME_LOW: { icon: TrendingDown, className: "ptr-badge-good" },
  GENUINE_DEAL: { icon: BadgeCheck, className: "ptr-badge-good" },
  PRESALE_HIKE: { icon: TrendingUp, className: "ptr-badge-amber" },
  RECENT_DROP: { icon: TrendingDown, className: "ptr-badge-good" },
  RECENT_HIKE: { icon: TrendingUp, className: "ptr-badge-amber" },
  NEWLY_TRACKED: { icon: Clock, className: "" },
  NORMAL_PRICE: { icon: MinusCircle, className: "" },
};

export const MARKET_BENCHMARK_TONES: Record<MarketBenchmark["status"], VerdictTone> = {
  CHEAPEST_IN_MARKET: { icon: BadgeCheck, className: "ptr-badge-good" },
  TIED_CHEAPEST: { icon: BadgeCheck, className: "ptr-badge-good" },
  ABOVE_MARKET: { icon: TrendingUp, className: "ptr-badge-amber" },
  OUT_OF_STOCK: { icon: Clock, className: "" },
};

export const DEFAULT_MARKET_BENCHMARK_TONE: VerdictTone = {
  icon: MinusCircle,
  className: "",
};

export function normalizeVerdict(verdict: string | null | undefined): DiscountVerdict {
  if (typeof verdict === "string" && Object.prototype.hasOwnProperty.call(VERDICT_TONES, verdict)) {
    return verdict as DiscountVerdict;
  }
  return "NORMAL_PRICE";
}

export function getVerdictTone(verdict: string | null | undefined): VerdictTone {
  return VERDICT_TONES[normalizeVerdict(verdict)] ?? DEFAULT_VERDICT_TONE;
}

export function getMarketBenchmarkTone(status: string | null | undefined): VerdictTone {
  if (
    typeof status === "string" &&
    Object.prototype.hasOwnProperty.call(MARKET_BENCHMARK_TONES, status)
  ) {
    return MARKET_BENCHMARK_TONES[status as MarketBenchmark["status"]] ?? DEFAULT_MARKET_BENCHMARK_TONE;
  }
  return DEFAULT_MARKET_BENCHMARK_TONE;
}

export const VERDICT_ORDER: DiscountVerdict[] = [
  "FAKE_DISCOUNT",
  "ALL_TIME_LOW",
  "GENUINE_DEAL",
  "PRESALE_HIKE",
  "RECENT_DROP",
  "RECENT_HIKE",
  "NEWLY_TRACKED",
  "NORMAL_PRICE",
];

/**
 * Determine exact tracked days count from API maturity fields first, falling
 * back cleanly to history dates or legacy mock payloads.
 */
export function getTrackedDaysCount(
  product: Pick<
    Product,
    | "tracked_days_count"
    | "history_maturity"
    | "discount_verdict"
    | "min_historical_price"
    | "max_historical_price"
  >,
  history?: Pick<PriceHistoryPoint, "snapshot_date" | "price">[],
): number {
  if (typeof product.tracked_days_count === "number" && product.tracked_days_count >= 1) {
    return Math.floor(product.tracked_days_count);
  }
  if (history && history.length > 0) {
    const times = history
      .map((pt) => Date.parse(pt.snapshot_date))
      .filter((ms) => Number.isFinite(ms));
    const distinctDates = new Set(history.map((pt) => pt.snapshot_date)).size;
    if (times.length >= 2) {
      const spanDays = Math.floor((Math.max(...times) - Math.min(...times)) / 86_400_000) + 1;
      return Math.max(distinctDates, spanDays, 1);
    }
    return Math.max(distinctDates, 1);
  }
  if (product.history_maturity === "MATURE") return 60;
  if (product.history_maturity === "GROWING") return 14;
  if (
    product.discount_verdict === "ALL_TIME_LOW" ||
    product.discount_verdict === "GENUINE_DEAL" ||
    product.discount_verdict === "FAKE_DISCOUNT" ||
    product.discount_verdict === "PRESALE_HIKE"
  ) {
    return 14;
  }
  return 1;
}

/**
 * Mirrors dbt `history_maturity`:
 * - EARLY:   < 7 tracked days (never emits 60-day median verdicts)
 * - GROWING: 7–59 tracked days (dynamic X-day median)
 * - MATURE:  >= 60 tracked days (full 60-day rolling median)
 */
export function getHistoryMaturity(
  product: Pick<
    Product,
    | "tracked_days_count"
    | "history_maturity"
    | "discount_verdict"
    | "min_historical_price"
    | "max_historical_price"
  >,
  history?: Pick<PriceHistoryPoint, "snapshot_date" | "price">[],
): HistoryMaturity {
  const days = getTrackedDaysCount(product, history);
  if (days < 7) return "EARLY";
  if (days < 60) return "GROWING";
  return "MATURE";
}

/**
 * Returns the verified historical median ONLY when `tracked_days_count >= 7`.
 * Always returns `null` during EARLY cold-start (< 7 days).
 */
export function getVerifiedMedian(
  product: Pick<
    Product,
    | "tracked_days_count"
    | "history_maturity"
    | "verified_historical_median"
    | "rolling_60d_median"
    | "discount_verdict"
    | "min_historical_price"
    | "max_historical_price"
  >,
  history?: Pick<PriceHistoryPoint, "snapshot_date" | "price">[],
): number | null {
  if (getHistoryMaturity(product, history) === "EARLY") {
    return null;
  }
  const med = product.verified_historical_median ?? product.rolling_60d_median;
  return typeof med === "number" && Number.isFinite(med) && med > 0 ? med : null;
}

export function hasSufficientPriceHistory(
  product: Pick<
    Product,
    | "tracked_days_count"
    | "history_maturity"
    | "min_historical_price"
    | "max_historical_price"
    | "real_discount_pct"
    | "discount_verdict"
  >,
  history?: Pick<PriceHistoryPoint, "snapshot_date" | "price">[],
): boolean {
  return getHistoryMaturity(product, history) !== "EARLY";
}

/** Natural Arabic & English day phrase ("يوم واحد", "يومان", "5 أيام", "14 يوم" / "1 day", "5 days"). */
export function formatTrackedDays(days: number, lang: "en" | "ar"): string {
  const n = Math.max(1, Math.floor(days));
  if (lang === "ar") {
    if (n === 1) return "يوم واحد";
    if (n === 2) return "يومان";
    if (n >= 3 && n <= 10) return `${n} أيام`;
    return `${n} يوم`;
  }
  return n === 1 ? "1 day" : `${n} days`;
}
