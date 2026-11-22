import { makeOgResponse } from "@/lib/og";

export const alt = "فضائح الخصومات vs أفضل خصم حقيقي — Price Truth Radar";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse(
    {
      title: "Fake Discount Scandals vs Verified Real Deals",
      verdictEn: "Fake inflation",
      isScandal: true,
      store: "30 Egyptian stores",
      price: "1,209 fake discounts exposed",
      footer: "Check the price truth before the sale starts",
    },
  );
}
