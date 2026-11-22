import { makeOgResponse } from "@/lib/og";

export const alt = "Price Truth Radar — Check a price";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return makeOgResponse(
    {
      title: "Is this a good price?",
      footer: "Check a retailer's price against its recorded history",
    },
  );
}
