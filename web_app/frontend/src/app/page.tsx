"use client";

import { useEffect, useState } from "react";
import type { RadarFeedResponse, StatsOverview } from "@/types/contract";
import { fetchRadarFeed, fetchStatsOverview, type ApiResult } from "@/lib/api";
import { browseHref, parseCategory, parsePage, setBrowseParams, useBrowseParams } from "@/lib/browse-state";
import { formatDateTime, formatNumber, formatPrice } from "@/lib/format";
import { observedTimestamp } from "@/lib/highlights";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";
import { defaultFilters, FeedFilters, type FeedFilterState, sortOptions, verdictOptions } from "@/components/FeedFilters";
import { AdSlot } from "@/components/AdSlot";
import { EditorialGuide } from "@/components/EditorialGuide";
import { MockBanner } from "@/components/MockBanner";
import { Pagination } from "@/components/Pagination";
import { ProductCard } from "@/components/ProductCard";
import { SearchBar, useProductSearch } from "@/components/SearchBar";
import { ErrorState } from "@/components/states";

const PAGE_LIMIT = 12;

function ResultSkeleton() {
  const { t } = useLanguage();
  return <div className="surface ptr-list" role="status">
    <span className="sr-only">{t("common.loading")}</span>
    {[0, 1, 2, 3].map((item) => <div key={item} className="ptr-list-skeleton" aria-hidden="true">
      <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
    </div>)}
  </div>;
}

function ExampleReceipt() {
  const { lang, t } = useLanguage();
  return (
    <aside className="ptr-example" aria-label={t("ui.example")}>
      <div className="ptr-example-heading"><strong>{t("ui.receipt")}</strong><span className="ptr-badge">{t("ui.example")}</span></div>
      <dl className="ptr-receipt-rows">
        <div><dt>{t("detail.current")}</dt><dd><bdi>{formatPrice(4000, lang)}</bdi></dd></div>
        <div><dt>{t("deals.claimedPrice")}</dt><dd><bdi>{formatPrice(5000, lang)}</bdi></dd></div>
        <div><dt>{t("detail.median60")}</dt><dd><bdi>{formatPrice(4000, lang)}</bdi></dd></div>
      </dl>
      <p>{t("deals.advertised", { pct: "20%" })} · {t("ui.same")}</p>
    </aside>
  );
}

