/**
 * Lightweight, SSR-safe Google Analytics 4 (GA4) event tracking helper for Asarak (أسعارك).
 * Zero external dependencies — silently no-ops during SSR or when GA4 is not configured.
 */

type GtagEventParams = Record<string, string | number | boolean | undefined>;

declare global {
  interface Window {
    gtag?: (
      command: "event" | "config" | "js",
      target: string | Date,
      params?: GtagEventParams,
    ) => void;
    dataLayer?: unknown[];
    ttq?: {
      page?: () => void;
      track?: (event: string, params?: Record<string, unknown>) => void;
    };
  }
}

export function trackEvent(eventName: string, params?: GtagEventParams): void {
  if (typeof window === "undefined") return;
  try {
    if (typeof window.gtag !== "function") return;
    window.gtag("event", eventName, params);
  } catch {
    // Ignore analytics failures (ad blockers, strict privacy browsers, etc.)
  }
}

export function trackSearchProduct(params: {
  query: string;
  isUrl: boolean;
  matchType?: string;
  resultsCount?: number;
}): void {
  const sanitizedTerm = params.isUrl
    ? "retailer_url"
    : params.query.trim().slice(0, 100);
  trackEvent("search_product", {
    search_term: sanitizedTerm,
    search_mode: params.isUrl ? "url" : "text",
    match_type: params.matchType,
    results_count: params.resultsCount,
  });
}

export function trackViewProduct(params: {
  productSk: string;
  productTitle: string;
  storeName: string;
  category: string;
  priceEgp: number;
  verdict?: string;
}): void {
  trackEvent("view_product", {
    item_id: params.productSk,
    item_name: params.productTitle.slice(0, 120),
    store_name: params.storeName,
    item_category: params.category,
    currency: "EGP",
    value: Number.isFinite(params.priceEgp) ? params.priceEgp : undefined,
    discount_verdict: params.verdict,
  });
}

export interface StoreOutboundEventParams {
  store: string;
  product_id: string;
  price?: number;
  category?: string;
  is_affiliate: boolean;
  network?: string;
  placement?: "product_hero" | "alternatives_table" | "similar_alternatives";
}

export function trackStoreOutbound(params: StoreOutboundEventParams): void {
  const validPrice =
    typeof params.price === "number" && Number.isFinite(params.price)
      ? params.price
      : undefined;

  trackEvent("click_store_outbound", {
    store: params.store,
    product_id: params.product_id,
    price: validPrice,
    category: params.category,
    currency: "EGP",
    value: validPrice,
    is_affiliate: params.is_affiliate,
    network: params.network ?? "direct",
    placement: params.placement,
  });
}
