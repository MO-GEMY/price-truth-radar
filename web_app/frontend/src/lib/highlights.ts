import type { HighlightItem } from "@/types/contract";

export interface PriceHighlight {
  id: string | null;
  title: string | null;
  store: string | null;
  category: string | null;
  image: string | null;
  price: number | null;
  advertisedPrice: number | null;
  baseline: number | null;
  observedSavings: number | null;
  advertisedSavings: number | null;
  priceHike: boolean;
  variantLabel: string | null;
  variantCount: number;
  hasMultipleVariants: boolean;
  minVariantPrice: number | null;
  maxVariantPrice: number | null;
}

function text(value: string | null | undefined): string | null {
  return typeof value === "string" ? value.trim() || null : null;
}

function positive(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

export function normalizeHighlight(item: HighlightItem): PriceHighlight {
  const price = positive(item.current_price);
  const advertisedPrice = positive(item.claimed_old_price ?? item.claimed_original_price);
  const baseline = positive(item.baseline_price ?? item.rolling_60d_median);
  const variantCount = typeof item.variant_count === "number" && item.variant_count > 1
    ? Math.floor(item.variant_count)
    : 1;
  const hasMultipleVariants = Boolean(item.has_multiple_variants || variantCount > 1);
  const minVariantPrice = positive(item.min_variant_price) ?? price;
  const maxVariantPrice = positive(item.max_variant_price) ?? price;
  return {
    id: text(item.id) ?? text(item.product_sk),
    title: text(item.title) ?? text(item.product_title),
    store: text(item.store_name),
    category: text(item.category),
    image: text(item.image_url),
    price,
    advertisedPrice,
    baseline,
    observedSavings: price !== null && baseline !== null ? (baseline - price) / baseline * 100 : null,
    advertisedSavings: price !== null && advertisedPrice !== null && advertisedPrice > price
      ? (advertisedPrice - price) / advertisedPrice * 100
      : null,
    priceHike: item.verdict === "inflated_before_sale" || item.discount_verdict === "PRESALE_HIKE",
    variantLabel: text(item.variant_label),
    variantCount,
    hasMultipleVariants,
    minVariantPrice,
    maxVariantPrice,
  };
}

export function observedTimestamp(value: string | null | undefined): string | null {
  return value && Number.isFinite(Date.parse(value)) ? value : null;
}

export function isStaleObservation(value: string | null | undefined, now = Date.now()): boolean {
  return Boolean(value && now - Date.parse(value) > 48 * 60 * 60 * 1000);
}
