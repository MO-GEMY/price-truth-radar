/**
 * XSS-safe Schema.org Product + AggregateOffer JSON-LD generator for
 * product detail pages (`/products/[product_sk]`).
 *
 * Uses `AggregateOffer` across all products because Asarak (`asarak.com`) is a
 * price-comparison aggregator rather than a direct merchant.
 */

import type { ProductDetailResponse } from "@/types/contract";
import { DEFAULT_OG_IMAGE_PATH, absoluteUrl, verifiedHttpsImageUrl } from "./site";

const IN_STOCK = "https://schema.org/InStock";
const OUT_OF_STOCK = "https://schema.org/OutOfStock";
const GTIN_RE = /^\d{8}(?:\d{4,6})?$/;

function cleanPrice(value: number): number {
  return Math.round(value * 100) / 100;
}

function extractGtin(attrs: Record<string, unknown> | null | undefined): string | null {
  if (!attrs || typeof attrs !== "object") return null;
  for (const key of ["ean", "gtin", "gtin13", "gtin14", "gtin12", "gtin8"] as const) {
    const raw = attrs[key];
    if (typeof raw !== "string" && typeof raw !== "number") continue;
    const digits = String(raw).replace(/\D/g, "");
    if (GTIN_RE.test(digits)) return digits;
  }
  return null;
}

function meaningfulBrand(brand: string | null | undefined): string | null {
  if (!brand) return null;
  const trimmed = brand.trim();
  if (!trimmed) return null;
  const low = trimmed.toLowerCase();
  if (low === "unknown" || low === "generic" || low === "other" || low === "n/a") return null;
  return trimmed;
}

export function buildProductJsonLd(
  detail: ProductDetailResponse,
  canonicalUrl: string,
  description?: string,
): Record<string, unknown> {
  const { product, alternatives } = detail;
  const image = verifiedHttpsImageUrl(product.image_url) ?? absoluteUrl(DEFAULT_OG_IMAGE_PATH);

  const schema: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: product.product_title,
    url: canonicalUrl,
    sku: product.product_sk,
    category: product.category,
    image: [image],
  };

  if (description) {
    schema.description = description;
  }

  const brand = meaningfulBrand(product.brand);
  if (brand) {
    schema.brand = {
      "@type": "Brand",
      name: brand,
    };
  }

  const gtin = extractGtin(product.attributes_json);
  if (gtin) {
    if (gtin.length === 13) schema.gtin13 = gtin;
    else schema.gtin = gtin;
  }

  let validOfferCount = 0;
  let inStockCount = 0;
  let inStockMin = Infinity;
  let allMin = Infinity;
  let allMax = -Infinity;

  const recordPrice = (price: number, inStock: boolean, countAsOffer: boolean) => {
    if (!Number.isFinite(price) || price <= 0) return;
    if (countAsOffer) validOfferCount++;
    if (price < allMin) allMin = price;
    if (price > allMax) allMax = price;
    if (inStock) {
      if (countAsOffer) inStockCount++;
      if (price < inStockMin) inStockMin = price;
    }
  };

  recordPrice(product.current_price, product.in_stock, true);
  if (product.has_multiple_variants) {
    if (typeof product.min_variant_price === "number") {
      recordPrice(product.min_variant_price, product.in_stock, false);
    }
    if (typeof product.max_variant_price === "number") {
      recordPrice(product.max_variant_price, product.in_stock, false);
    }
  }
  for (let i = 0; i < alternatives.length; i++) {
    const alt = alternatives[i];
    recordPrice(alt.price, alt.in_stock, true);
  }

  const resolvedLow = inStockCount > 0 && Number.isFinite(inStockMin)
    ? inStockMin
    : Number.isFinite(allMin)
      ? allMin
      : product.current_price;
  const lowPrice = cleanPrice(resolvedLow);
  const highPrice = cleanPrice(
    Number.isFinite(allMax) && allMax >= resolvedLow ? allMax : resolvedLow,
  );

  schema.offers = {
    "@type": "AggregateOffer",
    priceCurrency: "EGP",
    lowPrice,
    highPrice,
    offerCount: Math.max(1, validOfferCount),
    availability: inStockCount > 0 ? IN_STOCK : OUT_OF_STOCK,
    url: canonicalUrl,
  };

  return schema;
}

const JSONLD_ESCAPE_RE = /[<>&\u2028\u2029]/g;
const JSONLD_ESCAPE_MAP: Record<string, string> = {
  "<": "\\u003c",
  ">": "\\u003e",
  "&": "\\u0026",
  "\u2028": "\\u2028",
  "\u2029": "\\u2029",
};

/**
 * Serializes a JSON-LD payload safely for embedding inside a `<script>` tag,
 * neutralizing `</script>`, HTML angle brackets, ampersands, and JS line
 * separators against XSS injection in a single regex pass.
 */
export function serializeJsonLd(payload: Record<string, unknown>): string {
  return JSON.stringify(payload).replace(
    JSONLD_ESCAPE_RE,
    (ch) => JSONLD_ESCAPE_MAP[ch],
  );
}
