import { fetchSitemapChunk, isApiConfigured } from "@/lib/api";
import { CANONICAL_CATEGORIES, SITE_URL, absoluteUrl } from "@/lib/site";

export const dynamic = "force-dynamic";

const SITEMAP_FETCH_TIMEOUT_MS = 15000;
const MAX_CHUNKS = 10;

const SITEMAP_CACHE_EDGE = "public, s-maxage=3600, stale-while-revalidate=86400";
const SITEMAP_CACHE_404 = "public, s-maxage=3600, stale-while-revalidate=86400";

const XML_ESCAPE_RE = /[&<>"']/g;
const XML_ESCAPE_MAP: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&apos;",
};
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$/;

function escapeXml(value: string): string {
  return XML_ESCAPE_RE.test(value)
    ? value.replace(XML_ESCAPE_RE, (ch) => XML_ESCAPE_MAP[ch])
    : value;
}

interface UrlEntry {
  loc: string;
  lastmod?: string;
  changefreq?: "daily" | "weekly" | "monthly";
  priority?: string;
}

function renderUrlSet(urls: UrlEntry[]): string {
  const parts: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n',
  ];
  for (let i = 0; i < urls.length; i++) {
    const u = urls[i];
    parts.push("  <url>\n    <loc>", escapeXml(u.loc), "</loc>\n");
    if (u.lastmod) parts.push("    <lastmod>", u.lastmod, "</lastmod>\n");
    if (u.changefreq) parts.push("    <changefreq>", u.changefreq, "</changefreq>\n");
    if (u.priority) parts.push("    <priority>", u.priority, "</priority>\n");
    parts.push("  </url>\n");
  }
  parts.push("</urlset>\n");
  return parts.join("");
}

function xmlResponse(xml: string, cacheControl: string): Response {
  return new Response(xml, {
    status: 200,
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": cacheControl,
      "CDN-Cache-Control": cacheControl,
      "Cloudflare-CDN-Cache-Control": cacheControl,
    },
  });
}

function buildStaticSitemap(): Response {
  const today = new Date().toISOString().slice(0, 10);
  const core: UrlEntry[] = [
    { loc: absoluteUrl("/"), lastmod: today, changefreq: "daily", priority: "1.0" },
    { loc: absoluteUrl("/deals"), lastmod: today, changefreq: "daily", priority: "0.9" },
    { loc: absoluteUrl("/compare"), lastmod: today, changefreq: "daily", priority: "0.9" },
    { loc: absoluteUrl("/coupons"), lastmod: today, changefreq: "daily", priority: "0.85" },
    ...CANONICAL_CATEGORIES.map((slug) => ({
      loc: absoluteUrl(`/category/${slug}`),
      lastmod: today,
      changefreq: "daily" as const,
      priority: "0.85",
    })),
    { loc: absoluteUrl("/add-store"), lastmod: today, changefreq: "monthly", priority: "0.6" },
    { loc: absoluteUrl("/about"), lastmod: today, changefreq: "monthly", priority: "0.5" },
    { loc: absoluteUrl("/contact"), lastmod: today, changefreq: "monthly", priority: "0.5" },
    { loc: absoluteUrl("/disclaimer"), lastmod: today, changefreq: "monthly", priority: "0.4" },
    { loc: absoluteUrl("/privacy"), lastmod: today, changefreq: "monthly", priority: "0.4" },
    { loc: absoluteUrl("/terms"), lastmod: today, changefreq: "monthly", priority: "0.4" },
  ];

  return xmlResponse(renderUrlSet(core), SITEMAP_CACHE_EDGE);
}

/**
 * Sub-sitemap route handler engineered for <2ms Worker CPU even on 25k-row chunks:
 * - Avoids `new URL()` and `new Date()` per item inside the loop.
 * - Emits Cache-Control + CDN-Cache-Control + Cloudflare-CDN-Cache-Control.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ name: string }> },
): Promise<Response> {
  const { name } = await context.params;

  if (name === "static.xml") {
    return buildStaticSitemap();
  }

  const chunkMatch = /^products-([1-9]\d*)\.xml$/.exec(name);
  if (!chunkMatch) {
    return new Response("Not Found", {
      status: 404,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": SITEMAP_CACHE_404,
        "CDN-Cache-Control": SITEMAP_CACHE_404,
        "Cloudflare-CDN-Cache-Control": SITEMAP_CACHE_404,
      },
    });
  }

  const chunkId = Number(chunkMatch[1]);
  if (!Number.isInteger(chunkId) || chunkId < 1 || chunkId > MAX_CHUNKS) {
    return new Response("Not Found", {
      status: 404,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": SITEMAP_CACHE_404,
        "CDN-Cache-Control": SITEMAP_CACHE_404,
        "Cloudflare-CDN-Cache-Control": SITEMAP_CACHE_404,
      },
    });
  }

  if (!isApiConfigured()) {
    return new Response("Sitemap backend unavailable", {
      status: 503,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
        "Retry-After": "300",
      },
    });
  }

  const chunk = await fetchSitemapChunk(chunkId, undefined, SITEMAP_FETCH_TIMEOUT_MS);
  if (!chunk) {
    // Never cache a transient backend failure on Cloudflare edge
    return new Response("Sitemap chunk temporarily unavailable", {
      status: 503,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
        "Retry-After": "300",
      },
    });
  }

  const products = chunk.products ?? [];
  const seen = new Set<string>();
  const priority = chunkId <= 3 ? "0.8" : "0.75";
  const prefix = `${SITE_URL}/products/`;
  const parts: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n',
  ];

  for (let i = 0; i < products.length; i++) {
    const item = products[i];
    const sk = item?.product_sk;
    if (!sk || seen.has(sk)) continue;
    seen.add(sk);

    const encodedSk = encodeURIComponent(sk);
    parts.push("  <url>\n    <loc>", prefix, encodedSk, "</loc>\n");

    const rawLastMod = item.last_updated;
    if (rawLastMod && ISO_DATE_RE.test(rawLastMod)) {
      parts.push("    <lastmod>", rawLastMod, "</lastmod>\n");
    }
    parts.push("    <changefreq>weekly</changefreq>\n    <priority>", priority, "</priority>\n  </url>\n");
  }

  parts.push("</urlset>\n");
  return xmlResponse(parts.join(""), SITEMAP_CACHE_EDGE);
}
