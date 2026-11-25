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
  DiscountVerdict,
  HistoryMaturity,
  PriceHistoryPoint,
  Product,
} from "@/types/contract";

export const VERDICT_TONES: Record<DiscountVerdict, { icon: LucideIcon; className: string }> = {
  FAKE_DISCOUNT: { icon: ShieldAlert, className: "ptr-badge-warning" },
  ALL_TIME_LOW: { icon: TrendingDown, className: "ptr-badge-good" },
  GENUINE_DEAL: { icon: BadgeCheck, className: "ptr-badge-good" },
  PRESALE_HIKE: { icon: TrendingUp, className: "ptr-badge-amber" },
  RECENT_DROP: { icon: TrendingDown, className: "ptr-badge-good" },
  RECENT_HIKE: { icon: TrendingUp, className: "ptr-badge-amber" },
  NEWLY_TRACKED: { icon: Clock, className: "" },
  NORMAL_PRICE: { icon: MinusCircle, className: "" },
};

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
