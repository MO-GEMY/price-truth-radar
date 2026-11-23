import { makeOgResponse } from "@/lib/og";
import { LAUNCH_STORE_COUNT } from "@/lib/site";

export const alt =
  "مقارنة الأسعار عبر المتاجر المصرية — Cross-Store Price Comparison | Price Truth Radar";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse({
    eyebrow: "CROSS-STORE COMPARISON · EGP",
    title: "Compare Exact Product Prices Across Egyptian Stores",
    subtitle:
      "Find the cheapest in-stock store for the same model, SKU, or grocery pack size.",
    stats: [
      { value: `${LAUNCH_STORE_COUNT} Stores`, label: "Amazon, Noon, B.TECH & More" },
      { value: "3,000+ Matches", label: "Exact Cross-Store Groups" },
      { value: "Live Stock", label: "Real-Time EGP Price Spreads" },
    ],
    footer: "Never overpay — compare exact matched offers side by side in EGP",
  });
}
