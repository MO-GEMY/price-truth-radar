"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, BellRing } from "lucide-react";
import type { Product } from "@/types/contract";
import type { DataSource } from "@/lib/api";
import { categoryLabelKey, productHref } from "@/lib/browse-state";
import { formatPackSize, formatPctPlain, formatPrice, formatSubCategory, formatUnitPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { PriceAlertModal } from "./PriceAlertModal";
import { ProductImage } from "./ProductImage";
import { StoreBadge } from "./StoreBadge";
import { VerdictBadge } from "./VerdictBadge";

export function ProductCard({ product, from, source }: { product: Product; from: string; source: DataSource }) {
  const { lang, t } = useLanguage();
  const [alertOpen, setAlertOpen] = useState(false);
  const live = source === "api";
  const unit = formatUnitPrice(product, lang);
  const pack = formatPackSize(product.attributes_json);
  const catKey = categoryLabelKey(product.category);
  const subLabel = product.sub_category && product.sub_category !== "other"
    ? formatSubCategory(product.sub_category, lang)
    : null;
  const delta = product.real_discount_pct;
  const evidence = product.rolling_60d_median <= 0 ? null : Math.abs(delta) < 0.05
    ? t(product.min_historical_price === product.max_historical_price ? "ui.limitedEvidence" : "ui.same")
    : t(delta > 0 ? "ui.below" : "ui.above", { pct: formatPctPlain(Math.abs(delta), lang) });

  return (
    <article className="ptr-list-item">
      <Link className="ptr-list-link" href={productHref(product.product_sk, from, !live)}>
        <div className="ptr-result-identity">
          <ProductImage src={product.image_url} alt="" category={product.category} subCategory={product.sub_category}
            brand={product.brand} className="ptr-thumbnail" fit={product.category === "fashion" ? "cover" : "contain"}
            studio={product.category !== "fashion"} />
          <div className="min-w-0">
            <h3 className="ptr-result-title"><bdi>{product.product_title}</bdi></h3>
            <div className="ptr-controls text-xs ptr-muted">
              <StoreBadge name={product.store_name} size="sm" />
              {catKey && <span className="ptr-badge">{t(catKey)}</span>}
              {subLabel && <span>{subLabel}</span>}
              {pack && <bdi>{pack}</bdi>}
            </div>
          </div>
        </div>
        <div className="ptr-result-price">
          <p className="ptr-price"><bdi>{formatPrice(product.current_price, lang)}</bdi></p>
          {unit && <p className="ptr-muted text-xs"><bdi>{unit}</bdi></p>}
          {!product.in_stock && <p className="ptr-muted text-xs">{t("card.outOfStock")}</p>}
        </div>
        <div className="ptr-result-evidence">
          <VerdictBadge verdict={product.discount_verdict} size="sm" />
          {evidence && <p className="ptr-muted text-xs">{evidence}</p>}
        </div>
        <span className="ptr-result-action">{t("deals.viewTruth")} <ArrowUpRight size={14} aria-hidden="true" /></span>
      </Link>
      {live && product.current_price > 0.01 && <>
        <button type="button" className="ptr-icon-button ptr-card-alert" onClick={() => setAlertOpen(true)}
          aria-label={`${t("alert.bellAria")} · ${product.product_title}`}>
          <BellRing size={16} aria-hidden="true" />
        </button>
        <PriceAlertModal open={alertOpen} onClose={() => setAlertOpen(false)} productKey={product.canonical_product_key ?? product.product_sk}
          productTitle={product.product_title} storeName={product.store_name} currentPrice={product.current_price} />
      </>}
    </article>
  );
}
