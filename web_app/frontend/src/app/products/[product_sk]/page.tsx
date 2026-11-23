import { notFound } from "next/navigation";
import { buildProductJsonLd, serializeJsonLd } from "@/lib/jsonld";
import { loadProduct } from "@/lib/product-server";
import { absoluteUrl } from "@/lib/site";
import { buildProductDescription, productMetadata } from "./metadata";
import { ProductReceipt } from "./receipt";

interface ProductPageProps {
  params: Promise<{ product_sk: string }>;
  searchParams: Promise<{ sample?: string | string[] }>;
}

export async function generateMetadata({ params, searchParams }: ProductPageProps) {
  const [{ product_sk }, { sample }] = await Promise.all([params, searchParams]);
  return productMetadata(product_sk, sample === "1");
}

export default async function ProductPage({ params, searchParams }: ProductPageProps) {
  const [{ product_sk }, { sample }] = await Promise.all([params, searchParams]);
  const load = await loadProduct(product_sk, sample === "1");
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
