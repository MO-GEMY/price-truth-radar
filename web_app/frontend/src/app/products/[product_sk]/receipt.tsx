"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { ArrowLeft, BellRing, ExternalLink } from "lucide-react";
import type { ProductDetailResponse } from "@/types/contract";
import { ApiError, fetchProductDetail, type ApiResult } from "@/lib/api";
import { trackStoreOutbound, trackViewProduct } from "@/lib/analytics";
import { categoryLabelKey, productHref, safeBrowseHref, useBrowseParams } from "@/lib/browse-state";
import { formatDate, formatDateTime, formatNumber, formatPackSize, formatPctPlain, formatPrice, formatSubCategory, formatUnitPrice } from "@/lib/format";
import { isStaleObservation, observedTimestamp } from "@/lib/highlights";
import { useLanguage } from "@/lib/i18n";
import { buildAffiliateUrl, outboundLinkRel } from "@/lib/affiliate";
import { retailerHref } from "@/lib/offers";
import { absoluteUrl } from "@/lib/site";
import { storeDisplayName } from "@/lib/stores";
import { hasSufficientPriceHistory } from "@/lib/verdicts";
import { AdSlot } from "@/components/AdSlot";
import { AlternativesTable } from "@/components/AlternativesTable";
import { AttributesPanel } from "@/components/AttributesPanel";
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
      <div className="skeleton h-[260px] w-full rounded-lg" role="status" aria-hidden="true" />
    ),
  },
);

