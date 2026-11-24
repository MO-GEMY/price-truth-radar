import type { Metadata } from "next";
import { fetchCoupons } from "@/lib/api";
import { isTrustedCoupon } from "@/lib/coupons";
import { absoluteUrl, SITE_NAME } from "@/lib/site";
import { CouponsDirectory } from "./CouponsDirectory";

export const revalidate = 1800;

export const metadata: Metadata = {
  title: `كوبونات وأكواد الخصم في مصر | ${SITE_NAME}`,
  description:
    "أكواد خصم مُجرَّبة وعروض بنوك في المتاجر المصرية أونلاين — لا ننشر إلا الأكواد التي جرّبناها بأنفسنا، مع نسخ الكود بضغطة واحدة.",
  alternates: {
    canonical: absoluteUrl("/coupons"),
  },
  openGraph: {
    title: `كوبونات وأكواد الخصم في مصر | ${SITE_NAME}`,
    description: "أكواد خصم مُجرَّبة لأشهر المتاجر المصرية على أسعارك — لا ننشر إلا ما جرّبناه بأنفسنا.",
    url: absoluteUrl("/coupons"),
    type: "website",
  },
};

export default async function CouponsPage() {
  const data = await fetchCoupons(undefined, undefined, revalidate);
  // Drop unverified codes here so they never reach the page payload, not just the UI
  const initialCoupons = (data?.items ?? []).filter(isTrustedCoupon);
  return <CouponsDirectory initialCoupons={initialCoupons} />;
}
