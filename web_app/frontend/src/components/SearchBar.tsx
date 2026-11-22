"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Search, X } from "lucide-react";
import type { SearchResponse } from "@/types/contract";
import { fetchSearch, type ApiResult } from "@/lib/api";
import { productHref } from "@/lib/browse-state";
import { cleanSearchQuery, hasArabicChars, normalizeArabicAggressive } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";

type SearchState = { query: string; link: boolean } & (
  | { status: "loading" | "error" | "invalid" }
  | { status: "ready"; result: ApiResult<SearchResponse> }
);

// Keep the result within this browser view so Back can restore it after a receipt.
// Pasted retailer URLs are never written to storage or route parameters.
let lastSearch: Extract<SearchState, { status: "ready" }> | null = null;

function retailerQuery(input: string): string | null {
  if (/^https?:\/\//i.test(input)) return input;
  if (/^[a-z0-9.-]+\.[a-z]{2,}\//i.test(input)) return `https://${input}`;
  return null;
}

export function useProductSearch(from: string) {
  const router = useRouter();
  const [query, setQuery] = useState(() => lastSearch?.query ?? "");
  const [state, setState] = useState<SearchState | null>(() => lastSearch);
  const request = useRef<AbortController | null>(null);

  useEffect(() => () => request.current?.abort(), []);

  function clear() {
    request.current?.abort();
    lastSearch = null;
    setQuery("");
    setState(null);
  }

  async function run(rawQuery: string) {
    const input = rawQuery.trim();
    if (!input) return;
    const url = retailerQuery(input);
    const link = url !== null;
    request.current?.abort();
    if (url) {
      try { new URL(url); } catch {
        setState({ query: input, link, status: "invalid" });
        return;
      }
    }
    const controller = new AbortController();
    request.current = controller;
    setState({ query: input, link, status: "loading" });
    try {
      const q = url ? undefined : cleanSearchQuery(input);
      let result = await fetchSearch({ q, url: url ?? undefined, limit: 20 }, controller.signal);
      if (!url && !result.data.items.length && hasArabicChars(input)) {
        const normalized = normalizeArabicAggressive(input);
        if (normalized !== q && !controller.signal.aborted) {
          result = await fetchSearch({ q: normalized, limit: 20 }, controller.signal);
        }
      }
      if (controller.signal.aborted) return;
      const ready = { query: input, link, status: "ready", result } as const;
      lastSearch = ready;
      setState(ready);
      if (link && result.data.match_type === "url_exact" && result.data.items.length === 1) {
        router.push(productHref(result.data.items[0].product_sk, from, result.source === "mock"));
      }
    } catch {
      if (!controller.signal.aborted) setState({ query: input, link, status: "error" });
    }
  }

  return { query, setQuery, state, clear, run };
}

export function SearchBar({ search }: { search: ReturnType<typeof useProductSearch> }) {
  const { t } = useLanguage();
  const field = useRef<HTMLInputElement>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void search.run(search.query);
  }

  function clear() {
    search.clear();
    field.current?.focus();
  }

  return (
    <form className="ptr-search" role="search" onSubmit={submit}>
      <label htmlFor="ptr-search-query" className="ptr-label">{t("search.label")}</label>
      <div className="ptr-search-row">
        <div className="ptr-search-field">
          <Search size={17} aria-hidden="true" />
          <input ref={field} id="ptr-search-query" type="search" dir="auto" autoComplete="off"
            value={search.query} onChange={(event) => search.setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); clear(); } }}
            placeholder={t("search.placeholder")} />
          {search.query && <button type="button" className="ptr-icon-button" onClick={clear} aria-label={t("search.clear")}>
            <X size={15} aria-hidden="true" />
          </button>}
        </div>
        <button className="ptr-button ptr-primary" disabled={!search.query.trim() || search.state?.status === "loading"} type="submit">
          {t(search.state?.status === "loading" ? "search.checking" : "search.button")}
        </button>
      </div>
    </form>
  );
}
