"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { ArrowLeft, BellRing, ExternalLink } from "lucide-react";
import type { ProductDetailResponse } from "@/types/contract";
import { ApiError, fetchProductDetail, type ApiResult } from "@/lib/api";
import { trackStoreOutbound, trackViewProduct } from "@/lib/analytics";
import {
  categoryLabelKey,
  productHref,
  safeBrowseHref,
  useBrowseParams,
} from "@/lib/browse-state";
import {
  formatDate,
  formatDateTime,
  formatNumber,
  formatPackSize,
  formatPctPlain,
  formatPrice,
  formatSubCategory,
  formatUnitPrice,
} from "@/lib/format";
import { isStaleObservation, observedTimestamp } from "@/lib/highlights";
import { useLanguage } from "@/lib/i18n";
import { buildAffiliateUrl, outboundLinkRel } from "@/lib/affiliate";
import { retailerHref } from "@/lib/offers";
import { absoluteUrl } from "@/lib/site";
import { storeDisplayName } from "@/lib/stores";
import {
  formatTrackedDays,
  getHistoryMaturity,
  getTrackedDaysCount,
  getVerifiedMedian,
  normalizeVerdict,
} from "@/lib/verdicts";
import { AdSlot } from "@/components/AdSlot";
import { AlternativesTable } from "@/components/AlternativesTable";
import { AsarakEmblem } from "@/components/AsarakLogo";
import { AttributesPanel } from "@/components/AttributesPanel";
import { CouponPill } from "@/components/CouponPill";
import { MockBanner } from "@/components/MockBanner";
import { PriceAlertModal } from "@/components/PriceAlertModal";
import { ProductImage } from "@/components/ProductImage";
import { ShareButton } from "@/components/ShareButton";
import { SimilarAlternativesList } from "@/components/SimilarAlternativesList";
import { DetailSkeleton, ErrorState } from "@/components/states";
import { StoreBadge } from "@/components/StoreBadge";
import { VerdictBadge } from "@/components/VerdictBadge";
import MissingProduct from "./not-found";

const PriceChart = dynamic(
  () => import("@/components/PriceChart").then((m) => m.PriceChart),
  {
    ssr: false,
    loading: () => (
      <div
        className="skeleton h-[270px] w-full rounded-xl"
        role="status"
        aria-hidden="true"
      />
    ),
  },
);

