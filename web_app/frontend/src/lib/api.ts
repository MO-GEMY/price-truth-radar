/**
 * Typed API client for the Asarak (أسعارك) FastAPI serving layer
 * (CONTRACTS.md §5). Reads the backend base URL from
 * `process.env.NEXT_PUBLIC_API_URL`.
 *
 * Parallel-development fallback: when `NEXT_PUBLIC_API_URL` is empty, or a
 * browse request fails because the live service is unavailable, browse
 * responses may use labeled sample data. Live searches and receipts surface
 * errors so that an unavailable backend cannot appear to be a missing match.
 */

import type {
  CategoriesResponse,
  CompareParams,
  CompareResponse,
  CouponScope,
  CouponsListResponse,
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
  getMockCategories,
  getMockStatsOverview,
  mockCompare,
  mockProductDetail,
  mockRadarFeed,
  mockSearch,
} from "./mockData";
import { normalizeHighlight, observedTimestamp, type PriceHighlight } from "./highlights";

const DEFAULT_PROD_API_URL = "https://api.asarak.com";

const PUBLIC_API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production" ? DEFAULT_PROD_API_URL : "")
)
  .trim()
  .replace(/\/+$/, "");

function resolveApiBase(): string {
  if (typeof window === "undefined") {
    const internal = (process.env.INTERNAL_API_URL ?? "").trim().replace(/\/+$/, "");
    if (internal) return internal;
  }
  return PUBLIC_API_BASE;
}

const REQUEST_TIMEOUT_MS = 8000;

export function isApiConfigured(): boolean {
  return resolveApiBase().length > 0;
}

export type DataSource = "api" | "mock";

export interface ApiResult<T> {
  data: T;
  source: DataSource;
}

export class ApiError extends Error {
  readonly status: number;
  readonly fields: Readonly<Record<string, string>>;

  constructor(status: number, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fields = fields;
  }
}

/* ------------------------------------------------------------------ */
/* Low-level fetch helper                                              */
/* ------------------------------------------------------------------ */

function buildUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const url = `${resolveApiBase()}${path}`;
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
  timeoutMs = REQUEST_TIMEOUT_MS,
  revalidateSeconds?: number,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onOuterAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", onOuterAbort, { once: true });

  try {
    // Allow browser HTTP caching on public read-only client fetches; on SSR,
    // use Next.js revalidation when explicitly requested so canonical product &
    // category pages remain CDN-cacheable instead of emitting private/no-store.
    const isBrowser = typeof window !== "undefined";
    const cacheOpts: RequestInit & { next?: { revalidate: number } } = isBrowser
      ? {}
      : typeof revalidateSeconds === "number" && revalidateSeconds > 0
        ? { next: { revalidate: revalidateSeconds } }
        : { cache: "no-store" };
    const response = await fetch(buildUrl(path, params), {
      headers: { Accept: "application/json" },
      signal: controller.signal,
      ...cacheOpts,
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

/** GET /api/v1/categories — populated canonical categories with live product & compare counts */
export function fetchCategories(signal?: AbortSignal): Promise<ApiResult<CategoriesResponse>> {
  return withFallback(
    () => fetchJson<CategoriesResponse>("/api/v1/categories", undefined, signal),
    () => getMockCategories(),
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
export async function fetchSearch(
  params: SearchParams,
  signal?: AbortSignal,
): Promise<ApiResult<SearchResponse>> {
  if (!isApiConfigured()) return { data: mockSearch(params), source: "mock" };
  const data = await fetchJson<SearchResponse>(
    "/api/v1/products/search",
    { q: params.q, url: params.url, limit: params.limit ?? 20 },
    signal,
  );
  return { data, source: "api" };
}

/** §5.5 GET /api/v1/products/{product_sk} */
export async function fetchProductDetail(
  productSk: string,
  signal?: AbortSignal,
  timeoutMs = REQUEST_TIMEOUT_MS,
  revalidateSeconds?: number,
): Promise<ApiResult<ProductDetailResponse>> {
  if (!isApiConfigured()) {
    const mock = mockProductDetail(productSk);
    if (!mock) throw new ApiError(404, `Product ${productSk} not found`);
    return { data: mock, source: "mock" };
  }
  const data = await fetchJson<ProductDetailResponse>(
    `/api/v1/products/${encodeURIComponent(productSk)}`,
    undefined,
    signal,
    timeoutMs,
    revalidateSeconds,
  );
  return { data, source: "api" };
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

export interface HighlightsBucket {
  items: PriceHighlight[];
  source: DataSource;
  updatedAt: string | null;
}

export interface HighlightsView {
  scandals: HighlightsBucket | null;
  deals: HighlightsBucket | null;
  limited: boolean;
}

function highlightsFromFeed(result: ApiResult<RadarFeedResponse>, kind: "scandals" | "deals"): HighlightsBucket {
  const products = result.data.items.filter((product) => product.in_stock && product.current_price >= 10);
  const candidates = kind === "scandals"
    ? products.filter((p) => p.discount_verdict === "FAKE_DISCOUNT" || p.discount_verdict === "PRESALE_HIKE")
    : products.filter((p) => p.real_discount_pct >= 5 && p.discount_verdict !== "PRESALE_HIKE" && p.discount_verdict !== "FAKE_DISCOUNT");
  const timestamps = candidates
    .map((item) => observedTimestamp(item.last_updated_at))
    .filter((value): value is string => value !== null);
  const updatedAt = timestamps.reduce<string | null>(
    (latest, value) => !latest || Date.parse(value) > Date.parse(latest) ? value : latest, null,
  );
  const items = candidates.map(normalizeHighlight);
  return { source: result.source, updatedAt, items: kind === "deals" ? items.filter(hasObservedSavings) : items };
}

function hasObservedSavings(item: PriceHighlight): boolean {
  return item.observedSavings !== null && item.observedSavings >= 0.05;
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
  category: RadarFeedParams["category"],
  limit = HIGHLIGHT_LIMIT,
  signal?: AbortSignal,
): Promise<HighlightsView> {
  if (isApiConfigured()) {
    try {
      const data = await fetchJson<RadarHighlights>(
        "/api/radar/highlights",
        { limit, category },
        signal,
      );
      const updatedAt = observedTimestamp(data.updated_at);
      return {
        scandals: { items: (data.biggest_scandals ?? []).map(normalizeHighlight), updatedAt, source: "api" },
        deals: { items: (data.best_real_deals ?? []).map(normalizeHighlight).filter(hasObservedSavings), updatedAt, source: "api" },
        limited: false,
      };
    } catch (error) {
      if (signal?.aborted) throw error;
      // 404 = endpoint not deployed yet — expected during rollout. Anything
      // else (network/5xx) also falls through to the feed derivation below.
      if (error instanceof ApiError && error.status === 401) throw error;
    }
  }

  const [scandalsFeed, dealsFeed] = await Promise.allSettled([
    fetchRadarFeed(
      { category, sort: "claimed_vs_real_gap_desc", page: 1, limit },
      signal,
    ),
    fetchRadarFeed(
      { category, sort: "real_discount_pct_desc", page: 1, limit },
      signal,
    ),
  ]);
  if (scandalsFeed.status === "rejected" && dealsFeed.status === "rejected") throw scandalsFeed.reason;
  return { limited: true,
    scandals: scandalsFeed.status === "fulfilled" ? highlightsFromFeed(scandalsFeed.value, "scandals") : null,
    deals: dealsFeed.status === "fulfilled" ? highlightsFromFeed(dealsFeed.value, "deals") : null,
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
  if (!isApiConfigured()) throw new ApiError(503, "Alert service unavailable");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const onOuterAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", onOuterAbort, { once: true });
  try {
    const res = await fetch(`${resolveApiBase()}/api/alerts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    const text = await res.text();
    let payload: { id?: string | number; status?: string; message?: unknown; detail?: unknown } = {};
    try {
      const body: unknown = JSON.parse(text);
      if (body && typeof body === "object" && !Array.isArray(body)) payload = body;
    } catch {
      /* non-JSON body */
    }
    if (!res.ok) {
      const fields: Record<string, string> = {};
      if (Array.isArray(payload.detail)) {
        for (const issue of payload.detail) {
          const field = Array.isArray(issue?.loc) ? issue.loc.at(-1) : undefined;
          if ((field === "destination" || field === "target_price") && typeof issue.msg === "string") {
            fields[field] = issue.msg;
          }
        }
      }
      const message = typeof payload.message === "string" ? payload.message
        : typeof payload.detail === "string" ? payload.detail : `HTTP ${res.status}`;
      throw new ApiError(res.status, message, fields);
    }
    if ((typeof payload.id !== "number" && typeof payload.id !== "string") || !payload.id || payload.status !== "active") {
      throw new ApiError(502, "Alert confirmation could not be verified");
    }
    return {
      id: String(payload.id),
      status: payload.status,
      message: typeof payload.message === "string" ? payload.message : "",
    };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onOuterAbort);
  }
}

/* ------------------------------------------------------------------ */
/* Contact & store suggestions (zero-DB public forms)                  */
/* ------------------------------------------------------------------ */

const SUBMISSION_TIMEOUT_MS = 20000;
const SUBMISSION_CONFIG_TIMEOUT_MS = 6000;

export interface SubmissionsConfig {
  form_enabled: boolean;
  /** Cloudflare Turnstile site key; empty when the widget is not enabled. */
  turnstile_site_key: string;
  /** Public Telegram bot username (without `@`) for price-drop alert Chat ID onboarding. */
  telegram_bot_username?: string;
}

/** GET /api/v1/coupons — zero-Neon in-memory promo codes that are verified, active and unexpired. */
export async function fetchCoupons(
  params?: { store_id?: string; scope?: CouponScope | "all"; category?: string },
  signal?: AbortSignal,
  revalidateSeconds?: number,
): Promise<CouponsListResponse | null> {
  if (!isApiConfigured()) return null;
  try {
    return await fetchJson<CouponsListResponse>(
      "/api/v1/coupons",
      {
        store_id: params?.store_id && params.store_id !== "all" ? params.store_id : undefined,
        scope: params?.scope && params.scope !== "all" ? params.scope : undefined,
        category: params?.category && params.category !== "all" ? params.category : undefined,
      },
      signal,
      REQUEST_TIMEOUT_MS,
      revalidateSeconds,
    );
  } catch {
    return null;
  }
}

/**
 * Why a submission was not accepted. `unavailable` covers a backend with no
 * notification channel, a provider outage, or an API that is not deployed yet —
 * in every case the UI must offer the direct-email fallback.
 */
export type SubmissionFailure =
  | { reason: "validation"; fields: string[] }
  | { reason: "rate_limited"; retryAfterSeconds: number | null }
  | { reason: "turnstile" }
  | { reason: "unavailable" }
  | { reason: "network" };

export type SubmissionResult = { ok: true } | ({ ok: false } & SubmissionFailure);

/** GET /api/submissions/config — null when the backend cannot be reached. */
export async function fetchSubmissionsConfig(signal?: AbortSignal): Promise<SubmissionsConfig | null> {
  if (!isApiConfigured()) return { form_enabled: false, turnstile_site_key: "" };
  try {
    return await fetchJson<SubmissionsConfig>(
      "/api/submissions/config",
      undefined,
      signal,
      SUBMISSION_CONFIG_TIMEOUT_MS,
    );
  } catch {
    return null;
  }
}

/** POST /api/submissions/* — failures are classified instead of thrown so forms can react. */
export async function postSubmission(
  path: "/api/submissions/contact" | "/api/submissions/store-suggestion",
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<SubmissionResult> {
  if (!isApiConfigured()) return { ok: false, reason: "unavailable" };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SUBMISSION_TIMEOUT_MS);
  const onOuterAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", onOuterAbort, { once: true });

  try {
    // buildUrl() keeps this call on whatever base the client resolves to (public
    // or internal), instead of depending on the base constant's name.
    const res = await fetch(buildUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    if (res.status === 202) return { ok: true };
    if (res.status === 422) {
      const fields: string[] = [];
      try {
        const payload = await res.json();
        if (Array.isArray(payload?.detail)) {
          for (const issue of payload.detail) {
            const field = Array.isArray(issue?.loc) ? issue.loc.at(-1) : undefined;
            if (typeof field === "string" && !fields.includes(field)) fields.push(field);
          }
        }
      } catch {
        /* non-JSON body — still a validation failure */
      }
      return { ok: false, reason: "validation", fields };
    }
    if (res.status === 429) {
      const seconds = Number(res.headers.get("retry-after"));
      return {
        ok: false,
        reason: "rate_limited",
        retryAfterSeconds: Number.isFinite(seconds) && seconds > 0 ? seconds : null,
      };
    }
    if (res.status === 403) return { ok: false, reason: "turnstile" };
    return { ok: false, reason: "unavailable" };
  } catch {
    return { ok: false, reason: "network" };
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

export interface SitemapChunkProduct {
  product_sk: string;
  product_key?: string;
  category?: string;
  store_name?: string;
  last_updated?: string;
}

export interface SitemapChunkPayload {
  chunk_id: number;
  chunk_size: number;
  total_chunks: number;
  total_products: number;
  last_updated?: string;
  products: SitemapChunkProduct[];
}

/**
 * GET /api/v1/seo/sitemap-chunk/{chunkId} — returns 2,500 prioritized products
 * per chunk (1..4 = top 10,000 URLs) from FastAPI's single 24h-cached query.
 */
export async function fetchSitemapChunk(
  chunkId: number,
  signal?: AbortSignal,
  timeoutMs = 6000,
): Promise<SitemapChunkPayload | null> {
  if (!isApiConfigured()) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onOuterAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", onOuterAbort, { once: true });

  try {
    const res = await fetch(`${resolveApiBase()}/api/v1/seo/sitemap-chunk/${chunkId}`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
      next: { revalidate: 604800 },
    } as RequestInit & { next: { revalidate: number } });
    if (!res.ok) return null;
    const body = (await res.json()) as Partial<SitemapChunkPayload>;
    if (!Array.isArray(body?.products)) return null;
    return {
      chunk_id: Number(body.chunk_id ?? chunkId),
      chunk_size: Number(body.chunk_size ?? 2500),
      total_chunks: Number(body.total_chunks ?? 4),
      total_products: Number(body.total_products ?? body.products.length),
      last_updated: typeof body.last_updated === "string" ? body.last_updated : undefined,
      products: body.products,
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onOuterAbort);
  }
}

/**
 * GET /api/seo/sitemap-entries — tolerant parsing of product/compare slugs.
 * Returns null when the endpoint is missing (sitemap.ts falls back to the
 * core static routes).
 */
export async function fetchSitemapEntries(
  signal?: AbortSignal,
  timeoutMs = 4500,
  limit = 500,
): Promise<SitemapEntry[] | null> {
  if (!isApiConfigured()) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onOuterAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", onOuterAbort, { once: true });

  try {
    const res = await fetch(`${resolveApiBase()}/api/seo/sitemap-entries?limit=${limit}`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = await res.json();
    const list = Array.isArray(body) ? body : body?.products ?? body?.entries ?? body?.items;
    if (!Array.isArray(list)) return null;
    const entries: SitemapEntry[] = [];
    for (const item of list.slice(0, 1000)) {
      if (typeof item === "string") {
        entries.push({ loc: item });
        continue;
      }
      if (item && typeof item === "object") {
        const loc = typeof item.product_sk === "string" && item.product_sk
          ? `/products/${encodeURIComponent(item.product_sk)}`
          : item.loc ?? item.slug ?? item.url ?? item.path;
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
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onOuterAbort);
  }
}
