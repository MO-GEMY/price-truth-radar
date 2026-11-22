"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeftRight,
  ChevronDown,
  HelpCircle,
  Home,
  Link2,
  Radar,
  RotateCcw,
  SearchX,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import type { DiscountVerdict, RadarFeedResponse, StatsOverview } from "@/types/contract";
import { fetchRadarFeed, fetchStatsOverview, type DataSource } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatNumber } from "@/lib/format";
import { storeAccent, storeDisplayName } from "@/lib/stores";
import { useCompareSummary } from "@/lib/useCompareSummary";
import { KpiBar } from "@/components/KpiBar";
import { SearchBar, type ExternalSearchTrigger } from "@/components/SearchBar";
import { CompareSpotlight } from "@/components/CompareSpotlight";
import {
  CATEGORY_LABEL_KEY,
  FeedFilters,
  type FeedFilterState,
} from "@/components/FeedFilters";
import { VerdictLegend } from "@/components/VerdictLegend";
import { Pagination } from "@/components/Pagination";
import { ProductCard } from "@/components/ProductCard";
import { MockBanner } from "@/components/MockBanner";
import {
  ErrorState,
  KpiSkeletons,
  ProductCardSkeletons,
} from "@/components/states";

const PAGE_LIMIT = 12;
/** Stores shown in the hero strip before collapsing into a "+N more" pill. */
const MAX_VISIBLE_STORES = 10;
const DEFAULT_FILTERS: FeedFilterState = {
  category: "all",
  verdict: "",
  store: "",
  sort: "claimed_vs_real_gap_desc",
};

