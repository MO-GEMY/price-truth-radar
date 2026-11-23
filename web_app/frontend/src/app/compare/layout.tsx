import type { Metadata } from "next";
import {
  LAUNCH_STORE_COUNT,
  SITE_NAME_AR,
  SITE_NAME_BILINGUAL,
  absoluteUrl,
} from "@/lib/site";

const title = `مقارنة الأسعار عبر ${LAUNCH_STORE_COUNT} متجر مصري — Compare Stores in EGP`;
const description = `قارن سعر نفس المنتج والموديل بين ${LAUNCH_STORE_COUNT} متجر مصري (أمازون مصر، نون، بي تك، 2B، سيجما، سعودي، سبينيس وغيرها) واعرف أرخص متجر متاح الآن — Compare exact matched products side by side in EGP.`;
const url = absoluteUrl("/compare");
const ogImage = absoluteUrl("/compare/opengraph-image");

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

export default function CompareLayout({ children }: { children: React.ReactNode }) {
  return children;
}
