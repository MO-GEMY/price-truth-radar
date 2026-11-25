"use client";

import { useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HistoryMaturity, PriceHistoryPoint } from "@/types/contract";
import { formatChartTick, formatDate, formatNumber, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";

const DAY = 86_400_000;
const rangeLabels = {
  0: "ui.historyAll",
  14: "ui.history14",
  60: "ui.history60",
} as const;

function dayLabel(value: number, lang: "en" | "ar"): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? formatChartTick(date.toISOString().slice(0, 10), lang)
    : "";
}

export function PriceChart({
  history,
  trackedDaysCount,
  historyMaturity,
}: {
  history: PriceHistoryPoint[];
  trackedDaysCount?: number;
  historyMaturity?: HistoryMaturity;
}) {
  const { lang, t } = useLanguage();
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const [range, setRange] = useState<keyof typeof rangeLabels>(0);

  const effectiveDays =
    typeof trackedDaysCount === "number" && trackedDaysCount >= 1
      ? Math.floor(trackedDaysCount)
      : Math.max(1, history.length);
  const effectiveMaturity: HistoryMaturity =
    historyMaturity ??
    (effectiveDays < 7 ? "EARLY" : effectiveDays < 60 ? "GROWING" : "MATURE");
  const showVerifiedMedian = effectiveMaturity !== "EARLY" && effectiveDays >= 7;
  const medianLegendLabel =
    effectiveDays >= 60
      ? t("maturity.chartMedian60")
      : t("maturity.chartMedianDays", {
          days: formatNumber(effectiveDays, lang),
        });

  const series: ReadonlyArray<{
    key: "price" | "claimed" | "median";
    label: string;
    color: string;
    dash?: string;
  }> = [
    { key: "price", label: t("detail.current"), color: "#0CAE79" },
    {
      key: "claimed",
      label: t("chart.claimedOriginal"),
      color: isDark ? "#F87171" : "#DC2626",
      dash: "6 4",
    },
    ...(showVerifiedMedian
      ? [
          {
            key: "median" as const,
            label: medianLegendLabel,
            color: isDark ? "#94A3B8" : "#64748B",
            dash: "2 4",
          },
        ]
      : []),
  ];

  const data = history
    .map((point) => {
      const verifiedMed =
        showVerifiedMedian
          ? (point.verified_historical_median ??
            (point.rolling_60d_median > 0 ? point.rolling_60d_median : null))
          : null;
      return {
        time: Date.parse(point.snapshot_date),
        date: point.snapshot_date,
        price: point.price,
        claimed: point.claimed_original_price,
        median: verifiedMed && verifiedMed > 0 ? verifiedMed : null,
      };
    })
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.price))
    .sort((a, b) => a.time - b.time);

  if (!data.length)
    return <p className="ptr-muted text-sm">{t("ui.noHistory")}</p>;
  if (data.length === 1) {
    const [point] = data;
    return (
      <div className="ptr-notice ptr-baseline">
        <p className="font-semibold">
          {t("detail.baselineTitle", { date: formatDate(point.date, lang) })}
        </p>
        <p>
          {t("detail.baselineRecordedPrice")} ·{" "}
          <bdi className="ptr-mono">{formatPrice(point.price, lang)}</bdi>
        </p>
        {point.claimed !== null && (
          <p>
            {t("detail.baselineClaimedPrice")} ·{" "}
            <bdi className="ptr-mono">{formatPrice(point.claimed, lang)}</bdi>
          </p>
        )}
        <p className="ptr-muted">{t("detail.baselineBody")}</p>
      </div>
    );
  }

  const newest = data[data.length - 1].time;
  const ranges = ([0, 14, 60] as const).filter(
    (days) => days === 0 || newest - data[0].time >= days * DAY,
  );
  const days = ranges.includes(range) ? range : 0;
  const visible = days
    ? data.filter((point) => point.time >= newest - (days - 1) * DAY)
    : data;
  const active = series.filter((entry) =>
    visible.some((point) => point[entry.key] !== null),
  );
  const values = visible.flatMap((point) =>
    active
      .map((entry) => point[entry.key])
      .filter((value): value is number => value !== null),
  );
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const pad = Math.max((maximum - minimum) * 0.08, minimum * 0.02, 1);

  const gridColor = isDark ? "#1E3557" : "#E2E8F0";
  const tickColor = isDark ? "#94A3B8" : "#475569";
  const tooltipBg = isDark ? "#11223D" : "#FFFFFF";
  const tooltipBorder = isDark ? "#2B4873" : "#CBD5E1";
  const tooltipText = isDark ? "#FFFFFF" : "#0B192E";

  return (
    <div className="min-w-0 max-w-full space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="ptr-controls ptr-muted text-xs">
          {active.map((entry) => (
            <span key={entry.key} className="inline-flex items-center gap-2">
              <span
                className="w-5 border-t-2"
                style={{
                  borderColor: entry.color,
                  borderTopStyle: "dash" in entry ? "dashed" : "solid",
                }}
                aria-hidden="true"
              />
              {entry.label}
            </span>
          ))}
        </div>

        {ranges.length > 1 && (
          <div
            className="asarak-segmented"
            role="group"
            aria-label={t("ui.historyRange")}
          >
            {ranges.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={days === option}
                onClick={() => setRange(option)}
              >
                {t(rangeLabels[option])}
              </button>
            ))}
          </div>
        )}
      </div>

      {visible.length > 1 && (
        <figure
          className="min-w-0 max-w-full"
          aria-label={t("detail.history")}
        >
          <div dir="ltr" className="ptr-chart">
            <ResponsiveContainer width="100%" height={270} minWidth={0}>
              <ComposedChart
                data={visible}
                margin={{ top: 10, right: 12, bottom: 5, left: 4 }}
                accessibilityLayer
              >
                <defs>
                  <linearGradient
                    id="asarakPriceFill"
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop offset="0%" stopColor="#0CAE79" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="#0CAE79" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={gridColor} strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="time"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  scale="time"
                  tickFormatter={(value) => dayLabel(Number(value), lang)}
                  tick={{ fill: tickColor, fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: gridColor }}
                  minTickGap={35}
                />
                <YAxis
                  domain={[Math.max(0, minimum - pad), maximum + pad]}
                  width={lang === "ar" ? 60 : 48}
                  tick={{ fill: tickColor, fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(value) =>
                    new Intl.NumberFormat(
                      lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB",
                      {
                        notation: "compact",
                        maximumFractionDigits: 1,
                      },
                    ).format(Number(value))
                  }
                />
                <Tooltip
                  wrapperStyle={{
                    maxWidth: "calc(100vw - 48px)",
                    whiteSpace: "normal",
                    zIndex: 10,
                  }}
                  contentStyle={{
                    backgroundColor: tooltipBg,
                    border: `1px solid ${tooltipBorder}`,
                    borderRadius: 10,
                    color: tooltipText,
                    boxShadow: "0 8px 24px rgba(11, 25, 46, 0.16)",
                  }}
                  labelStyle={{ color: tickColor, fontWeight: 600 }}
                  labelFormatter={(value) => dayLabel(Number(value), lang)}
                  formatter={(value) => formatPrice(Number(value), lang)}
                />
                <Area
                  type="monotone"
                  dataKey="price"
                  stroke="none"
                  fill="url(#asarakPriceFill)"
                  tooltipType="none"
                  isAnimationActive={false}
                />
                {active.map((entry) => (
                  <Line
                    key={entry.key}
                    type="linear"
                    dataKey={entry.key}
                    name={entry.label}
                    stroke={entry.color}
                    strokeDasharray={"dash" in entry ? entry.dash : undefined}
                    strokeWidth={entry.key === "price" ? 2.6 : 1.7}
                    connectNulls={false}
                    dot={visible.length <= 4}
                    isAnimationActive={false}
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </figure>
      )}

      <details
        open={visible.length === 1 || undefined}
        className="min-w-0 max-w-full"
      >
        <summary className="ptr-link">{t("ui.recordedPrices")}</summary>
        <div className="ptr-table-scroll">
          <table className="ptr-history-table">
            <thead>
              <tr>
                <th scope="col">{t("ui.date")}</th>
                {active.map((entry) => (
                  <th scope="col" key={entry.key}>
                    {entry.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((point, index) => (
                <tr key={`${point.date}-${index}`}>
                  <th scope="row">{formatDate(point.date, lang)}</th>
                  {active.map((entry) => (
                    <td key={entry.key}>
                      <bdi>{formatPrice(point[entry.key], lang)}</bdi>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
