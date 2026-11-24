import { makeOgResponse } from "@/lib/og";
import { LAUNCH_PRODUCT_COUNT, LAUNCH_STORE_COUNT } from "@/lib/site";

export const alt =
  "عروض موثّقة وفحص الخصومات المعلنة — Verified Deals & Discount Checks | أسعارك (Asarak)";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse({
    eyebrow: "DEALS & DISCOUNT VERIFICATION",
    title: "Verified Deals & Reference-Price Checks in Egypt",
    subtitle:
      "Every offer checked against recorded 60-day EGP price history before calling it a verified deal.",
    stats: [
      { value: `${LAUNCH_STORE_COUNT} Stores`, label: "Live EGP Tracking" },
      { value: LAUNCH_PRODUCT_COUNT, label: "Products Monitored Daily" },
      { value: "Evidence-First", label: "Transparent Price History" },
    ],
    footer: "See verified price drops and compare advertised reference prices",
  });
}
