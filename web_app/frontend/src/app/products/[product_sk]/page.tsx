"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  ArrowLeftRight,
  ArrowRight,
  CalendarClock,
  ExternalLink,
  Flame,
  Info,
  PackageX,
} from "lucide-react";
import type { ProductDetailResponse } from "@/types/contract";
import { ApiError, fetchProductDetail, type DataSource } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";
import {
  formatDateTime,
  formatNumber,
  formatPackSize,
  formatPct,
  formatPctPlain,
  formatPrice,
  formatSubCategory,
  formatUnitPrice,
} from "@/lib/format";
import { storeDisplayName } from "@/lib/stores";
import { VERDICT_TONES } from "@/lib/verdicts";
import { MockBanner } from "@/components/MockBanner";
import { PriceChart } from "@/components/PriceChart";
import { AttributesPanel } from "@/components/AttributesPanel";
import { AlternativesTable } from "@/components/AlternativesTable";
import { ProductImage } from "@/components/ProductImage";
import { VerdictBadge } from "@/components/VerdictBadge";
import { StoreBadge } from "@/components/StoreBadge";
import { DetailSkeleton, ErrorState } from "@/components/states";

type Status = "loading" | "ready" | "notfound" | "error";

function MetricCell({
  label,
  value,
  accent = "text-white",
  ltrValue = false,
}: {
  label: string;
  value: string;
  accent?: string;
  ltrValue?: boolean;
}) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3.5">
      <p className="truncate text-[11px] font-medium text-slate-500" title={label}>
        {label}
      </p>
      <p
        dir={ltrValue ? "ltr" : undefined}
        className={`num mt-1 truncate text-sm font-bold tracking-tight sm:text-base ${
          ltrValue ? "text-start" : ""
        } ${accent}`}
        title={value}
      >
        {value}
      </p>
    </div>
  );
}