export function ProductReceipt({
  productSk,
  initial,
}: {
  productSk: string;
  initial: ApiResult<ProductDetailResponse> | null;
}) {
  const { lang, ready, t } = useLanguage();
  const params = useBrowseParams();
  const from = safeBrowseHref(params.get("from"));
  const [retry, setRetry] = useState(0);
  const [response, setResponse] = useState<{
    attempt: number;
    result?: ApiResult<ProductDetailResponse>;
    missing?: boolean;
  } | null>(null);
  const [alertOpen, setAlertOpen] = useState(false);
  const trackedSkRef = useRef<string | null>(null);

  useEffect(() => {
    if (retry === 0) return;
    const controller = new AbortController();
    fetchProductDetail(productSk, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setResponse({ attempt: retry, result });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setResponse({
            attempt: retry,
            missing: error instanceof ApiError && error.status === 404,
          });
      });
    return () => controller.abort();
  }, [productSk, retry]);

  const loaded = retry ? response?.result : initial;
  const loadedProduct = loaded?.source === "api" ? loaded.data.product : null;

  useEffect(() => {
    if (!loadedProduct || trackedSkRef.current === loadedProduct.product_sk)
      return;
    trackedSkRef.current = loadedProduct.product_sk;
    trackViewProduct({
      productSk: loadedProduct.product_sk,
      productTitle: loadedProduct.product_title,
      storeName: loadedProduct.store_name,
      category: loadedProduct.category,
      priceEgp: loadedProduct.current_price,
      verdict: loadedProduct.discount_verdict,
    });
  }, [loadedProduct]);

  if (retry > 0 && response?.attempt !== retry) {
    return (
      <div className="ptr-wrap ptr-page" role="status">
        <span className="sr-only">{t("common.loading")}</span>
        <DetailSkeleton />
      </div>
    );
  }
  if (retry > 0 && response?.missing) return <MissingProduct />;
  if (!loaded)
    return (
      <div className="ptr-wrap ptr-page">
        <ErrorState onRetry={() => setRetry((value) => value + 1)} />
      </div>
    );

  const {
    product,
    history,
    alternatives,
    market_benchmark: detailMarketBenchmark = null,
    similar_alternatives = [],
    similar_products = [],
    variants = [],
  } = loaded.data;
  const marketBenchmark = detailMarketBenchmark ?? product.market_benchmark ?? null;
  const similarItems =
    similar_products.length > 0 ? similar_products : similar_alternatives;
  const label = storeDisplayName(product.store_name, lang);
  const price = formatPrice(product.current_price, lang);
  const timestamp = observedTimestamp(product.last_updated_at);
  const stale = isStaleObservation(timestamp);
  const safeStoreUrl = retailerHref(product.product_url);
  const storeLink = safeStoreUrl
    ? buildAffiliateUrl(safeStoreUrl, product.store_name)
    : null;
  const compareReady = alternatives.some((offer) => offer.in_stock);
  const hasHistory = history.length > 1;
  const trackedDays = getTrackedDaysCount(product, history);
  const historyMaturity = getHistoryMaturity(product, history);
  const sufficientHistory = historyMaturity !== "EARLY";
  const trackedDaysLabel = formatTrackedDays(trackedDays, lang);
  const median = getVerifiedMedian(product, history);
  const medianLabel =
    historyMaturity === "MATURE"
      ? t("maturity.medianWindow60")
      : t("maturity.medianWindowDays", {
          days: formatNumber(trackedDays, lang),
        });
  const delta = product.real_discount_pct;
  const recentDropPct =
    !sufficientHistory &&
    product.discount_verdict === "RECENT_DROP" &&
    product.max_historical_price > product.current_price &&
    product.max_historical_price > 0
      ? ((product.max_historical_price - product.current_price) /
          product.max_historical_price) *
        100
      : null;
  const recentHikePct =
    !sufficientHistory &&
    product.discount_verdict === "RECENT_HIKE" &&
    product.min_historical_price > 0 &&
    product.current_price > product.min_historical_price
      ? ((product.current_price - product.min_historical_price) /
          product.min_historical_price) *
        100
      : null;
  const takeaway =
    median !== null
      ? Math.abs(delta) < 0.05
        ? t("ui.same")
        : historyMaturity === "MATURE"
          ? t(delta > 0 ? "ui.below" : "ui.above", {
              pct: formatPctPlain(Math.abs(delta), lang),
            })
          : t(delta > 0 ? "maturity.belowWindow" : "maturity.aboveWindow", {
              pct: formatPctPlain(Math.abs(delta), lang),
              days: formatNumber(trackedDays, lang),
            })
      : marketBenchmark
        ? marketBenchmark.status === "CHEAPEST_IN_MARKET" &&
          (marketBenchmark.savings_vs_next_cheapest_egp ?? 0) >= 1
          ? t("market.cheaperBy", {
              amount: formatPrice(
                marketBenchmark.savings_vs_next_cheapest_egp ?? 0,
                lang,
              ),
              count: formatNumber(marketBenchmark.stores_count, lang),
            })
          : marketBenchmark.status === "ABOVE_MARKET" &&
              marketBenchmark.price_diff_vs_cheapest_egp >= 1
            ? t("market.aboveDetail", {
                amount: formatPrice(
                  marketBenchmark.price_diff_vs_cheapest_egp,
                  lang,
                ),
                store: storeDisplayName(marketBenchmark.cheapest_store, lang),
                price: formatPrice(marketBenchmark.cheapest_price, lang),
                count: formatNumber(marketBenchmark.stores_count, lang),
              })
            : marketBenchmark.status === "OUT_OF_STOCK"
              ? t("market.outOfStockOther", {
                  store: storeDisplayName(marketBenchmark.cheapest_store, lang),
                  price: formatPrice(marketBenchmark.cheapest_price, lang),
                })
              : null
        : recentDropPct !== null
          ? t("maturity.recentDropSummary", {
              pct: formatPctPlain(recentDropPct, lang),
              days: trackedDaysLabel,
              high: formatPrice(product.max_historical_price, lang),
              current: price,
            })
          : recentHikePct !== null
            ? t("maturity.recentHikeSummary", {
                pct: formatPctPlain(recentHikePct, lang),
                days: trackedDaysLabel,
                low: formatPrice(product.min_historical_price, lang),
                current: price,
              })
            : null;
  const pack = formatPackSize(product.attributes_json);
  const unit = formatUnitPrice(product, lang);
  const live = loaded.source === "api";
  const canVisit = live && Boolean(storeLink) && product.in_stock;
  const canAlert = live && product.current_price > 0.01;
  const variantCount = Math.max(1, product.variant_count ?? 1, variants.length);
  const hasMultipleVariants = Boolean(
    product.has_multiple_variants || variantCount > 1,
  );
  const minVarPrice =
    typeof product.min_variant_price === "number" &&
    product.min_variant_price > 0
      ? product.min_variant_price
      : product.current_price;
  const maxVarPrice =
    typeof product.max_variant_price === "number" &&
    product.max_variant_price > 0
      ? product.max_variant_price
      : product.current_price;
  const hasPriceRange =
    hasMultipleVariants && maxVarPrice > minVarPrice + 0.01;
  const showVariantSelector = variants.length > 1;
  const showRangeNote =
    hasMultipleVariants && hasPriceRange && variants.length <= 1;

  const decisionTone =
    median !== null && product.discount_verdict === "FAKE_DISCOUNT"
      ? "ptr-decision--fake"
      : median !== null && product.discount_verdict === "PRESALE_HIKE"
        ? "ptr-decision--hike"
        : "";

  return (
    <div className="ptr-wrap ptr-page">
      <Link
        className="ptr-link inline-flex w-fit items-center gap-2 text-sm"
        href={from ?? "/"}
      >
        <ArrowLeft size={16} aria-hidden="true" className="rtl:rotate-180" />
        {t(from ? "detail.back" : "nav.feed")}
      </Link>

      <MockBanner source={loaded.source} />
      {stale && live && <p className="ptr-notice ptr-warning">{t("ui.stale")}</p>}

      <header className="surface ptr-product-heading">
        <ProductImage
          src={product.image_url}
          alt=""
          category={product.category}
          subCategory={product.sub_category}
          brand={product.brand}
          className="ptr-product-photo"
          priority
          fit={product.category === "fashion" ? "cover" : "contain"}
          studio={product.category !== "fashion"}
        />
        <div className="min-w-0">
          <div className="ptr-controls text-sm ptr-muted">
            <StoreBadge name={product.store_name} size="sm" />
            {categoryLabelKey(product.category) && (
              <span className="ptr-badge">
                {t(categoryLabelKey(product.category)!)}
              </span>
            )}
            {product.variant_label && (
              <span className="ptr-badge ptr-badge-variant">
                <bdi>{product.variant_label}</bdi>
              </span>
            )}
            {hasMultipleVariants && !product.variant_label && (
              <span className="ptr-badge ptr-badge-variant">
                <bdi>
                  {t(
                    variantCount >= 11
                      ? "variant.optionsCountMany"
                      : "variant.optionsCount",
                    { count: formatNumber(variantCount, lang) },
                  )}
                </bdi>
              </span>
            )}
            <span>{formatSubCategory(product.sub_category, lang)}</span>
          </div>
          <h1>
            <bdi>{product.product_title}</bdi>
          </h1>
          {(product.brand || pack) && (
            <p className="ptr-muted text-sm">
              <bdi>{[product.brand, pack].filter(Boolean).join(" · ")}</bdi>
            </p>
          )}
        </div>
      </header>

      {showVariantSelector && (
        <section
          className="surface ptr-section ptr-variant-section"
          aria-label={t("variant.selectorTitle")}
        >
          <div className="ptr-variant-header">
            <h2>{t("variant.selectorTitle")}</h2>
            <span className="ptr-badge ptr-badge-variant">
              <bdi>
                {t(
                  variantCount >= 11
                    ? "variant.optionsCountMany"
                    : "variant.optionsCount",
                  { count: formatNumber(variantCount, lang) },
                )}
              </bdi>
            </span>
          </div>
          <div className="ptr-variant-list" role="list">
            {variants.map((variant) => {
              const selected = variant.product_sk === product.product_sk;
              const chipLabel = variant.variant_label || variant.title;
              return (
                <Link
                  key={variant.product_sk}
                  role="listitem"
                  href={productHref(variant.product_sk, from ?? undefined, !live)}
                  aria-current={selected ? "true" : undefined}
                  className={`ptr-variant-chip${variant.in_stock ? "" : " ptr-variant-oos"}`}
                >
                  <span className="ptr-variant-chip-label">
                    <bdi>{chipLabel}</bdi>
                  </span>
                  <span className="ptr-variant-chip-meta">
                    <bdi>{formatPrice(variant.current_price, lang)}</bdi>
                    {!variant.in_stock && (
                      <span className="ptr-variant-chip-stock">
                        {" "}
                        · {t("card.outOfStock")}
                      </span>
                    )}
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {showRangeNote && (
        <p className="ptr-notice ptr-variant-range-note">
          <bdi>
            {t(
              variantCount >= 11
                ? "variant.storeRangeNoteMany"
                : "variant.storeRangeNote",
              {
                count: formatNumber(variantCount, lang),
                min: formatPrice(minVarPrice, lang),
                max: formatPrice(maxVarPrice, lang),
              },
            )}
          </bdi>
        </p>
      )}

      <div className="ptr-receipt-layout">
        <aside className={`surface ptr-decision ${decisionTone}`}>
          <p className="ptr-stock-pill">
            <span
              className={`ptr-stock-dot ${product.in_stock ? "" : "ptr-stock-dot--oos"}`}
              aria-hidden="true"
            />
            <span>
              {t("detail.current")} ·{" "}
              {t(product.in_stock ? "detail.inStock" : "card.outOfStock")}
            </span>
          </p>

          <p className="ptr-price ptr-current-price">
            <bdi>{price}</bdi>
          </p>

          <CouponPill
            coupons={product.applicable_coupons}
            estimatedPrice={product.estimated_price_after_coupon}
          />

          {unit && (
            <p className="text-sm ptr-muted">
              <bdi>{unit}</bdi>
            </p>
          )}

          {median !== null ? (
            <VerdictBadge verdict={product.discount_verdict} />
          ) : marketBenchmark ? (
            <div className="flex flex-wrap items-center gap-2">
              {marketBenchmark.status === "CHEAPEST_IN_MARKET" && (
                <span className="ptr-badge ptr-badge-good">
                  {t("market.cheapestBadge")}
                </span>
              )}
              {marketBenchmark.status === "TIED_CHEAPEST" && (
                <span className="ptr-badge ptr-badge-good">
                  {t("market.tiedCheapestBadge")}
                </span>
              )}
              {marketBenchmark.status === "ABOVE_MARKET" && (
                <a href="#alternatives" className="ptr-badge ptr-badge-amber">
                  <bdi>
                    {t("market.aboveBadge", {
                      amount: formatPrice(
                        marketBenchmark.price_diff_vs_cheapest_egp,
                        lang,
                      ),
                    })}
                  </bdi>
                </a>
              )}
              {(product.discount_verdict === "RECENT_DROP" ||
                product.discount_verdict === "RECENT_HIKE") && (
                <VerdictBadge verdict={product.discount_verdict} size="sm" />
              )}
            </div>
          ) : product.discount_verdict === "RECENT_DROP" ||
            product.discount_verdict === "RECENT_HIKE" ? (
            <VerdictBadge verdict={product.discount_verdict} />
          ) : (
            <span className="ptr-badge">
              {t("maturity.earlyBadge", { days: trackedDaysLabel })}
            </span>
          )}

          {timestamp && live && (
            <p className="text-xs ptr-muted">
              {t("ui.lastChecked", { time: formatDateTime(timestamp, lang) })}
            </p>
          )}
          {!product.in_stock && compareReady && (
            <p className="text-sm">{t("ui.outOfStockHint")}</p>
          )}
          {product.scarcity_flag && product.in_stock && (
            <p className="text-sm ptr-error">{t("card.lowStock")}</p>
          )}

          <div className="ptr-decision-actions">
            {!canVisit && compareReady && (
              <a href="#alternatives" className="ptr-button ptr-primary">
                {t("ui.viewOffers")}
              </a>
            )}
            {canVisit && storeLink && (
              <a
                href={storeLink.url}
                target="_blank"
                rel={outboundLinkRel(storeLink.isAffiliate)}
                onClick={() =>
                  trackStoreOutbound({
                    store: product.store_name,
                    product_id: product.product_sk,
                    price: product.current_price,
                    category: product.category,
                    is_affiliate: storeLink.isAffiliate,
                    network: storeLink.network,
                    placement: "product_hero",
                  })
                }
                className="ptr-button ptr-primary"
              >
                {t("detail.openAtStore", { store: label })}{" "}
                <ExternalLink size={15} aria-hidden="true" />
              </a>
            )}
            {canAlert && (
              <button
                type="button"
                disabled={!ready}
                onClick={() => setAlertOpen(true)}
                className={`ptr-button ${!canVisit && !compareReady ? "ptr-primary" : ""}`}
              >
                <BellRing size={16} aria-hidden="true" />
                {t("alert.bellAria")}
              </button>
            )}
            {canVisit && alternatives.length > 0 && (
              <a href="#alternatives" className="ptr-button">
                {t("ui.viewOffers")}
              </a>
            )}
            {live && (
              <ShareButton
                title={product.product_title}
                url={absoluteUrl(productHref(product.product_sk))}
                text={
                  timestamp && !stale
                    ? [product.product_title, label, price, takeaway]
                        .filter(Boolean)
                        .join(" · ")
                    : undefined
                }
              />
            )}
          </div>
        </aside>

        <section className="surface ptr-section ptr-receipt">
          <div className="flex items-center justify-between gap-2 mb-3">
            <h2 className="flex items-center gap-2 !mb-0">
              <AsarakEmblem variant="auto" size={24} />
              <span>{t("ui.receipt")}</span>
            </h2>
            {median !== null && (
              <span
                className={`ptr-badge ${
                  product.discount_verdict === "FAKE_DISCOUNT"
                    ? "ptr-badge-warning"
                    : "ptr-badge-good"
                }`}
              >
                {t(
                  product.discount_verdict === "FAKE_DISCOUNT"
                    ? "receipt.fakeStamp"
                    : "receipt.verifiedStamp",
                )}
              </span>
            )}
          </div>

          <dl className="ptr-receipt-rows">
            <div>
              <dt>{t("detail.current")}</dt>
              <dd>
                <bdi>{price}</bdi>
              </dd>
            </div>
            {hasPriceRange && (
              <div>
                <dt>{t("variant.rangeLabel")}</dt>
                <dd className="ptr-variant-range">
                  <bdi>
                    {t("variant.priceRange", {
                      min: formatPrice(minVarPrice, lang),
                      max: formatPrice(maxVarPrice, lang),
                    })}
                  </bdi>
                </dd>
              </div>
            )}
            {product.claimed_original_price !== null && (
              <div>
                <dt>{t("deals.claimedPrice")}</dt>
                <dd className="ptr-strike">
                  <bdi>{formatPrice(product.claimed_original_price, lang)}</bdi>
                </dd>
              </div>
            )}
            {median !== null ? (
              <div>
                <dt>{medianLabel}</dt>
                <dd>
                  <bdi>{formatPrice(median, lang)}</bdi>
                </dd>
              </div>
            ) : (
              <div>
                <dt>{t("detail.history")}</dt>
                <dd className="text-sm ptr-muted">
                  {t("maturity.earlyCard", { days: trackedDaysLabel })}
                </dd>
              </div>
            )}
            {marketBenchmark && (
              <div>
                <dt>
                  {t("market.liveBenchmarkLabel", {
                    count: formatNumber(marketBenchmark.stores_count, lang),
                  })}
                </dt>
                <dd>
                  <a href="#alternatives" className="ptr-link">
                    <bdi>
                      {marketBenchmark.status === "CHEAPEST_IN_MARKET"
                        ? t("market.cheapestBadge")
                        : marketBenchmark.status === "TIED_CHEAPEST"
                          ? t("market.tiedCheapestBadge")
                          : `${formatPrice(marketBenchmark.cheapest_price, lang)} (${storeDisplayName(marketBenchmark.cheapest_store, lang)})`}
                    </bdi>
                  </a>
                </dd>
              </div>
            )}
            {product.claimed_discount_pct > 0 && (
              <div>
                <dt>
                  {sufficientHistory
                    ? t("detail.claimedDisc")
                    : t("maturity.claimedUnverified")}
                </dt>
                <dd>
                  <bdi>{formatPctPlain(product.claimed_discount_pct, lang)}</bdi>
                </dd>
              </div>
            )}
          </dl>

          {takeaway && <p className="ptr-notice">{takeaway}</p>}

          {(median !== null ||
            product.discount_verdict === "RECENT_DROP" ||
            product.discount_verdict === "RECENT_HIKE") && (
            <details>
              <summary className="ptr-link">{t("detail.whatMeans")}</summary>
              <p className="ptr-muted text-sm mt-2">
                {t(`explain.${normalizeVerdict(product.discount_verdict)}`)}
              </p>
            </details>
          )}

          {!sufficientHistory && (
            <p className="text-sm ptr-muted">
              {t("maturity.earlyCard", { days: trackedDaysLabel })}
            </p>
          )}
        </section>
      </div>

      <section id="alternatives" className="surface ptr-section">
        <h2>{t("detail.alternatives")}</h2>
        <p className="ptr-muted text-sm">{t("detail.alternativesHint")}</p>
        {alternatives.length > 0 ? (
          <AlternativesTable
            alternatives={alternatives}
            category={product.category}
            from={from ?? undefined}
            sample={!live}
            currentOffer={{
              price: product.current_price,
              in_stock: product.in_stock,
            }}
          />
        ) : (
          <p className="ptr-muted text-sm">{t("detail.noAlternatives")}</p>
        )}
      </section>

      {similarItems.length > 0 && (
        <section id="similar-products" className="surface ptr-section">
          <SimilarAlternativesList
            items={similarItems}
            category={product.category}
            from={from ?? undefined}
            sample={!live}
            hasExactAlternatives={alternatives.length > 0}
          />
        </section>
      )}

      <AdSlot
        slot={process.env.NEXT_PUBLIC_ADSENSE_SLOT_PRODUCT}
        format="auto"
        minHeight={120}
      />

      <section className="surface ptr-section">
        <h2>{t("detail.history")}</h2>
        {history.length === 0 ? (
          <p className="ptr-muted text-sm">{t("ui.noHistory")}</p>
        ) : history.length === 1 ? (
          <div className="ptr-notice ptr-baseline">
            <p className="font-semibold">
              {t("detail.baselineTitle", {
                date: formatDate(history[0].snapshot_date, lang),
              })}
            </p>
            <p>
              {t("detail.baselineRecordedPrice")} ·{" "}
              <bdi className="ptr-mono">
                {formatPrice(history[0].price, lang)}
              </bdi>
            </p>
            {history[0].claimed_original_price !== null && (
              <p>
                {t("detail.baselineClaimedPrice")} ·{" "}
                <bdi className="ptr-mono">
                  {formatPrice(history[0].claimed_original_price, lang)}
                </bdi>
              </p>
            )}
            <p className="ptr-muted">{t("detail.baselineBody")}</p>
          </div>
        ) : (
          <PriceChart
            history={history}
            trackedDaysCount={trackedDays}
            historyMaturity={historyMaturity}
          />
        )}
        {hasHistory && (
          <dl className="ptr-history-extremes">
            <div>
              <dt>{t("detail.allTimeLow")}</dt>
              <dd className="ptr-price" style={{ color: "var(--asarak-verified-ink)" }}>
                <bdi>{formatPrice(product.min_historical_price, lang)}</bdi>
              </dd>
            </div>
            <div>
              <dt>{t("detail.allTimeHigh")}</dt>
              <dd className="ptr-price">
                <bdi>{formatPrice(product.max_historical_price, lang)}</bdi>
              </dd>
            </div>
          </dl>
        )}
      </section>

      <AttributesPanel product={product} />

      {canAlert && (
        <PriceAlertModal
          open={alertOpen}
          onClose={() => setAlertOpen(false)}
          productKey={product.canonical_product_key ?? product.product_sk}
          productTitle={product.product_title}
          storeName={product.store_name}
          currentPrice={product.current_price}
        />
      )}
    </div>
  );
}
