import { makeOgResponse } from "@/lib/og";

export const alt = "Price highlights — Price Truth Radar";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse(
    {
      title: "Price highlights",
      footer: "Selected listings with recorded price evidence",
    },
  );
}
