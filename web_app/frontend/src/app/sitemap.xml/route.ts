import { SITE_URL } from "@/lib/site";

export const dynamic = "force-dynamic";

/**
 * Number of prioritized product sub-sitemaps (4 x 2,500 = 10,000 top URLs):
 *   - Priority 1: ~8,080 cross-store matched products (cheapest in-stock offer)
 *   - Priority 2: ~1,920 high-demand electronics/appliances & verified-discount SKUs
 */
const PRODUCT_SITEMAP_CHUNKS = 4;

const SITEMAP_CACHE_HEADER = "public, s-maxage=604800, stale-while-revalidate=604800";

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/**
 * Sitemap Index (`/sitemap.xml`) with zero database or backend calls.
 * Cached 7 days on Cloudflare edge (`s-maxage=604800, stale-while-revalidate=604800`).
 */
export function GET(): Response {
  const today = new Date().toISOString().slice(0, 10);
  const sitemapUrls = [
    `${SITE_URL}/sitemaps/static.xml`,
    ...Array.from(
      { length: PRODUCT_SITEMAP_CHUNKS },
      (_, idx) => `${SITE_URL}/sitemaps/products-${idx + 1}.xml`,
    ),
  ];

  const entriesXml = sitemapUrls
    .map(
      (loc) =>
        `  <sitemap>\n    <loc>${escapeXml(loc)}</loc>\n    <lastmod>${today}</lastmod>\n  </sitemap>`,
    )
    .join("\n");

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    entriesXml,
    "</sitemapindex>",
    "",
  ].join("\n");

  return new Response(xml, {
    status: 200,
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": SITEMAP_CACHE_HEADER,
      "CDN-Cache-Control": SITEMAP_CACHE_HEADER,
    },
  });
}
