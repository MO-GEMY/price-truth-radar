import type { Metadata } from "next";
import { fetchCoupons } from "@/lib/api";
import { absoluteUrl, SITE_NAME } from "@/lib/site";
import { CouponsDirectory } from "./CouponsDirectory";

export const revalidate = 1800;

export const metadata: Metadata = {
  title: `كوبونات وأكواد الخصم في مصر | ${SITE_NAME}`,
  description:
    "أكواد خصم نشطة وعروض بنوك وكوبونات متاجر مصرية (نون، أمازون مصر، بي تك، 2B، رنين) محدثة باستمرار مع نسخ بضغطة واحدة.",
  alternates: {
    canonical: absoluteUrl("/coupons"),
  },
  openGraph: {
    title: `كوبونات وأكواد الخصم في مصر | ${SITE_NAME}`,
    description:
      "أكواد خصم نشطة وعروض بنوك وكوبونات لأشهر المتاجر المصرية على أسعارك.",
    url: absoluteUrl("/coupons"),
    type: "website",
  },
};

export default async function CouponsPage() {
  const data = await fetchCoupons(undefined, undefined, revalidate);
  return <CouponsDirectory initialCoupons={data?.items ?? []} />;
}
