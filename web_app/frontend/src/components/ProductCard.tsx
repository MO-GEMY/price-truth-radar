"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, BellRing, Check } from "lucide-react";
import type { Product } from "@/types/contract";
import type { DataSource } from "@/lib/api";
import { categoryLabelKey, productHref } from "@/lib/browse-state";
import {
  formatNumber,
  formatPackSize,
  formatPctPlain,
  formatPrice,
  formatSubCategory,
  formatUnitPrice,
} from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { useSavedAlerts } from "@/lib/saved-alerts";
import {
  formatTrackedDays,
  getHistoryMaturity,
  getTrackedDaysCount,
  getVerifiedMedian,
} from "@/lib/verdicts";
import { PriceAlertModal } from "./PriceAlertModal";
import { ProductImage } from "./ProductImage";
import { StoreBadge } from "./StoreBadge";
import { VerdictBadge } from "./VerdictBadge";

export function ProductCard({
  product,
  from,
  source,
  view = "grid",
  tourTarget = false,
}: {
  product: Product;
  from: string;
  source: DataSource;
  view?: "list" | "grid";
  tourTarget?: boolean;
}) {
  const { lang, t } = useLanguage();
  const { hydrated: alertsHydrated, getAlertForProduct } = useSavedAlerts();
  const [alertOpen, setAlertOpen] = useState(false);
  const live = source === "api";
  const productKey = product.canonical_product_key ?? product.product_sk;
  const savedAlert = alertsHydrated
    ? getAlertForProduct({
        product_sk: product.product_sk,
        product_key: productKey,
        store_name: product.store_name,
      })
    : null;
  const alertActive = Boolean(savedAlert);
  const unit = formatUnitPrice(product, lang);
  const pack = formatPackSize(product.attributes_json);
  const catKey = categoryLabelKey(product.category);
  const subLabel =
    product.sub_category && product.sub_category !== "other"
      ? formatSubCategory(product.sub_category, lang)
      : null;
  const delta = product.real_discount_pct;
  const trackedDays = getTrackedDaysCount(product);
  const historyMaturity = getHistoryMaturity(product);
  const sufficientHistory = historyMaturity !== "EARLY";
  const verifiedMedian = getVerifiedMedian(product);
  const trackedDaysLabel = formatTrackedDays(trackedDays, lang);
  const marketBenchmark = product.market_benchmark ?? null;
  const evidence =
    sufficientHistory && verifiedMedian !== null
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
      : marketBenchmark &&
          marketBenchmark.status === "CHEAPEST_IN_MARKET" &&
          (marketBenchmark.savings_vs_next_cheapest_egp ?? 0) >= 1
        ? t("market.cheaperBy", {
            amount: formatPrice(
              marketBenchmark.savings_vs_next_cheapest_egp ?? 0,
              lang,
            ),
            count: formatNumber(marketBenchmark.stores_count, lang),
          })
        : !sufficientHistory && product.claimed_discount_pct > 0
          ? t("maturity.claimedUnverified")
          : null;

  const badgeNode = sufficientHistory ? (
    <VerdictBadge verdict={product.discount_verdict} size="sm" />
  ) : marketBenchmark?.status === "CHEAPEST_IN_MARKET" ? (
    <span className="ptr-badge ptr-badge-good">
      {t("market.cheapestBadge")}
    </span>
  ) : marketBenchmark?.status === "TIED_CHEAPEST" ? (
    <span className="ptr-badge ptr-badge-good">
      {t("market.tiedCheapestBadge")}
    </span>
  ) : marketBenchmark?.status === "ABOVE_MARKET" ? (
    <span className="ptr-badge ptr-badge-amber">
      <bdi>
        {t("market.aboveBadge", {
          amount: formatPrice(marketBenchmark.price_diff_vs_cheapest_egp, lang),
        })}
      </bdi>
    </span>
  ) : product.discount_verdict === "RECENT_DROP" ||
    product.discount_verdict === "RECENT_HIKE" ? (
    <VerdictBadge verdict={product.discount_verdict} size="sm" />
  ) : (
    <span className="ptr-badge">
      {t("maturity.earlyBadge", { days: trackedDaysLabel })}
    </span>
  );
  const variantCount = Math.max(1, product.variant_count ?? 1);
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
  const showClaimedStrike =
    !hasPriceRange &&
    product.claimed_original_price !== null &&
    product.claimed_original_price > product.current_price + 0.5;
  const href = productHref(product.product_sk, from, !live);

  if (view === "grid") {
    return (
      <article
        className="asarak-grid-card group"
        data-tour={tourTarget ? "product-card" : undefined}
      >
        {live && product.current_price > 0.01 && (
          <button
            type="button"
            className={`ptr-icon-button asarak-grid-card__alert${alertActive ? " ptr-alert-btn--active" : ""}`}
            aria-pressed={alertActive}
            onClick={() => setAlertOpen(true)}
            aria-label={`${t(alertActive ? "alert.activeAria" : "alert.bellAria")} · ${product.product_title}`}
            title={t(alertActive ? "alert.activeButton" : "alert.bellAria")}
          >
            {alertActive ? (
              <span className="ptr-bell-active-icon" aria-hidden="true">
                <BellRing size={15} />
                <Check size={9} strokeWidth={3} className="ptr-bell-active-check" />
              </span>
            ) : (
              <BellRing size={15} aria-hidden="true" />
            )}
          </button>
        )}

        <Link className="asarak-grid-card__link" href={href}>
          <div className="asarak-grid-card__media">
            <ProductImage
              src={product.image_url}
              alt=""
              category={product.category}
              subCategory={product.sub_category}
              brand={product.brand}
              className="asarak-grid-card__thumb"
              fit={product.category === "fashion" ? "cover" : "contain"}
              studio={product.category !== "fashion"}
              zoomOnGroupHover
            />
          </div>

          <div className="asarak-grid-card__body">
            <div className="ptr-controls text-xs ptr-muted">
              <StoreBadge name={product.store_name} size="sm" />
              {catKey && <span className="ptr-badge">{t(catKey)}</span>}
              {hasMultipleVariants && (
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
            </div>

            <h3 className="ptr-result-title asarak-grid-card__title" dir="auto">
              <bdi>{product.product_title}</bdi>
            </h3>

            {(subLabel || pack) && (
              <p className="text-xs ptr-muted truncate">
                {[subLabel, pack].filter(Boolean).join(" · ")}
              </p>
            )}

            <div className="space-y-1">
              {badgeNode}
              {evidence && <p className="ptr-muted text-xs">{evidence}</p>}
            </div>

            <div className="asarak-grid-card__footer">
              <div className="min-w-0">
                {hasPriceRange ? (
                  <>
                    <p className="ptr-price">
                      <bdi>
                        {t("variant.fromPrice", {
                          price: formatPrice(minVarPrice, lang),
                        })}
                      </bdi>
                    </p>
                    <p className="ptr-muted text-xs ptr-variant-range">
                      <bdi>
                        {t("variant.priceRange", {
                          min: formatPrice(minVarPrice, lang),
                          max: formatPrice(maxVarPrice, lang),
                        })}
                      </bdi>
                    </p>
                  </>
                ) : (
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <p className="ptr-price">
                      <bdi>{formatPrice(product.current_price, lang)}</bdi>
                    </p>
                    {showClaimedStrike && product.claimed_original_price && (
                      <span
                        className="ptr-claimed-ref"
                        title={t("card.listedRefTitle")}
                      >
                        <span className="ptr-claimed-ref__tag">
                          {t("card.listedRef")}
                        </span>
                        <span className="ptr-strike ptr-mono text-xs">
                          <bdi>
                            {formatPrice(product.claimed_original_price, lang)}
                          </bdi>
                        </span>
                      </span>
                    )}
                  </div>
                )}
                {unit && (
                  <p className="ptr-muted text-xs">
                    <bdi>{unit}</bdi>
                  </p>
                )}
                {!product.in_stock && (
                  <p className="ptr-muted text-xs">{t("card.outOfStock")}</p>
                )}
              </div>

              <span className="ptr-result-action shrink-0">
                {t("card.viewTruth")}
                <ArrowUpRight size={14} aria-hidden="true" />
              </span>
            </div>
          </div>
        </Link>

        {live && product.current_price > 0.01 && (
          <PriceAlertModal
            open={alertOpen}
            onClose={() => setAlertOpen(false)}
            productKey={productKey}
            productSk={product.product_sk}
            productTitle={product.product_title}
            imageUrl={product.image_url}
            category={product.category}
            storeName={product.store_name}
            currentPrice={product.current_price}
            existingAlert={savedAlert}
          />
        )}
      </article>
    );
  }

  return (
    <article
      className="ptr-list-item"
      data-tour={tourTarget ? "product-card" : undefined}
    >
      <Link className="ptr-list-link" href={href}>
        <div className="ptr-result-identity">
          <ProductImage
            src={product.image_url}
            alt=""
            category={product.category}
            subCategory={product.sub_category}
            brand={product.brand}
            className="ptr-thumbnail"
            fit={product.category === "fashion" ? "cover" : "contain"}
            studio={product.category !== "fashion"}
          />
          <div className="min-w-0">
            <h3 className="ptr-result-title" dir="auto">
              <bdi>{product.product_title}</bdi>
            </h3>
            <div className="ptr-controls text-xs ptr-muted">
              <StoreBadge name={product.store_name} size="sm" />
              {catKey && <span className="ptr-badge">{t(catKey)}</span>}
              {hasMultipleVariants && (
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
              {subLabel && <span>{subLabel}</span>}
              {pack && <bdi>{pack}</bdi>}
            </div>
          </div>
        </div>
        <div className="ptr-result-price">
          {hasPriceRange ? (
            <>
              <p className="ptr-price">
                <bdi>
                  {t("variant.fromPrice", {
                    price: formatPrice(minVarPrice, lang),
                  })}
                </bdi>
              </p>
              <p className="ptr-muted text-xs ptr-variant-range">
                <bdi>
                  {t("variant.priceRange", {
                    min: formatPrice(minVarPrice, lang),
                    max: formatPrice(maxVarPrice, lang),
                  })}
                </bdi>
              </p>
            </>
          ) : (
            <>
              <p className="ptr-price">
                <bdi>{formatPrice(product.current_price, lang)}</bdi>
              </p>
              {showClaimedStrike && product.claimed_original_price && (
                <p
                  className="ptr-claimed-ref"
                  title={t("card.listedRefTitle")}
                >
                  <span className="ptr-claimed-ref__tag">
                    {t("card.listedRef")}
                  </span>
                  <span className="ptr-strike ptr-mono text-xs">
                    <bdi>{formatPrice(product.claimed_original_price, lang)}</bdi>
                  </span>
                </p>
              )}
            </>
          )}
          {unit && (
            <p className="ptr-muted text-xs">
              <bdi>{unit}</bdi>
            </p>
          )}
          {!product.in_stock && (
            <p className="ptr-muted text-xs">{t("card.outOfStock")}</p>
          )}
        </div>
        <div className="ptr-result-evidence">
          {badgeNode}
          {evidence && <p className="ptr-muted text-xs">{evidence}</p>}
        </div>
        <span className="ptr-result-action">
          <span className="ptr-result-action__desktop">{t("deals.viewTruth")}</span>
          <span className="ptr-result-action__mobile">{t("card.mobileInspect")}</span>
          <ArrowUpRight size={14} aria-hidden="true" />
        </span>
      </Link>
      {live && product.current_price > 0.01 && (
        <>
          <button
            type="button"
            className={`ptr-icon-button ptr-card-alert${alertActive ? " ptr-alert-btn--active" : ""}`}
            aria-pressed={alertActive}
            onClick={() => setAlertOpen(true)}
            aria-label={`${t(alertActive ? "alert.activeAria" : "alert.bellAria")} · ${product.product_title}`}
            title={t(alertActive ? "alert.activeButton" : "alert.bellAria")}
          >
            {alertActive ? (
              <span className="ptr-bell-active-icon" aria-hidden="true">
                <BellRing size={16} />
                <Check size={9} strokeWidth={3} className="ptr-bell-active-check" />
              </span>
            ) : (
              <BellRing size={16} aria-hidden="true" />
            )}
          </button>
          <PriceAlertModal
            open={alertOpen}
            onClose={() => setAlertOpen(false)}
            productKey={productKey}
            productSk={product.product_sk}
            productTitle={product.product_title}
            imageUrl={product.image_url}
            category={product.category}
            storeName={product.store_name}
            currentPrice={product.current_price}
            existingAlert={savedAlert}
          />
        </>
      )}
    </article>
  );
}
