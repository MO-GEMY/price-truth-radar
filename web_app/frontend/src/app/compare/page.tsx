"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeftRight,
  Check,
  ChevronDown,
  Crown,
  ExternalLink,
  PiggyBank,
  RotateCcw,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import type {
  Category,
  CompareResponse,
  CrossStoreMatch,
} from "@/types/contract";
import { fetchCompare, type DataSource } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatNumber, formatPctPlain, formatPrice } from "@/lib/format";
import { storeDisplayName } from "@/lib/stores";
import { MockBanner } from "@/components/MockBanner";
import { Pagination } from "@/components/Pagination";
import { StoreBadge } from "@/components/StoreBadge";
import { VerdictBadge } from "@/components/VerdictBadge";
import { VerdictLegend } from "@/components/VerdictLegend";
import { CompareCardSkeletons, ErrorState } from "@/components/states";

const PAGE_LIMIT = 10;
const CATEGORIES: ("all" | Category)[] = [
  "all",
  "electronics",
  "home_appliances",
  "groceries",
  "fashion",
];
const SPREAD_OPTIONS = [0, 5, 10, 20];

function MatchCard({
  match,
  defaultExpanded = false,
}: {
  match: CrossStoreMatch;
  defaultExpanded?: boolean;
}) {
  const { lang, t } = useLanguage();
  const [expanded, setExpanded] = useState(defaultExpanded);

  const highestStore =
    match.listings_json.find((l) => l.price === match.highest_price)?.store_name ?? "";
  const spreadSpan = Math.max(match.highest_price - match.lowest_price, 0);

  return (
    <article className="surface overflow-hidden rounded-2xl">
      {/* Header: Product title + Savings pill */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/[0.06] p-5 pb-4">
        <div className="min-w-0 flex-1">
          <h2 dir="auto" className="text-base font-bold leading-snug text-white sm:text-lg">
            {match.product_title_clean}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5 font-semibold text-slate-200">
              {match.brand}
            </span>
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5">
              {match.category === "electronics"
                ? t("filters.catElectronics")
                : match.category === "home_appliances"
                  ? t("filters.catHomeAppliances")
                  : match.category === "groceries"
                    ? t("filters.catGroceries")
                    : t("filters.catFashion")}
            </span>
            <span className="num rounded-full border border-teal-400/25 bg-teal-400/10 px-2.5 py-0.5 font-semibold text-teal-200">
              {t("compare.storesCount", { count: formatNumber(match.stores_count, lang) })}
            </span>
          </div>
        </div>

        <span className="num inline-flex shrink-0 items-center gap-2 rounded-xl border border-emerald-400/35 bg-emerald-500/12 px-3.5 py-2 text-sm font-extrabold text-emerald-300">
          <PiggyBank className="size-4 shrink-0" />
          {t("compare.saving")}{" "}
          {formatPrice(match.price_spread_egp, lang, { maximumFractionDigits: 0 })}
          <span className="text-emerald-200/80">
            ({formatPctPlain(match.price_spread_pct, lang)})
          </span>
        </span>
      </div>

      {/* Price spread overview well */}
      <div className="grid gap-3 p-5 sm:grid-cols-3">
        <div className="rounded-xl border border-emerald-400/25 bg-emerald-500/[0.07] p-3.5">
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-emerald-400">
            <TrendingDown className="size-3.5" />
            {t("compare.lowest")}
          </p>
          <p className="num mt-1.5 text-xl font-extrabold text-emerald-300">
            {formatPrice(match.lowest_price, lang)}
          </p>
          <div className="mt-2">
            <StoreBadge name={match.lowest_price_store} size="sm" />
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5">
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-400">
            <TrendingUp className="size-3.5 text-rose-400" />
            {t("compare.highest")}
          </p>
          <p className="num mt-1.5 text-xl font-bold text-slate-200">
            {formatPrice(match.highest_price, lang)}
          </p>
          <div className="mt-2">
            {highestStore ? <StoreBadge name={highestStore} size="sm" /> : null}
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
            {t("compare.spreadEgp")} / {t("compare.spreadPct")}
          </p>
          <p className="num mt-1.5 text-xl font-extrabold text-white">
            {formatPrice(match.price_spread_egp, lang)}
          </p>
          <p className="num mt-1 text-xs font-semibold text-emerald-300/90">
            {formatPctPlain(match.price_spread_pct, lang)}
          </p>
        </div>
      </div>

      {/* Expandable 2-Zone Store Breakdown (Price Position vs. Discount Honesty) */}
      <div className="border-t border-white/[0.06]">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center justify-between px-5 py-3 text-xs font-bold text-slate-300 transition hover:bg-white/[0.02] hover:text-teal-200 sm:text-sm"
          aria-expanded={expanded}
        >
          <span>
            {expanded
              ? t("compare.hideListings")
              : t("compare.listings", { count: formatNumber(match.listings_json.length, lang) })}
          </span>
          <ChevronDown
            className={`size-4 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          />
        </button>

        {expanded ? (
          <div className="border-t border-white/[0.05] bg-[#040810]/60 px-3 pb-3 pt-2 sm:px-5">
            {/* Explicit 2-zone column labels on desktop */}
            <div className="hidden grid-cols-12 items-center gap-4 px-3 pb-2 pt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500 md:grid">
              <span className="col-span-5">{t("compare.colPricePos")}</span>
              <span className="col-span-4">{t("compare.colHonesty")}</span>
              <span className="col-span-3 text-end"></span>
            </div>

            <ul className="space-y-2">
              {match.listings_json.map((listing) => {
                const isCheapest = listing.price === match.lowest_price;
                const delta = listing.price - match.lowest_price;
                const positionPct =
                  spreadSpan > 0
                    ? Math.max(8, Math.min(100, Math.round(((listing.price - match.lowest_price) / spreadSpan) * 100)))
                    : 8;

                return (
                  <li
                    key={listing.product_sk}
                    className={`grid grid-cols-1 gap-3 rounded-xl border p-3.5 transition md:grid-cols-12 md:items-center md:gap-4 ${
                      isCheapest
                        ? "border-emerald-400/30 bg-emerald-500/[0.06]"
                        : "border-white/[0.06] bg-white/[0.02] hover:border-white/15"
                    }`}
                  >
                    {/* ZONE 1: Price Position */}
                    <div className="space-y-2 md:col-span-5">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 md:hidden">
                        {t("compare.colPricePos")}
                      </p>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <StoreBadge name={listing.store_name} size="sm" />
                          {isCheapest ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-400/45 bg-emerald-500/18 px-2 py-0.5 text-[10px] font-bold text-emerald-200">
                              <Crown className="size-3 shrink-0" />
                              {t("detail.cheapest")}
                            </span>
                          ) : null}
                        </div>
                        <span className="num text-base font-extrabold text-white">
                          {formatPrice(listing.price, lang)}
                        </span>
                      </div>

                      {/* Horizontal price-range bar comparing store against min/max */}
                      <div className="flex items-center gap-2.5">
                        <div
                          className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.08]"
                          aria-hidden
                        >
                          <div
                            className={`h-full rounded-full ${
                              isCheapest
                                ? "bg-emerald-400"
                                : positionPct > 75
                                  ? "bg-rose-400/80"
                                  : "bg-slate-400/70"
                            }`}
                            style={{ width: `${positionPct}%` }}
                          />
                        </div>
                        <span className="num shrink-0 text-[11px] font-medium text-slate-400">
                          {isCheapest
                            ? t("compare.bestBuy", {
                                count: formatNumber(match.stores_count, lang),
                              })
                            : t("compare.aboveLowest", {
                                amount: formatPrice(delta, lang, { maximumFractionDigits: 0 }),
                              })}
                        </span>
                      </div>
                    </div>

                    {/* ZONE 2: Discount Honesty (visually separated from buy price) */}
                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] pt-2.5 md:col-span-4 md:justify-start md:border-s md:border-t-0 md:ps-4 md:pt-0">
                      <div className="space-y-1.5">
                        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 md:hidden">
                          {t("compare.colHonesty")}
                        </p>
                        <div className="flex flex-wrap items-center gap-2">
                          <VerdictBadge
                            verdict={listing.discount_verdict}
                            size="sm"
                            showInfo
                          />
                          <span
                            className={`inline-flex items-center gap-1 text-[11px] font-semibold ${
                              listing.in_stock ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {listing.in_stock ? (
                              <>
                                <Check className="size-3" />
                                {t("detail.inStock")}
                              </>
                            ) : (
                              <>
                                <X className="size-3" />
                                {t("card.outOfStock")}
                              </>
                            )}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center justify-end gap-2 md:col-span-3">
                      <Link
                        href={`/products/${listing.product_sk}`}
                        className="rounded-lg border border-teal-400/30 bg-teal-400/10 px-3 py-1.5 text-xs font-semibold text-teal-200 transition hover:bg-teal-400/20"
                      >
                        {t("compare.viewProduct")}
                      </Link>
                      <a
                        href={listing.product_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`${storeDisplayName(listing.store_name, lang)} — ${t("detail.openAtStoreGeneric")}`}
                        className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition hover:border-white/25 hover:text-white"
                      >
                        <ExternalLink className="size-3.5" />
                      </a>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>
    </article>
  );
}

export default function ComparePage() {
  const { lang, t } = useLanguage();

  const [category, setCategory] = useState<"all" | Category>("all");
  const [minSpread, setMinSpread] = useState(0);
  const [page, setPage] = useState(1);

  const [data, setData] = useState<CompareResponse | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(
    (abort: AbortController) => {
      setLoading(true);
      setError(false);
      fetchCompare(
        {
          category,
          min_spread_pct: minSpread > 0 ? minSpread : undefined,
          page,
          limit: PAGE_LIMIT,
        },
        abort.signal,
      )
        .then(({ data, source }) => {
          setData(data);
          setSource(source);
        })
        .catch((err: unknown) => {
          if (!abort.signal.aborted) {
            console.error(err);
            setError(true);
          }
        })
        .finally(() => {
          if (!abort.signal.aborted) setLoading(false);
        });
    },
    [category, minSpread, page],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller);
    return () => controller.abort();
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;
  const hasFilters = category !== "all" || minSpread > 0;

  return (
    <>
      <MockBanner source={source} />

      <div className="mx-auto max-w-5xl space-y-6 px-4 py-8 sm:px-6 sm:py-10">
        <header className="space-y-2.5">
          <div className="flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-emerald-400/30 bg-emerald-500/12 text-emerald-300">
              <ArrowLeftRight className="size-5" />
            </span>
            <h1 className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
              {t("compare.title")}
            </h1>
          </div>
          <p className="max-w-2xl text-sm leading-relaxed text-slate-400">
            {t("compare.subtitle")}
          </p>
        </header>

        {/* Filters */}
        <div className="surface flex flex-col gap-4 rounded-2xl p-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {t("filters.category")}
            </p>
            <div className="well inline-flex flex-wrap gap-1 rounded-xl p-1">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => {
                    setCategory(cat);
                    setPage(1);
                  }}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition sm:px-3.5 sm:text-sm ${
                    category === cat
                      ? "bg-teal-400/18 text-teal-200 ring-1 ring-teal-400/35"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  {cat === "all"
                    ? t("filters.catAll")
                    : cat === "electronics"
                      ? t("filters.catElectronics")
                      : cat === "home_appliances"
                        ? t("filters.catHomeAppliances")
                        : cat === "groceries"
                          ? t("filters.catGroceries")
                          : t("filters.catFashion")}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {t("compare.minSpread")}
            </p>
            <div className="well inline-flex rounded-xl p-1">
              {SPREAD_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => {
                    setMinSpread(opt);
                    setPage(1);
                  }}
                  className={`num rounded-lg px-3 py-1.5 text-xs font-semibold transition sm:px-3.5 sm:text-sm ${
                    minSpread === opt
                      ? "bg-emerald-500/18 text-emerald-200 ring-1 ring-emerald-400/35"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  {opt === 0 ? t("compare.spreadAny") : `≥ ${opt}%`}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Scannable Verdict Legend */}
        <VerdictLegend />

        {/* Active results readout + Reset */}
        {data ? (
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <p className="num font-semibold text-slate-300">
              {t("filters.showing", { total: formatNumber(data.total, lang) })}
            </p>
            {hasFilters ? (
              <button
                type="button"
                onClick={() => {
                  setCategory("all");
                  setMinSpread(0);
                  setPage(1);
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/35 bg-teal-400/10 px-2.5 py-1 text-xs font-semibold text-teal-200 transition hover:bg-teal-400/20"
              >
                <RotateCcw className="size-3" />
                {t("filters.reset")}
              </button>
            ) : null}
          </div>
        ) : null}

        {error && !data ? (
          <ErrorState
            onRetry={() => {
              const controller = new AbortController();
              load(controller);
            }}
          />
        ) : data === null && loading ? (
          <CompareCardSkeletons count={4} />
        ) : data && data.items.length === 0 ? (
          <div className="surface flex flex-col items-center gap-3 rounded-2xl px-6 py-14 text-center">
            <span className="flex size-12 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-slate-400">
              <ArrowLeftRight className="size-6" />
            </span>
            <p className="text-sm font-bold text-slate-200">{t("compare.empty")}</p>
            <p className="text-xs text-slate-500">{t("compare.emptyHint")}</p>
          </div>
        ) : data ? (
          <>
            <div className={`space-y-4 transition-opacity ${loading ? "opacity-55" : ""}`}>
              {data.items.map((match, idx) => (
                <MatchCard
                  key={match.canonical_product_key}
                  match={match}
                  defaultExpanded={idx === 0}
                />
              ))}
            </div>
            <Pagination page={data.page} totalPages={totalPages} onPage={setPage} />
          </>
        ) : null}
      </div>
    </>
  );
}
