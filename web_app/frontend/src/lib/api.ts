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
  PriceAlertRequest,
  PriceAlertResponse,
  ProductDetailResponse,
  RadarFeedParams,
  RadarFeedResponse,
  RadarHighlights,
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

export async function fetchJson<T>(
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

/* ------------------------------------------------------------------ */
/* Scandals vs Real Deals radar (launch page)                          */
/* ------------------------------------------------------------------ */

const HIGHLIGHT_LIMIT = 24;

function highlightsFromFeed(
  feed: RadarFeedResponse,
  kind: "scandals" | "deals",
): RadarHighlights["biggest_scandals"] {
  // Price floor: marketplace bait listings (EGP 1 "TVs") poison the scandal
  // ranking with 100% fake inflation — exclude anything below EGP 10.
  const items = feed.items.filter((p) => p.current_price >= 10);
  if (kind === "scandals") {
    return items
      .filter((p) => p.claimed_discount_pct >= 10)
      .sort((a, b) => b.claimed_discount_pct - Math.max(b.real_discount_pct, 0) - (a.claimed_discount_pct - Math.max(a.real_discount_pct, 0)))
      .map((p) => ({ ...p }));
  }
  return items
    .filter((p) => p.real_discount_pct >= 5)
    .sort((a, b) => b.real_discount_pct - a.real_discount_pct)
    .map((p) => ({ ...p }));
}

/**
 * Scandals vs Real Deals highlights.
 *
 * 1. Prefers the dedicated `/api/radar/highlights` endpoint (Backend Prompt 3).
 * 2. Falls back to the standard radar feed (which IS live) so the page works
 *    today: fake-discount scandals by claimed-vs-real gap, and verified real
 *    deals by real discount vs the 60-day baseline.
 * 3. If even the feed is unreachable, surfaces the caller's error so the page
 *    can render its empty state.
 */
export async function fetchRadarHighlights(
  category: string,
  limit = HIGHLIGHT_LIMIT,
  signal?: AbortSignal,
): Promise<ApiResult<RadarHighlights>> {
  if (isApiConfigured()) {
    try {
      const data = await fetchJson<RadarHighlights>(
        "/api/radar/highlights",
        { limit, category },
        signal,
      );
      return {
        data: {
          updated_at: data.updated_at ?? new Date().toISOString(),
          biggest_scandals: data.biggest_scandals ?? [],
          best_real_deals: data.best_real_deals ?? [],
        },
        source: "api",
      };
    } catch (error) {
      if (signal?.aborted) throw error;
      // 404 = endpoint not deployed yet — expected during rollout. Anything
      // else (network/5xx) also falls through to the feed derivation below.
      if (error instanceof ApiError && error.status === 401) throw error;
    }
  }

  const cat = category === "all" ? "all" : (category as RadarFeedParams["category"]);
  const [scandalsFeed, dealsFeed] = await Promise.all([
    fetchRadarFeed(
      { category: cat, sort: "claimed_vs_real_gap_desc", page: 1, limit },
      signal,
    ),
    fetchRadarFeed(
      { category: cat, sort: "real_discount_pct_desc", page: 1, limit },
      signal,
    ),
  ]);
  return {
    data: {
      updated_at: scandalsFeed.data.items[0]?.last_updated_at ?? new Date().toISOString(),
      biggest_scandals: highlightsFromFeed(scandalsFeed.data, "scandals").map((i) => ({ ...i })),
      best_real_deals: highlightsFromFeed(dealsFeed.data, "deals").map((i) => ({ ...i })),
    },
    source: scandalsFeed.source,
  };
}

/* ------------------------------------------------------------------ */
/* Price-drop alerts ("نبّهني لما السعر ينزل")                          */
/* ------------------------------------------------------------------ */

/**
 * POST /api/alerts — no silent fallback: alerts are a real user commitment,
 * so failures surface to the UI with the server message when present.
 */
export async function submitPriceAlert(
  body: PriceAlertRequest,
  signal?: AbortSignal,
): Promise<PriceAlertResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const onOuterAbort = () => controller.abort();
  signal?.addEventListener("abort", onOuterAbort, { once: true });
  try {
    const res = await fetch(`${API_BASE}/api/alerts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    const text = await res.text();
    let payload: Partial<PriceAlertResponse> & { detail?: string; message?: string } = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      /* non-JSON body */
    }
    if (!res.ok) {
      throw new ApiError(res.status, payload.message || payload.detail || `HTTP ${res.status}`);
    }
    return {
      id: String(payload.id ?? ""),
      status: payload.status ?? "active",
      message: payload.message ?? "",
    };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onOuterAbort);
  }
}

/* ------------------------------------------------------------------ */
/* SEO — dynamic sitemap entries                                       */
/* ------------------------------------------------------------------ */

export interface SitemapEntry {
  loc: string;
  lastmod?: string;
}

/**
 * GET /api/seo/sitemap-entries — tolerant parsing of product/compare slugs.
 * Returns null when the endpoint is missing (sitemap.ts falls back to the
 * core static routes).
 */
export async function fetchSitemapEntries(signal?: AbortSignal): Promise<SitemapEntry[] | null> {
  if (!isApiConfigured()) return null;
  try {
    const res = await fetch(`${API_BASE}/api/seo/sitemap-entries`, {
      headers: { Accept: "application/json" },
      signal,
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = await res.json();
    const list = Array.isArray(body) ? body : body?.entries ?? body?.items;
    if (!Array.isArray(list)) return null;
    const entries: SitemapEntry[] = [];
    for (const item of list.slice(0, 5000)) {
      if (typeof item === "string") {
        entries.push({ loc: item });
        continue;
      }
      if (item && typeof item === "object") {
        const loc = item.loc ?? item.slug ?? item.url ?? item.path;
        if (typeof loc === "string" && loc) {
          entries.push({
            loc,
            lastmod: typeof (item.last_updated ?? item.lastmod) === "string" ? item.last_updated ?? item.lastmod : undefined,
          });
        }
      }
    }
    return entries;
  } catch {
    return null;
  }
}
