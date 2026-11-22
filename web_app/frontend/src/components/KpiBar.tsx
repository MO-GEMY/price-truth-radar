"use client";

import Link from "next/link";
import {
  ArrowRight,
  ArrowLeftRight,
  BadgeCheck,
  Database,
  Flame,
  ShieldAlert,
  Store,
  TrendingDown,
  type LucideIcon,
} from "lucide-react";
import type { DiscountVerdict, StatsOverview } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";
import { formatDateTime, formatNumber, formatPctPlain } from "@/lib/format";

interface DynamicPill {
  verdict: DiscountVerdict;
  labelKey: TranslationKey;
  count: number;
  icon: LucideIcon;
  tone: string;
}

export function KpiBar({
  stats,
  compareTotal,
  activeVerdict,
  onSelectVerdict,
}: {
  stats: StatsOverview;
  compareTotal: number | null;
  activeVerdict?: DiscountVerdict | "";
  onSelectVerdict?: (verdict: DiscountVerdict) => void;
}) {
  const { lang, t } = useLanguage();

  const storesCount = stats.available_stores?.length ?? 0;

  // Only surface historical-signal KPI pills when they hold live non-zero counts
  const dynamicSignals: DynamicPill[] = [
    {
      verdict: "GENUINE_DEAL" as DiscountVerdict,
      labelKey: "kpi.genuineDeals" as TranslationKey,
      count: stats.genuine_deals_today,
      icon: BadgeCheck,
      tone: "border-emerald-400/30 bg-emerald-500/10 text-emerald-300 hover:border-emerald-400/50",
    },
    {
      verdict: "ALL_TIME_LOW" as DiscountVerdict,
      labelKey: "kpi.allTimeLows" as TranslationKey,
      count: stats.all_time_lows_today,
      icon: TrendingDown,
      tone: "border-emerald-400/35 bg-emerald-500/12 text-emerald-200 hover:border-emerald-400/60",
    },
    {
      verdict: "PRESALE_HIKE" as DiscountVerdict,
      labelKey: "kpi.presaleHikes" as TranslationKey,
      count: stats.presale_hikes_today,
      icon: Flame,
      tone: "border-rose-400/30 bg-rose-500/10 text-rose-300 hover:border-rose-400/50",
    },
  ].filter((item) => item.count > 0);

  return (
    <section aria-label={t("kpi.title")} className="space-y-3">
      {/* 4 always-live, high-signal KPI cards (zero dead 0 tiles) */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {/* 1. Products Tracked */}
        <div className="surface rounded-2xl p-4 sm:p-5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-400">{t("kpi.totalTracked")}</span>
            <span className="inline-flex size-8 items-center justify-center rounded-lg border border-teal-400/25 bg-teal-400/10 text-teal-300">
              <Database className="size-4" strokeWidth={2} />
            </span>
          </div>
          <p className="num mt-3 text-2xl font-bold tracking-tight text-white sm:text-3xl">
            {formatNumber(stats.total_tracked, lang)}
          </p>
          <p className="mt-1.5 text-[11px] text-slate-500">
            {t("kpi.lastPipelineRun")}:{" "}
            <span className="num text-slate-400">
              {stats.last_pipeline_run_at ? formatDateTime(stats.last_pipeline_run_at, lang) : "—"}
            </span>
          </p>
        </div>

        {/* 2. Fake Discounts Exposed (+ avg inflation pill) */}
        <button
          type="button"
          onClick={() => onSelectVerdict?.("FAKE_DISCOUNT")}
          className={`surface surface-hover group rounded-2xl p-4 text-start sm:p-5 ${
            activeVerdict === "FAKE_DISCOUNT" ? "border-rose-400/50 ring-1 ring-rose-400/30" : ""
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-400">{t("kpi.fakeDiscounts")}</span>
            <span className="inline-flex size-8 items-center justify-center rounded-lg border border-rose-400/25 bg-rose-500/12 text-rose-300">
              <ShieldAlert className="size-4" strokeWidth={2} />
            </span>
          </div>
          <p className="num mt-3 text-2xl font-bold tracking-tight text-white sm:text-3xl">
            {formatNumber(stats.fake_discounts_today, lang)}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {stats.avg_fake_inflation_pct > 0 ? (
              <span className="num inline-flex items-center rounded-full border border-rose-400/25 bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold text-rose-300">
                {t("kpi.avgInflationPill", {
                  pct: formatPctPlain(stats.avg_fake_inflation_pct, lang),
                })}
              </span>
            ) : null}
          </div>
        </button>

        {/* 3. Egyptian Stores */}
        <div className="surface rounded-2xl p-4 sm:p-5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-400">{t("kpi.storesTracked")}</span>
            <span className="inline-flex size-8 items-center justify-center rounded-lg border border-sky-400/25 bg-sky-400/10 text-sky-300">
              <Store className="size-4" strokeWidth={2} />
            </span>
          </div>
          <p className="num mt-3 text-2xl font-bold tracking-tight text-white sm:text-3xl">
            {t("kpi.storesValue", { count: formatNumber(storesCount, lang) })}
          </p>
          <p className="mt-1.5 text-[11px] text-slate-500">{t("kpi.storesHint")}</p>
        </div>

        {/* 4. Cross-Store Matches (direct link to /compare) */}
        <Link
          href="/compare"
          className="surface surface-hover group rounded-2xl p-4 sm:p-5"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-400">
              {t("kpi.crossStoreMatches")}
            </span>
            <span className="inline-flex size-8 items-center justify-center rounded-lg border border-emerald-400/25 bg-emerald-500/12 text-emerald-300">
              <ArrowLeftRight className="size-4" strokeWidth={2} />
            </span>
          </div>
          <p className="num mt-3 text-2xl font-bold tracking-tight text-emerald-300 sm:text-3xl">
            {compareTotal !== null ? formatNumber(compareTotal, lang) : "—"}
          </p>
          <p className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400/90 transition group-hover:text-emerald-300">
            <span>{t("kpi.crossStoreCta")}</span>
            <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5 rtl:rotate-180 rtl:group-hover:-translate-x-0.5" />
          </p>
        </Link>
      </div>

      {/* Dynamic secondary row: active multi-day signal pills when > 0, otherwise concise accumulation bar */}
      {dynamicSignals.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          {dynamicSignals.map((sig) => {
            const Icon = sig.icon;
            const isSelected = activeVerdict === sig.verdict;
            return (
              <button
                key={sig.verdict}
                type="button"
                onClick={() => onSelectVerdict?.(sig.verdict)}
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${sig.tone} ${
                  isSelected ? "ring-2 ring-white/25" : ""
                }`}
              >
                <Icon className="size-3.5 shrink-0" />
                <span>{t(sig.labelKey)}</span>
                <span className="num font-bold">{formatNumber(sig.count, lang)}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="flex items-center gap-2.5 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2 text-xs text-slate-400">
          <span
            className="pulse-dot size-2 shrink-0 rounded-full bg-emerald-400 text-emerald-400"
            aria-hidden
          />
          <p className="leading-relaxed">{t("kpi.historyBuilding")}</p>
        </div>
      )}
    </section>
  );
}
