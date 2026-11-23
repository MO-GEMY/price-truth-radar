import { makeOgResponse } from "@/lib/og";
import { LAUNCH_PRODUCT_COUNT, LAUNCH_STORE_COUNT } from "@/lib/site";

export const alt =
  "عروض حقيقية وكشف الخصومات الوهمية — Verified Deals & Fake Discounts | Price Truth Radar";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse({
    eyebrow: "DEALS & FAKE-DISCOUNT RADAR",
    title: "Verified Deals vs. Inflated Discounts in Egypt",
    subtitle:
      "Every offer checked against recorded 60-day price history before calling it a deal.",
    stats: [
      { value: `${LAUNCH_STORE_COUNT} Stores`, label: "Live EGP Tracking" },
      { value: LAUNCH_PRODUCT_COUNT, label: "Products Monitored Daily" },
      { value: "Evidence-First", label: "Zero Fake Sale Hype" },
    ],
    footer: "See real price drops and expose inflated strikethrough discounts",
  });
}
