"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, BellRing } from "lucide-react";
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
import { hasSufficientPriceHistory } from "@/lib/verdicts";
import { PriceAlertModal } from "./PriceAlertModal";
import { ProductImage } from "./ProductImage";
import { StoreBadge } from "./StoreBadge";
import { VerdictBadge } from "./VerdictBadge";

export function ProductCard({
  product,
  from,
  source,
  view = "list",
}: {
  product: Product;
  from: string;
  source: DataSource;
  view?: "list" | "grid";
}) {
  const { lang, t } = useLanguage();
  const [alertOpen, setAlertOpen] = useState(false);
  const live = source === "api";
  const unit = formatUnitPrice(product, lang);
  const pack = formatPackSize(product.attributes_json);
  const catKey = categoryLabelKey(product.category);
  const subLabel =
    product.sub_category && product.sub_category !== "other"
      ? formatSubCategory(product.sub_category, lang)
      : null;
  const delta = product.real_discount_pct;
  const sufficientHistory = hasSufficientPriceHistory(product);
  const evidence =
    !sufficientHistory || product.rolling_60d_median <= 0
      ? null
      : Math.abs(delta) < 0.05
        ? t("ui.same")
        : t(delta > 0 ? "ui.below" : "ui.above", {
            pct: formatPctPlain(Math.abs(delta), lang),
          });
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
      <article className="asarak-grid-card group">
        {live && product.current_price > 0.01 && (
          <button
            type="button"
            className="ptr-icon-button asarak-grid-card__alert"
            onClick={() => setAlertOpen(true)}
            aria-label={`${t("alert.bellAria")} · ${product.product_title}`}
            title={t("alert.bellAria")}
          >
            <BellRing size={15} aria-hidden="true" />
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

            <h3 className="ptr-result-title asarak-grid-card__title">
              <bdi>{product.product_title}</bdi>
            </h3>

            {(subLabel || pack) && (
              <p className="text-xs ptr-muted truncate">
                {[subLabel, pack].filter(Boolean).join(" · ")}
              </p>
            )}

            <div className="space-y-1">
              {sufficientHistory ? (
                <VerdictBadge verdict={product.discount_verdict} size="sm" />
              ) : (
                <span className="ptr-badge">{t("detail.baselineBadge")}</span>
              )}
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
                      <span className="ptr-strike ptr-mono text-xs">
                        <bdi>
                          {formatPrice(product.claimed_original_price, lang)}
                        </bdi>
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
            productKey={product.canonical_product_key ?? product.product_sk}
            productTitle={product.product_title}
            storeName={product.store_name}
            currentPrice={product.current_price}
          />
        )}
      </article>
    );
  }

  return (
    <article className="ptr-list-item">
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
            <h3 className="ptr-result-title">
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
                <p className="ptr-strike ptr-mono text-xs">
                  <bdi>{formatPrice(product.claimed_original_price, lang)}</bdi>
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
          {sufficientHistory ? (
            <VerdictBadge verdict={product.discount_verdict} size="sm" />
          ) : (
            <span className="ptr-badge">{t("detail.baselineBadge")}</span>
          )}
          {evidence && <p className="ptr-muted text-xs">{evidence}</p>}
        </div>
        <span className="ptr-result-action">
          {t("deals.viewTruth")} <ArrowUpRight size={14} aria-hidden="true" />
        </span>
      </Link>
      {live && product.current_price > 0.01 && (
        <>
          <button
            type="button"
            className="ptr-icon-button ptr-card-alert"
            onClick={() => setAlertOpen(true)}
            aria-label={`${t("alert.bellAria")} · ${product.product_title}`}
            title={t("alert.bellAria")}
          >
            <BellRing size={16} aria-hidden="true" />
          </button>
          <PriceAlertModal
            open={alertOpen}
            onClose={() => setAlertOpen(false)}
            productKey={product.canonical_product_key ?? product.product_sk}
            productTitle={product.product_title}
            storeName={product.store_name}
            currentPrice={product.current_price}
          />
        </>
      )}
    </article>
  );
}
