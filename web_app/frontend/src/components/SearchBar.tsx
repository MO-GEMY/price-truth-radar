"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftRight, Link2, ScanSearch, Search, SearchX, X } from "lucide-react";
import type { SearchResponse } from "@/types/contract";
import { fetchSearch } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatNumber, formatPrice, cleanSearchQuery, normalizeArabicAggressive, hasArabicChars } from "@/lib/format";
import { useCompareSummary } from "@/lib/useCompareSummary";
import { FEATURED_LINK_STORES, STORE_META, storeDisplayName } from "@/lib/stores";
import { ProductImage } from "./ProductImage";
import { VerdictBadge } from "./VerdictBadge";
import { StoreBadge } from "./StoreBadge";

/**
 * Detects store-URL pastes (direct-link checker) vs plain text queries.
 * `GET /api/v1/products/search` receives `url=` for links, `q=` for text.
 */
function extractUrlCandidate(raw: string): string | null {
  const s = raw.trim();
  if (s.length === 0) return null;
  if (/^https?:\/\//i.test(s)) return s;
  if (s.includes("/") && /^[a-z0-9-]+(\.[a-z0-9-]+)+(\/.*)?$/i.test(s)) {
    return `https://${s}`;
  }
  return null;
}

export interface ExternalSearchTrigger {
  query: string;
  seq: number;
}

export function SearchBar({
  externalTrigger,
}: {
  externalTrigger?: ExternalSearchTrigger | null;
}) {
  const { lang, t } = useLanguage();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const { summary: compareSummary } = useCompareSummary();
  const storesByKey = compareSummary?.storesByKey;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [open, setOpen] = useState(false);
  const [wasUrl, setWasUrl] = useState(false);

  const executeSearch = useCallback(async (rawInput: string) => {
    const trimmed = rawInput.trim();
    if (trimmed.length === 0) return;
    const url = extractUrlCandidate(trimmed);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setNotFound(false);
    setOpen(true);
    setWasUrl(url !== null);
    try {
      // Primary attempt: lightly cleaned query (spaces + diacritics), letters
      // kept exactly as typed so ILIKE matches store titles verbatim.
      const q = url ? undefined : cleanSearchQuery(trimmed);
      const { data } = await fetchSearch(
        url ? { url, limit: 6 } : { q, limit: 6 },
        controller.signal,
      );

      // Bilingual recall fallback: when the primary Arabic query finds nothing,
      // retry once with aggressively normalized letters (أإآ→ا، ى→ي، ة→ه، ث→ت)
      // — Egyptian stores spell the same product differently across listings.
      const needsArabicRetry =
        !url && data.total === 0 && hasArabicChars(trimmed);

      if (needsArabicRetry && !controller.signal.aborted) {
        const retry = await fetchSearch(
          { q: normalizeArabicAggressive(trimmed), limit: 6 },
          controller.signal,
        ).catch(() => null);
        if (retry && !controller.signal.aborted) {
          setResults(retry.data);
          setNotFound(retry.data.total === 0);
          setLoading(false);
          return;
        }
      }

      setResults(data);
      setNotFound(data.total === 0 || data.match_type === "url_not_found");
    } catch {
      if (!controller.signal.aborted) {
        setResults(null);
        setNotFound(true);
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  // Allow hero quick-try chips to run an immediate search
  useEffect(() => {
    if (!externalTrigger || !externalTrigger.query.trim()) return;
    setQuery(externalTrigger.query);
    void executeSearch(externalTrigger.query);
  }, [externalTrigger, executeSearch]);

  const goToProduct = (productSk: string) => {
    setOpen(false);
    router.push(`/products/${productSk}`);
  };

  const reset = () => {
    abortRef.current?.abort();
    setQuery("");
    setResults(null);
    setNotFound(false);
    setOpen(false);
    setLoading(false);
    inputRef.current?.focus();
  };

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    void executeSearch(query);
  };

  const urlDetected = extractUrlCandidate(query) !== null;
  const isUrlNotFound =
    wasUrl && (results?.match_type === "url_not_found" || (notFound && !loading));

  return (
    <div className="relative">
      {open ? (
        <button
          type="button"
          aria-label="Close results"
          className="fixed inset-0 z-30 cursor-default"
          onClick={() => setOpen(false)}
        />
      ) : null}

      <form onSubmit={handleSubmit} className="relative z-40" role="search">
        <div className="surface flex items-center gap-2 rounded-2xl p-1.5 ps-3.5 shadow-[0_14px_48px_rgba(0,0,0,0.55)] transition focus-within:border-teal-400/50 focus-within:ring-2 focus-within:ring-teal-400/15 sm:ps-4">
          {urlDetected ? (
            <Link2 className="size-4 shrink-0 text-emerald-400 sm:size-5" />
          ) : (
            <Search className="size-4 shrink-0 text-slate-400 sm:size-5" />
          )}
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => (results || notFound) && setOpen(true)}
            placeholder={t("search.placeholder")}
            className="h-10 min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-500 sm:h-11"
            aria-label={t("search.placeholder")}
          />
          {urlDetected ? (
            <span className="hidden shrink-0 items-center gap-1 rounded-full border border-emerald-400/30 bg-emerald-500/12 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 md:inline-flex">
              {t("search.urlBadge")}
            </span>
          ) : null}
          {query ? (
            <button
              type="button"
              onClick={reset}
              aria-label="Clear"
              className="rounded-full p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
            >
              <X className="size-4" />
            </button>
          ) : null}
          <button
            type="submit"
            disabled={loading || query.trim().length === 0}
            className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-gradient-to-r from-teal-400 to-emerald-400 px-3.5 text-xs font-bold text-[#031214] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45 sm:h-11 sm:gap-2 sm:px-5 sm:text-sm"
          >
            <ScanSearch className="size-4 shrink-0" />
            <span>{loading ? t("search.checking") : t("search.button")}</span>
          </button>
        </div>
      </form>

      {open ? (
        <div className="surface absolute inset-x-0 top-full z-40 mt-2 max-h-[26rem] overflow-y-auto rounded-2xl p-2 shadow-[0_24px_70px_rgba(0,0,0,0.8)]">
          {loading ? (
            <div className="space-y-2 p-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl p-2">
                  <div className="skeleton size-11 shrink-0 rounded-lg" />
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="skeleton h-3.5 w-3/4" />
                    <div className="skeleton h-3 w-1/3" />
                  </div>
                  <div className="skeleton h-5 w-20 rounded-full" />
                </div>
              ))}
            </div>
          ) : isUrlNotFound ? (
            <div className="p-4">
              <div className="flex items-start gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-amber-400/25 bg-amber-400/10 text-amber-300">
                  <Link2 className="size-4" />
                </span>
                <div className="min-w-0 space-y-1.5">
                  <p className="text-sm font-bold text-white">
                    {t("search.urlNotFoundTitle")}
                  </p>
                  <p className="text-xs leading-relaxed text-slate-400">
                    {t("search.urlNotFoundBody")}
                  </p>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {FEATURED_LINK_STORES.map((slug) => (
                      <span
                        key={slug}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] font-medium text-slate-300"
                      >
                        {storeDisplayName(slug, lang)}{" "}
                        <span className="text-slate-500">({STORE_META[slug]?.domain})</span>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ) : notFound || !results || results.items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
              <SearchX className="size-6 text-slate-500" />
              <p className="text-sm font-semibold text-slate-300">{t("search.noResults")}</p>
              <p className="text-xs text-slate-500">{t("search.hint")}</p>
            </div>
          ) : (
            <>
              <p className="flex items-center gap-2 px-3 pb-1.5 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {wasUrl ? (
                  <>
                    <Link2 className="size-3.5 text-emerald-400" />
                    {t("search.urlMatch")}
                  </>
                ) : (
                  <>
                    <Search className="size-3.5 text-teal-400" />
                    {t("search.textMatch")}
                  </>
                )}
              </p>
              <ul className="divide-y divide-white/[0.05]">
                {results.items.map((item) => {
                  const matchStores = item.canonical_product_key
                    ? storesByKey?.[item.canonical_product_key]
                    : undefined;
                  return (
                  <li key={item.product_sk}>
                    <button
                      type="button"
                      onClick={() => goToProduct(item.product_sk)}
                      className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-start transition hover:bg-white/[0.05]"
                    >
                      <ProductImage
                        src={item.image_url}
                        alt={item.product_title}
                        category={item.category}
                        subCategory={item.sub_category}
                        brand={item.brand}
                        fit={item.category === "fashion" ? "cover" : "contain"}
                        objectPosition={item.category === "fashion" ? "top" : "center"}
                        studio={item.category !== "fashion"}
                        className="size-11 shrink-0 rounded-lg"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-slate-100">
                          {item.product_title}
                        </span>
                        <span className="mt-1 flex flex-wrap items-center gap-2">
                          <StoreBadge name={item.store_name} size="sm" />
                          <span className="num text-xs font-bold text-white">
                            {formatPrice(item.current_price, lang)}
                          </span>
                          {matchStores && matchStores >= 2 ? (
                            <span className="num inline-flex items-center gap-1 rounded-full border border-emerald-400/35 bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-bold text-emerald-300">
                              <ArrowLeftRight className="size-3 shrink-0" />
                              {formatNumber(matchStores, lang)}
                            </span>
                          ) : null}
                        </span>
                      </span>
                      <span className="hidden shrink-0 sm:inline-flex">
                        <VerdictBadge verdict={item.discount_verdict} size="sm" />
                      </span>
                    </button>
                  </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