export function ProductReceipt({ productSk, initial }: {
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
    fetchProductDetail(productSk, controller.signal).then((result) => {
      if (!controller.signal.aborted) setResponse({ attempt: retry, result });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setResponse({ attempt: retry, missing: error instanceof ApiError && error.status === 404 });
    });
    return () => controller.abort();
  }, [productSk, retry]);

  const loaded = retry ? response?.result : initial;
  const loadedProduct = loaded?.source === "api" ? loaded.data.product : null;

  useEffect(() => {
    if (!loadedProduct || trackedSkRef.current === loadedProduct.product_sk) return;
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
    return <div className="ptr-wrap ptr-page" role="status"><span className="sr-only">{t("common.loading")}</span><DetailSkeleton /></div>;
  }
  if (retry > 0 && response?.missing) return <MissingProduct />;
  if (!loaded) return <div className="ptr-wrap ptr-page"><ErrorState onRetry={() => setRetry((value) => value + 1)} /></div>;

  const { product, history, alternatives, similar_alternatives = [], variants = [] } = loaded.data;
  const label = storeDisplayName(product.store_name, lang);
  const price = formatPrice(product.current_price, lang);
  const timestamp = observedTimestamp(product.last_updated_at);
  const stale = isStaleObservation(timestamp);
  const safeStoreUrl = retailerHref(product.product_url);
  const storeLink = safeStoreUrl ? buildAffiliateUrl(safeStoreUrl, product.store_name) : null;
  const compareReady = alternatives.some((offer) => offer.in_stock);
  const hasHistory = history.length > 1;
  const sufficientHistory = hasSufficientPriceHistory(product, history);
  const median = sufficientHistory && product.rolling_60d_median > 0 ? product.rolling_60d_median : null;
  const delta = product.real_discount_pct;
  const takeaway = median === null ? null : Math.abs(delta) < 0.05 ? t("ui.same")
    : t(delta > 0 ? "ui.below" : "ui.above", { pct: formatPctPlain(Math.abs(delta), lang) });
  const pack = formatPackSize(product.attributes_json);
  const unit = formatUnitPrice(product, lang);
  const live = loaded.source === "api";
  const canVisit = live && Boolean(storeLink) && product.in_stock;
  const canAlert = live && product.current_price > 0.01;
  const variantCount = Math.max(1, product.variant_count ?? 1, variants.length);
  const hasMultipleVariants = Boolean(product.has_multiple_variants || variantCount > 1);
  const minVarPrice = typeof product.min_variant_price === "number" && product.min_variant_price > 0
    ? product.min_variant_price
    : product.current_price;
  const maxVarPrice = typeof product.max_variant_price === "number" && product.max_variant_price > 0
    ? product.max_variant_price
    : product.current_price;
  const hasPriceRange = hasMultipleVariants && maxVarPrice > minVarPrice + 0.01;
  const showVariantSelector = variants.length > 1;
  const showRangeNote = hasMultipleVariants && hasPriceRange && variants.length <= 1;

  return (
    <div className="ptr-wrap ptr-page">
      <Link className="ptr-link inline-flex items-center gap-2" href={from ?? "/"}>
        <ArrowLeft size={16} aria-hidden="true" className="rtl:rotate-180" />{t(from ? "detail.back" : "nav.feed")}
      </Link>
      <MockBanner source={loaded.source} />
      {stale && live && <p className="ptr-notice ptr-warning">{t("ui.stale")}</p>}
      <header className="ptr-product-heading">
        <ProductImage src={product.image_url} alt="" category={product.category} subCategory={product.sub_category}
          brand={product.brand} className="ptr-product-photo" priority
          fit={product.category === "fashion" ? "cover" : "contain"} studio={product.category !== "fashion"} />
        <div className="min-w-0">
          <div className="ptr-controls text-sm ptr-muted">
            <StoreBadge name={product.store_name} size="sm" />
            {categoryLabelKey(product.category) && (
              <span className="ptr-badge">{t(categoryLabelKey(product.category)!)}</span>
            )}
            {product.variant_label && (
              <span className="ptr-badge ptr-badge-variant"><bdi>{product.variant_label}</bdi></span>
            )}
            {hasMultipleVariants && !product.variant_label && (
              <span className="ptr-badge ptr-badge-variant">
                <bdi>{t(variantCount >= 11 ? "variant.optionsCountMany" : "variant.optionsCount", { count: formatNumber(variantCount, lang) })}</bdi>
              </span>
            )}
            <span>{formatSubCategory(product.sub_category, lang)}</span>
          </div>
          <h1><bdi>{product.product_title}</bdi></h1>
          {(product.brand || pack) && <p className="ptr-muted"><bdi>{[product.brand, pack].filter(Boolean).join(" · ")}</bdi></p>}
        </div>
      </header>
      {showVariantSelector && (
        <section className="surface ptr-section ptr-variant-section" aria-label={t("variant.selectorTitle")}>
          <div className="ptr-variant-header">
            <h2>{t("variant.selectorTitle")}</h2>
            <span className="ptr-badge ptr-badge-variant">
              <bdi>{t(variantCount >= 11 ? "variant.optionsCountMany" : "variant.optionsCount", { count: formatNumber(variantCount, lang) })}</bdi>
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
                  <span className="ptr-variant-chip-label"><bdi>{chipLabel}</bdi></span>
                  <span className="ptr-variant-chip-meta">
                    <bdi>{formatPrice(variant.current_price, lang)}</bdi>
                    {!variant.in_stock && <span className="ptr-variant-chip-stock"> · {t("card.outOfStock")}</span>}
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
            {t(variantCount >= 11 ? "variant.storeRangeNoteMany" : "variant.storeRangeNote", {
              count: formatNumber(variantCount, lang),
              min: formatPrice(minVarPrice, lang),
              max: formatPrice(maxVarPrice, lang),
            })}
          </bdi>
        </p>
      )}
      <div className="ptr-receipt-layout">
        <aside className="surface ptr-decision">
          <p className="ptr-muted text-sm">{t("detail.current")} · {t(product.in_stock ? "detail.inStock" : "card.outOfStock")}</p>
          <p className="ptr-price ptr-current-price"><bdi>{price}</bdi></p>
          {unit && <p className="text-sm ptr-muted"><bdi>{unit}</bdi></p>}
          {median !== null ? <VerdictBadge verdict={product.discount_verdict} /> : <span className="ptr-badge">
            {t(history.length >= 1 ? "detail.baselineBadge" : "ui.noHistory")}
          </span>}
          {timestamp && live && <p className="text-xs ptr-muted">{t("ui.lastChecked", { time: formatDateTime(timestamp, lang) })}</p>}
          {!product.in_stock && compareReady && <p className="text-sm">{t("ui.outOfStockHint")}</p>}
          {product.scarcity_flag && product.in_stock && <p className="text-sm ptr-muted">{t("card.lowStock")}</p>}
          <div className="ptr-decision-actions">
            {!canVisit && compareReady && <a href="#alternatives" className="ptr-button ptr-primary">{t("ui.viewOffers")}</a>}
            {canVisit && storeLink && <a href={storeLink.url} target="_blank" rel={outboundLinkRel(storeLink.isAffiliate)}
              onClick={() => trackStoreOutbound({
                store: product.store_name,
                product_id: product.product_sk,
                price: product.current_price,
                category: product.category,
                is_affiliate: storeLink.isAffiliate,
                network: storeLink.network,
                placement: "product_hero",
              })}
              className="ptr-button ptr-primary">
              {t("detail.openAtStore", { store: label })} <ExternalLink size={15} aria-hidden="true" />
            </a>}
            {canAlert && <button type="button" disabled={!ready} onClick={() => setAlertOpen(true)}
              className={`ptr-button ${!canVisit && !compareReady ? "ptr-primary" : ""}`}>
              <BellRing size={16} aria-hidden="true" />{t("alert.bellAria")}
            </button>}
            {canVisit && alternatives.length > 0 && <a href="#alternatives" className="ptr-button">{t("ui.viewOffers")}</a>}
            {live && <ShareButton
              title={product.product_title}
              url={absoluteUrl(productHref(product.product_sk))}
              text={timestamp && !stale ? [product.product_title, label, price, takeaway].filter(Boolean).join(" · ") : undefined}
            />}
          </div>
        </aside>
        <section className="surface ptr-section ptr-receipt">
          <h2>{t("ui.receipt")}</h2>
          <dl className="ptr-receipt-rows">
            <div><dt>{t("detail.current")}</dt><dd><bdi>{price}</bdi></dd></div>
            {hasPriceRange && (
              <div>
                <dt>{t("variant.rangeLabel")}</dt>
                <dd className="ptr-variant-range">
                  <bdi>{t("variant.priceRange", { min: formatPrice(minVarPrice, lang), max: formatPrice(maxVarPrice, lang) })}</bdi>
                </dd>
              </div>
            )}
            {product.claimed_original_price !== null && <div><dt>{t("deals.claimedPrice")}</dt>
              <dd><bdi>{formatPrice(product.claimed_original_price, lang)}</bdi></dd></div>}
            {median !== null && <div><dt>{t("detail.median60")}</dt><dd><bdi>{formatPrice(median, lang)}</bdi></dd></div>}
            {product.claimed_discount_pct > 0 && <div><dt>{t("detail.claimedDisc")}</dt>
              <dd><bdi>{formatPctPlain(product.claimed_discount_pct, lang)}</bdi></dd></div>}
          </dl>
          {takeaway && <p className="ptr-notice">{takeaway}</p>}
          {median !== null && <details>
            <summary className="ptr-link">{t("detail.whatMeans")}</summary>
            <p className="ptr-muted text-sm mt-2">{t(`explain.${product.discount_verdict}`)}</p>
          </details>}
          {!sufficientHistory && (
            <p className="text-sm ptr-muted">
              {history.length === 0
                ? t("ui.noHistory")
                : history.length === 1
                  ? t("detail.baselineBody")
                  : t("detail.baselineBodyFew", { count: formatNumber(history.length, lang) })}
            </p>
          )}
        </section>
      </div>
      <section id="alternatives" className="surface ptr-section">
        {alternatives.length > 0 ? (
          <>
            <h2>{t("detail.alternatives")}</h2>
            <AlternativesTable
              alternatives={alternatives}
              category={product.category}
              from={from ?? undefined}
              sample={!live}
              currentOffer={{ price: product.current_price, in_stock: product.in_stock }}
            />
          </>
        ) : similar_alternatives.length > 0 ? (
          <SimilarAlternativesList
            items={similar_alternatives}
            category={product.category}
            from={from ?? undefined}
            sample={!live}
          />
        ) : (
          <>
            <h2>{t("detail.alternatives")}</h2>
            <p className="ptr-muted text-sm">{t("detail.noAlternatives")}</p>
          </>
        )}
      </section>
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
              {t("detail.baselineTitle", { date: formatDate(history[0].snapshot_date, lang) })}
            </p>
            <p>
              {t("detail.baselineRecordedPrice")} · <bdi>{formatPrice(history[0].price, lang)}</bdi>
            </p>
            {history[0].claimed_original_price !== null && (
              <p>
                {t("detail.baselineClaimedPrice")} ·{" "}
                <bdi>{formatPrice(history[0].claimed_original_price, lang)}</bdi>
              </p>
            )}
            <p className="ptr-muted">{t("detail.baselineBody")}</p>
          </div>
        ) : (
          <PriceChart history={history} />
        )}
        {hasHistory && <dl className="ptr-history-extremes">
          <div><dt>{t("detail.allTimeLow")}</dt><dd className="ptr-price"><bdi>{formatPrice(product.min_historical_price, lang)}</bdi></dd></div>
          <div><dt>{t("detail.allTimeHigh")}</dt><dd className="ptr-price"><bdi>{formatPrice(product.max_historical_price, lang)}</bdi></dd></div>
        </dl>}
      </section>
      <AttributesPanel product={product} />
      {canAlert && <PriceAlertModal open={alertOpen} onClose={() => setAlertOpen(false)}
        productKey={product.canonical_product_key ?? product.product_sk} productTitle={product.product_title}
        storeName={product.store_name} currentPrice={product.current_price} />}
    </div>
  );
}
