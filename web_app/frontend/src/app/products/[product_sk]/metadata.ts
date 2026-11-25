import type { Metadata } from "next";
import type { ProductDetailResponse } from "@/types/contract";
import { loadProduct } from "@/lib/product-server";
import {
  DEFAULT_OG_IMAGE_PATH,
  SITE_NAME_AR,
  SITE_NAME_BILINGUAL,
  absoluteUrl,
  verifiedHttpsImageUrl,
} from "@/lib/site";
import { storeDisplayName } from "@/lib/stores";

function formatEgpPlain(value: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatPctPlain(value: number): string {
  return Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
}

export function buildProductDescription(detail: ProductDetailResponse): string {
  const { product, history, alternatives } = detail;
  const priceText = formatEgpPlain(product.current_price);
  const storeAr = storeDisplayName(product.store_name, "ar");

  const lead = product.in_stock
    ? `السعر الحالي ${priceText} ج.م. في ${storeAr}.`
    : `السعر المرصود ${priceText} ج.م. في ${storeAr} (غير متوفر حالياً).`;

  // 1. Exact cross-store matches take priority when available
  if (alternatives.length > 0) {
    const distinctStores = new Set([
      product.store_name,
      ...alternatives.map((a) => a.store_name),
    ]).size;
    const storeCount = Math.max(2, distinctStores);
    const inStockAlts = alternatives.filter(
      (a) => a.in_stock && Number.isFinite(a.price) && a.price > 0,
    );
    const cheapestAlt = inStockAlts.reduce<(typeof inStockAlts)[number] | null>(
      (best, cur) => (!best || cur.price < best.price ? cur : best),
      null,
    );

    if (cheapestAlt && cheapestAlt.price < product.current_price) {
      const diff = product.current_price - cheapestAlt.price;
      const cheapestStoreAr = storeDisplayName(cheapestAlt.store_name, "ar");
      return `${lead} متوفر أرخص في ${cheapestStoreAr} بسعر ${formatEgpPlain(cheapestAlt.price)} ج.م. (وفر ${formatEgpPlain(diff)} ج.م. عبر ${storeCount} متاجر).`;
    }

    const higherAlt = alternatives
      .filter((a) => Number.isFinite(a.price) && a.price > product.current_price)
      .sort((a, b) => b.price - a.price)[0];

    if (product.in_stock && higherAlt) {
      const diff = higherAlt.price - product.current_price;
      const otherStoreAr = storeDisplayName(higherAlt.store_name, "ar");
      return `${lead} أرخص سعر مرصود بين ${storeCount} متاجر — أقل بـ ${formatEgpPlain(diff)} ج.م. من ${otherStoreAr}.`;
    }

    return `${lead} قارن السعر بين ${storeCount} متاجر مصرية على ${SITE_NAME_AR}.`;
  }

  // 2. Historical verdict context ONLY when real multi-week history exists (>= 7 tracked days)
  const trackedDays =
    typeof product.tracked_days_count === "number" && product.tracked_days_count >= 1
      ? Math.floor(product.tracked_days_count)
      : history.length;
  const maturity =
    product.history_maturity ??
    (trackedDays < 7 ? "EARLY" : trackedDays < 60 ? "GROWING" : "MATURE");
  const windowLabelAr =
    maturity === "MATURE" ? "آخر 60 يوم" : `آخر ${trackedDays} يوم`;
  const verifiedMedian =
    maturity !== "EARLY"
      ? (product.verified_historical_median ??
        (Number.isFinite(product.rolling_60d_median) && product.rolling_60d_median > 0
          ? product.rolling_60d_median
          : null))
      : null;

  if (maturity !== "EARLY") {
    const medianText =
      verifiedMedian !== null && verifiedMedian > 0
        ? formatEgpPlain(verifiedMedian)
        : null;

    if (product.discount_verdict === "ALL_TIME_LOW") {
      return `${lead} أقل سعر مرصود منذ بدء المتابعة (توفير ${formatPctPlain(product.real_discount_pct)}% مقارنة بوسيط ${windowLabelAr}).`;
    }
    if (product.discount_verdict === "GENUINE_DEAL") {
      return medianText
        ? `${lead} خصم حقيقي ${formatPctPlain(product.real_discount_pct)}% مقارنة بوسيط ${windowLabelAr} (${medianText} ج.م.).`
        : `${lead} خصم حقيقي ${formatPctPlain(product.real_discount_pct)}% بناءً على سجل الأسعار.`;
    }
    if (product.discount_verdict === "FAKE_DISCOUNT") {
      return medianText
        ? `${lead} تنبيه: الخصم المعلن (${formatPctPlain(product.claimed_discount_pct)}%) أكبر من التوفير الفعلي مقابل وسيط ${windowLabelAr} (${medianText} ج.م.).`
        : `${lead} تنبيه: الخصم المعلن أكبر من التوفير الفعلي مقارنة بسجل الأسعار.`;
    }
    if (product.discount_verdict === "PRESALE_HIKE") {
      return medianText
        ? `${lead} ارتفع السعر مؤخراً مقارنة بوسيط ${windowLabelAr} (${medianText} ج.م.).`
        : `${lead} ارتفع السعر مؤخراً مقارنة بسجل الأسعار المرصود.`;
    }
    return medianText
      ? `${lead} سعر طبيعي متماشي مع وسيط ${windowLabelAr} (${medianText} ج.م.).`
      : `${lead} تابع سجل الأسعار وقارن البدائل على ${SITE_NAME_AR}.`;
  }

  // 3. Early-tracking (< 7 days) product: NEVER falsely claim a 60-day median verdict
  return `${lead} قيد الرصد (${trackedDays} أيام) — جاري بناء التاريخ السعري ومتابعة تغيّر السعر على ${SITE_NAME_AR}.`;
}

export async function productMetadata(productSk: string, sample: boolean): Promise<Metadata> {
  const canonical = absoluteUrl(`/products/${encodeURIComponent(productSk)}`);
  const fallbackOgImage = absoluteUrl(DEFAULT_OG_IMAGE_PATH);

  if (sample) {
    return {
      title: "إيصال سعر تجريبي — Sample Price Receipt",
      robots: { index: false, follow: false },
    };
  }

  const load = await loadProduct(productSk, false);
  if (load.status === "missing") {
    return {
      title: "المنتج غير موجود — Product Not Found",
      robots: { index: false, follow: false },
    };
  }

  if (load.status !== "ready" || load.result.source !== "api") {
    const fallbackTitle = `فحص سعر المنتج | ${SITE_NAME_AR}`;
    const fallbackDesc = `تحقق من سجل الأسعار الحقيقي وقارن العروض بالجنيه المصري على ${SITE_NAME_AR}.`;
    return {
      title: { absolute: fallbackTitle },
      description: fallbackDesc,
      alternates: { canonical },
      robots: { index: false, follow: true },
      openGraph: {
        title: fallbackTitle,
        description: fallbackDesc,
        url: canonical,
        siteName: SITE_NAME_BILINGUAL,
        locale: "ar_EG",
        alternateLocale: ["en_EG", "en_US"],
        type: "website",
        images: [{ url: fallbackOgImage, width: 1200, height: 630, alt: fallbackTitle }],
      },
      twitter: {
        card: "summary_large_image",
        title: fallbackTitle,
        description: fallbackDesc,
        images: [fallbackOgImage],
      },
    };
  }

  const detail = load.result.data;
  const { product } = detail;
  const storeAr = storeDisplayName(product.store_name, "ar");
  const priceText = formatEgpPlain(product.current_price);
  const fullTitle = `${product.product_title} — ${priceText} ج.م. (${storeAr}) | ${SITE_NAME_AR}`;
  const description = buildProductDescription(detail);

  const verifiedProductImage = verifiedHttpsImageUrl(product.image_url);
  const ogImages = verifiedProductImage
    ? [
        {
          url: verifiedProductImage,
          alt: `${product.product_title} — ${storeAr}`,
        },
      ]
    : [
        {
          url: fallbackOgImage,
          width: 1200,
          height: 630,
          alt: fullTitle,
        },
      ];

  const twitterImage = verifiedProductImage ?? fallbackOgImage;

  return {
    title: { absolute: fullTitle },
    description,
    alternates: { canonical },
    openGraph: {
      title: fullTitle,
      description,
      url: canonical,
      siteName: SITE_NAME_BILINGUAL,
      locale: "ar_EG",
      alternateLocale: ["en_EG", "en_US"],
      type: "website",
      images: ogImages,
    },
    twitter: {
      card: "summary_large_image",
      title: fullTitle,
      description,
      images: [twitterImage],
    },
  };
}
