"use client";

import { useEffect, useState } from "react";
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
import { formatChartTick, formatPrice } from "@/lib/format";

interface ChartDatum {
  date: string;
  price: number;
  claimed: number | null;
  median: number;
}

const COLOR_PRICE = "#22d3ee";
const COLOR_CLAIMED = "#f59e0b";
const COLOR_MEDIAN = "#a78bfa";

function compactNumber(value: number, lang: "en" | "ar"): string {
  return new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/**
 * Interactive price-history time series (CONTRACTS.md §3.2 / §5.5):
 *  - `price`                → solid cyan line
 *  - `claimed_original_price` → dashed amber line
 *  - `rolling_60d_median`   → dotted violet reference line
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

  const isSinglePoint = data.length === 1;
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
    { color: COLOR_PRICE, label: t("detail.current") },
    { color: COLOR_CLAIMED, label: t("chart.claimedOriginal") },
    { color: COLOR_MEDIAN, label: t("chart.median") },
  ];

  if (data.length === 0) return null;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-x-5 gap-y-2">
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {legend.map((item) => (
            <span key={item.label} className="flex items-center gap-2 text-xs font-medium text-slate-300">
              <span
                className="inline-block h-0.5 w-6 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              {item.label}
            </span>
          ))}
        </div>
        {isSinglePoint ? (
          <span className="rounded-full border border-cyan-400/25 bg-cyan-400/10 px-3 py-1 text-[11px] font-medium text-cyan-200">
            {t("chart.singlePointHint", { date: formatChartTick(data[0].date, lang) })}
          </span>
        ) : null}
      </div>

      {mounted ? (
        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="rgba(148,163,184,0.12)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={(value) => formatChartTick(String(value), lang)}
              tick={{ fill: "#64748b", fontSize: 11 }}
              axisLine={{ stroke: "rgba(148,163,184,0.2)" }}
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
              cursor={{ stroke: "rgba(148,163,184,0.3)", strokeDasharray: "4 4" }}
              contentStyle={{
                backgroundColor: "rgba(7,12,24,0.96)",
                border: "1px solid rgba(148,163,184,0.25)",
                borderRadius: 12,
                fontSize: 12,
                boxShadow: "0 12px 40px rgba(2,8,20,0.6)",
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
              dot={isSinglePoint ? { r: 6, fill: COLOR_PRICE, stroke: "#05080f", strokeWidth: 2 } : false}
              activeDot={{ r: 5, strokeWidth: 0 }}
            />
            <Line
              type="monotone"
              dataKey="claimed"
              name="claimed"
              stroke={COLOR_CLAIMED}
              strokeWidth={1.8}
              strokeDasharray="7 5"
              dot={isSinglePoint ? { r: 5, fill: COLOR_CLAIMED, stroke: "#05080f", strokeWidth: 2 } : false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="median"
              name="median"
              stroke={COLOR_MEDIAN}
              strokeWidth={2}
              strokeDasharray="2 5"
              dot={isSinglePoint ? { r: 4, fill: COLOR_MEDIAN, stroke: "#05080f", strokeWidth: 1.5 } : false}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="skeleton h-[360px] w-full" />
      )}
    </div>
  );
}