export default function HomePage() {
  const { lang, t } = useLanguage();
  const params = useBrowseParams();
  const category = parseCategory(params.get("category"));
  const store = params.get("store") ?? "";
  const sort = sortOptions.find((value) => value === params.get("sort")) ?? defaultFilters.sort;
  const verdict = verdictOptions.find((value) => value === params.get("verdict")) ?? "";
  const page = parsePage(params.get("page"));
  const key = JSON.stringify([category, verdict, store, sort, page]);
  const from = browseHref("/", params);
  const search = useProductSearch(from);
  const [stats, setStats] = useState<ApiResult<StatsOverview> | null>(null);
  const [feed, setFeed] = useState<{ key: string; value: ApiResult<RadarFeedResponse> } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchStatsOverview(controller.signal).then((value) => {
      if (!controller.signal.aborted) setStats(value);
    }).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(null);
    fetchRadarFeed({ category, verdict: verdict || undefined, store: store || undefined, sort, page, limit: PAGE_LIMIT },
      controller.signal).then((value) => {
      if (!controller.signal.aborted) setFeed({ key, value });
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(key);
    });
    return () => controller.abort();
  }, [key, category, verdict, store, sort, page, attempt]);

  const current = feed?.key === key ? feed.value : null;
  const loading = !current && failed !== key;
  const liveStats = stats?.source === "api";
  const storedStats = stats?.data;
  const checked = liveStats ? observedTimestamp(storedStats?.last_pipeline_run_at) : null;
  const storeChoices = liveStats || current?.source !== "api"
    ? storedStats?.available_stores ?? []
    : (current.data.items.map((product) => product.store_name));
  const searchState = search.state;
  const searchResult = searchState?.status === "ready" ? searchState.result : null;
  const searchItems = searchResult?.data.items ?? [];

  function updateFilters(next: FeedFilterState) {
    setBrowseParams({
      category: next.category === "all" ? undefined : next.category,
      verdict: next.verdict || undefined,
      store: next.store || undefined,
      sort: next.sort === defaultFilters.sort ? undefined : next.sort,
      page: undefined,
    });
  }

  function scrollToResults() {
    document.getElementById("radar-results")?.scrollIntoView({ block: "start" });
  }

  return (
    <div className="ptr-wrap ptr-page">
      <section className="ptr-hero">
        <div className="min-w-0">
          <p className="ptr-eyebrow">{t("hero.overline")}</p>
          <h1>{t("hero.title")}</h1>
          <p className="ptr-hero-lede">{t("hero.subtitle")}</p>
          <SearchBar search={search} />
        </div>
        <ExampleReceipt />
      </section>

      <div className="ptr-home-meta">
        {storedStats && <details>
          <summary className="ptr-link">
            {t("kpi.title")} · {t("kpi.storesValue", { count: formatNumber(storedStats.available_stores.length, lang) })}
            {stats.source === "mock" && ` · ${t("ui.sample")}`}
          </summary>
          <p className="ptr-muted mt-2">{t("kpi.totalTracked")} · <bdi>{formatNumber(storedStats.total_tracked, lang)}</bdi></p>
          <div className="ptr-controls my-2">
            {([
              ["FAKE_DISCOUNT", storedStats.fake_discounts_today], ["GENUINE_DEAL", storedStats.genuine_deals_today],
              ["ALL_TIME_LOW", storedStats.all_time_lows_today], ["PRESALE_HIKE", storedStats.presale_hikes_today],
            ] as const).map(([value, count]) => <button type="button" className="ptr-chip" key={value}
              onClick={() => { search.clear(); updateFilters({ category, store, sort, verdict: value }); scrollToResults(); }}>
              {t(`verdict.${value}`)} · <bdi>{formatNumber(count, lang)}</bdi>
            </button>)}
          </div>
          <div className="ptr-controls ptr-stores-scroll">
            {storedStats.available_stores.map((name) => <button className="ptr-chip" type="button" key={name}
              onClick={() => { search.clear(); updateFilters({ category, verdict, sort, store: name }); scrollToResults(); }}>
              {storeDisplayName(name, lang)}
            </button>)}
          </div>
        </details>}
        {checked && <p className="ptr-muted">{t("ui.lastChecked", { time: formatDateTime(checked, lang) })}</p>}
      </div>

      <section id="radar-results" className="min-w-0 space-y-3" aria-busy={searchState ? searchState.status === "loading" : loading}>
        <div className="ptr-toolbar ptr-result-heading">
          <h2>{t(searchState ? searchResult?.data.match_type === "fuzzy_trgm" ? "search.similar" : "search.results" : "feed.title")}</h2>
          {searchState && <button type="button" className="ptr-link" onClick={search.clear}>{t("search.close")}</button>}
          {!searchState && current && <p className="ptr-muted text-sm" role="status">
            {t("filters.showing", { total: formatNumber(current.data.total, lang) })}
          </p>}
        </div>
        {!searchState && <>
          <FeedFilters value={{ category, verdict, store, sort }} stores={storeChoices}
            categoryCounts={storedStats?.category_counts} onChange={updateFilters} />
          <MockBanner source={current?.source ?? null} onRetry={() => setAttempt((value) => value + 1)} />
          {failed === key && <ErrorState onRetry={() => setAttempt((value) => value + 1)} />}
          {loading && <ResultSkeleton />}
          {current && current.data.items.length === 0 && <div className="surface ptr-empty">
            <p>{t("feed.empty")}</p><button type="button" className="ptr-button" onClick={() => updateFilters(defaultFilters)}>{t("filters.reset")}</button>
          </div>}
          {current && current.data.items.length > 0 && <div className="surface ptr-list">
            {current.data.items.map((product) => <ProductCard key={product.product_sk} product={product} from={from} source={current.source} />)}
          </div>}
          {current && <Pagination page={page} totalPages={current.data.total_pages} onPage={(value) => {
            setBrowseParams({ page: value > 1 ? value : undefined });
            scrollToResults();
          }} />}
        </>}
        {searchState?.status === "loading" && <ResultSkeleton />}
        {searchState?.status === "error" && <ErrorState message={t("search.error")} onRetry={() => void search.run(searchState.query)} />}
        {searchState?.status === "invalid" && <p className="ptr-notice ptr-warning" role="alert">{t("search.invalidUrl")}</p>}
        {searchResult && <>
          <MockBanner source={searchResult.source} />
          {searchItems.length === 0 ? <div className="surface ptr-empty" role="status">
            <p className="font-semibold">{t(searchState?.link ? "search.urlNotFoundTitle" : "search.noResults")}</p>
            <p className="ptr-muted">{t("search.hint")}</p>
          </div> : <>
            <p className="text-sm ptr-muted" role="status">
              {t(searchResult.data.match_type === "url_exact" ? "search.urlMatch" : searchResult.data.match_type === "fuzzy_trgm" ? "search.similar" : "search.textMatch")}
              {" · "}<bdi>{formatNumber(searchItems.length, lang)}</bdi>
            </p>
            <div className="surface ptr-list">{searchItems.map((product) => <ProductCard
              key={product.product_sk} product={product} from={from} source={searchResult.source} />)}</div>
          </>}
        </>}
      </section>

      <AdSlot
        slot={process.env.NEXT_PUBLIC_ADSENSE_SLOT_HOME}
        format="auto"
        minHeight={100}
      />

      <EditorialGuide variant="home" />
    </div>
  );
}
