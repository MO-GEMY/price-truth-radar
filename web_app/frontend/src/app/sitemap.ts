import type { MetadataRoute } from "next";
import type { CompareResponse, RadarFeedResponse } from "@/types/contract";
import { fetchJson, fetchSitemapEntries, isApiConfigured } from "@/lib/api";
import { CANONICAL_CATEGORIES, SITE_URL, absoluteUrl } from "@/lib/site";

export const revalidate = 3600;

const SITEMAP_FETCH_TIMEOUT_MS = 4500;
const MAX_PRODUCT_URLS = 500;

/**
 * Fast, curated sitemap covering:
 * 1. Core top-level routes (`/`, `/deals`, `/compare`)
 * 2. All 10 canonical category landing URLs (`/?category=...`)
 * 3. Top cross-store matched products + active catalog products (capped at 500
 *    so sitemap generation stays fast and resilient even if the backend is slow).
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date().toISOString();

  const core: MetadataRoute.Sitemap = [
    { url: absoluteUrl("/"), lastModified: now, changeFrequency: "daily", priority: 1.0 },
    { url: absoluteUrl("/deals"), lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: absoluteUrl("/compare"), lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: absoluteUrl("/about"), lastModified: now, changeFrequency: "monthly", priority: 0.5 },
    { url: absoluteUrl("/privacy"), lastModified: now, changeFrequency: "monthly", priority: 0.4 },
    { url: absoluteUrl("/terms"), lastModified: now, changeFrequency: "monthly", priority: 0.4 },
    { url: absoluteUrl("/contact"), lastModified: now, changeFrequency: "monthly", priority: 0.5 },
  ];

  const categories: MetadataRoute.Sitemap = CANONICAL_CATEGORIES.map((slug) => ({
    url: absoluteUrl(`/?category=${slug}`),
    lastModified: now,
    changeFrequency: "daily",
    priority: 0.85,
  }));

  const baseEntries: MetadataRoute.Sitemap = [...core, ...categories];
  if (!isApiConfigured()) return baseEntries;

  const seen = new Set<string>(baseEntries.map((entry) => entry.url));
  const productEntries: MetadataRoute.Sitemap = [];
  const origin = new URL(SITE_URL).origin;

  const addProduct = (
    productSkOrPath: string,
    priority: number,
    lastModified?: string,
  ): void => {
    if (productEntries.length >= MAX_PRODUCT_URLS) return;
    const rawPath = productSkOrPath.startsWith("/")
      ? productSkOrPath
      : `/products/${encodeURIComponent(productSkOrPath)}`;
    let candidate: URL;
    try {
      candidate = new URL(rawPath, SITE_URL);
    } catch {
      return;
    }
    if (candidate.origin !== origin || !/^\/products\/[^/]+$/.test(candidate.pathname)) {
      return;
    }
    const url = absoluteUrl(candidate.pathname);
    if (seen.has(url)) return;
    seen.add(url);
    const validLastMod =
      lastModified && Number.isFinite(Date.parse(lastModified)) ? lastModified : undefined;
    productEntries.push({
      url,
      lastModified: validLastMod,
      changeFrequency: "daily",
      priority,
    });
  };

  // Run fast parallel fetches with strict 4.5s timeouts so sitemap never stalls
  const [compareP1, compareP2, feedP1, seoEntries] = await Promise.allSettled([
    fetchJson<CompareResponse>(
      "/api/v1/compare",
      { page: 1, limit: 50 },
      undefined,
      SITEMAP_FETCH_TIMEOUT_MS,
    ),
    fetchJson<CompareResponse>(
      "/api/v1/compare",
      { page: 2, limit: 50 },
      undefined,
      SITEMAP_FETCH_TIMEOUT_MS,
    ),
    fetchJson<RadarFeedResponse>(
      "/api/v1/radar/feed",
      { category: "all", sort: "real_discount_pct_desc", page: 1, limit: 50 },
      undefined,
      SITEMAP_FETCH_TIMEOUT_MS,
    ),
    fetchSitemapEntries(undefined, SITEMAP_FETCH_TIMEOUT_MS),
  ]);

  // 1. Prioritize exact cross-store matched products (highest search & comparison intent)
  for (const res of [compareP1, compareP2]) {
    if (res.status !== "fulfilled") continue;
    for (const group of res.value.items ?? []) {
      for (const listing of group.listings_json ?? []) {
        if (listing.product_sk) {
          addProduct(listing.product_sk, 0.8, now);
        }
      }
    }
  }

  // 2. Top real-discount / active feed products
  if (feedP1.status === "fulfilled") {
    for (const item of feedP1.value.items ?? []) {
      if (item.product_sk) {
        addProduct(item.product_sk, 0.75, item.last_updated_at);
      }
    }
  }

  // 3. Fill remaining slots (up to MAX_PRODUCT_URLS) from /api/seo/sitemap-entries
  if (seoEntries.status === "fulfilled" && seoEntries.value) {
    for (const entry of seoEntries.value) {
      if (!entry.loc) continue;
      addProduct(entry.loc, 0.7, entry.lastmod);
    }
  }

  return [...baseEntries, ...productEntries];
}
