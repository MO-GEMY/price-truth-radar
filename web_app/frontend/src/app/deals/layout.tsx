import type { Metadata } from "next";
import { SITE_NAME, absoluteUrl } from "@/lib/site";

export const metadata: Metadata = {
  title: "فضائح الخصومات vs أفضل خصم حقيقي | Fake Discount Scandals vs Real Deals",
  description:
    "The season's loudest fake discount scandals and verified real deals across Egyptian stores — share them before the sale starts. فضائح الخصومات وأفضل الصفقات الحقيقية بالجنيه المصري.",
  alternates: { canonical: absoluteUrl("/deals") },
  openGraph: {
    title: "فضائح الخصومات vs أفضل خصم حقيقي — Price Truth Radar",
    description:
      "أكبر تضخيمات الخصومات وأفضل الصفقات الحقيقية عبر متاجر مصر — شاركها قبل بدء التخفيضات.",
    url: absoluteUrl("/deals"),
    siteName: SITE_NAME,
    locale: "ar_EG",
    alternateLocale: ["en_US"],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "فضائح الخصومات vs أفضل خصم حقيقي — Price Truth Radar",
    description:
      "أكبر تضخيمات الخصومات وأفضل الصفقات الحقيقية عبر متاجر مصر — شاركها قبل بدء التخفيضات.",
  },
};

export default function DealsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
