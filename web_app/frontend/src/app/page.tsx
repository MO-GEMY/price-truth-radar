"use client";

import { useCallback, useEffect, useState } from "react";
import { Radar, SearchX } from "lucide-react";
import type { RadarFeedResponse, StatsOverview } from "@/types/contract";
import { fetchRadarFeed, fetchStatsOverview, type DataSource } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatNumber } from "@/lib/format";
import { KpiBar } from "@/components/KpiBar";
import { SearchBar } from "@/components/SearchBar";
import { FeedFilters, type FeedFilterState } from "@/components/FeedFilters";
import { Pagination } from "@/components/Pagination";
import { ProductCard } from "@/components/ProductCard";
import { MockBanner } from "@/components/MockBanner";
import {
  ErrorState,
  KpiSkeletons,
  ProductCardSkeletons,
} from "@/components/states";

const PAGE_LIMIT = 12;
const DEFAULT_FILTERS: FeedFilterState = {
  category: "all",
  verdict: "",
  store: "",
  sort: "claimed_vs_real_gap_desc",
};

export default function HomePage() {
  const { lang, t } = useLanguage();

  const [stats, setStats] = useState<StatsOverview | null>(null);
  const [statsSource, setStatsSource] = useState<DataSource | null>(null);
  const [statsError, setStatsError] = useState(false);

  const [feed, setFeed] = useState<RadarFeedResponse | null>(null);
  const [feedSource, setFeedSource] = useState<DataSource | null>(null);
  const [feedLoading, setFeedLoading] = useState(true);
  const [feedError, setFeedError] = useState(false);

  const [filters, setFilters] = useState<FeedFilterState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [stores, setStores] = useState<string[]>([]);

  const loadStats = useCallback(() => {
    const controller = new AbortController();
    setStatsError(false);
    fetchStatsOverview(controller.signal)
      .then(({ data, source }) => {
        setStats(data);
        setStatsSource(source);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          console.error(err);
          setStatsError(true);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => loadStats(), [loadStats]);

  // Store filter options: sweep all unfiltered feed pages (up to 10 pages × 50)
  // so stores outside the top-50 gap-sorted slice (e.g. sigma) are never omitted.
  useEffect(() => {
    const controller = new AbortController();
    const loadAllStores = async () => {
      try {
        const first = await fetchRadarFeed(
          { category: "all", sort: "price_asc", page: 1, limit: 50 },
          controller.signal,
        );
        const found = new Set(first.data.items.map((p) => p.store_name));
        const maxPages = Math.min(first.data.total_pages, 10);
        if (maxPages > 1) {
          const rest = await Promise.all(
            Array.from({ length: maxPages - 1 }, (_, i) =>
              fetchRadarFeed(
                { category: "all", sort: "price_asc", page: i + 2, limit: 50 },
                controller.signal,
              ),
            ),
          );
          for (const pageRes of rest) {
            for (const item of pageRes.data.items) {
              found.add(item.store_name);
            }
          }
        }
        if (!controller.signal.aborted) {
          setStores([...found].sort());
        }
      } catch {
        /* store filter stays with current options */
      }
    };
    void loadAllStores();
    return () => controller.abort();
  }, []);

  const loadFeed = useCallback(
    (abort: AbortController) => {
      setFeedLoading(true);
      setFeedError(false);
      fetchRadarFeed(
        {
          category: filters.category,
          verdict: filters.verdict === "" ? undefined : filters.verdict,
          store: filters.store === "" ? undefined : filters.store,
          sort: filters.sort,
          page,
          limit: PAGE_LIMIT,
        },
        abort.signal,
      )
        .then(({ data, source }) => {
          setFeed(data);
          setFeedSource(source);
        })
        .catch((err: unknown) => {
          if (!abort.signal.aborted) {
            console.error(err);
            setFeedError(true);
          }
        })
        .finally(() => {
          if (!abort.signal.aborted) setFeedLoading(false);
        });
    },
    [filters, page],
  );

  useEffect(() => {
    const controller = new AbortController();
    loadFeed(controller);
    return () => controller.abort();
  }, [loadFeed]);

  const updateFilters = (next: FeedFilterState) => {
    setFilters(next);
    setPage(1);
  };

  const bannerSource: DataSource | null =
    feedSource === "mock" || statsSource === "mock" ? "mock" : (feedSource ?? statsSource);

  return (
    <>
      <MockBanner source={bannerSource} />

      {/* Hero + direct-link checker */}
      <section className="radar-scene border-b border-white/[0.04]">
        <div className="mx-auto max-w-7xl px-4 pb-8 pt-10 sm:px-6 sm:pt-12">
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-cyan-400/90">
            {t("hero.overline")}
          </p>
          <h1 className="mt-2 max-w-2xl text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            {t("hero.title")}
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-base">
            {t("hero.subtitle")}
          </p>
          <div className="mt-6 max-w-3xl">
            <SearchBar />
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6">
        {/* KPI overview — §5.2 /api/v1/stats/overview */}
        {stats && !statsError ? (
          <KpiBar stats={stats} />
        ) : statsError ? (
          <ErrorState onRetry={loadStats} />
        ) : (
          <KpiSkeletons />
        )}

        {/* Filters + feed — §5.3 /api/v1/radar/feed */}
        <FeedFilters value={filters} stores={stores} onChange={updateFilters} />

        <section className="space-y-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-bold text-white">
              <Radar className="size-5 text-cyan-400" />
              {t("nav.feed")}
            </h2>
            {feed ? (
              <span className="num rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-semibold text-slate-300">
                {t("feed.resultsCount", { total: formatNumber(feed.total, lang) })}
              </span>
            ) : null}
          </div>

          {feedError && !feed ? (
            <ErrorState onRetry={() => {
              const controller = new AbortController();
              loadFeed(controller);
            }} />
          ) : feed === null && feedLoading ? (
            <ProductCardSkeletons count={8} />
          ) : feed && feed.items.length === 0 ? (
            <div className="glass flex flex-col items-center gap-3 rounded-2xl px-6 py-14 text-center">
              <span className="flex size-12 items-center justify-center rounded-full bg-slate-500/12 text-slate-400">
                <SearchX className="size-6" />
              </span>
              <p className="text-sm font-semibold text-slate-300">{t("feed.empty")}</p>
              <p className="text-xs text-slate-500">{t("feed.emptyHint")}</p>
            </div>
          ) : feed ? (
            <div
              className={`grid grid-cols-1 gap-4 transition-opacity sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 ${
                feedLoading ? "opacity-50" : ""
              }`}
            >
              {feed.items.map((product) => (
                <ProductCard key={product.product_sk} product={product} />
              ))}
            </div>
          ) : null}

          {feed ? (
            <Pagination
              page={feed.page}
              totalPages={feed.total_pages}
              onPage={setPage}
            />
          ) : null}
        </section>
      </div>
    </>
  );
}
