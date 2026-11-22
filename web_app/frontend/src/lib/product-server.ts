import { cache } from "react";
import type { ProductDetailResponse } from "@/types/contract";
import { ApiError, fetchProductDetail, type ApiResult } from "./api";
import { mockProductDetail } from "./mockData";

export type ProductLoad =
  | { status: "ready"; result: ApiResult<ProductDetailResponse> }
  | { status: "missing" | "error" };

export const loadProduct = cache(async (productSk: string, sample = false): Promise<ProductLoad> => {
  if (sample) {
    const data = mockProductDetail(productSk);
    return data ? { status: "ready", result: { data, source: "mock" } } : { status: "missing" };
  }
  try {
    return { status: "ready", result: await fetchProductDetail(productSk) };
  } catch (error) {
    return { status: error instanceof ApiError && error.status === 404 ? "missing" : "error" };
  }
});
