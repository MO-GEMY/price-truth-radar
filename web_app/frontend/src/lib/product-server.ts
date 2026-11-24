import { cache } from "react";
import type { ProductDetailResponse } from "@/types/contract";
import { ApiError, fetchProductDetail, type ApiResult } from "./api";
import { mockProductDetail } from "./mockData";

/**
 * Short server-side timeout so a slow backend response never blocks SSR or
 * metadata generation; clients can still retry interactively if needed.
 */
const SSR_PRODUCT_TIMEOUT_MS = 4500;
const PRODUCT_SSR_REVALIDATE_SECONDS = 86400; // 24h edge/SSR cache shield

export type ProductLoad =
  | { status: "ready"; result: ApiResult<ProductDetailResponse> }
  | { status: "missing" | "error" };

export const loadProduct = cache(async (productSk: string, sample = false): Promise<ProductLoad> => {
  if (sample) {
    const data = mockProductDetail(productSk);
    return data ? { status: "ready", result: { data, source: "mock" } } : { status: "missing" };
  }
  try {
    return {
      status: "ready",
      result: await fetchProductDetail(
        productSk,
        undefined,
        SSR_PRODUCT_TIMEOUT_MS,
        PRODUCT_SSR_REVALIDATE_SECONDS,
      ),
    };
  } catch (error) {
    return { status: error instanceof ApiError && error.status === 404 ? "missing" : "error" };
  }
});
