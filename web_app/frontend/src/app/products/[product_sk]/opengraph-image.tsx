import { makeOgResponse } from "@/lib/og";
import { loadProduct } from "@/lib/product-server";
import { LAUNCH_PRODUCT_COUNT, LAUNCH_STORE_COUNT } from "@/lib/site";
import { storeDisplayName } from "@/lib/stores";

export const alt = "Asarak (أسعارك) — Product Price Receipt";
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
  const fallback = () =>
    makeOgResponse({
      eyebrow: "EGYPT · PRICE RECEIPT",
      title: "Check Real Price History in Egypt",
      subtitle: `Compare EGP prices across ${LAUNCH_STORE_COUNT} verified stores and ${LAUNCH_PRODUCT_COUNT} tracked products.`,
    });

  if (load.status !== "ready" || load.result.source !== "api") return fallback();
  const { product } = load.result.data;
  const title = product.product_title.trim();

  // Bundled Satori font only shapes Latin characters; Arabic titles fall back cleanly
  // while OG/Twitter tags carry the full Arabic title and verified HTTPS product photo.
  if (!title || !/^[\x20-\x7E\u00A0-\u024F\u2000-\u206F]+$/u.test(title)) {
    return fallback();
  }

  const price =
    Number.isFinite(product.current_price) && product.current_price > 0
      ? `EGP ${product.current_price.toLocaleString("en-US", { maximumFractionDigits: 2 })}`
      : undefined;

  try {
    const image = makeOgResponse({
      eyebrow: "LIVE PRICE RECEIPT · EGP",
      title,
      store: storeDisplayName(product.store_name, "en"),
      price,
      footer: "Verified against recorded price history & matched Egyptian stores",
    });
    return new Response(await image.arrayBuffer(), { headers: image.headers });
  } catch {
    return fallback();
  }
}
