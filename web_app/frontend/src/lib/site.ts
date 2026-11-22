/**
 * Site-level constants for SEO surfaces (robots.ts, sitemap.ts, metadata,
 * OpenGraph cards). The public base URL comes from `NEXT_PUBLIC_SITE_URL`
 * and falls back to the Vercel deployment domain.
 */

export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ??
  "https://price-truth-radar.vercel.app"
)
  .trim()
  .replace(/\/+$/, "");

export const SITE_NAME = "Price Truth Radar";
export const SITE_NAME_AR = "رادار الحقيقة السعرية";

export function absoluteUrl(path: string): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${SITE_URL}${clean}`;
}
