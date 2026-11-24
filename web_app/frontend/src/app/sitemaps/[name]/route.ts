import { fetchSitemapChunk, isApiConfigured } from "@/lib/api";
import { CANONICAL_CATEGORIES, SITE_URL, absoluteUrl } from "@/lib/site";

export const dynamic = "force-dynamic";

const SITEMAP_FETCH_TIMEOUT_MS = 15000;
const MAX_CHUNKS = 4;

const SITEMAP_CACHE_7D = "public, s-maxage=604800, stale-while-revalidate=604800";
const SITEMAP_CACHE_1H = "public, s-maxage=3600, stale-while-revalidate=86400";

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

interface UrlEntry {
  loc: string;
  lastmod?: string;
  changefreq?: "daily" | "weekly" | "monthly";
  priority?: string;
}

function renderUrlSet(urls: UrlEntry[]): string {
  const body = urls
    .map((u) => {
      const lines = [`  <url>`, `    <loc>${escapeXml(u.loc)}</loc>`];
      if (u.lastmod) lines.push(`    <lastmod>${escapeXml(u.lastmod)}</lastmod>`);
      if (u.changefreq) lines.push(`    <changefreq>${u.changefreq}</changefreq>`);
      if (u.priority) lines.push(`    <priority>${u.priority}</priority>`);
      lines.push(`  </url>`);
      return lines.join("\n");
    })
    .join("\n");

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    body,
    "</urlset>",
    "",
  ].join("\n");
}

function xmlResponse(xml: string, cacheControl: string): Response {
  return new Response(xml, {
    status: 200,
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": cacheControl,
      "CDN-Cache-Control": cacheControl,
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

  return xmlResponse(renderUrlSet(core), SITEMAP_CACHE_7D);
}

/**
 * Sub-sitemap route handler:
 * - `/sitemaps/static.xml`: Core pages + 10 clean canonical `/category/<slug>` URLs (0 DB calls).
 * - `/sitemaps/products-1.xml` .. `/sitemaps/products-4.xml`: Up to 10,000 prioritized products
 *   (2,500 per chunk) backed by FastAPI's single 24h-cached 10k query and cached 7 days on Cloudflare.
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
        "Cache-Control": SITEMAP_CACHE_1H,
      },
    });
  }

  const chunkId = Number(chunkMatch[1]);
  if (!Number.isInteger(chunkId) || chunkId < 1 || chunkId > MAX_CHUNKS) {
    return new Response("Not Found", {
      status: 404,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": SITEMAP_CACHE_1H,
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
    // Never cache a transient backend failure for 7 days on Cloudflare edge
    return new Response("Sitemap chunk temporarily unavailable", {
      status: 503,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
        "Retry-After": "300",
      },
    });
  }

  const origin = new URL(SITE_URL).origin;
  const seen = new Set<string>();
  const priority = chunkId <= 3 ? "0.8" : "0.75";
  const urls: UrlEntry[] = [];

  for (const item of chunk.products ?? []) {
    if (!item?.product_sk) continue;
    const rawPath = `/products/${encodeURIComponent(item.product_sk)}`;
    let candidate: URL;
    try {
      candidate = new URL(rawPath, SITE_URL);
    } catch {
      continue;
    }
    if (candidate.origin !== origin || !/^\/products\/[^/]+$/.test(candidate.pathname)) {
      continue;
    }
    const loc = absoluteUrl(candidate.pathname);
    if (seen.has(loc)) continue;
    seen.add(loc);

    const validLastMod =
      item.last_updated && Number.isFinite(Date.parse(item.last_updated))
        ? new Date(item.last_updated).toISOString()
        : undefined;

    urls.push({
      loc,
      lastmod: validLastMod,
      changefreq: "weekly",
      priority,
    });
  }

  return xmlResponse(renderUrlSet(urls), urls.length > 0 ? SITEMAP_CACHE_7D : SITEMAP_CACHE_1H);
}
