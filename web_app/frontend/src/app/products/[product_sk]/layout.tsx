import type { Metadata } from "next";
import { fetchJson } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { SITE_NAME, absoluteUrl } from "@/lib/site";
import { storeDisplayName } from "@/lib/stores";
import type { Lang } from "@/lib/i18n";
import type { ProductDetailResponse } from "@/types/contract";

const VERDICT_AR: Record<string, string> = {
  FAKE_DISCOUNT: "خصم وهمي",
  GENUINE_DEAL: "عرض حقيقي",
  ALL_TIME_LOW: "أدنى سعر تاريخي",
  PRESALE_HIKE: "رفع قبل العروض",
  NORMAL_PRICE: "السعر الطبيعي",
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ product_sk: string }>;
}): Promise<Metadata> {
  const { product_sk } = await params;

  let product: ProductDetailResponse["product"] | null = null;
  try {
    const detail = await fetchJson<ProductDetailResponse>(
      `/api/v1/products/${encodeURIComponent(product_sk)}`,
      undefined,
    );
    product = detail.product;
  } catch {
    product = null;
  }

  if (!product) {
    return {
      title: "Product not found",
      description: "This product is not in the tracked dataset.",
    };
  }

  const store = storeDisplayName(product.store_name, "en");
  const title = `${product.product_title} — ${formatPrice(
    product.current_price,
    "en",
  )} | ${store}`;
  const isScandal = product.discount_verdict === "FAKE_DISCOUNT" || product.discount_verdict === "PRESALE_HIKE";
  const verdictAr = VERDICT_AR[product.discount_verdict] ?? product.discount_verdict;
  const claimed =
    product.claimed_original_price !== null
      ? ` claimed ${formatPrice(product.claimed_original_price, "en")}`
      : "";
  const descriptionEn = `${verdictAr}: tracked at ${store} for ${formatPrice(
    product.current_price,
    "en",
  )}.${claimed} 60-day median ${formatPrice(product.rolling_60d_median, "en")}.`;

  const descriptionAr = `${verdictAr} — تتبعنا السعر في ${storeDisplayName(
    product.store_name,
    "ar" as Lang,
  )}: ${formatPrice(product.current_price, "ar")} مقابل وسيط 60 يوم ${formatPrice(
    product.rolling_60d_median,
    "ar",
  )}.`;

  return {
    title,
    description: descriptionEn,
    alternates: { canonical: absoluteUrl(`/products/${product_sk}`) },
    openGraph: {
      title,
      description: `${descriptionEn} ${descriptionAr}`,
      url: absoluteUrl(`/products/${product_sk}`),
      siteName: SITE_NAME,
      locale: "ar_EG",
      alternateLocale: ["en_US"],
      type: "website",
      images: [
        {
          url: absoluteUrl(`/products/${product_sk}/opengraph-image`),
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
      images: [absoluteUrl(`/products/${product_sk}/opengraph-image`)],
    },
    other: isScandal
      ? { "product:price:alert": "true" }
      : undefined,
  };
}


export default function ProductLayout({ children }: { children: React.ReactNode }) {
  return children;
}