export default function HomePage() {
  const { lang, t } = useLanguage();
  const router = useRouter();
  const feedSectionRef = useRef<HTMLElement>(null);

  const [stats, setStats] = useState<StatsOverview | null>(null);
  const [statsSource, setStatsSource] = useState<DataSource | null>(null);
  const [statsError, setStatsError] = useState(false);

  const [feed, setFeed] = useState<RadarFeedResponse | null>(null);
  const [feedSource, setFeedSource] = useState<DataSource | null>(null);
  const [feedLoading, setFeedLoading] = useState(true);
  const [feedError, setFeedError] = useState(false);

  const [filters, setFilters] = useState<FeedFilterState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [searchTrigger, setSearchTrigger] = useState<ExternalSearchTrigger | null>(null);
  const [showHowItWorks, setShowHowItWorks] = useState(false);
  const [showAllStores, setShowAllStores] = useState(false);

  const { summary: compareSummary } = useCompareSummary();

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

  const stores = stats?.available_stores ?? [];

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

  const resetFilters = () => {
    setFilters(DEFAULT_FILTERS);
    setPage(1);
  };

  const scrollToFeed = () => {
    feedSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const handleSelectStoreChip = (slug: string) => {
    updateFilters({
      ...filters,
      store: filters.store === slug ? "" : slug,
    });
    scrollToFeed();
  };

  const handleSelectKpiVerdict = (verdict: DiscountVerdict) => {
    updateFilters({
      ...filters,
      verdict: filters.verdict === verdict ? "" : verdict,
    });
    scrollToFeed();
  };

  const hasActiveFilters =
    filters.category !== DEFAULT_FILTERS.category ||
    filters.verdict !== DEFAULT_FILTERS.verdict ||
    filters.store !== DEFAULT_FILTERS.store ||
    filters.sort !== DEFAULT_FILTERS.sort;

  const activeSummaryParts: string[] = [];
  if (filters.category !== "all") {
    activeSummaryParts.push(t(CATEGORY_LABEL_KEY[filters.category]));
  }
  if (filters.store) {
    activeSummaryParts.push(storeDisplayName(filters.store, lang));
  }
  if (filters.verdict) {
    activeSummaryParts.push(t(`verdict.${filters.verdict}`));
  }
  activeSummaryParts.push(t("filters.sortedBy", { sort: t(`sort.${filters.sort}`) }));

  const bannerSource: DataSource | null =
    feedSource === "mock" || statsSource === "mock" ? "mock" : (feedSource ?? statsSource);

  return (
    <>
      <MockBanner source={bannerSource} />

      {/* Compact, High-Authority Hero + Command Search + Zero-Friction Onboarding */}
      <section className="hero-backdrop border-b border-white/[0.06]">
        <div className="mx-auto max-w-7xl px-4 pb-7 pt-8 sm:px-6 sm:pb-9 sm:pt-10">
          <div className="max-w-3xl">
            <p className="inline-flex items-center gap-2 rounded-full border border-teal-400/25 bg-teal-400/10 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-teal-300">
              <span className="size-1.5 rounded-full bg-teal-300" aria-hidden />
              {t("hero.overline")}
            </p>
            <h1 className="mt-3 text-2xl font-extrabold tracking-tight text-white sm:text-4xl">
              {t("hero.title")}
            </h1>
            {stores.length > 0 ? (
              <p className="mt-2.5 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-[15px]">
                {t("hero.subtitle", { count: formatNumber(stores.length, lang) })}
              </p>
            ) : (
              <span
                className="mt-3.5 block h-4 w-72 max-w-full rounded skeleton"
                aria-hidden
              />
            )}

            {/* Command Search Bar */}
            <div className="mt-5">
              <SearchBar externalTrigger={searchTrigger} />
            </div>

            {/* Quick-Try Interactive Chips — bilingual AR/EN examples */}
            <div className="mt-3.5 flex flex-wrap items-center gap-1.5 sm:gap-2">
              <span className="text-[11px] font-semibold text-slate-500">
                {t("search.quickTryLabel")}
              </span>
              {[
                {
                  key: "search.chipIphone" as const,
                  query: "iPhone",
                },
                {
                  key: "search.chipSharp" as const,
                  query: lang === "ar" ? "تلاجة شارب" : "Sharp fridge",
                },
                {
                  key: "search.chipWasher" as const,
                  query: lang === "ar" ? "غسالة" : "Washing machine",
                },
              ].map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  onClick={() =>
                    setSearchTrigger((prev) => ({
                      query: chip.query,
                      seq: (prev?.seq ?? 0) + 1,
                    }))
                  }
                  className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-medium text-slate-200 transition hover:border-teal-400/40 hover:bg-teal-400/10 hover:text-teal-200"
                >
                  <Sparkles className="size-3 text-teal-400" />
                  {t(chip.key)}
                </button>
              ))}
              <button
                type="button"
                onClick={() => {
                  updateFilters({
                    ...DEFAULT_FILTERS,
                    verdict: "FAKE_DISCOUNT",
                    sort: "claimed_vs_real_gap_desc",
                  });
                  scrollToFeed();
                }}
                className="inline-flex items-center gap-1.5 rounded-full border border-rose-400/25 bg-rose-500/[0.08] px-3 py-1 text-xs font-medium text-rose-200 transition hover:border-rose-400/50 hover:bg-rose-500/15"
              >
                <ShieldAlert className="size-3 text-rose-400" />
                {t("search.chipTopFake")}
              </button>
              <button
                type="button"
                onClick={() => {
                  updateFilters({
                    ...DEFAULT_FILTERS,
                    category: "home_appliances",
                  });
                  scrollToFeed();
                }}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-medium text-slate-200 transition hover:border-teal-400/40 hover:bg-teal-400/10 hover:text-teal-200"
              >
                <Home className="size-3 text-sky-400" />
                {t("search.chipAppliances")}
              </button>
              <button
                type="button"
                onClick={() => router.push("/compare")}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-500/[0.08] px-3 py-1 text-xs font-medium text-emerald-200 transition hover:border-emerald-400/50 hover:bg-emerald-500/15"
              >
                <ArrowLeftRight className="size-3 text-emerald-400" />
                {t("search.chipCompare")}
              </button>
            </div>
          </div>

          {/* Clickable Supported Stores Strip + Collapsible How-It-Works toggle */}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              <span className="me-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                {t("stores.stripLabel")}
              </span>
              {(() => {
                // Keep the strip scannable at 30+ stores: show the first 10 and
                // collapse the rest behind an expandable pill — while always
                // keeping the currently selected store visible.
                const selectedOutside =
                  filters.store &&
                  stores.length > MAX_VISIBLE_STORES &&
                  !stores.slice(0, MAX_VISIBLE_STORES).includes(filters.store);
                const visibleStores =
                  showAllStores || stores.length <= MAX_VISIBLE_STORES
                    ? stores
                    : selectedOutside
                      ? [...stores.slice(0, MAX_VISIBLE_STORES), filters.store]
                      : stores.slice(0, MAX_VISIBLE_STORES);
                const hiddenCount = stores.length - visibleStores.length;

                return (
                  <>
                    {visibleStores.map((slug) => {
                      const isSelected = filters.store === slug;
                      return (
                        <button
                          key={slug}
                          type="button"
                          onClick={() => handleSelectStoreChip(slug)}
                          aria-pressed={isSelected}
                          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition ${
                            isSelected
                              ? "border-teal-400/50 bg-teal-400/15 text-teal-200"
                              : "border-white/[0.08] bg-white/[0.03] text-slate-300 hover:border-white/20 hover:bg-white/[0.07] hover:text-white"
                          }`}
                        >
                          <span
                            className="size-1.5 shrink-0 rounded-full"
                            style={{ backgroundColor: storeAccent(slug) }}
                            aria-hidden
                          />
                          {storeDisplayName(slug, lang)}
                        </button>
                      );
                    })}
                    {hiddenCount > 0 ? (
                      <button
                        type="button"
                        onClick={() => setShowAllStores((v) => !v)}
                        aria-expanded={showAllStores}
                        className="inline-flex items-center gap-1 rounded-full border border-teal-400/30 bg-teal-400/8 px-2.5 py-1 text-xs font-semibold text-teal-300 transition hover:border-teal-400/55 hover:bg-teal-400/15"
                      >
                        <span className="num">
                          {showAllStores
                            ? t("stores.showLess")
                            : t("stores.moreCount", { count: formatNumber(hiddenCount, lang) })}
                        </span>
                        <ChevronDown
                          className={`size-3 shrink-0 transition-transform duration-200 ${
                            showAllStores ? "rotate-180" : ""
                          }`}
                          aria-hidden
                        />
                      </button>
                    ) : null}
                  </>
                );
              })()}
            </div>

            <button
              type="button"
              onClick={() => setShowHowItWorks((v) => !v)}
              aria-expanded={showHowItWorks}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs font-semibold text-slate-300 transition hover:border-teal-400/35 hover:text-white"
            >
              <HelpCircle className="size-3.5 text-teal-400" />
              <span>{t("how.toggle")}</span>
              <ChevronDown
                className={`size-3.5 transition-transform duration-200 ${
                  showHowItWorks ? "rotate-180" : ""
                }`}
              />
            </button>
          </div>

          {/* Ultra-scannable 3-Step Guide */}
          {showHowItWorks ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                { num: "01", icon: Link2, title: t("how.step1Title"), desc: t("how.step1Desc") },
                { num: "02", icon: ShieldAlert, title: t("how.step2Title"), desc: t("how.step2Desc") },
                { num: "03", icon: ArrowLeftRight, title: t("how.step3Title"), desc: t("how.step3Desc") },
              ].map((step) => {
                const Icon = step.icon;
                return (
                  <div
                    key={step.num}
                    className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3.5"
                  >
                    <div className="flex items-center gap-2">
                      <span className="num rounded-md border border-teal-400/25 bg-teal-400/10 px-1.5 py-0.5 text-[10px] font-bold text-teal-300">
                        {step.num}
                      </span>
                      <Icon className="size-3.5 text-slate-400" />
                      <h3 className="text-xs font-bold text-white">{step.title}</h3>
                    </div>
                    <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{step.desc}</p>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      </section>

      <div className="mx-auto max-w-7xl space-y-9 px-4 py-7 sm:px-6 sm:py-9">
        {/* Smart Dynamic KPI Strip — zero dead 0 tiles */}
        {stats && !statsError ? (
          <KpiBar
            stats={stats}
            compareTotal={compareSummary?.total ?? null}
            activeVerdict={filters.verdict}
            onSelectVerdict={handleSelectKpiVerdict}
          />
        ) : statsError ? (
          <ErrorState onRetry={loadStats} />
        ) : (
          <KpiSkeletons count={4} />
        )}

        {/* Cross-Store Savings Spotlight surfaced right on Home */}
        {compareSummary && compareSummary.topBySavings.length > 0 ? (
          <CompareSpotlight
            matches={compareSummary.topBySavings}
            total={compareSummary.total}
          />
        ) : null}

        {/* Radar Feed + Structured Filters + Active Summary */}
        <section ref={feedSectionRef} id="radar-feed" className="space-y-4 scroll-mt-20">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-extrabold tracking-tight text-white sm:text-xl">
              <Radar className="size-5 text-teal-400" />
              {t("nav.feed")}
            </h2>
          </div>

          <FeedFilters value={filters} stores={stores} onChange={updateFilters} />

          <VerdictLegend />

          {/* Active Filter Summary Bar + one-click Reset */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-2.5 text-xs">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-slate-300">
              <span className="num font-bold text-white">
                {feed
                  ? t("filters.showing", { total: formatNumber(feed.total, lang) })
                  : t("common.loading")}
              </span>
              {activeSummaryParts.map((part) => (
                <span key={part} className="inline-flex items-center gap-2 text-slate-400">
                  <span className="text-slate-600" aria-hidden>
                    •
                  </span>
                  <span>{part}</span>
                </span>
              ))}
            </div>

            {hasActiveFilters ? (
              <button
                type="button"
                onClick={resetFilters}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-teal-400/35 bg-teal-400/10 px-2.5 py-1 text-xs font-semibold text-teal-200 transition hover:border-teal-400/60 hover:bg-teal-400/20"
              >
                <RotateCcw className="size-3" />
                {t("filters.reset")}
              </button>
            ) : null}
          </div>

          {feedError && !feed ? (
            <ErrorState
              onRetry={() => {
                const controller = new AbortController();
                loadFeed(controller);
              }}
            />
          ) : feed === null && feedLoading ? (
            <ProductCardSkeletons count={8} />
          ) : feed && feed.items.length === 0 ? (
            <div className="surface flex flex-col items-center gap-3 rounded-2xl px-6 py-14 text-center">
              <span className="flex size-12 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-slate-400">
                <SearchX className="size-6" />
              </span>
              <p className="text-sm font-bold text-slate-200">{t("feed.empty")}</p>
              <p className="max-w-sm text-xs text-slate-500">{t("feed.emptyHint")}</p>
              {hasActiveFilters ? (
                <button
                  type="button"
                  onClick={resetFilters}
                  className="mt-1 inline-flex items-center gap-1.5 rounded-full border border-teal-400/35 bg-teal-400/12 px-4 py-1.5 text-xs font-semibold text-teal-200 transition hover:bg-teal-400/20"
                >
                  <RotateCcw className="size-3.5" />
                  {t("filters.reset")}
                </button>
              ) : null}
            </div>
          ) : feed ? (
            <div
              className={`grid grid-cols-1 gap-4 transition-opacity sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 ${
                feedLoading ? "opacity-55" : ""
              }`}
            >
              {feed.items.map((product) => (
                <ProductCard
                  key={product.product_sk}
                  product={product}
                  compareStoreCount={
                    product.canonical_product_key
                      ? compareSummary?.storesByKey[product.canonical_product_key]
                      : undefined
                  }
                />
              ))}
            </div>
          ) : null}

          {feed ? (
            <div className="pt-2">
              <Pagination
                page={feed.page}
                totalPages={feed.total_pages}
                onPage={(p) => {
                  setPage(p);
                  scrollToFeed();
                }}
              />
            </div>
          ) : null}
        </section>
      </div>
    </>
  );
}
