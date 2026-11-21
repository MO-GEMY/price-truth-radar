"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Link2, ScanSearch, Search, X } from "lucide-react";
import type { SearchResponse } from "@/types/contract";
import { fetchSearch } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatPrice } from "@/lib/format";
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

export function SearchBar() {
  const { lang, t } = useLanguage();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [open, setOpen] = useState(false);
  const [wasUrl, setWasUrl] = useState(false);

  const runSearch = useCallback(async () => {
    const raw = query;
    if (raw.trim().length === 0) return;
    const url = extractUrlCandidate(raw);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setNotFound(false);
    setOpen(true);
    setWasUrl(url !== null);
    try {
      const { data } = await fetchSearch(
        url ? { url, limit: 6 } : { q: raw.trim(), limit: 6 },
        controller.signal,
      );
      setResults(data);
      setNotFound(data.total === 0);
    } catch {
      if (!controller.signal.aborted) {
        setResults(null);
        setNotFound(true);
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [query]);

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
    void runSearch();
  };

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
        <div className="glass flex items-center gap-2 rounded-2xl px-4 py-2 shadow-[0_8px_40px_rgba(2,8,20,0.55)] focus-within:border-cyan-400/50">
          <Search className="size-5 shrink-0 text-slate-400" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results && setOpen(true)}
            placeholder={t("search.placeholder")}
            className="h-11 w-full bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
            aria-label={t("search.placeholder")}
          />
          {query ? (
            <button
              type="button"
              onClick={reset}
              aria-label="Clear"
              className="rounded-full p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
            >
              <X className="size-4" />
            </button>
          ) : null}
          <button
            type="submit"
            disabled={loading || query.trim().length === 0}
            className="flex h-10 shrink-0 items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-4 text-sm font-bold text-[#04121a] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ScanSearch className="size-4" />
            <span>{loading ? t("search.checking") : t("search.button")}</span>
          </button>
        </div>
        <p className="mt-2 px-1 text-[11px] text-slate-500">{t("search.hint")}</p>
      </form>

      {open ? (
        <div className="glass absolute inset-x-0 top-full z-40 mt-2 max-h-96 overflow-y-auto rounded-2xl p-2 shadow-[0_16px_60px_rgba(2,8,20,0.7)]">
          {loading ? (
            <p className="px-3 py-4 text-sm text-slate-400">{t("search.checking")}</p>
          ) : notFound || !results || results.items.length === 0 ? (
            <p className="px-3 py-4 text-sm text-slate-400">{t("search.noResults")}</p>
          ) : (
            <>
              <p className="flex items-center gap-2 px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                {wasUrl ? (
                  <>
                    <Link2 className="size-3 text-emerald-400" />
                    {t("search.urlMatch")}
                  </>
                ) : (
                  <>
                    <Search className="size-3 text-cyan-400" />
                    {t("search.textMatch")}
                  </>
                )}
              </p>
              <ul>
                {results.items.map((item) => (
                  <li key={item.product_sk}>
                    <button
                      type="button"
                      onClick={() => goToProduct(item.product_sk)}
                      className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start transition hover:bg-white/[0.06]"
                    >
                      <span className="num flex w-28 shrink-0 flex-col text-sm font-bold text-white">
                        {formatPrice(item.current_price, lang)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-slate-100">
                          {item.product_title}
                        </span>
                        <span className="mt-1 flex items-center gap-2">
                          <StoreBadge name={item.store_name} size="sm" />
                          <span className="text-[11px] text-slate-500">{item.brand}</span>
                        </span>
                      </span>
                      <VerdictBadge verdict={item.discount_verdict} size="sm" />
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
