import { makeOgResponse } from "@/lib/og";

export const alt = "مقارنة الأسعار عبر المتاجر — Cross-Store Price Comparison";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse(
    {
      title: "Compare stores",
      footer: "See available offers for the same model or pack",
    },
  );
}
