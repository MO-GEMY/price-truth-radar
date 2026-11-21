/**
 * Locale-aware formatting helpers (prices in EGP, percentages, dates).
 * Uses Latin digits even in Arabic (ar-EG-u-nu-latn) for readability of
 * financial figures.
 */

import type { Lang } from "./i18n";

export function formatPrice(
  value: number | null | undefined,
  lang: Lang,
  opts?: { maximumFractionDigits?: number },
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const formatter = new Intl.NumberFormat(
    lang === "ar" ? "ar-EG-u-nu-latn" : "en-EG",
    {
      style: "currency",
      currency: "EGP",
      maximumFractionDigits: opts?.maximumFractionDigits ?? 2,
      minimumFractionDigits: 0,
    },
  );
  return formatter.format(value);
}

export function formatNumber(value: number, lang: Lang): string {
  return new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US").format(value);
}

/** Signed percentage, e.g. "+12.4%" / "-2.8%". */
export function formatPct(value: number, lang: Lang, digits = 1): string {
  const formatter = new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
    signDisplay: "exceptZero",
  });
  return `${formatter.format(value)}%`;
}

export function formatPctPlain(value: number, lang: Lang, digits = 1): string {
  const formatter = new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
  return `${formatter.format(value)}%`;
}

export function formatDate(iso: string, lang: Lang): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn-ca-gregory" : "en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function formatDateTime(iso: string, lang: Lang): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn-ca-gregory" : "en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** "2026-10-01" → "01 Oct" style axis ticks. */
export function formatChartTick(iso: string, lang: Lang): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn-ca-gregory" : "en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}
