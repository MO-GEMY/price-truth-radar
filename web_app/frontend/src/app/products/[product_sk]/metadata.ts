import type { Metadata } from "next";
import { formatPrice } from "@/lib/format";
import { isStaleObservation, observedTimestamp } from "@/lib/highlights";
import { loadProduct } from "@/lib/product-server";
import { SITE_NAME, absoluteUrl } from "@/lib/site";
import { storeDisplayName } from "@/lib/stores";
import type { Lang } from "@/lib/i18n";

export async function productMetadata(productSk: string, sample: boolean): Promise<Metadata> {
  if (sample) return { title: "Sample price receipt", robots: { index: false } };
  const load = await loadProduct(productSk, false);
  if (load.status === "missing") return { title: "Product not found", robots: { index: false } };
  if (load.status !== "ready" || load.result.source !== "api") return { title: "Check a product", robots: { index: false } };
  const { product } = load.result.data;
  const store = storeDisplayName(product.store_name, "en");
  const timestamp = observedTimestamp(product.last_updated_at);
  const price = timestamp && !isStaleObservation(timestamp) ? formatPrice(product.current_price, "en") : null;
  const title = `${product.product_title} | ${store}`;
  const descriptionEn = price
    ? `Observed at ${store} for ${price}. Check the retailer’s price history and matched offers.`
    : `Check price history and matched offers for this listing at ${store}.`;

  const descriptionAr = `شوف سجل الأسعار والعروض المطابقة في ${storeDisplayName(
    product.store_name,
    "ar" as Lang,
  )}.`;
  const canonical = absoluteUrl(`/products/${encodeURIComponent(productSk)}`);

  return {
    title,
    description: descriptionEn,
    alternates: { canonical },
    openGraph: {
      title,
      description: `${descriptionEn} ${descriptionAr}`,
      url: canonical,
      siteName: SITE_NAME,
      locale: "ar_EG",
      alternateLocale: ["en_US"],
      type: "website",
      images: [
        {
          url: `${canonical}/opengraph-image`,
          width: 1200,
          height: 630,
          alt: product.product_title,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description: descriptionEn,
      images: [`${canonical}/opengraph-image`],
    },
  };
}
