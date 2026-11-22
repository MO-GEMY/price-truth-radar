"use client";

/**
 * "فضائح الخصومات vs أفضل خصم حقيقي" — the viral launch page.
 *
 * Two tabs backed by `/api/radar/highlights` (with a graceful fallback to the
 * live radar feed + empty states when neither is reachable), category pills,
 * and one-click Web Share / clipboard cards tuned for WhatsApp & Facebook.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Check,
  Flame,
  Info,
  Share2,
  TrendingDown,
} from "lucide-react";
import type { Category, HighlightItem, RadarHighlights } from "@/types/contract";
import { fetchRadarHighlights, type DataSource } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { absoluteUrl } from "@/lib/site";
import {
  formatPctPlain,
  formatPrice,
  formatSubCategory,
} from "@/lib/format";
import { storeAccent, storeDisplayName } from "@/lib/stores";
import { MockBanner } from "@/components/MockBanner";
import { ErrorState } from "@/components/states";

type DealTab = "scandals" | "deals";

const CATEGORIES: ("all" | Category)[] = [
  "all",
  "electronics",
  "home_appliances",
  "groceries",
  "fashion",
];

function asNumber(value: unknown, fallback = 0): number {
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : fallback;
}

function asText(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function DealCard({
  item,
  kind,
  copied,
  onShare,
}: {
  item: HighlightItem;
  kind: DealTab;
  copied: boolean;
  onShare: () => void;
}) {
  const { lang, t } = useLanguage();

  const title = asText(item.product_title, "");
  const store = asText(item.store_name, "");
  const price = asNumber(item.current_price);
  const claimed = asNumber(item.claimed_original_price, NaN);
  const claimedPct = asNumber(item.claimed_discount_pct);
  const realPct = asNumber(item.real_discount_pct);
  const isScandal = kind === "scandals";
  const detailHref = item.product_sk ? `/products/${item.product_sk}` : null;
  const imageUrl = typeof item.image_url === "string" && item.image_url ? item.image_url : null;
  const badgePct = isScandal
    ? claimedPct || Math.round(((claimed - price) / claimed) * 100)
    : realPct;

  return (
    <article
      className={`surface surface-hover relative flex min-w-0 flex-col gap-3 overflow-hidden rounded-2xl p-4 sm:flex-row sm:items-stretch sm:gap-4 sm:p-5 ${
        isScandal ? "border-s-4 border-s-rose-400/70" : "border-s-4 border-s-emerald-400/70"
      }`}
    >
      {/* Thumbnail */}
      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imageUrl}
          alt={title}
          loading="lazy"
          referrerPolicy="no-referrer"
          className="studio-frame h-28 w-full shrink-0 rounded-xl object-contain p-2 sm:h-24 sm:w-24"
        />
      ) : null}

      {/* Body */}
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5 text-[11px] font-semibold text-slate-200">
              <span
                className="size-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: storeAccent(asText(store, "")) }}
                aria-hidden
              />
              {storeDisplayName(asText(store, ""), lang)}
            </span>
            {item.sub_category ? (
              <span className="rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[10px] font-medium text-slate-400">
                {formatSubCategory(asText(item.sub_category, ""), lang)}
              </span>
            ) : null}
          </div>
          <span
            className={`num inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-extrabold ${
              isScandal
                ? "border border-rose-400/45 bg-rose-500/15 text-rose-300"
                : "border border-emerald-400/45 bg-emerald-500/15 text-emerald-300"
            }`}
          >
            {isScandal ? <Flame className="size-3.5 shrink-0" /> : <TrendingDown className="size-3.5 shrink-0" />}
            {isScandal ? t("deals.scandalBadge") : t("deals.dealBadge")}
            {badgePct ? (
              <span className="opacity-90">{formatPctPlain(badgePct, lang, 0)}</span>
            ) : null}
          </span>
        </div>

        <h3 className="line-clamp-2 text-sm font-bold leading-snug text-slate-100">{title}</h3>

        {/* Price truth row: claimed strikethrough vs real */}
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <span className="num text-xl font-extrabold tracking-tight text-white">
            {formatPrice(price, lang)}
          </span>
          {isScandal && Number.isFinite(claimed) && claimed > price ? (
            <span className="num text-sm font-medium text-slate-500 line-through">
              {formatPrice(claimed, lang)}
            </span>
          ) : null}
          <span
            className={`num text-[11px] font-semibold ${
              isScandal ? "text-rose-300/90" : "text-emerald-300/90"
            }`}
          >
            {isScandal
              ? `${t("deals.baselinePrice")}: ${formatPrice(price, lang)}`
              : `${t("card.real")}: ${formatPctPlain(realPct, lang)}`}
          </span>
        </div>

        {/* Actions: share + inspect */}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
          <button
            type="button"
            onClick={onShare}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-bold transition ${
              copied
                ? "border border-emerald-400/45 bg-emerald-500/15 text-emerald-200"
                : isScandal
                  ? "border border-rose-400/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
                  : "border border-emerald-400/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
            }`}
          >
            {copied ? <Check className="size-3.5 shrink-0" /> : <Share2 className="size-3.5 shrink-0" />}
            {copied
              ? t("deals.copied")
              : isScandal
                ? t("deals.shareScandal")
                : t("deals.shareDeal")}
          </button>
          {detailHref ? (
            <Link
              href={detailHref}
              className="inline-flex items-center gap-1 text-xs font-semibold text-teal-300/90 transition hover:text-teal-200"
            >
              {t("deals.viewTruth")}
              <Info className="size-3.5" />
            </Link>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export default function DealsPage() {
  const { lang, t } = useLanguage();
  const [tab, setTab] = useState<DealTab>("scandals");
  const [category, setCategory] = useState<"all" | Category>("all");
  const [data, setData] = useState<RadarHighlights | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string>("");

  const load = useCallback(
    (abort: AbortController) => {
      setLoading(true);
      setError(false);
      fetchRadarHighlights(category, 24, abort.signal)
        .then(({ data: payload, source: src }) => {
          setData(payload);
          setSource(src);
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
    [category],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller);
    return () => controller.abort();
  }, [load]);

  const items = useMemo(() => {
    if (!data) return [];
    const raw = tab === "scandals" ? data.biggest_scandals : data.best_real_deals;
    return raw.filter(
      (item) =>
        category === "all" ||
        !item.category ||
        (item.category as string) === category,
    );
  }, [data, tab, category]);

  async function shareItem(item: HighlightItem, kind: DealTab) {
    const title = asText(item.product_title, "");
    const store = storeDisplayName(asText(item.store_name, ""), lang);
    const price = asNumber(item.current_price);
    const claimed = asNumber(item.claimed_original_price);
    const realPct = asNumber(item.real_discount_pct);
    const claimedPct = asNumber(item.claimed_discount_pct);
    const pct = formatPctPlain(kind === "scandals" ? claimedPct || Math.round(realPct) : realPct, lang, 0);
    const url = item.product_sk ? absoluteUrl(`/products/${item.product_sk}`) : absoluteUrl("/deals");

    const text =
      kind === "scandals"
        ? t("deals.shareScandalText", {
            title,
            store,
            claimed: formatPrice(claimed, lang, { maximumFractionDigits: 0 }),
            real: formatPrice(price, lang, { maximumFractionDigits: 0 }),
            pct,
          })
        : t("deals.shareDealText", {
            title,
            store,
            real: formatPrice(price, lang, { maximumFractionDigits: 0 }),
            pct,
          });

    setCopiedKey("");
    // Web Share API on mobile (WhatsApp/Facebook pick the text + link);
    // clipboard fallback on desktop.
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({ title: t("brand.name"), text, url });
        return;
      } catch (err) {
        if ((err as DOMException)?.name === "AbortError") return;
        /* fall through to clipboard */
      }
    }
    try {
      await navigator.clipboard.writeText(`${text}\n${url}`);
      setCopiedKey(item.product_sk ?? url);
      setTimeout(() => setCopiedKey(""), 2600);
    } catch {
      setCopiedKey("__failed__");
      setTimeout(() => setCopiedKey(""), 2600);
    }
  }

  const tabButton = (value: DealTab, icon: React.ReactNode, labelKey: "deals.tabScandals" | "deals.tabDeals", tone: string) => (
    <button
      type="button"
      onClick={() => setTab(value)}
      aria-pressed={tab === value}
      className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-bold transition ${
        tab === value
          ? tone
          : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
      }`}
    >
      {icon}
      {t(labelKey)}
    </button>
  );

  return (
    <>
      <MockBanner source={source} />

      <div className="mx-auto max-w-5xl space-y-6 px-4 py-8 sm:px-6 sm:py-10">
        <header className="space-y-2.5">
          <div className="flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-rose-400/30 bg-rose-500/12 text-rose-300">
              <Flame className="size-5" />
            </span>
            <h1 className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
              {t("deals.title")}
            </h1>
          </div>
          <p className="max-w-2xl text-sm leading-relaxed text-slate-400">
            {t("deals.subtitle")}
          </p>
          {data?.updated_at ? (
            <p className="num text-[11px] font-medium text-slate-500">
              {t("deals.updated", { time: new Date(data.updated_at).toLocaleString(lang === "ar" ? "ar-EG" : "en-GB") })}
            </p>
          ) : null}
        </header>

        {/* Tabs: Scandals vs Real Deals */}
        <div
          className="surface flex flex-wrap items-center gap-2 rounded-2xl p-2"
          role="tablist"
          aria-label={t("deals.title")}
        >
          {tabButton(
            "scandals",
            <Flame className="size-4 shrink-0 text-rose-400" />,
            "deals.tabScandals",
            "bg-rose-500/18 text-rose-200 ring-1 ring-rose-400/40",
          )}
          {tabButton(
            "deals",
            <TrendingDown className="size-4 shrink-0 text-emerald-400" />,
            "deals.tabDeals",
            "bg-emerald-500/18 text-emerald-200 ring-1 ring-emerald-400/40",
          )}
        </div>

        {/* Category pills */}
        <div className="surface flex flex-wrap items-center gap-1.5 rounded-2xl p-2">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setCategory(cat)}
              aria-pressed={category === cat}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                category === cat
                  ? "bg-teal-400/15 text-teal-200 ring-1 ring-teal-400/35"
                  : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
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

        {/* Cards */}
        {error && !data ? (
          <ErrorState onRetry={() => {
            const controller = new AbortController();
            load(controller);
          }} />
        ) : loading && !data ? (
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-32 rounded-2xl" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="surface flex flex-col items-center gap-3 rounded-2xl px-6 py-14 text-center">
            <span className="flex size-12 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-slate-400">
              <Flame className="size-6" />
            </span>
            <p className="text-sm font-bold text-slate-200">{t("deals.empty")}</p>
            <p className="text-xs text-slate-500">
              {error ? t("deals.errorHint") : t("deals.emptyHint")}
            </p>
          </div>
        ) : (
          <div
            className={`space-y-3 transition-opacity ${loading ? "opacity-55" : ""}`}
          >
            {items.map((item, i) => (
              <DealCard
                key={`${item.product_sk ?? "item"}-${i}`}
                item={item}
                kind={tab}
                copied={copiedKey === (item.product_sk ?? String(i))}
                onShare={() => void shareItem(item, tab)}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