export default function ProductDetailPage() {
  const params = useParams<{ product_sk: string }>();
  const productSk = params.product_sk;

  const { lang, t } = useLanguage();
  const [status, setStatus] = useState<Status>("loading");
  const [detail, setDetail] = useState<ProductDetailResponse | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const loadDetail = useCallback(() => {
    const controller = new AbortController();
    setStatus("loading");
    fetchProductDetail(productSk, controller.signal)
      .then(({ data, source }) => {
        setDetail(data);
        setSource(source);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setStatus("notfound");
        } else {
          console.error(err);
          setStatus("error");
        }
      });
    return () => controller.abort();
  }, [productSk]);

  useEffect(() => loadDetail(), [loadDetail, reloadKey]);

  if (status === "loading") {
    return (
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
        <DetailSkeleton />
      </div>
    );
  }

  if (status === "notfound") {
    return (
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="surface mx-auto flex max-w-md flex-col items-center gap-3 rounded-2xl px-6 py-12 text-center">
          <span className="flex size-12 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-slate-300">
            <Info className="size-6" />
          </span>
          <h1 className="text-lg font-bold text-white">{t("detail.notFound")}</h1>
          <p className="text-sm text-slate-400">{t("detail.notFoundBody")}</p>
          <Link
            href="/"
            className="mt-2 inline-flex items-center gap-2 rounded-full border border-teal-400/35 bg-teal-400/10 px-4 py-2 text-sm font-semibold text-teal-200 hover:bg-teal-400/20"
          >
            <ArrowLeft className="size-4 rtl:rotate-180" />
            {t("detail.back")}
          </Link>
        </div>
      </div>
    );
  }

  if (status === "error" || !detail) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <ErrorState onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    );
  }

  const { product, history, alternatives } = detail;
  const tone = VERDICT_TONES[product.discount_verdict];
  const VerdictIcon = tone.icon;
  const storeLabel = storeDisplayName(product.store_name, lang);
  const gap = product.claimed_discount_pct - Math.max(product.real_discount_pct, 0);
  const showInflation =
    product.claimed_discount_pct >= 10 && product.real_discount_pct < 3 && gap >= 10;

  const realAccent =
    product.real_discount_pct >= 5
      ? "text-emerald-300"
      : product.real_discount_pct < 0
        ? "text-rose-300"
        : "text-white";

  const totalMatchedStores = alternatives.length + 1;
  const packSize = formatPackSize(product.attributes_json);
  const unitPrice = formatUnitPrice(product, lang);

  return (
    <>
      <MockBanner source={source} />

      <div className="mx-auto max-w-6xl space-y-6 px-4 py-7 sm:px-6 sm:py-9">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-xs font-semibold text-slate-400 transition hover:text-teal-300 sm:text-sm"
        >
          <ArrowLeft className="size-4 rtl:rotate-180" />
          {t("detail.back")}
        </Link>

        {/* ============================================================ */}
        {/* SECTION 1: Verdict & Buy Decision Hero                       */}
        {/* ============================================================ */}
        <section className="surface space-y-6 rounded-2xl p-5 sm:p-7">
          <div className="flex flex-col gap-6 md:flex-row md:items-start">
            {/* Category-aware product image */}
            <ProductImage
              src={product.image_url}
              alt={product.product_title}
              category={product.category}
              subCategory={product.sub_category}
              brand={product.brand}
              fit={product.category === "fashion" ? "cover" : "contain"}
              objectPosition={product.category === "fashion" ? "top" : "center"}
              studio={product.category !== "fashion"}
              dimmed={!product.in_stock}
              priority
              className="aspect-square w-full max-w-[260px] shrink-0 self-center rounded-2xl md:w-60 md:self-start"
            />

            <div className="min-w-0 flex-1 space-y-4">
              {/* Store & category metadata */}
              <div className="flex flex-wrap items-center gap-2">
                <StoreBadge name={product.store_name} />
                <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs font-medium text-slate-300">
                  {product.brand} · {formatSubCategory(product.sub_category, lang)}
                </span>
                {packSize ? (
                  <span
                    className="num rounded-full border border-teal-400/25 bg-teal-400/10 px-2.5 py-1 text-xs font-semibold text-teal-200"
                    title={t("attr.pack_size")}
                  >
                    {packSize}
                  </span>
                ) : null}
                {product.scarcity_flag ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/35 bg-amber-500/12 px-2.5 py-1 text-xs font-semibold text-amber-300">
                    <Flame className="size-3.5 shrink-0" />
                    {t("card.lowStock")}
                  </span>
                ) : null}
                {!product.in_stock ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-rose-400/35 bg-rose-500/12 px-2.5 py-1 text-xs font-semibold text-rose-300">
                    <PackageX className="size-3.5 shrink-0" />
                    {t("card.outOfStock")}
                  </span>
                ) : null}
              </div>

              <h1 className="text-xl font-extrabold leading-snug tracking-tight text-white sm:text-2xl">
                {product.product_title}
              </h1>

              {/* Color-coded single-sentence Price Truth Verdict Banner */}
              <div className={`flex items-start gap-3 rounded-xl border p-3.5 ${tone.banner}`}>
                <span
                  className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border ${tone.chip}`}
                >
                  <VerdictIcon className="size-4" strokeWidth={2.2} />
                </span>
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <VerdictBadge verdict={product.discount_verdict} size="sm" />
                    {showInflation ? (
                      <span className="num text-xs font-bold text-rose-300">
                        · {t("card.inflation", { pts: formatPctPlain(gap, lang, 0) })}
                      </span>
                    ) : null}
                  </div>
                  <p className="text-xs leading-relaxed text-slate-200 sm:text-sm">
                    {t(`explain.${product.discount_verdict}` as TranslationKey)}
                  </p>
                </div>
              </div>

              {/* Hero EGP pricing */}
              <div className="space-y-1.5 pt-1">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
                  <span className="num text-3xl font-extrabold tracking-tight text-white">
                    {formatPrice(product.current_price, lang)}
                  </span>
                  {product.claimed_original_price !== null ? (
                    <span className="num text-base font-medium text-slate-500 line-through">
                      {formatPrice(product.claimed_original_price, lang)}
                    </span>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-1.5">
                    {product.claimed_discount_pct > 0 ? (
                      <span className="num inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-xs font-semibold text-slate-300">
                        <span>{t("card.claimed")}</span>
                        <span dir="ltr" className="inline-block">
                          −{formatPctPlain(product.claimed_discount_pct, lang)}
                        </span>
                      </span>
                    ) : null}
                    <span
                      className={`num inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-bold ${
                        product.real_discount_pct >= 5
                          ? "border-emerald-400/35 bg-emerald-500/12 text-emerald-300"
                          : product.real_discount_pct >= 0
                            ? "border-slate-500/35 bg-slate-500/10 text-slate-300"
                            : "border-rose-400/35 bg-rose-500/12 text-rose-300"
                      }`}
                    >
                      <span>{t("card.real")}</span>
                      <span dir="ltr" className="inline-block">
                        {formatPct(product.real_discount_pct, lang)}
                      </span>
                    </span>
                  </div>
                </div>
                {unitPrice ? (
                  <p className="num text-xs font-medium text-slate-500">{unitPrice}</p>
                ) : null}
              </div>

              {/* Primary CTAs */}
              <div className="flex flex-wrap items-center gap-2.5 pt-1">
                <a
                  href={product.product_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-emerald-400 px-5 py-2.5 text-sm font-bold text-[#031214] transition hover:brightness-110"
                >
                  <ExternalLink className="size-4 shrink-0" />
                  {t("detail.openAtStore", { store: storeLabel })}
                </a>

                {alternatives.length > 0 ? (
                  <a
                    href="#alternatives"
                    className="inline-flex items-center gap-2 rounded-xl border border-emerald-400/35 bg-emerald-500/10 px-4 py-2.5 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-500/18"
                  >
                    <ArrowLeftRight className="size-4 shrink-0" />
                    {t("detail.compareAcross", {
                      count: formatNumber(totalMatchedStores, lang),
                    })}
                  </a>
                ) : product.canonical_product_key ? (
                  <Link
                    href="/compare"
                    className="inline-flex items-center gap-2 rounded-xl border border-white/12 bg-white/[0.04] px-4 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-teal-400/40 hover:text-white"
                  >
                    <ArrowLeftRight className="size-4 shrink-0" />
                    {t("nav.compare")}
                  </Link>
                ) : null}

                <span className="ms-auto inline-flex items-center gap-1.5 text-xs text-slate-500">
                  <CalendarClock className="size-3.5 shrink-0" />
                  {t("detail.lastUpdated")}:{" "}
                  <span className="num text-slate-400">
                    {formatDateTime(product.last_updated_at, lang)}
                  </span>
                </span>
              </div>
            </div>
          </div>

          {/* Compact price metrics strip */}
          <div className="grid grid-cols-2 gap-2.5 border-t border-white/[0.06] pt-5 sm:grid-cols-3 lg:grid-cols-6">
            <MetricCell
              label={t("detail.median60")}
              value={formatPrice(product.rolling_60d_median, lang)}
            />
            <MetricCell
              label={t("detail.allTimeLow")}
              value={formatPrice(product.min_historical_price, lang)}
              accent="text-emerald-300"
            />
            <MetricCell
              label={t("detail.allTimeHigh")}
              value={formatPrice(product.max_historical_price, lang)}
              accent="text-rose-300"
            />
            <MetricCell
              label={t("detail.claimedOriginal")}
              value={formatPrice(product.claimed_original_price, lang)}
              accent={product.claimed_original_price === null ? "text-slate-500" : "text-amber-300"}
            />
            <MetricCell
              label={t("detail.claimedDisc")}
              value={formatPct(product.claimed_discount_pct, lang)}
              accent={product.claimed_discount_pct >= 10 ? "text-amber-300" : "text-white"}
              ltrValue
            />
            <MetricCell
              label={t("detail.realDisc")}
              value={formatPct(product.real_discount_pct, lang)}
              accent={realAccent}
              ltrValue
            />
          </div>
        </section>

        {/* ============================================================ */}
        {/* SECTION 2: Price History Chart Card                          */}
        {/* ============================================================ */}
        <section className="surface rounded-2xl p-5 sm:p-6">
          <div className="mb-4">
            <h2 className="text-base font-bold text-white">{t("detail.history")}</h2>
            <p className="mt-0.5 text-xs text-slate-500">{t("detail.historyHint")}</p>
          </div>
          <PriceChart history={history} />
        </section>

        {/* ============================================================ */}
        {/* SECTION 3: Specifications & Cross-Store Alternatives         */}
        {/* ============================================================ */}
        <section className="space-y-6">
          <AttributesPanel product={product} />

          <div id="alternatives" className="surface scroll-mt-24 rounded-2xl p-5 sm:p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-bold text-white">{t("detail.alternatives")}</h2>
                <p className="mt-0.5 text-xs text-slate-500">{t("detail.alternativesHint")}</p>
              </div>
              {alternatives.length > 0 ? (
                <Link
                  href="/compare"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-300 transition hover:text-emerald-200"
                >
                  <span>{t("nav.compare")}</span>
                  <ArrowRight className="size-3.5 rtl:rotate-180" />
                </Link>
              ) : null}
            </div>
            {alternatives.length > 0 ? (
              <AlternativesTable
                alternatives={alternatives}
                currentPrice={product.current_price}
              />
            ) : (
              <p className="rounded-xl border border-dashed border-white/10 px-4 py-7 text-center text-sm text-slate-500">
                {t("detail.noAlternatives")}
              </p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
