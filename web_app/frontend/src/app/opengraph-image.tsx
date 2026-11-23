import { makeOgResponse } from "@/lib/og";
import { LAUNCH_PRODUCT_COUNT, LAUNCH_STORE_COUNT } from "@/lib/site";

export const alt =
  "رادار الحقيقة السعرية — Price Truth Radar | Real Price History & Comparison Across 172 Egyptian Stores";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse({
    eyebrow: "EGYPT · BLACK FRIDAY READY",
    title: "Spot Fake Discounts Before You Buy in Egypt",
    subtitle:
      "Track daily price history and compare matched offers in EGP across Egypt's top retailers.",
    stats: [
      { value: `${LAUNCH_STORE_COUNT} Stores`, label: "Verified Egyptian Retailers" },
      { value: LAUNCH_PRODUCT_COUNT, label: "Tracked Products in EGP" },
      { value: "60-Day History", label: "Real vs. Fake Deal Verdicts" },
    ],
    footer: "Check any price before you buy · Electronics, Appliances, Fashion & Groceries",
  });
}
