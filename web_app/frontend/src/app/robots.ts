import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/products/", "/deals", "/compare"],
        disallow: [
          "/api/",
          "/_next/",
          "/*?*from=*",
          "/*?*sample=*",
          "/*?*page=*",
          "/*?*sort=*",
          "/*?*store=*",
          "/*?*verdict=*",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
