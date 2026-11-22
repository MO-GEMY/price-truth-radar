import { makeOgResponse } from "@/lib/og";

export const alt = "Price Truth Radar — كشف الخصومات الوهمية في مصر";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse(
    {
      title: "Expose fake discounts. Buy at the real lowest price.",
      verdictEn: "Egyptian price intelligence",
      isScandal: false,
      store: "30 Egyptian stores tracked daily",
    },
  );
}
