import type { MetadataRoute } from "next";
import { fetchSitemapEntries } from "@/lib/api";
import { SITE_URL, absoluteUrl } from "@/lib/site";

/**
 * Dynamic sitemap: product/compare slugs from
 * `GET /api/seo/sitemap-entries` when the backend serves them, with a
 * graceful fallback to the core static routes so the file always exists.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const core: MetadataRoute.Sitemap = [
    { url: absoluteUrl("/"), changeFrequency: "daily", priority: 1 },
    { url: absoluteUrl("/deals"), changeFrequency: "daily", priority: 0.9 },
    { url: absoluteUrl("/compare"), changeFrequency: "daily", priority: 0.8 },
  ];

  try {
    const entries = await fetchSitemapEntries();
    if (!entries || entries.length === 0) return core;

    const dynamic: MetadataRoute.Sitemap = [];
    const seen = new Set(core.map((entry) => entry.url));
    const origin = new URL(SITE_URL).origin;
    for (const entry of entries) {
      if (!entry.loc) continue;
      let candidate: URL;
      try { candidate = new URL(entry.loc, SITE_URL); } catch { continue; }
      if (candidate.origin !== origin || !/^\/products\/[^/]+$/.test(candidate.pathname)) continue;
      const url = absoluteUrl(candidate.pathname);
      if (seen.has(url)) continue;
      seen.add(url);
      const lastModified = entry.lastmod && Number.isFinite(Date.parse(entry.lastmod)) ? entry.lastmod : undefined;
      dynamic.push({
        url,
        lastModified,
        changeFrequency: "daily",
        priority: 0.7,
      });
    }
    return [...core, ...dynamic];
  } catch {
    return core;
  }
}
