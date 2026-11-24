import type { NextConfig } from "next";

const PAGE_CDN_CACHE = "public, s-maxage=86400, stale-while-revalidate=604800";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  images: {
    unoptimized: true,
  },
  async headers() {
    const edgePageHeaders = [
      { key: "Cache-Control", value: PAGE_CDN_CACHE },
      { key: "CDN-Cache-Control", value: PAGE_CDN_CACHE },
    ];
    return [
      { source: "/products/:product_sk", headers: edgePageHeaders },
      { source: "/category/:slug", headers: edgePageHeaders },
      { source: "/deals", headers: edgePageHeaders },
      { source: "/compare", headers: edgePageHeaders },
      { source: "/about", headers: edgePageHeaders },
      { source: "/privacy", headers: edgePageHeaders },
      { source: "/terms", headers: edgePageHeaders },
      { source: "/contact", headers: edgePageHeaders },
      { source: "/robots.txt", headers: edgePageHeaders },
    ];
  },
};

export default nextConfig;
