"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  BadgeCheck,
  Check,
  Filter,
  Link2,
  Search,
  ShieldAlert,
  X,
} from "lucide-react";
import type { FeedCategoryFilter, SearchResponse } from "@/types/contract";
import { fetchSearch, type ApiResult } from "@/lib/api";
import { trackSearchProduct } from "@/lib/analytics";
import { categoryLabels, productHref } from "@/lib/browse-state";
import { getCategorySearchCopy } from "@/lib/category-search-config";
import {
  cleanSearchQuery,
  hasArabicChars,
  normalizeArabicAggressive,
} from "@/lib/format";
import { useLanguage } from "@/lib/i18n";

export interface SearchScope {
  category: FeedCategoryFilter;
  subcategory: string;
  store: string;
  brand: string;
}

type SearchState = { query: string; link: boolean } & (
  | { status: "loading" | "error" | "invalid" }
  | { status: "ready"; result: ApiResult<SearchResponse> }
);

// Keep the result within this browser view so Back can restore it after a receipt.
// Pasted retailer URLs are never written to storage or route parameters.
let lastSearch: (Extract<SearchState, { status: "ready" }> & { scopeKey: string }) | null = null;

function retailerQuery(input: string): string | null {
  if (/^https?:\/\//i.test(input)) return input;
  if (/^[a-z0-9.-]+\.[a-z]{2,}\//i.test(input)) return `https://${input}`;
  return null;
}

function makeScopeKey(scope: SearchScope): string {
  return JSON.stringify([scope.category, scope.subcategory, scope.store, scope.brand]);
}

export function useProductSearch(
  from: string,
  scope: SearchScope,
  urlQuery: string,
  onUrlQueryChange?: (nextQuery: string | undefined) => void,
) {
  const router = useRouter();
  const scopeKey = makeScopeKey(scope);
  const initialQuery = urlQuery.trim() || lastSearch?.query || "";
  const [query, setQuery] = useState(initialQuery);
  const [state, setState] = useState<SearchState | null>(() => {
    if (urlQuery.trim()) {
      return lastSearch &&
        lastSearch.query === urlQuery.trim() &&
        lastSearch.scopeKey === scopeKey
        ? lastSearch
        : null;
    }
    return lastSearch && lastSearch.scopeKey === scopeKey ? lastSearch : null;
  });
  const request = useRef<AbortController | null>(null);
  const lastExecutedRef = useRef<string>(
    lastSearch && lastSearch.query === initialQuery && lastSearch.scopeKey === scopeKey
      ? `${lastSearch.query}::${lastSearch.scopeKey}`
      : "",
  );

  useEffect(() => () => request.current?.abort(), []);

  async function execute(
    rawQuery: string,
    activeScope: SearchScope,
    syncUrl: boolean,
  ) {
    const input = rawQuery.trim();
    if (!input) return;
    const url = retailerQuery(input);
    const link = url !== null;
    const activeScopeKey = makeScopeKey(activeScope);
    request.current?.abort();
    if (url) {
      try {
        new URL(url);
      } catch {
        setState({ query: input, link, status: "invalid" });
        return;
      }
    } else if (syncUrl) {
      onUrlQueryChange?.(input);
    }

    const execSig = `${input}::${activeScopeKey}`;
    lastExecutedRef.current = execSig;

    const controller = new AbortController();
    request.current = controller;
    setState({ query: input, link, status: "loading" });
    try {
      const q = url ? undefined : cleanSearchQuery(input);
      const searchParams = {
        q,
        url: url ?? undefined,
        category: !url && activeScope.category !== "all" ? activeScope.category : undefined,
        subcategory: !url && activeScope.subcategory ? activeScope.subcategory : undefined,
        store: !url && activeScope.store ? activeScope.store : undefined,
        brand: !url && activeScope.brand ? activeScope.brand : undefined,
        limit: 20,
      };
      let result = await fetchSearch(searchParams, controller.signal);
      if (!url && !result.data.items.length && hasArabicChars(input)) {
        const normalized = normalizeArabicAggressive(input);
        if (normalized !== q && !controller.signal.aborted) {
          result = await fetchSearch(
            { ...searchParams, q: normalized },
            controller.signal,
          );
        }
      }
      if (controller.signal.aborted) return;
      const ready = {
        query: input,
        link,
        status: "ready" as const,
        result,
        scopeKey: activeScopeKey,
      };
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
      if (!controller.signal.aborted) {
        setState({ query: input, link, status: "error" });
      }
    }
  }

  // Re-run or restore search when URL `?q=` or active filter scope changes.
  useEffect(() => {
    const trimmed = urlQuery.trim();
    if (!trimmed) {
      // Only clear text search state when `?q=` disappears (preserve URL-paste results).
      if (state && !state.link) {
        request.current?.abort();
        lastSearch = null;
        lastExecutedRef.current = "";
        setQuery("");
        setState(null);
      }
      return;
    }
    const sig = `${trimmed}::${scopeKey}`;
    if (lastExecutedRef.current === sig) return;
    setQuery(trimmed);
    void execute(trimmed, scope, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery, scopeKey]);

  function clear() {
    request.current?.abort();
    lastSearch = null;
    lastExecutedRef.current = "";
    setQuery("");
    setState(null);
    if (urlQuery.trim()) {
      onUrlQueryChange?.(undefined);
    }
  }

  async function run(rawQuery: string) {
    await execute(rawQuery, scope, true);
  }

  return { query, setQuery, state, clear, run };
}

export function SearchBar({
  search,
  category = "all",
  subcategory = "",
  subcategoryLabel,
  onClearCategory,
  onClearSubcategory,
  onFilterVerifiedDeals,
  onFilterDiscountsToReview,
}: {
  search: ReturnType<typeof useProductSearch>;
  category?: FeedCategoryFilter;
  subcategory?: string;
  subcategoryLabel?: string | null;
  onClearCategory?: () => void;
  onClearSubcategory?: () => void;
  onFilterVerifiedDeals?: () => void;
  onFilterDiscountsToReview?: () => void;
}) {
  const { lang, t } = useLanguage();
  const field = useRef<HTMLInputElement>(null);
  const isUrlInput = retailerQuery(search.query.trim()) !== null;
  const categoryCopy = getCategorySearchCopy(category);
  const placeholder = categoryCopy
    ? lang === "ar"
      ? categoryCopy.placeholderAr
      : categoryCopy.placeholderEn
    : t("search.placeholder");
  const quickChips: readonly string[] = categoryCopy
    ? lang === "ar"
      ? categoryCopy.chipsAr
      : categoryCopy.chipsEn
    : [t("search.chipIphone"), t("search.chipSharp"), t("search.chipWasher")];

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
    <form className="ptr-search" role="search" onSubmit={submit} data-tour="search">
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
            placeholder={placeholder}
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

      {category !== "all" && !isUrlInput && (
        <div className="ptr-search-scope-row" role="status">
          <span className="ptr-search-scope-pill">
            <Filter size={12} aria-hidden="true" />
            <span>
              {t("search.searchingIn")}: {t(categoryLabels[category] ?? "filters.catAll")}
              {subcategory && subcategoryLabel ? ` › ${subcategoryLabel}` : ""}
            </span>
          </span>
          {subcategory && onClearSubcategory && (
            <button
              type="button"
              className="ptr-search-scope-clear"
              onClick={onClearSubcategory}
            >
              <X size={12} aria-hidden="true" />
              <span>{t(categoryLabels[category] ?? "filters.catAll")}</span>
            </button>
          )}
          {onClearCategory && (
            <button
              type="button"
              className="ptr-search-scope-clear"
              onClick={onClearCategory}
              aria-label={t("search.clearScope")}
            >
              <X size={12} aria-hidden="true" />
              <span>{t("search.allCategories")}</span>
            </button>
          )}
        </div>
      )}

      <div className="ptr-quick-try" aria-label={t("search.quickTryLabel")}>
        <span className="ptr-quick-try-label">{t("search.quickTryLabel")}</span>
        {quickChips.map((term) => (
          <button
            key={`${category}-${term}`}
            type="button"
            className="ptr-quick-chip"
            onClick={() => runQuickQuery(term)}
          >
            {term}
          </button>
        ))}
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
