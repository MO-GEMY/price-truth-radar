import { makeOgResponse } from "@/lib/og";

export const alt = "مقارنة الأسعار عبر المتاجر — Cross-Store Price Comparison";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse(
    {
      title: "Cross-Store Price Comparison — same model, real lowest price",
      verdictEn: "Compare before you buy",
      isScandal: false,
      store: "Electronics · Appliances · Groceries · Fashion",
    },
  );
}
