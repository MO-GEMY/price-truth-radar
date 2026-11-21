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
import { MockBanner } from "@/components/MockBanner";
import { Pagination } from "@/components/Pagination";
import { StoreBadge } from "@/components/StoreBadge";
import { VerdictBadge } from "@/components/VerdictBadge";
import { CompareCardSkeletons, ErrorState } from "@/components/states";

const PAGE_LIMIT = 10;
const CATEGORIES: ("all" | Category)[] = ["all", "electronics", "fashion"];
const SPREAD_OPTIONS = [0, 5, 10, 20];

function MatchCard({ match }: { match: CrossStoreMatch }) {
  const { lang, t } = useLanguage();
  const [expanded, setExpanded] = useState(false);

  return (
    <article className="glass overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/[0.06] p-5 pb-4">
        <div className="min-w-0">
          <h2 className="text-base font-bold leading-snug text-white">
            {match.product_title_clean}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 font-semibold text-slate-300">
              {match.brand}
            </span>
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1">
              {match.category === "electronics" ? "Electronics" : "Fashion"}
            </span>
            <span className="num rounded-full border border-cyan-400/25 bg-cyan-400/10 px-2.5 py-1 font-semibold text-cyan-200">
              {t("compare.storesCount", { count: formatNumber(match.stores_count, lang) })}
            </span>
          </div>
        </div>
        <span className="num flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3.5 py-2 text-sm font-bold text-emerald-300">
          <PiggyBank className="size-4" />
          {t("compare.saving")} {formatPrice(match.price_spread_egp, lang)}
          <span className="text-emerald-400/70">
            ({formatPctPlain(match.price_spread_pct, lang)})
          </span>
        </span>
      </div>

      <div className="grid gap-3 p-5 sm:grid-cols-3">
        <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/[0.07] p-4">
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-emerald-400">
            <TrendingDown className="size-3.5" />
            {t("compare.lowest")}
          </p>
          <p className="num mt-2 text-xl font-extrabold text-emerald-300">
            {formatPrice(match.lowest_price, lang)}
          </p>
          <div className="mt-2">
            <StoreBadge name={match.lowest_price_store} size="sm" />
          </div>
        </div>
        <div className="rounded-xl border border-rose-500/25 bg-rose-500/[0.07] p-4">
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-rose-400">
            <TrendingUp className="size-3.5" />
            {t("compare.highest")}
          </p>
          <p className="num mt-2 text-xl font-extrabold text-rose-300">
            {formatPrice(match.highest_price, lang)}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <StoreBadge
              name={
                match.listings_json.find((l) => l.price === match.highest_price)
                  ?.store_name ?? "—"
              }
              size="sm"
            />
          </div>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
            {t("compare.spreadEgp")} / {t("compare.spreadPct")}
          </p>
          <p className="num mt-2 text-xl font-extrabold text-white">
            {formatPrice(match.price_spread_egp, lang)}
          </p>
          <p className="num mt-1 text-xs font-semibold text-slate-400">
            {formatPctPlain(match.price_spread_pct, lang)}
          </p>
        </div>
      </div>

      {/* Expandable per-store listings (§5.6 listings_json) */}
      <div className="border-t border-white/[0.06]">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center justify-between px-5 py-3 text-sm font-semibold text-slate-300 transition hover:text-cyan-300"
          aria-expanded={expanded}
        >
          <span>{expanded ? t("compare.hideListings") : t("compare.listings")}</span>
          <ChevronDown
            className={`size-4 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          />
        </button>
        {expanded ? (
          <ul className="divide-y divide-white/[0.05] px-2 pb-2">
            {match.listings_json.map((listing, index) => (
              <li
                key={listing.product_sk}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-3"
              >
                <span className="flex min-w-28 items-center gap-2">
                  <StoreBadge name={listing.store_name} size="sm" />
                  {listing.price === match.lowest_price ? (
                    <Crown className="size-3.5 text-emerald-400" />
                  ) : null}
                </span>
                <span className="num min-w-24 text-sm font-bold text-white">
                  {formatPrice(listing.price, lang)}
                </span>
                <VerdictBadge verdict={listing.discount_verdict} size="sm" />
                <span
                  className={`inline-flex items-center gap-1 text-xs font-semibold ${
                    listing.in_stock ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {listing.in_stock ? (
                    <>
                      <Check className="size-3.5" />
                      {t("detail.inStock")}
                    </>
                  ) : (
                    <>
                      <X className="size-3.5" />
                      {t("card.outOfStock")}
                    </>
                  )}
                </span>
                <span className="ms-auto flex items-center gap-2">
                  {index === 0 && listing.price === match.lowest_price ? (
                    <span className="hidden rounded-full border border-emerald-500/40 bg-emerald-500/12 px-2.5 py-0.5 text-[10px] font-bold text-emerald-300 sm:inline">
                      {t("detail.cheapest")}
                    </span>
                  ) : null}
                  <Link
                    href={`/products/${listing.product_sk}`}
                    className="rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-xs font-semibold text-cyan-300 transition hover:bg-cyan-400/20"
                  >
                    {t("compare.viewProduct")}
                  </Link>
                  <a
                    href={listing.product_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${listing.store_name} — ${t("detail.openAtStore")}`}
                    className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition hover:border-white/25 hover:text-white"
                  >
                    <ExternalLink className="size-3.5" />
                  </a>
                </span>
              </li>
            ))}
          </ul>
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
        { category, min_spread_pct: minSpread > 0 ? minSpread : undefined, page, limit: PAGE_LIMIT },
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

  return (
    <>
      <MockBanner source={source} />

      <div className="mx-auto max-w-5xl space-y-6 px-4 py-10 sm:px-6">
        <header className="space-y-3">
          <h1 className="flex items-center gap-3 text-2xl font-extrabold tracking-tight text-white">
            <span className="flex size-10 items-center justify-center rounded-xl border border-cyan-400/30 bg-cyan-400/10 text-cyan-300">
              <ArrowLeftRight className="size-5" />
            </span>
            {t("compare.title")}
          </h1>
          <p className="max-w-2xl text-sm text-slate-400">{t("compare.subtitle")}</p>
        </header>

        {/* Filters */}
        <div className="glass flex flex-col gap-4 rounded-2xl p-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {t("filters.category")}
            </p>
            <div className="inline-flex rounded-xl border border-white/10 bg-white/[0.03] p-1">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => {
                    setCategory(cat);
                    setPage(1);
                  }}
                  className={`rounded-lg px-3.5 py-1.5 text-sm font-semibold transition ${
                    category === cat
                      ? "bg-gradient-to-r from-cyan-500/25 to-emerald-500/25 text-cyan-200 ring-1 ring-cyan-400/40"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  {cat === "all"
                    ? t("filters.catAll")
                    : cat === "electronics"
                      ? t("filters.catElectronics")
                      : t("filters.catFashion")}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {t("compare.minSpread")}
            </p>
            <div className="inline-flex rounded-xl border border-white/10 bg-white/[0.03] p-1">
              {SPREAD_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => {
                    setMinSpread(opt);
                    setPage(1);
                  }}
                  className={`num rounded-lg px-3.5 py-1.5 text-sm font-semibold transition ${
                    minSpread === opt
                      ? "bg-cyan-400/15 text-cyan-200 ring-1 ring-cyan-400/40"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  {opt === 0 ? t("compare.spreadAny") : `≥ ${opt}%`}
                </button>
              ))}
            </div>
          </div>
        </div>

        {data && data.total > 0 ? (
          <p className="num text-xs font-semibold text-slate-400">
            {t("feed.resultsCount", { total: formatNumber(data.total, lang) })}
          </p>
        ) : null}

        {error && !data ? (
          <ErrorState onRetry={() => {
            const controller = new AbortController();
            load(controller);
          }} />
        ) : data === null && loading ? (
          <CompareCardSkeletons count={4} />
        ) : data && data.items.length === 0 ? (
          <div className="glass flex flex-col items-center gap-3 rounded-2xl px-6 py-14 text-center">
            <span className="flex size-12 items-center justify-center rounded-full bg-slate-500/12 text-slate-400">
              <ArrowLeftRight className="size-6" />
            </span>
            <p className="text-sm font-semibold text-slate-300">{t("compare.empty")}</p>
            <p className="text-xs text-slate-500">{t("compare.emptyHint")}</p>
          </div>
        ) : data ? (
          <>
            <div className={`space-y-4 transition-opacity ${loading ? "opacity-50" : ""}`}>
              {data.items.map((match) => (
                <MatchCard key={match.canonical_product_key} match={match} />
              ))}
            </div>
            <Pagination
              page={data.page}
              totalPages={totalPages}
              onPage={setPage}
            />
          </>
        ) : null}
      </div>
    </>
  );
}
