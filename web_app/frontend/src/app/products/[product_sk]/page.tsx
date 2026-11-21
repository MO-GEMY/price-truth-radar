"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  BadgeCheck,
  CalendarClock,
  ExternalLink,
  Flame,
  Info,
  Link2,
  PackageX,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import type { ProductDetailResponse } from "@/types/contract";
import { ApiError, fetchProductDetail, type DataSource } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";
import { formatDateTime, formatPct, formatPctPlain, formatPrice } from "@/lib/format";
import { MockBanner } from "@/components/MockBanner";
import { PriceChart } from "@/components/PriceChart";
import { AttributesPanel } from "@/components/AttributesPanel";
import { AlternativesTable } from "@/components/AlternativesTable";
import { VerdictBadge } from "@/components/VerdictBadge";
import { StoreBadge } from "@/components/StoreBadge";
import { DetailSkeleton, ErrorState } from "@/components/states";

type Status = "loading" | "ready" | "notfound" | "error";

const VERDICT_EXPLAIN_ICON: Record<string, LucideIcon> = {
  FAKE_DISCOUNT: ShieldAlert,
  ALL_TIME_LOW: TrendingDown,
  GENUINE_DEAL: BadgeCheck,
  PRESALE_HIKE: TrendingUp,
  NORMAL_PRICE: Info,
};

