"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronUp, Store } from "lucide-react";
import type {
  CategoryFacetsResponse,
  RadarFeedResponse,
  StatsOverview,
} from "@/types/contract";
import {
  fetchCategoryFacets,
  fetchRadarFeed,
  fetchStatsOverview,
  type ApiResult,
} from "@/lib/api";
import {
  browseHref,
  parseCategory,
  parsePage,
  setBrowseParams,
  useBrowseParams,
} from "@/lib/browse-state";
import { formatDateTime, formatNumber } from "@/lib/format";
import { observedTimestamp } from "@/lib/highlights";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";
import {
  defaultFilters,
  FeedFilters,
  type FeedFilterState,
  sortOptions,
  verdictOptions,
} from "@/components/FeedFilters";
import { AdSlot } from "@/components/AdSlot";
import { EditorialGuide } from "@/components/EditorialGuide";
import { MockBanner } from "@/components/MockBanner";
import { Pagination } from "@/components/Pagination";
import { ProductCard } from "@/components/ProductCard";
import { SearchBar, useProductSearch } from "@/components/SearchBar";
import { ErrorState } from "@/components/states";

const PAGE_LIMIT = 12;

function ResultSkeleton({ view }: { view: "list" | "grid" }) {
  const { t } = useLanguage();
  if (view === "grid") {
    return (
      <div className="asarak-product-grid" role="status">
        <span className="sr-only">{t("common.loading")}</span>
        {[0, 1, 2, 3, 4, 5].map((item) => (
          <div key={item} className="surface p-4 space-y-3" aria-hidden="true">
            <div className="skeleton aspect-[4/3] w-full rounded-xl" />
            <div className="skeleton h-4 w-3/4" />
            <div className="skeleton h-4 w-1/2" />
            <div className="skeleton h-6 w-1/3" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="surface ptr-list" role="status">
      <span className="sr-only">{t("common.loading")}</span>
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="ptr-list-skeleton" aria-hidden="true">
          <span className="skeleton" />
          <span className="skeleton" />
          <span className="skeleton" />
        </div>
      ))}
    </div>
  );
}

export default function HomePage() {
  const { lang, t } = useLanguage();
  const params = useBrowseParams();
  const category = parseCategory(params.get("category"));
  const subcategory = category === "all" ? "" : (params.get("subcategory") ?? "").trim().toLowerCase();
  const brand = (params.get("brand") ?? "").trim();
  const store = params.get("store") ?? "";
  const urlQuery = params.get("q") ?? "";
  const sort =
    sortOptions.find((value) => value === params.get("sort")) ??
    defaultFilters.sort;
  const verdict =
    verdictOptions.find((value) => value === params.get("verdict")) ?? "";
  const page = parsePage(params.get("page"));
  const key = JSON.stringify([category, subcategory, brand, verdict, store, sort, page]);
  const facetsKey = `${category}::${subcategory}`;
  const from = browseHref("/", params);

  const search = useProductSearch(
    from,
    { category, subcategory, store, brand },
    urlQuery,
    (nextQuery) => {
      setBrowseParams({
        q: nextQuery && nextQuery.trim() ? nextQuery.trim() : undefined,
        page: undefined,
      });
    },
  );

  const [stats, setStats] = useState<ApiResult<StatsOverview> | null>(null);
  const [facetsState, setFacetsState] = useState<{
    key: string;
    value: ApiResult<CategoryFacetsResponse>;
  } | null>(null);
  const [feed, setFeed] = useState<{
    key: string;
    value: ApiResult<RadarFeedResponse>;
  } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<"list" | "grid">("list");
  const [storesOpen, setStoresOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchStatsOverview(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setStats(value);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (category === "all") return;
    const controller = new AbortController();
    fetchCategoryFacets(category, subcategory || undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setFacetsState({ key: facetsKey, value });
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [category, subcategory, facetsKey]);

  const activeFacets =
    category !== "all" && facetsState?.value.data.category === category
      ? facetsState.value.data
      : null;
  const facetsLoading =
    category !== "all" && facetsState?.key !== facetsKey && !activeFacets;

  const hasActiveTextSearch = Boolean(urlQuery.trim() || search.state);

  useEffect(() => {
    if (hasActiveTextSearch) return;
    const controller = new AbortController();
    setFailed(null);
    fetchRadarFeed(
      {
        category,
        subcategory: subcategory || undefined,
        brand: brand || undefined,
        verdict: verdict || undefined,
        store: store || undefined,
        sort,
        page,
        limit: PAGE_LIMIT,
      },
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setFeed({ key, value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(key);
      });
    return () => controller.abort();
  }, [key, category, subcategory, brand, verdict, store, sort, page, attempt, hasActiveTextSearch]);

  const current = feed?.key === key ? feed.value : null;
  const loading = !current && failed !== key;
  const liveStats = stats?.source === "api";
  const storedStats = stats?.data;
  const checked = liveStats
    ? observedTimestamp(storedStats?.last_pipeline_run_at)
    : null;
  const storeChoices =
    category !== "all" && activeFacets?.stores?.length
      ? activeFacets.stores.map((s) => s.slug)
      : liveStats || current?.source !== "api"
        ? (storedStats?.available_stores ?? [])
        : current.data.items.map((product) => product.store_name);
  const drawerStores =
    category !== "all" && activeFacets?.stores?.length
      ? activeFacets.stores.map((s) => s.slug)
      : (storedStats?.available_stores ?? []);

  const searchState = search.state;
  const searchResult =
    searchState?.status === "ready" ? searchState.result : null;
  const searchItems = searchResult?.data.items ?? [];

  const activeSubcatObj = activeFacets?.subcategories.find(
    (s) => s.slug === subcategory,
  );
  const activeSubcatLabel = activeSubcatObj
    ? lang === "ar"
      ? activeSubcatObj.label_ar
      : activeSubcatObj.label_en
    : subcategory
      ? subcategory.replace(/_/g, " ")
      : null;

  function updateFilters(next: FeedFilterState) {
    setBrowseParams({
      category: next.category === "all" ? undefined : next.category,
      subcategory:
        next.category !== "all" && next.subcategory ? next.subcategory : undefined,
      brand: next.brand || undefined,
      verdict: next.verdict || undefined,
      store: next.store || undefined,
      sort: next.sort === defaultFilters.sort ? undefined : next.sort,
      page: undefined,
    });
  }

  function scrollToResults() {
    document
      .getElementById("radar-results")
      ?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function filterByVerdict(nextVerdict: FeedFilterState["verdict"]) {
    search.clear();
    updateFilters({
      category,
      subcategory,
      brand,
      store,
      sort,
      verdict: verdict === nextVerdict ? "" : nextVerdict,
    });
    scrollToResults();
  }

  return (
    <>
      <section className="asarak-hero-greeting">
        <div className="ptr-wrap">
          <div className="asarak-hero-center">
            <p className="ptr-eyebrow">
              {storedStats && storedStats.available_stores.length > 0
                ? t("hero.overlineDynamic", {
                    count: formatNumber(storedStats.available_stores.length, lang),
                  })
                : t("hero.overline")}
            </p>
            <h1>{t("hero.title")}</h1>
            <p className="ptr-hero-lede">{t("hero.subtitle")}</p>
            <SearchBar
              search={search}
              category={category}
              subcategory={subcategory}
              subcategoryLabel={activeSubcatLabel}
              onClearCategory={() =>
                updateFilters({
                  ...defaultFilters,
                  verdict,
                  sort,
                })
              }
              onClearSubcategory={() =>
                updateFilters({
                  category,
                  subcategory: "",
                  brand: "",
                  verdict,
                  store,
                  sort,
                })
              }
              onFilterVerifiedDeals={() => filterByVerdict("GENUINE_DEAL")}
              onFilterDiscountsToReview={() => filterByVerdict("FAKE_DISCOUNT")}
            />
          </div>

          {storedStats && (
            <div className="asarak-kpi-section" aria-label={t("kpi.title")}>
              <div className="asarak-kpi-grid">
                <button
                  type="button"
                  className="asarak-kpi-card"
                  aria-expanded={storesOpen}
                  onClick={() => setStoresOpen((prev) => !prev)}
                >
                  <span className="asarak-kpi-value">
                    <bdi>{formatNumber(storedStats.total_tracked, lang)}</bdi>
                  </span>
                  <span className="asarak-kpi-label">
                    {t("kpi.totalTracked")}
                  </span>
                  <span className="asarak-kpi-sub">
                    <Store size={12} aria-hidden="true" />
                    <span>
                      {t("kpi.storesValue", {
                        count: formatNumber(
                          storedStats.available_stores.length,
                          lang,
                        ),
                      })}
                    </span>
                    {storesOpen ? (
                      <ChevronUp size={12} aria-hidden="true" />
                    ) : (
                      <ChevronDown size={12} aria-hidden="true" />
                    )}
                  </span>
                </button>

                <button
                  type="button"
                  className="asarak-kpi-card"
                  aria-pressed={verdict === "GENUINE_DEAL"}
                  onClick={() => filterByVerdict("GENUINE_DEAL")}
                >
                  <span className="asarak-kpi-value asarak-kpi-value--emerald">
                    <bdi>
                      {formatNumber(storedStats.genuine_deals_today, lang)}
                    </bdi>
                  </span>
                  <span className="asarak-kpi-label">
                    {t("kpi.genuineDeals")}
                  </span>
                  <span className="asarak-kpi-sub">
                    {t("kpi.activeFilterHint")}
                  </span>
                </button>

                <button
                  type="button"
                  className="asarak-kpi-card"
                  aria-pressed={verdict === "FAKE_DISCOUNT"}
                  onClick={() => filterByVerdict("FAKE_DISCOUNT")}
                >
                  <span className="asarak-kpi-value">
                    <bdi>
                      {formatNumber(storedStats.fake_discounts_today, lang)}
                    </bdi>
                  </span>
                  <span className="asarak-kpi-label">
                    {t("kpi.fakeDiscounts")}
                  </span>
                  <span className="asarak-kpi-sub">
                    {t("kpi.activeFilterHint")}
                  </span>
                </button>

                {storedStats.all_time_lows_today > 0 ? (
                  <button
                    type="button"
                    className="asarak-kpi-card"
                    aria-pressed={verdict === "ALL_TIME_LOW"}
                    onClick={() => filterByVerdict("ALL_TIME_LOW")}
                  >
                    <span className="asarak-kpi-value asarak-kpi-value--emerald">
                      <bdi>
                        {formatNumber(storedStats.all_time_lows_today, lang)}
                      </bdi>
                    </span>
                    <span className="asarak-kpi-label">
                      {t("kpi.allTimeLows")}
                    </span>
                    <span className="asarak-kpi-sub">
                      {t("kpi.activeFilterHint")}
                    </span>
                  </button>
                ) : (
                  <Link href="/compare" className="asarak-kpi-card">
                    <span className="asarak-kpi-value asarak-kpi-value--emerald">
                      <bdi>
                        {formatNumber(
                          storedStats.cross_store_matches_count ?? 0,
                          lang,
                        )}
                      </bdi>
                    </span>
                    <span className="asarak-kpi-label">
                      {t("kpi.crossStoreCompared")}
                    </span>
                    <span className="asarak-kpi-sub">
                      {t("kpi.crossStoreCta")}
                    </span>
                  </Link>
                )}
              </div>

              <div className="asarak-kpi-meta">
                <button
                  type="button"
                  className="ptr-link inline-flex items-center gap-1.5"
                  onClick={() => setStoresOpen((prev) => !prev)}
                >
                  <Store size={14} aria-hidden="true" />
                  <span>
                    {storesOpen
                      ? t("stores.hideAll")
                      : t("stores.browseAll", {
                          count: formatNumber(drawerStores.length, lang),
                        })}
                  </span>
                  {stats?.source === "mock" && ` · ${t("ui.sample")}`}
                </button>
                {checked && (
                  <p className="ptr-muted">
                    {t("ui.lastChecked", {
                      time: formatDateTime(checked, lang),
                    })}
                  </p>
                )}
              </div>

              {storesOpen && (
                <div className="asarak-store-drawer">
                  <div className="ptr-controls ptr-stores-scroll">
                    <button
                      className="ptr-chip"
                      type="button"
                      aria-pressed={store === ""}
                      onClick={() => {
                        updateFilters({
                          category,
                          subcategory,
                          brand,
                          verdict,
                          sort,
                          store: "",
                        });
                        scrollToResults();
                      }}
                    >
                      {t("stores.allLabel")}
                    </button>
                    {drawerStores.map((name) => (
                      <button
                        className="ptr-chip"
                        type="button"
                        key={name}
                        aria-pressed={store === name}
                        onClick={() => {
                          updateFilters({
                            category,
                            subcategory,
                            brand,
                            verdict,
                            sort,
                            store: name,
                          });
                          scrollToResults();
                        }}
                      >
                        {storeDisplayName(name, lang)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <div className="ptr-wrap ptr-page">
        <section
          id="radar-results"
          className="min-w-0 space-y-4"
          aria-busy={searchState ? searchState.status === "loading" : loading}
        >
          <div className="ptr-toolbar ptr-result-heading">
            <h2>
              {t(
                searchState
                  ? searchResult?.data.match_type === "fuzzy_trgm"
                    ? "search.similar"
                    : "search.results"
                  : "feed.title",
              )}
            </h2>
            {searchState && (
              <button type="button" className="ptr-link" onClick={search.clear}>
                {t("search.close")}
              </button>
            )}
            {!searchState && current && (
              <p className="ptr-muted text-sm" role="status">
                {t("filters.showing", {
                  total: formatNumber(current.data.total, lang),
                })}
              </p>
            )}
          </div>

          <FeedFilters
            value={{ category, subcategory, brand, verdict, store, sort }}
            stores={storeChoices}
            categoryCounts={storedStats?.category_counts}
            facets={activeFacets}
            facetsLoading={facetsLoading}
            view={view}
            onViewChange={setView}
            onChange={updateFilters}
          />

          {!searchState && (
            <>
              <MockBanner
                source={current?.source ?? null}
                onRetry={() => setAttempt((value) => value + 1)}
              />
              {failed === key && (
                <ErrorState onRetry={() => setAttempt((value) => value + 1)} />
              )}
              {loading && <ResultSkeleton view={view} />}
              {current && current.data.items.length === 0 && (
                <div className="surface ptr-empty">
                  <p className="font-semibold">{t("feed.empty")}</p>
                  <p className="ptr-muted text-sm">{t("feed.emptyHint")}</p>
                  <button
                    type="button"
                    className="ptr-button ptr-primary"
                    onClick={() => updateFilters(defaultFilters)}
                  >
                    {t("filters.reset")}
                  </button>
                </div>
              )}
              {current &&
                current.data.items.length > 0 &&
                (view === "grid" ? (
                  <div className="asarak-product-grid">
                    {current.data.items.map((product) => (
                      <ProductCard
                        key={product.product_sk}
                        product={product}
                        from={from}
                        source={current.source}
                        view="grid"
                      />
                    ))}
                  </div>
                ) : (
                  <div className="surface ptr-list">
                    {current.data.items.map((product) => (
                      <ProductCard
                        key={product.product_sk}
                        product={product}
                        from={from}
                        source={current.source}
                        view="list"
                      />
                    ))}
                  </div>
                ))}
              {current && (
                <Pagination
                  page={page}
                  totalPages={current.data.total_pages}
                  onPage={(value) => {
                    setBrowseParams({ page: value > 1 ? value : undefined });
                    scrollToResults();
                  }}
                />
              )}
            </>
          )}

          {searchState?.status === "loading" && <ResultSkeleton view={view} />}
          {searchState?.status === "error" && (
            <ErrorState
              message={t("search.error")}
              onRetry={() => void search.run(searchState.query)}
            />
          )}
          {searchState?.status === "invalid" && (
            <p className="ptr-notice ptr-warning" role="alert">
              {t("search.invalidUrl")}
            </p>
          )}
          {searchResult && (
            <>
              <MockBanner source={searchResult.source} />
              {searchItems.length === 0 ? (
                <div className="surface ptr-empty" role="status">
                  <p className="font-semibold">
                    {t(
                      searchState?.link
                        ? "search.urlNotFoundTitle"
                        : "search.noResults",
                    )}
                  </p>
                  <p className="ptr-muted">{t("search.hint")}</p>
                  {category !== "all" && !searchState?.link && (
                    <button
                      type="button"
                      className="ptr-button ptr-primary"
                      onClick={() =>
                        updateFilters({
                          ...defaultFilters,
                          verdict,
                          sort,
                        })
                      }
                    >
                      {t("search.clearScope")}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <p className="text-sm ptr-muted" role="status">
                    {t(
                      searchResult.data.match_type === "url_exact"
                        ? "search.urlMatch"
                        : searchResult.data.match_type === "fuzzy_trgm"
                          ? "search.similar"
                          : "search.textMatch",
                    )}
                    {" · "}
                    <bdi>{formatNumber(searchItems.length, lang)}</bdi>
                  </p>
                  {view === "grid" ? (
                    <div className="asarak-product-grid">
                      {searchItems.map((product) => (
                        <ProductCard
                          key={product.product_sk}
                          product={product}
                          from={from}
                          source={searchResult.source}
                          view="grid"
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="surface ptr-list">
                      {searchItems.map((product) => (
                        <ProductCard
                          key={product.product_sk}
                          product={product}
                          from={from}
                          source={searchResult.source}
                          view="list"
                        />
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </section>

        <AdSlot
          slot={process.env.NEXT_PUBLIC_ADSENSE_SLOT_HOME}
          format="auto"
          minHeight={100}
        />

        <EditorialGuide variant="home" />
      </div>
    </>
  );
}
