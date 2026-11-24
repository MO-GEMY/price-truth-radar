import { notFound } from "next/navigation";
import { buildProductJsonLd, serializeJsonLd } from "@/lib/jsonld";
import { loadProduct } from "@/lib/product-server";
import { absoluteUrl } from "@/lib/site";
import { buildProductDescription, productMetadata } from "./metadata";
import { ProductReceipt } from "./receipt";

/**
 * 24-hour ISR/CDN cache window so crawler visits to canonical product pages
 * are served from Cloudflare Edge instead of waking Neon PostgreSQL.
 */
export const revalidate = 86400;

interface ProductPageProps {
  params: Promise<{ product_sk: string }>;
}

export async function generateMetadata({ params }: ProductPageProps) {
  const { product_sk } = await params;
  return productMetadata(product_sk, false);
}

export default async function ProductPage({ params }: ProductPageProps) {
  const { product_sk } = await params;
  const load = await loadProduct(product_sk, false);
  if (load.status === "missing") notFound();

  const jsonLd =
    load.status === "ready" && load.result.source === "api"
      ? serializeJsonLd(
          buildProductJsonLd(
            load.result.data,
            absoluteUrl(`/products/${encodeURIComponent(product_sk)}`),
            buildProductDescription(load.result.data),
          ),
        )
      : null;

  return (
    <>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
      )}
      <ProductReceipt
        key={product_sk}
        productSk={product_sk}
        initial={load.status === "ready" ? load.result : null}
      />
    </>
  );
}
