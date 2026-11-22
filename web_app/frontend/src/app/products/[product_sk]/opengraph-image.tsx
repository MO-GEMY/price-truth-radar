import { makeOgResponse } from "@/lib/og";
import { isStaleObservation, observedTimestamp } from "@/lib/highlights";
import { loadProduct } from "@/lib/product-server";
import { storeDisplayName } from "@/lib/stores";

export const alt = "Price Truth Radar — product price truth card";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const runtime = "nodejs";



export default async function OgImage({
  params,
}: {
  params: Promise<{ product_sk: string }>;
}) {
  const { product_sk } = await params;

  const load = await loadProduct(product_sk);
  const fallback = () => makeOgResponse({ title: "Check this price", footer: "Price history and matched offers in Egypt" });
  if (load.status !== "ready" || load.result.source !== "api") return fallback();
  const { product } = load.result.data;
  const title = product.product_title.trim();
  // The image renderer's bundled font cannot shape Arabic. The page and
  // Open Graph text carry the complete listing name.
  if (!title || !/^[\x20-\x7E\u00A0-\u024F\u2000-\u206F]+$/u.test(title)) return fallback();
  const timestamp = observedTimestamp(product.last_updated_at);
  const price = timestamp && !isStaleObservation(timestamp)
    ? `EGP ${product.current_price.toLocaleString("en-US", { maximumFractionDigits: 2 })}` : undefined;
  try {
    const image = makeOgResponse({ title, store: storeDisplayName(product.store_name, "en"), price });
    return new Response(await image.arrayBuffer(), { headers: image.headers });
  } catch {
    return fallback();
  }
}
