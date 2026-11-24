import type { Metadata } from "next";
import {
  LAUNCH_PRODUCT_COUNT,
  LAUNCH_STORE_COUNT,
  SITE_NAME_AR,
  SITE_NAME_BILINGUAL,
  absoluteUrl,
} from "@/lib/site";

const title = `عروض موثّقة وفحص الخصومات المعلنة — Verified Deals & Discount Checks`;
const description = `اكتشف التخفيضات الموثّقة وتحقق من الخصومات المعلنة مقابل سجل الأسعار لآخر 60 يوم عبر ${LAUNCH_STORE_COUNT} متجر مصري و${LAUNCH_PRODUCT_COUNT} منتج بالجنيه المصري — Verified real deals and reference-price checks across ${LAUNCH_STORE_COUNT} Egyptian stores.`;
const url = absoluteUrl("/deals");
const ogImage = absoluteUrl("/deals/opengraph-image");

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: url },
  openGraph: {
    title: `${title} | ${SITE_NAME_AR}`,
    description,
    url,
    siteName: SITE_NAME_BILINGUAL,
    locale: "ar_EG",
    alternateLocale: ["en_EG", "en_US"],
    type: "website",
    images: [{ url: ogImage, width: 1200, height: 630, alt: title }],
  },
  twitter: {
    card: "summary_large_image",
    title: `${title} | ${SITE_NAME_AR}`,
    description,
    images: [ogImage],
  },
};

export default function DealsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
