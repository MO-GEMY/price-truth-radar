import { BadgeCheck, MinusCircle, ShieldAlert, TrendingDown, TrendingUp, type LucideIcon } from "lucide-react";
import type { DiscountVerdict, PriceHistoryPoint, Product } from "@/types/contract";

export const VERDICT_TONES: Record<DiscountVerdict, { icon: LucideIcon; className: string }> = {
  FAKE_DISCOUNT: { icon: ShieldAlert, className: "ptr-badge-warning" },
  ALL_TIME_LOW: { icon: TrendingDown, className: "ptr-badge-good" },
  GENUINE_DEAL: { icon: BadgeCheck, className: "ptr-badge-good" },
  PRESALE_HIKE: { icon: TrendingUp, className: "ptr-badge-amber" },
  NORMAL_PRICE: { icon: MinusCircle, className: "" },
};

export const VERDICT_ORDER = Object.keys(VERDICT_TONES) as DiscountVerdict[];

/**
 * Mirrors the dbt history gate in `mart_product_verdicts.sql`:
 * A product needs >= 3 distinct snapshot dates OR an observed price change
 * across >= 2 dates before historical verdict rules activate.
 *
 * Keeps product cards and the product detail page 100% consistent by showing
 * the neutral "History is building" badge on both surfaces whenever a listing
 * lacks sufficient history.
 */
export function hasSufficientPriceHistory(
  product: Pick<Product, "min_historical_price" | "max_historical_price" | "real_discount_pct" | "discount_verdict">,
  history?: Pick<PriceHistoryPoint, "snapshot_date" | "price">[],
): boolean {
  const hasObservedPriceChange =
    Math.abs(product.max_historical_price - product.min_historical_price) > 0.005;

  if (history) {
    const distinctDates = new Set(history.map((point) => point.snapshot_date)).size;
    if (distinctDates >= 3) return true;
    if (distinctDates >= 2 && hasObservedPriceChange) return true;
    return false;
  }

  // Listing cards do not receive the full history array; infer building state
  // cleanly from the verdict + flat min/max/median signals.
  if (product.discount_verdict !== "NORMAL_PRICE") return true;
  if (hasObservedPriceChange || Math.abs(product.real_discount_pct) >= 0.05) return true;
  return false;
}
