"use client";

import {
  BadgeCheck,
  Flame,
  Percent,
  Radar,
  ShieldAlert,
  TrendingDown,
  type LucideIcon,
} from "lucide-react";
import type { StatsOverview } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { formatDateTime, formatNumber, formatPctPlain } from "@/lib/format";

interface KpiTile {
  key: string;
  icon: LucideIcon;
  value: string;
  accent: string;
}

export function KpiBar({ stats }: { stats: StatsOverview }) {
  const { lang, t } = useLanguage();

  const tiles: KpiTile[] = [
    {
      key: "kpi.totalTracked",
      icon: Radar,
      value: formatNumber(stats.total_tracked, lang),
      accent: "text-cyan-300 bg-cyan-400/12 border-cyan-400/25",
    },
    {
      key: "kpi.fakeDiscounts",
      icon: ShieldAlert,
      value: formatNumber(stats.fake_discounts_today, lang),
      accent: "text-rose-300 bg-rose-500/12 border-rose-500/25",
    },
    {
      key: "kpi.genuineDeals",
      icon: BadgeCheck,
      value: formatNumber(stats.genuine_deals_today, lang),
      accent: "text-teal-300 bg-teal-500/12 border-teal-500/25",
    },
    {
      key: "kpi.allTimeLows",
      icon: TrendingDown,
      value: formatNumber(stats.all_time_lows_today, lang),
      accent: "text-emerald-300 bg-emerald-500/12 border-emerald-500/25",
    },
    {
      key: "kpi.presaleHikes",
      icon: Flame,
      value: formatNumber(stats.presale_hikes_today, lang),
      accent: "text-amber-300 bg-amber-500/12 border-amber-500/25",
    },
    {
      key: "kpi.avgFakeInflation",
      icon: Percent,
      value: formatPctPlain(stats.avg_fake_inflation_pct, lang),
      accent: "text-violet-300 bg-violet-500/12 border-violet-500/25",
    },
  ];

  return (
    <section aria-label={t("kpi.title")} className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {tiles.map((tile) => {
          const Icon = tile.icon;
          return (
            <div
              key={tile.key}
              className="glass rounded-2xl p-4 transition-colors hover:border-white/20"
            >
              <span
                className={`inline-flex size-8 items-center justify-center rounded-lg border ${tile.accent}`}
              >
                <Icon className="size-4" strokeWidth={2.2} />
              </span>
              <p className="num mt-3 text-2xl font-bold tracking-tight text-white">
                {tile.value}
              </p>
              <p className="mt-1 text-xs leading-snug text-slate-400">{t(tile.key as never)}</p>
            </div>
          );
        })}
      </div>
      <p className="text-[11px] text-slate-500">
        {t("kpi.lastPipelineRun")}: {formatDateTime(stats.last_pipeline_run_at, lang)}
      </p>
    </section>
  );
}
