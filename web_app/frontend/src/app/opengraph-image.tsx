import { makeOgResponse } from "@/lib/og";
import { LAUNCH_PRODUCT_COUNT, LAUNCH_STORE_COUNT } from "@/lib/site";

export const alt =
  "أسعارك — Asarak | Real Price History & Comparison Across 200 Egyptian Stores";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse({
    eyebrow: "EGYPT · PRICE TRANSPARENCY",
    title: "Verify Real Discounts & Compare True Prices in Egypt",
    subtitle:
      "Track daily EGP price history and compare matched offers across Egypt's top retailers.",
    stats: [
      { value: `${LAUNCH_STORE_COUNT} Stores`, label: "Verified Egyptian Retailers" },
      { value: LAUNCH_PRODUCT_COUNT, label: "Tracked Products in EGP" },
      { value: "60-Day History", label: "Verified vs. Unverified Deals" },
    ],
    footer: "Check any price before you buy · Electronics, Appliances, Fashion & Groceries",
  });
}
