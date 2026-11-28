import type { NextConfig } from "next";

/**
 * Aggressive Cloudflare Edge caching to keep the Free Tier Worker under its
 * 10ms CPU limit by serving repeat visitors and crawlers directly from Edge:
 * - Dynamic browse/listing pages: 5m fresh at Edge + 1h stale-while-revalidate
 * - Product detail, sitemaps, and static pages: 1h fresh at Edge + 24h SWR
 */
const LISTING_EDGE_CACHE = "public, s-maxage=300, stale-while-revalidate=3600";
const DETAIL_EDGE_CACHE = "public, s-maxage=3600, stale-while-revalidate=86400";

function edgeCacheHeaders(policy: string) {
  return [
    { key: "Cache-Control", value: policy },
    { key: "CDN-Cache-Control", value: policy },
    { key: "Cloudflare-CDN-Cache-Control", value: policy },
  ];
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  images: {
    unoptimized: true,
  },
  async headers() {
    const listingHeaders = edgeCacheHeaders(LISTING_EDGE_CACHE);
    const detailHeaders = edgeCacheHeaders(DETAIL_EDGE_CACHE);
    return [
      // Home, deals, compare, coupons, tags & category listings (5m Edge + 1h SWR)
      { source: "/", headers: listingHeaders },
      { source: "/deals", headers: listingHeaders },
      { source: "/compare", headers: listingHeaders },
      { source: "/coupons", headers: listingHeaders },
      { source: "/tags", headers: listingHeaders },
      { source: "/category/:slug", headers: listingHeaders },

      // Product detail pages, OG images & sitemaps (1h Edge + 24h SWR)
      { source: "/products/:product_sk", headers: detailHeaders },
      { source: "/products/:product_sk/opengraph-image", headers: detailHeaders },
      { source: "/opengraph-image", headers: detailHeaders },
      { source: "/deals/opengraph-image", headers: detailHeaders },
      { source: "/compare/opengraph-image", headers: detailHeaders },
      { source: "/sitemap.xml", headers: detailHeaders },
      { source: "/sitemaps/:name", headers: detailHeaders },
      { source: "/robots.txt", headers: detailHeaders },
      { source: "/ads.txt", headers: detailHeaders },

      // Static informational & legal pages (1h Edge + 24h SWR)
      { source: "/about", headers: detailHeaders },
      { source: "/privacy", headers: detailHeaders },
      { source: "/terms", headers: detailHeaders },
      { source: "/contact", headers: detailHeaders },
      { source: "/disclaimer", headers: detailHeaders },
      { source: "/add-store", headers: detailHeaders },
    ];
  },
};

export default nextConfig;
