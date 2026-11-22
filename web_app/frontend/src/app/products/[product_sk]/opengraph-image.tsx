import { makeOgResponse } from "@/lib/og";
import { fetchJson } from "@/lib/api";
import type { ProductDetailResponse } from "@/types/contract";

export const alt = "Price Truth Radar — product price truth card";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const runtime = "nodejs";



const VERDICT_EN: Record<string, string> = {
  FAKE_DISCOUNT: "Fake Discount",
  GENUINE_DEAL: "Verified Real Deal",
  ALL_TIME_LOW: "All-Time Low",
  PRESALE_HIKE: "Pre-Sale Hike",
  NORMAL_PRICE: "Normal Price",
};

function egp(value: number): string {
  return `EGP ${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

export default async function OgImage({
  params,
}: {
  params: Promise<{ product_sk: string }>;
}) {
  const { product_sk } = await params;

  let product: ProductDetailResponse["product"] | null = null;
  try {
    const detail = await fetchJson<ProductDetailResponse>(
      `/api/v1/products/${encodeURIComponent(product_sk)}`,
      undefined,
    );
    product = detail.product;
  } catch {
    product = null;
  }

  const isScandal =
    product?.discount_verdict === "FAKE_DISCOUNT" ||
    product?.discount_verdict === "PRESALE_HIKE";
  const verdict = product?.discount_verdict ?? "NORMAL_PRICE";

  return makeOgResponse(
    {
      title: product?.product_title ?? "Price Truth Radar",
      store: product?.store_name,
      price: product ? egp(product.current_price) : undefined,
      claimedPrice: product?.claimed_original_price
        ? egp(product.claimed_original_price)
        : null,
      verdictEn: VERDICT_EN[verdict] ?? "Price Truth",
      isScandal,
    },
  );
}