function PriceTile({
  label,
  value,
  accent = "text-white",
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="glass rounded-2xl p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className={`num mt-2 text-lg font-bold tracking-tight sm:text-xl ${accent}`}>
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
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-10 sm:px-6">
        <DetailSkeleton />
      </div>
    );
  }

  if (status === "notfound") {
    return (
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <div className="glass mx-auto flex max-w-md flex-col items-center gap-3 rounded-2xl px-6 py-12 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-slate-500/12 text-slate-300">
            <Info className="size-6" />
          </span>
          <h1 className="text-lg font-bold text-white">{t("detail.notFound")}</h1>
          <p className="text-sm text-slate-400">{t("detail.notFoundBody")}</p>
          <Link
            href="/"
            className="mt-2 inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-300 hover:bg-cyan-400/20"
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
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <ErrorState onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    );
  }

  const { product, history, alternatives } = detail;
  const ExplainIcon = VERDICT_EXPLAIN_ICON[product.discount_verdict] ?? Info;
  const realAccent =
    product.real_discount_pct >= 5
      ? "text-emerald-300"
      : product.real_discount_pct < 0
        ? "text-rose-300"
        : "text-white";

  return (
    <>
      <MockBanner source={source} />

      <div className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm font-semibold text-slate-400 transition hover:text-cyan-300"
        >
          <ArrowLeft className="size-4 rtl:rotate-180" />
          {t("detail.back")}
        </Link>

        {/* Product header */}
        <section className="glass rounded-2xl p-5 sm:p-6">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
            {product.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={product.image_url}
                alt={product.product_title}
                className="h-32 w-32 shrink-0 rounded-xl border border-white/10 object-cover"
              />
            ) : null}
            <div className="min-w-0 flex-1 space-y-3">
              <h1 className="text-xl font-bold leading-snug tracking-tight text-white sm:text-2xl">
                {product.product_title}
              </h1>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <StoreBadge name={product.store_name} />
                <VerdictBadge verdict={product.discount_verdict} />
                {product.scarcity_flag ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/35 bg-amber-500/12 px-2.5 py-1 font-semibold text-amber-300">
                    <Flame className="size-3.5" />
                    {t("card.lowStock")}
                  </span>
                ) : null}
                {!product.in_stock ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/35 bg-rose-500/12 px-2.5 py-1 font-semibold text-rose-300">
                    <PackageX className="size-3.5" />
                    {t("card.outOfStock")}
                  </span>
                ) : null}
                <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1">
                  {product.category === "electronics" ? "Electronics" : "Fashion"}
                  · {product.sub_category.replace(/_/g, " ")}
                </span>
                {product.canonical_product_key ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-1 font-medium text-violet-300">
                    <Link2 className="size-3" />
                    {t("detail.canonical")}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-3 pt-1">
                <a
                  href={product.product_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-4 py-2.5 text-sm font-bold text-[#04121a] transition hover:brightness-110"
                >
                  <ExternalLink className="size-4" />
                  {t("detail.openAtStore")}
                </a>
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
                  <CalendarClock className="size-3.5" />
                  {t("detail.lastUpdated")}: {formatDateTime(product.last_updated_at, lang)}
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Price breakdown — §3.1 numeric fields */}
        <section>
          <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-400">
            {t("detail.priceBreakdown")}
          </h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <PriceTile label={t("detail.current")} value={formatPrice(product.current_price, lang)} accent="text-cyan-300" />
            <PriceTile label={t("detail.median60")} value={formatPrice(product.rolling_60d_median, lang)} />
            <PriceTile label={t("detail.allTimeLow")} value={formatPrice(product.min_historical_price, lang)} accent="text-emerald-300" />
            <PriceTile label={t("detail.allTimeHigh")} value={formatPrice(product.max_historical_price, lang)} accent="text-rose-300" />
            <PriceTile
              label={t("detail.claimedOriginal")}
              value={formatPrice(product.claimed_original_price, lang)}
              accent={product.claimed_original_price === null ? "text-slate-500" : "text-amber-300"}
            />
            <PriceTile
              label={t("detail.claimedDisc")}
              value={formatPct(product.claimed_discount_pct, lang)}
              accent={product.claimed_discount_pct >= 10 ? "text-amber-300" : "text-white"}
            />
            <PriceTile
              label={t("detail.realDisc")}
              value={formatPct(product.real_discount_pct, lang)}
              accent={realAccent}
            />
          </div>
        </section>

        {/* Verdict explainer */}
        <section className="glass flex items-start gap-4 rounded-2xl p-5">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-cyan-300">
            <ExplainIcon className="size-5" />
          </span>
          <div>
            <h2 className="text-sm font-bold text-white">{t("detail.whatMeans")}</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-300">
              <strong className="text-cyan-300">
                {t(`verdict.${product.discount_verdict}`)}:
              </strong>{" "}
              {t(`explain.${product.discount_verdict}` as TranslationKey)}
            </p>
          </div>
        </section>

        {/* Interactive price history — §5.5 history[] */}
        <section className="glass rounded-2xl p-5 sm:p-6">
          <h2 className="text-sm font-bold text-white">{t("detail.history")}</h2>
          <p className="mb-5 mt-1 text-xs text-slate-500">{t("detail.historyHint")}</p>
          <PriceChart history={history} />
        </section>

        {/* Attributes + cross-store alternatives */}
        <section className="grid gap-5 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <AttributesPanel product={product} />
          </div>
          <div className="glass rounded-2xl p-5 sm:p-6 lg:col-span-3">
            <h2 className="text-sm font-bold text-white">{t("detail.alternatives")}</h2>
            <p className="mb-4 mt-1 text-xs text-slate-500">{t("detail.alternativesHint")}</p>
            {alternatives.length > 0 ? (
              <AlternativesTable alternatives={alternatives} />
            ) : (
              <p className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-500">
                {t("detail.noAlternatives")}
              </p>
            )}
          </div>
        </section>

        {/* Compact inflation callout */}
        {product.claimed_discount_pct >= 10 && product.real_discount_pct < 3 ? (
          <section className="flex items-center gap-3 rounded-2xl border border-rose-500/25 bg-rose-500/[0.06] p-4">
            <ShieldAlert className="size-5 shrink-0 text-rose-400" />
            <p className="text-sm text-rose-200">
              {t("explain.FAKE_DISCOUNT")}{" "}
              <span className="num font-bold">
                {t("card.inflation", {
                  pts: formatPctPlain(
                    product.claimed_discount_pct - Math.max(product.real_discount_pct, 0),
                    lang,
                  ),
                })}
              </span>
            </p>
          </section>
        ) : null}
      </div>
    </>
  );
}
