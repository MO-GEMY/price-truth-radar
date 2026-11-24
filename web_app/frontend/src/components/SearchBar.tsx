"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { BadgeCheck, Check, Link2, Search, ShieldAlert, X } from "lucide-react";
import type { SearchResponse } from "@/types/contract";
import { fetchSearch, type ApiResult } from "@/lib/api";
import { trackSearchProduct } from "@/lib/analytics";
import { productHref } from "@/lib/browse-state";
import {
  cleanSearchQuery,
  hasArabicChars,
  normalizeArabicAggressive,
} from "@/lib/format";
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
      try {
        new URL(url);
      } catch {
        setState({ query: input, link, status: "invalid" });
        return;
      }
    }
    const controller = new AbortController();
    request.current = controller;
    setState({ query: input, link, status: "loading" });
    try {
      const q = url ? undefined : cleanSearchQuery(input);
      let result = await fetchSearch(
        { q, url: url ?? undefined, limit: 20 },
        controller.signal,
      );
      if (!url && !result.data.items.length && hasArabicChars(input)) {
        const normalized = normalizeArabicAggressive(input);
        if (normalized !== q && !controller.signal.aborted) {
          result = await fetchSearch(
            { q: normalized, limit: 20 },
            controller.signal,
          );
        }
      }
      if (controller.signal.aborted) return;
      const ready = { query: input, link, status: "ready", result } as const;
      lastSearch = ready;
      setState(ready);
      trackSearchProduct({
        query: input,
        isUrl: link,
        matchType: result.data.match_type,
        resultsCount: result.data.items.length,
      });
      if (
        link &&
        result.data.match_type === "url_exact" &&
        result.data.items.length === 1
      ) {
        router.push(
          productHref(
            result.data.items[0].product_sk,
            from,
            result.source === "mock",
          ),
        );
      }
    } catch {
      if (!controller.signal.aborted)
        setState({ query: input, link, status: "error" });
    }
  }

  return { query, setQuery, state, clear, run };
}

export function SearchBar({
  search,
  onFilterVerifiedDeals,
  onFilterDiscountsToReview,
}: {
  search: ReturnType<typeof useProductSearch>;
  onFilterVerifiedDeals?: () => void;
  onFilterDiscountsToReview?: () => void;
}) {
  const { t } = useLanguage();
  const field = useRef<HTMLInputElement>(null);
  const isUrlInput = retailerQuery(search.query.trim()) !== null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!search.query.trim()) {
      field.current?.focus();
      return;
    }
    void search.run(search.query);
  }

  function clear() {
    search.clear();
    field.current?.focus();
  }

  function runQuickQuery(term: string) {
    search.setQuery(term);
    void search.run(term);
  }

  return (
    <form className="ptr-search" role="search" onSubmit={submit}>
      <label htmlFor="ptr-search-query" className="sr-only">
        {t("search.label")}
      </label>
      <div className="ptr-search-shell">
        <div className="ptr-search-field">
          {isUrlInput ? (
            <Link2 size={19} aria-hidden="true" style={{ color: "var(--asarak-emerald)" }} />
          ) : (
            <Search size={19} aria-hidden="true" />
          )}
          <input
            ref={field}
            id="ptr-search-query"
            type="search"
            dir={search.query ? "auto" : undefined}
            autoComplete="off"
            value={search.query}
            onChange={(event) => search.setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                clear();
              }
            }}
            placeholder={t("search.placeholder")}
          />
          {isUrlInput && (
            <span className="ptr-url-pill">
              <Link2 size={11} aria-hidden="true" />
              {t("search.urlBadge")}
            </span>
          )}
          {search.query && (
            <button
              type="button"
              className="ptr-icon-button"
              onClick={clear}
              aria-label={t("search.clear")}
            >
              <X size={15} aria-hidden="true" />
            </button>
          )}
        </div>
        <button
          className="ptr-button ptr-primary ptr-search-submit"
          disabled={search.state?.status === "loading"}
          type="submit"
        >
          <Check size={16} strokeWidth={2.5} aria-hidden="true" />
          <span>
            {t(
              search.state?.status === "loading"
                ? "search.checking"
                : "search.button",
            )}
          </span>
        </button>
      </div>

      <div className="ptr-quick-try" aria-label={t("search.quickTryLabel")}>
        <span className="ptr-quick-try-label">{t("search.quickTryLabel")}</span>
        {(
          [
            "search.chipIphone",
            "search.chipSharp",
            "search.chipWasher",
          ] as const
        ).map((key) => {
          const term = t(key);
          return (
            <button
              key={key}
              type="button"
              className="ptr-quick-chip"
              onClick={() => runQuickQuery(term)}
            >
              {term}
            </button>
          );
        })}
        {onFilterVerifiedDeals && (
          <button
            type="button"
            className="ptr-quick-chip"
            onClick={onFilterVerifiedDeals}
          >
            <BadgeCheck size={13} aria-hidden="true" />
            {t("kpi.genuineDeals")}
          </button>
        )}
        {onFilterDiscountsToReview && (
          <button
            type="button"
            className="ptr-quick-chip ptr-quick-chip--review"
            onClick={onFilterDiscountsToReview}
          >
            <ShieldAlert size={13} aria-hidden="true" />
            {t("search.chipTopFake")}
          </button>
        )}
      </div>
    </form>
  );
}
