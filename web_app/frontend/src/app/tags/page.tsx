"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
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
  categoryLabels,
  parseCategory,
  parsePage,
  setBrowseParams,
  useBrowseParams,
} from "@/lib/browse-state";
import { formatNumber, formatSubCategory } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";
import {
  defaultFilters,
  FeedFilters,
  type FeedFilterState,
  sortOptions,
  verdictOptions,
} from "@/components/FeedFilters";
import { InlineBadgeGuide } from "@/components/LandingDiscovery";
import { MockBanner } from "@/components/MockBanner";
import { Pagination } from "@/components/Pagination";
import { ProductCard } from "@/components/ProductCard";
import { ErrorState, FeedResultSkeleton } from "@/components/states";

const PAGE_LIMIT = 12;

export default function TagsPage() {
  const { lang, t } = useLanguage();
  const params = useBrowseParams();
  const category = parseCategory(params.get("category"));
  const subcategory = (params.get("subcategory") ?? "").trim().toLowerCase();
  const brand = (params.get("brand") ?? "").trim();
  const store = (params.get("store") ?? "").trim().toLowerCase();
  const sort =
    sortOptions.find((value) => value === params.get("sort")) ??
    defaultFilters.sort;
  const verdict =
    verdictOptions.find((value) => value === params.get("verdict")) ?? "";
  const page = parsePage(params.get("page"));
  const key = JSON.stringify([category, subcategory, brand, verdict, store, sort, page]);
  const facetsKey = `${category}::${subcategory}`;
  const from = browseHref("/tags", params);

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
  const [view, setView] = useState<"list" | "grid">("grid");

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

  useEffect(() => {
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
  }, [key, category, subcategory, brand, verdict, store, sort, page, attempt]);

  const current = feed?.key === key ? feed.value : null;
  const loading = !current && failed !== key;
  const liveStats = stats?.source === "api";
  const storedStats = stats?.data;
  const storeChoices =
    category !== "all" && activeFacets?.stores?.length
      ? activeFacets.stores.map((s) => s.slug)
      : liveStats || current?.source !== "api"
        ? (storedStats?.available_stores ?? [])
        : current.data.items.map((product) => product.store_name);

  const activeSubcatObj = activeFacets?.subcategories.find(
    (s) => s.slug === subcategory,
  );
  const activeSubcatLabel = activeSubcatObj
    ? lang === "ar"
      ? activeSubcatObj.label_ar
      : activeSubcatObj.label_en
    : subcategory
      ? formatSubCategory(subcategory, lang)
      : null;

  const headingParts: string[] = [];
  if (activeSubcatLabel) headingParts.push(activeSubcatLabel);
  if (brand) headingParts.push(brand);
  if (store) headingParts.push(storeDisplayName(store, lang));
  if (category !== "all") {
    headingParts.push(t(categoryLabels[category] ?? "filters.catAll"));
  }
  if (verdict) headingParts.push(t(`verdict.${verdict}`));
  const headingTitle =
    headingParts.length > 0 ? headingParts.join(" · ") : t("feed.title");

  function updateFilters(next: FeedFilterState) {
    setBrowseParams({
      category: next.category === "all" ? undefined : next.category,
      subcategory: next.subcategory || undefined,
      brand: next.brand || undefined,
      verdict: next.verdict || undefined,
      store: next.store || undefined,
      sort: next.sort === defaultFilters.sort ? undefined : next.sort,
      page: undefined,
    });
  }

  function scrollToResults() {
    window.requestAnimationFrame(() => {
      document
        .getElementById("tag-results")
        ?.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  return (
    <div className="ptr-wrap ptr-page">
      <Link
        className="ptr-link inline-flex w-fit items-center gap-2 text-sm"
        href="/"
      >
        <ArrowLeft size={16} aria-hidden="true" className="rtl:rotate-180" />
        {t("tags.backHome")}
      </Link>

      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">{t("tags.eyebrow")}</p>
        <div className="ptr-toolbar ptr-result-heading">
          <div className="min-w-0 space-y-1">
            <h1>
              <bdi>{headingTitle}</bdi>
            </h1>
            {current && (
              <p className="ptr-muted text-sm" role="status">
                {t("tags.subtitle", {
                  total: formatNumber(current.data.total, lang),
                })}
              </p>
            )}
          </div>
          <div className="ptr-controls">
            <InlineBadgeGuide />
          </div>
        </div>
      </header>

      <section
        id="tag-results"
        className="min-w-0 space-y-4"
        aria-busy={loading}
      >
        <FeedFilters
          value={{ category, subcategory, brand, verdict, store, sort }}
          stores={storeChoices}
          stats={storedStats}
          categoryCounts={storedStats?.category_counts}
          facets={activeFacets}
          facetsLoading={facetsLoading}
          view={view}
          onViewChange={setView}
          onChange={updateFilters}
        />

        <MockBanner
          source={current?.source ?? null}
          onRetry={() => setAttempt((value) => value + 1)}
        />
        {failed === key && (
          <ErrorState onRetry={() => setAttempt((value) => value + 1)} />
        )}
        {loading && <FeedResultSkeleton view={view} />}

        {current && current.data.items.length === 0 && (
          <div className="surface ptr-empty">
            <p className="font-semibold">{t("tags.empty")}</p>
            <p className="ptr-muted text-sm">{t("tags.emptyHint")}</p>
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
      </section>
    </div>
  );
}
