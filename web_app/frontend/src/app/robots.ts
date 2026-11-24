import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * Crawler access rules engineered to protect Neon Free Tier CU-hrs:
 * - Allows clean canonical routes (`/`, `/products/<sk>`, `/category/<slug>`,
 *   `/deals`, `/compare`, `/sitemap.xml`, `/sitemaps/*`, `/ads.txt`).
 * - Blocks ALL query-string URLs (`/*?*`) as well as `/search`, `/go/`,
 *   `/api/`, and `/_next/` so bots never trigger GIN trigram search queries,
 *   dynamic filter/sort combinations, or pagination crawls against Neon.
 *
 * Note on RFC 9309 longest-match precedence: keeping `allow: "/"` (length 1)
 * guarantees `disallow: "/*?*"` (length 4) always wins on parameterized URLs
 * such as `/products/<sk>?from=...` or `/deals?tab=scandals`.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/*?*",
          "/search",
          "/go/",
          "/api/",
          "/_next/",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
