"use client";

import { useEffect, useState } from "react";
import { CalendarClock, CheckCircle2 } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PriceHistoryPoint } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { formatChartTick, formatDate, formatPrice } from "@/lib/format";

interface ChartDatum {
  date: string;
  price: number;
  claimed: number | null;
  median: number;
}

const COLOR_PRICE = "#2dd4bf";
const COLOR_CLAIMED = "#fbbf24";
const COLOR_MEDIAN = "#94a3b8";

function compactNumber(value: number, lang: "en" | "ar"): string {
  return new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/**
 * Interactive price-history time series (CONTRACTS.md §3.2 / §5.5).
 * When only a Day-1 baseline snapshot exists, renders a clean, trustworthy
 * baseline card instead of a sparse single-dot chart.
 */
export function PriceChart({ history }: { history: PriceHistoryPoint[] }) {
  const { lang, t } = useLanguage();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const data: ChartDatum[] = history.map((h) => ({
    date: h.snapshot_date,
    price: h.price,
    claimed: h.claimed_original_price,
    median: h.rolling_60d_median,
  }));

  if (data.length === 0) return null;

  /* -------- Polished Day-1 Baseline state -------- */
  if (data.length === 1) {
    const point = data[0];
    return (
      <div className="rounded-xl border border-teal-400/20 bg-gradient-to-br from-teal-500/[0.06] via-[#060b14] to-[#050810] p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-emerald-400/35 bg-emerald-500/12 px-3 py-1 text-xs font-bold text-emerald-300">
            <CheckCircle2 className="size-3.5 shrink-0" />
            {t("detail.baselineBadge")}
          </span>
          <span className="num text-xs font-semibold text-slate-400">
            {t("detail.baselineTitle", { date: formatDate(point.date, lang) })}
          </span>
        </div>

        <p className="mt-3 max-w-2xl text-xs leading-relaxed text-slate-300 sm:text-sm">
          {t("detail.baselineBody")}
        </p>

        {/* Visual baseline timeline */}
        <div className="mt-5 flex items-center gap-3" aria-hidden>
          <span className="pulse-dot size-2.5 shrink-0 rounded-full bg-teal-400 text-teal-400" />
          <div className="h-0.5 flex-1 rounded-full bg-gradient-to-r from-teal-400/70 via-slate-600/40 to-transparent rtl:bg-gradient-to-l" />
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {t("detail.baselineRecordedPrice")}
            </p>
            <p className="num mt-1 text-lg font-extrabold text-teal-300">
              {formatPrice(point.price, lang)}
            </p>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {t("detail.baselineClaimedPrice")}
            </p>
            <p className="num mt-1 text-lg font-bold text-slate-200">
              {point.claimed !== null ? formatPrice(point.claimed, lang) : "—"}
            </p>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3.5">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <CalendarClock className="size-3.5 text-slate-400" />
              {t("detail.baselineNextSnapshot")}
            </p>
            <p className="mt-1 text-sm font-semibold text-slate-200">
              {t("detail.baselineDaily")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  /* -------- Multi-day interactive time series -------- */
  const prices = data.map((d) => d.price);
  const claimedValues = data
    .map((d) => d.claimed)
    .filter((c): c is number => c !== null);
  const min = Math.min(...prices, ...data.map((d) => d.median));
  const max = Math.max(...prices, ...data.map((d) => d.median), ...claimedValues);
  const span = max - min;
  const pad = Math.max(span * 0.1, span === 0 ? min * 0.05 : 0, 50);
  const yMin = Math.max(0, Math.floor(min - pad));
  const yMax = Math.ceil(max + pad);

  const legend = [
    { color: COLOR_PRICE, label: t("detail.current"), dashed: false },
    { color: COLOR_CLAIMED, label: t("chart.claimedOriginal"), dashed: true },
    { color: COLOR_MEDIAN, label: t("chart.median"), dashed: true },
  ];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2">
        {legend.map((item) => (
          <span key={item.label} className="flex items-center gap-2 text-xs font-medium text-slate-300">
            <span
              className="inline-block h-0.5 w-5 rounded-full"
              style={{
                backgroundColor: item.dashed ? "transparent" : item.color,
                borderTop: item.dashed ? `2px dashed ${item.color}` : undefined,
              }}
            />
            {item.label}
          </span>
        ))}
      </div>

      {mounted ? (
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="rgba(148,163,184,0.1)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={(value) => formatChartTick(String(value), lang)}
              tick={{ fill: "#64748b", fontSize: 11 }}
              axisLine={{ stroke: "rgba(148,163,184,0.18)" }}
              tickLine={false}
              minTickGap={32}
            />
            <YAxis
              tickFormatter={(value) => compactNumber(Number(value), lang)}
              tick={{ fill: "#64748b", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={56}
              domain={[yMin, yMax]}
            />
            <Tooltip
              cursor={{ stroke: "rgba(148,163,184,0.28)", strokeDasharray: "4 4" }}
              contentStyle={{
                backgroundColor: "rgba(6,10,18,0.96)",
                border: "1px solid rgba(148,163,184,0.22)",
                borderRadius: 12,
                fontSize: 12,
                boxShadow: "0 16px 48px rgba(0,0,0,0.7)",
              }}
              labelStyle={{ color: "#e2e8f0", fontWeight: 700, marginBottom: 6 }}
              itemStyle={{ padding: 0 }}
              labelFormatter={(label) => formatChartTick(String(label), lang)}
              formatter={(value, name) => [
                formatPrice(Number(value), lang),
                name === "price"
                  ? t("detail.current")
                  : name === "claimed"
                    ? t("chart.claimedOriginal")
                    : t("chart.median"),
              ]}
            />
            <Line
              type="monotone"
              dataKey="price"
              name="price"
              stroke={COLOR_PRICE}
              strokeWidth={2.4}
              dot={false}
              activeDot={{ r: 5, strokeWidth: 0 }}
            />
            <Line
              type="monotone"
              dataKey="claimed"
              name="claimed"
              stroke={COLOR_CLAIMED}
              strokeWidth={1.8}
              strokeDasharray="6 4"
              dot={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="median"
              name="median"
              stroke={COLOR_MEDIAN}
              strokeWidth={1.8}
              strokeDasharray="2 4"
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="skeleton h-[340px] w-full" />
      )}
    </div>
  );
}
