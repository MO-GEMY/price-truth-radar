"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PriceHistoryPoint } from "@/types/contract";
import { formatChartTick, formatDate, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";

const DAY = 86_400_000;
const rangeLabels = { 0: "ui.historyAll", 14: "ui.history14", 60: "ui.history60" } as const;
const series = [
  { key: "price", label: "detail.current", color: "#005e53" },
  { key: "claimed", label: "chart.claimedOriginal", color: "#943b25", dash: "6 4" },
  { key: "median", label: "chart.median", color: "#775015", dash: "2 4" },
] as const;

function dayLabel(value: number, lang: "en" | "ar"): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? formatChartTick(date.toISOString().slice(0, 10), lang) : "";
}

export function PriceChart({ history }: { history: PriceHistoryPoint[] }) {
  const { lang, t } = useLanguage();
  const [range, setRange] = useState<keyof typeof rangeLabels>(0);
  const data = history.map((point) => ({
    time: Date.parse(point.snapshot_date),
    date: point.snapshot_date,
    price: point.price,
    claimed: point.claimed_original_price,
    median: point.rolling_60d_median > 0 ? point.rolling_60d_median : null,
  })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.price))
    .sort((a, b) => a.time - b.time);

  if (!data.length) return <p className="ptr-muted text-sm">{t("ui.noHistory")}</p>;
  if (data.length === 1) {
    const [point] = data;
    return <div className="ptr-notice ptr-baseline">
      <p className="font-semibold">{t("detail.baselineTitle", { date: formatDate(point.date, lang) })}</p>
      <p>{t("detail.baselineRecordedPrice")} · <bdi>{formatPrice(point.price, lang)}</bdi></p>
      {point.claimed !== null && <p>{t("detail.baselineClaimedPrice")} · <bdi>{formatPrice(point.claimed, lang)}</bdi></p>}
      <p className="ptr-muted">{t("detail.baselineBody")}</p>
    </div>;
  }

  const newest = data[data.length - 1].time;
  const ranges = ([0, 14, 60] as const).filter((days) => days === 0 || newest - data[0].time >= days * DAY);
  const days = ranges.includes(range) ? range : 0;
  const visible = days ? data.filter((point) => point.time >= newest - (days - 1) * DAY) : data;
  const active = series.filter((entry) => visible.some((point) => point[entry.key] !== null));
  const values = visible.flatMap((point) => active.map((entry) => point[entry.key]).filter((value) => value !== null));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const pad = Math.max((maximum - minimum) * 0.08, minimum * 0.02, 1);

  return (
    <div className="space-y-4">
      {ranges.length > 1 && <label className="ptr-control-label inline-grid">{t("ui.historyRange")}
        <select className="ptr-field" value={days} onChange={(event) => {
          setRange(ranges.find((option) => option === Number(event.target.value)) ?? 0);
        }}>
          {ranges.map((option) => <option value={option} key={option}>{t(rangeLabels[option])}</option>)}
        </select>
      </label>}
      {visible.length > 1 && <figure aria-label={t("detail.history")}>
        <figcaption className="ptr-controls ptr-muted text-xs mb-3">
          {active.map((entry) => <span key={entry.key} className="inline-flex items-center gap-2">
            <span className="w-5 border-t-2" style={{ borderColor: entry.color, borderTopStyle: "dash" in entry ? "dashed" : "solid" }} aria-hidden="true" />
            {t(entry.label)}
          </span>)}
        </figcaption>
        <div dir="ltr" className="ptr-chart">
          <ResponsiveContainer width="100%" height={260} minWidth={0}>
            <LineChart data={visible} margin={{ top: 10, right: 14, bottom: 5, left: 4 }} accessibilityLayer>
              <CartesianGrid stroke="#dcded4" vertical={false} />
              <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} scale="time"
                tickFormatter={(value) => dayLabel(Number(value), lang)} tick={{ fill: "#52605a", fontSize: 11 }}
                tickLine={false} minTickGap={35} />
              <YAxis domain={[Math.max(0, minimum - pad), maximum + pad]} width={50}
                tick={{ fill: "#52605a", fontSize: 11 }} tickLine={false} axisLine={false}
                tickFormatter={(value) => new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB", {
                  notation: "compact", maximumFractionDigits: 1,
                }).format(Number(value))} />
              <Tooltip contentStyle={{ backgroundColor: "#fff", border: "1px solid #dcded4", borderRadius: 8 }}
                labelFormatter={(value) => dayLabel(Number(value), lang)}
                formatter={(value) => formatPrice(Number(value), lang)} />
              {active.map((entry) => <Line key={entry.key} type="linear" dataKey={entry.key} name={t(entry.label)}
                stroke={entry.color} strokeDasharray={"dash" in entry ? entry.dash : undefined}
                strokeWidth={entry.key === "price" ? 2.5 : 1.6} connectNulls={false}
                dot={visible.length <= 4} isAnimationActive={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </figure>}
      <details open={visible.length === 1 || undefined}>
        <summary className="ptr-link">{t("ui.recordedPrices")}</summary>
        <table className="ptr-history-table">
          <thead><tr><th scope="col">{t("ui.date")}</th>
            {active.map((entry) => <th scope="col" key={entry.key}>{t(entry.label)}</th>)}</tr></thead>
          <tbody>{visible.map((point, index) => <tr key={`${point.date}-${index}`}>
            <th scope="row">{formatDate(point.date, lang)}</th>
            {active.map((entry) => <td key={entry.key}><bdi>{formatPrice(point[entry.key], lang)}</bdi></td>)}
          </tr>)}</tbody>
        </table>
      </details>
    </div>
  );
}
