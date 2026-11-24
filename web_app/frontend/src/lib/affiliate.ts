/**
 * Config-driven outbound affiliate link wrapper for Asarak (أسعارك).
 *
 * Strictly pass-through when a retailer's affiliate credentials are empty,
 * and ready to activate per store via environment variables without touching
 * component code. Always pair outbound retailer links with
 * `target="_blank"` and `rel={OUTBOUND_LINK_REL}`.
 */

import { retailerHref } from "./offers";

export const OUTBOUND_LINK_REL = "sponsored noopener noreferrer";

interface StoreAffiliateRule {
  /** Query parameter name appended to the destination URL (e.g. `tag` for Amazon). */
  param?: string;
  /** Value for `param` (empty string disables wrapping for this store). */
  value: string;
  /**
   * Optional redirect-network wrapper prefix (e.g. Admitad / ArabClicks deeplink
   * base ending in `?ulp=`). When non-empty, the destination URL is URL-encoded
   * and appended to this prefix.
   */
  redirectPrefix?: string;
}

const AFFILIATE_CONFIG: Readonly<Record<string, StoreAffiliateRule>> = {
  amazon_eg: {
    param: "tag",
    value: (process.env.NEXT_PUBLIC_AFFILIATE_AMAZON_TAG ?? "").trim(),
  },
  noon: {
    param: "utm_source",
    value: (process.env.NEXT_PUBLIC_AFFILIATE_NOON_ID ?? "").trim(),
    redirectPrefix: (process.env.NEXT_PUBLIC_AFFILIATE_NOON_PREFIX ?? "").trim(),
  },
  jumia: {
    param: "utm_source",
    value: (process.env.NEXT_PUBLIC_AFFILIATE_JUMIA_ID ?? "").trim(),
    redirectPrefix: (process.env.NEXT_PUBLIC_AFFILIATE_JUMIA_PREFIX ?? "").trim(),
  },
  btech: {
    param: "utm_source",
    value: (process.env.NEXT_PUBLIC_AFFILIATE_BTECH_ID ?? "").trim(),
    redirectPrefix: (process.env.NEXT_PUBLIC_AFFILIATE_BTECH_PREFIX ?? "").trim(),
  },
  carrefour_eg: {
    param: "utm_source",
    value: (process.env.NEXT_PUBLIC_AFFILIATE_CARREFOUR_ID ?? "").trim(),
    redirectPrefix: (process.env.NEXT_PUBLIC_AFFILIATE_CARREFOUR_PREFIX ?? "").trim(),
  },
  adidas_eg: {
    param: "utm_source",
    value: (process.env.NEXT_PUBLIC_AFFILIATE_ADIDAS_ID ?? "").trim(),
    redirectPrefix: (process.env.NEXT_PUBLIC_AFFILIATE_ADIDAS_PREFIX ?? "").trim(),
  },
};

/**
 * Validates `rawUrl` as http/https and applies configured affiliate tracking
 * for `storeName` when active. Returns null for invalid/unsafe URLs.
 */
export function buildAffiliateUrl(
  rawUrl: string | null | undefined,
  storeName?: string | null,
): string | null {
  if (!rawUrl) return null;
  const safeUrl = retailerHref(rawUrl);
  if (!safeUrl) return null;

  const key = (storeName ?? "").trim().toLowerCase();
  const rule = key ? AFFILIATE_CONFIG[key] : undefined;
  if (!rule) return safeUrl;

  if (rule.redirectPrefix) {
    return `${rule.redirectPrefix}${encodeURIComponent(safeUrl)}`;
  }

  if (rule.param && rule.value) {
    try {
      const parsed = new URL(safeUrl);
      parsed.searchParams.set(rule.param, rule.value);
      return parsed.toString();
    } catch {
      return safeUrl;
    }
  }

  return safeUrl;
}
