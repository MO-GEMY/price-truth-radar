/**
 * Typed API client for the Price Truth Radar FastAPI serving layer
 * (CONTRACTS.md §5). Reads the backend base URL from
 * `process.env.NEXT_PUBLIC_API_URL`.
 *
 * Parallel-development fallback: when `NEXT_PUBLIC_API_URL` is empty, or a
 * request fails at the network level / times out / returns a 5xx, every call
 * transparently resolves from the local contract-matching mock dataset and
 * reports `source: "mock"` so the UI can show the demo-data banner.
 * Client errors (4xx, e.g. a 404 for an unknown product_sk) are surfaced.
 */

import type {
  CompareParams,
  CompareResponse,
  ProductDetailResponse,
  RadarFeedParams,
  RadarFeedResponse,
  SearchParams,
  SearchResponse,
  StatsOverview,
} from "@/types/contract";
import {
  getMockStatsOverview,
  mockCompare,
  mockProductDetail,
  mockRadarFeed,
  mockSearch,
} from "./mockData";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "")
  .trim()
  .replace(/\/+$/, "");

const REQUEST_TIMEOUT_MS = 8000;

export function isApiConfigured(): boolean {
  return API_BASE.length > 0;
}

export type DataSource = "api" | "mock";

export interface ApiResult<T> {
  data: T;
  source: DataSource;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/* ------------------------------------------------------------------ */
/* Low-level fetch helper                                              */
/* ------------------------------------------------------------------ */

function buildUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const url = `${API_BASE}${path}`;
  if (!params) return url;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${url}?${qs}` : url;
}

async function fetchJson<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const onOuterAbort = () => controller.abort();
  signal?.addEventListener("abort", onOuterAbort, { once: true });

  try {
    const response = await fetch(buildUrl(path, params), {
      headers: { Accept: "application/json" },
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) {
      throw new ApiError(response.status, `API ${path} responded with ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onOuterAbort);
  }
}

function isFallbackEligible(error: unknown): boolean {
  // Network failures, timeouts and server errors fall back to mock data.
  // Client errors (4xx) are real answers from the API and must surface.
  if (error instanceof ApiError) return error.status >= 500;
  return true; // TypeError from fetch, AbortError from timeout, etc.
}

async function withFallback<T>(
  live: () => Promise<T>,
  mock: () => T,
  signal?: AbortSignal,
): Promise<ApiResult<T>> {
  if (!isApiConfigured()) {
    return { data: mock(), source: "mock" };
  }
  try {
    return { data: await live(), source: "api" };
  } catch (error) {
    if (!isFallbackEligible(error) || signal?.aborted) throw error;
    return { data: mock(), source: "mock" };
  }
}

/* ------------------------------------------------------------------ */
/* Public API — mirrors CONTRACTS.md §5                                */
/* ------------------------------------------------------------------ */

/** §5.2 GET /api/v1/stats/overview */
export function fetchStatsOverview(signal?: AbortSignal): Promise<ApiResult<StatsOverview>> {
  return withFallback(
    () => fetchJson<StatsOverview>("/api/v1/stats/overview", undefined, signal),
    () => getMockStatsOverview(),
    signal,
  );
}

/** §5.3 GET /api/v1/radar/feed */
export function fetchRadarFeed(
  params: RadarFeedParams,
  signal?: AbortSignal,
): Promise<ApiResult<RadarFeedResponse>> {
  return withFallback(
    () =>
      fetchJson<RadarFeedResponse>(
        "/api/v1/radar/feed",
        {
          category: params.category,
          verdict: params.verdict,
          store: params.store,
          sort: params.sort,
          page: params.page,
          limit: params.limit,
        },
        signal,
      ),
    () => mockRadarFeed(params),
    signal,
  );
}

/** §5.4 GET /api/v1/products/search */
export function fetchSearch(
  params: SearchParams,
  signal?: AbortSignal,
): Promise<ApiResult<SearchResponse>> {
  return withFallback(
    () =>
      fetchJson<SearchResponse>(
        "/api/v1/products/search",
        { q: params.q, url: params.url, limit: params.limit ?? 20 },
        signal,
      ),
    () => mockSearch(params),
    signal,
  );
}

/** §5.5 GET /api/v1/products/{product_sk} */
export function fetchProductDetail(
  productSk: string,
  signal?: AbortSignal,
): Promise<ApiResult<ProductDetailResponse>> {
  return withFallback(
    () => fetchJson<ProductDetailResponse>(`/api/v1/products/${encodeURIComponent(productSk)}`, undefined, signal),
    () => {
      const mock = mockProductDetail(productSk);
      if (!mock) {
        throw new ApiError(404, `Product ${productSk} not found`);
      }
      return mock;
    },
    signal,
  );
}

/** §5.6 GET /api/v1/compare */
export function fetchCompare(
  params: CompareParams,
  signal?: AbortSignal,
): Promise<ApiResult<CompareResponse>> {
  return withFallback(
    () =>
      fetchJson<CompareResponse>(
        "/api/v1/compare",
        {
          category: params.category === "all" ? undefined : params.category,
          min_spread_pct: params.min_spread_pct !== undefined && params.min_spread_pct > 0
            ? params.min_spread_pct
            : undefined,
          page: params.page,
          limit: params.limit,
        },
        signal,
      ),
    () => mockCompare(params),
    signal,
  );
}
