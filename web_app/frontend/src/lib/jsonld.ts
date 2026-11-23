/**
 * XSS-safe Schema.org Product + Offer / AggregateOffer JSON-LD generator for
 * product detail pages (`/products/[product_sk]`).
 */

import type { ProductDetailResponse } from "@/types/contract";
import { retailerHref } from "./offers";
import { DEFAULT_OG_IMAGE_PATH, absoluteUrl, verifiedHttpsImageUrl } from "./site";
import { storeDisplayName } from "./stores";

const IN_STOCK = "https://schema.org/InStock";
const OUT_OF_STOCK = "https://schema.org/OutOfStock";
const NEW_CONDITION = "https://schema.org/NewCondition";
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
  const sellerName = storeDisplayName(product.store_name, "en");
  const selfOfferUrl = retailerHref(product.product_url) ?? canonicalUrl;

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

  if (alternatives.length > 0) {
    const allListings = [
      {
        price: product.current_price,
        in_stock: product.in_stock,
        store_name: product.store_name,
        url: selfOfferUrl,
      },
      ...alternatives.map((alt) => ({
        price: alt.price,
        in_stock: alt.in_stock,
        store_name: alt.store_name,
        url: retailerHref(alt.product_url) ?? absoluteUrl(`/products/${encodeURIComponent(alt.product_sk)}`),
      })),
    ].filter((offer) => Number.isFinite(offer.price) && offer.price > 0);

    const inStockListings = allListings.filter((o) => o.in_stock);
    const pricePool = inStockListings.length > 0 ? inStockListings : allListings;
    const prices = pricePool.map((o) => o.price);
    const lowPrice = cleanPrice(Math.min(...prices));
    const highPrice = cleanPrice(Math.max(...prices));

    schema.offers = {
      "@type": "AggregateOffer",
      priceCurrency: "EGP",
      lowPrice,
      highPrice,
      offerCount: allListings.length,
      availability: inStockListings.length > 0 ? IN_STOCK : OUT_OF_STOCK,
      offers: allListings.map((offer) => ({
        "@type": "Offer",
        priceCurrency: "EGP",
        price: cleanPrice(offer.price),
        availability: offer.in_stock ? IN_STOCK : OUT_OF_STOCK,
        itemCondition: NEW_CONDITION,
        url: offer.url,
        seller: {
          "@type": "Organization",
          name: storeDisplayName(offer.store_name, "en"),
        },
      })),
    };
  } else if (
    product.has_multiple_variants &&
    typeof product.min_variant_price === "number" &&
    typeof product.max_variant_price === "number" &&
    product.min_variant_price > 0 &&
    product.max_variant_price > product.min_variant_price
  ) {
    schema.offers = {
      "@type": "AggregateOffer",
      priceCurrency: "EGP",
      lowPrice: cleanPrice(product.min_variant_price),
      highPrice: cleanPrice(product.max_variant_price),
      offerCount: Math.max(2, product.variant_count ?? 2),
      availability: product.in_stock ? IN_STOCK : OUT_OF_STOCK,
      url: selfOfferUrl,
      seller: {
        "@type": "Organization",
        name: sellerName,
      },
    };
  } else {
    schema.offers = {
      "@type": "Offer",
      priceCurrency: "EGP",
      price: cleanPrice(product.current_price),
      availability: product.in_stock ? IN_STOCK : OUT_OF_STOCK,
      itemCondition: NEW_CONDITION,
      url: selfOfferUrl,
      seller: {
        "@type": "Organization",
        name: sellerName,
      },
    };
  }

  return schema;
}

/**
 * Serializes a JSON-LD payload safely for embedding inside a `<script>` tag,
 * neutralizing `</script>`, HTML angle brackets, ampersands, and JS line
 * separators against XSS injection.
 */
export function serializeJsonLd(payload: Record<string, unknown>): string {
  return JSON.stringify(payload)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}
