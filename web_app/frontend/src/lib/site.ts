/**
 * Site-level constants and URL/image validators for SEO surfaces (robots.ts,
 * sitemap.ts, metadata, OpenGraph cards, JSON-LD).
 */

import type { Category } from "@/types/contract";

export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ??
  "https://price-truth-radar.vercel.app"
)
  .trim()
  .replace(/\/+$/, "");

export const SITE_NAME = "Price Truth Radar";
export const SITE_NAME_AR = "رادار الحقيقة السعرية";
export const SITE_NAME_BILINGUAL = `${SITE_NAME_AR} | ${SITE_NAME}`;

export const DEFAULT_OG_IMAGE_PATH = "/opengraph-image";

export const LAUNCH_STORE_COUNT = "172";
export const LAUNCH_PRODUCT_COUNT = "100,000+";

export const CANONICAL_CATEGORIES: readonly Category[] = [
  "electronics",
  "home_appliances",
  "home_furniture",
  "fashion",
  "beauty",
  "groceries",
  "health",
  "sports",
  "pet_care",
  "baby_kids",
] as const;

export function absoluteUrl(path: string): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${SITE_URL}${clean}`;
}

/**
 * Returns a clean, verified HTTPS image URL suitable for OpenGraph/Twitter
 * cards and JSON-LD Product schema, or null if the URL is missing, non-HTTPS,
 * local/private, SVG, or a placeholder asset.
 */
export function verifiedHttpsImageUrl(raw: string | null | undefined): string | null {
  if (!raw || typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (!trimmed || trimmed.length > 2048) return null;
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "https:") return null;
    const host = parsed.hostname.toLowerCase();
    if (
      !host ||
      host === "localhost" ||
      host.endsWith(".local") ||
      host.startsWith("127.") ||
      host.startsWith("10.") ||
      host.startsWith("192.168.")
    ) {
      return null;
    }
    const lowerPath = parsed.pathname.toLowerCase();
    if (lowerPath.endsWith(".svg") || lowerPath.includes("placeholder")) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}
