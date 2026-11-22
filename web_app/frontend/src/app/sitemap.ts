import type { MetadataRoute } from "next";
import { fetchSitemapEntries } from "@/lib/api";
import { SITE_URL, absoluteUrl } from "@/lib/site";

/**
 * Dynamic sitemap: product/compare slugs from
 * `GET /api/seo/sitemap-entries` when the backend serves them, with a
 * graceful fallback to the core static routes so the file always exists.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const core: MetadataRoute.Sitemap = [
    { url: absoluteUrl("/"), lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: absoluteUrl("/deals"), lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: absoluteUrl("/compare"), lastModified: now, changeFrequency: "daily", priority: 0.8 },
  ];

  try {
    const entries = await fetchSitemapEntries();
    if (!entries || entries.length === 0) return core;

    const dynamic: MetadataRoute.Sitemap = [];
    for (const entry of entries) {
      const raw = entry.loc;
      if (!raw) continue; // absolute URLs pass through as-is
      const url = raw.startsWith("http")
        ? raw
        : raw.startsWith("/")
          ? absoluteUrl(raw)
          : `${SITE_URL}/${raw.replace(/^\/+/, "")}`;
      dynamic.push({
        url,
        lastModified: entry.lastmod ? new Date(entry.lastmod) : now,
        changeFrequency: "daily",
        priority: 0.7,
      });
    }
    return [...core, ...dynamic];
  } catch {
    return core;
  }
}
