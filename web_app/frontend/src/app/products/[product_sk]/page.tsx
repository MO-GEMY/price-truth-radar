import { notFound } from "next/navigation";
import { loadProduct } from "@/lib/product-server";
import { productMetadata } from "./metadata";
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
  return <ProductReceipt key={product_sk} productSk={product_sk} initial={load.status === "ready" ? load.result : null} />;
}
