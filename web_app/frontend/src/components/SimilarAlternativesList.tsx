"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import type { Category, SimilarAlternative } from "@/types/contract";
import { productHref } from "@/lib/browse-state";
import { formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { buildAffiliateUrl, outboundLinkRel } from "@/lib/affiliate";
import { trackStoreOutbound } from "@/lib/analytics";
import { retailerHref } from "@/lib/offers";
import { storeDisplayName } from "@/lib/stores";
import { ProductImage } from "./ProductImage";
import { StoreBadge } from "./StoreBadge";

export function SimilarAlternativesList({
  items,
  category,
  from,
  sample = false,
}: {
  items: SimilarAlternative[];
  category: Category;
  from?: string;
  sample?: boolean;
}) {
  const { lang, t } = useLanguage();

  return (
    <div className="ptr-similar-wrap">
      <div className="ptr-similar-header">
        <h2>{t("similar.title")}</h2>
        <span className="ptr-badge ptr-badge-variant">{t("similar.badge")}</span>
      </div>
      <p className="ptr-muted text-sm">{t("similar.subtitle")}</p>
      <ul className="ptr-offers ptr-similar-list">
        {items.map((item) => {
          const safeUrl = retailerHref(item.product_url);
          const storeLink = safeUrl ? buildAffiliateUrl(safeUrl, item.store_name) : null;
          const diffAbs = Math.abs(item.price_diff_egp);
          const isCheaper = item.price_diff_egp <= -1;
          const isHigher = item.price_diff_egp >= 1;
          return (
            <li key={item.product_sk} className="ptr-similar-row">
              <div className="ptr-similar-identity">
                <ProductImage
                  src={item.image_url}
                  alt=""
                  category={category}
                  className="ptr-similar-thumb"
                  fit={category === "fashion" ? "cover" : "contain"}
                  studio={category !== "fashion"}
                />
                <div className="min-w-0 space-y-1">
                  <Link
                    href={productHref(item.product_sk, from, sample)}
                    className="ptr-similar-title"
                  >
                    <bdi>{item.title}</bdi>
                  </Link>
                  <div className="ptr-controls text-xs ptr-muted">
                    <StoreBadge name={item.store_name} size="sm" />
                    <span>{t(item.in_stock ? "detail.inStock" : "card.outOfStock")}</span>
                  </div>
                </div>
              </div>
              <div className="ptr-similar-price">
                <p className="ptr-price">
                  <bdi>{formatPrice(item.current_price, lang)}</bdi>
                </p>
                {isCheaper ? (
                  <span className="ptr-badge ptr-badge-good">
                    <bdi>{t("similar.cheaper", { amount: formatPrice(diffAbs, lang) })}</bdi>
                  </span>
                ) : isHigher ? (
                  <span className="ptr-badge">
                    <bdi>{t("similar.moreExpensive", { amount: formatPrice(diffAbs, lang) })}</bdi>
                  </span>
                ) : (
                  <span className="ptr-badge">{t("similar.samePrice")}</span>
                )}
              </div>
              <div className="ptr-controls ptr-similar-actions">
                <Link
                  className="ptr-button ptr-small-button"
                  href={productHref(item.product_sk, from, sample)}
                >
                  {t("similar.viewDetails")}
                </Link>
                {!sample && storeLink && item.in_stock && (
                  <a
                    className="ptr-button ptr-small-button"
                    href={storeLink.url}
                    target="_blank"
                    rel={outboundLinkRel(storeLink.isAffiliate)}
                    onClick={() => trackStoreOutbound({
                      store: item.store_name,
                      product_id: item.product_sk,
                      price: item.current_price,
                      category,
                      is_affiliate: storeLink.isAffiliate,
                      network: storeLink.network,
                      placement: "similar_alternatives",
                    })}
                    aria-label={t("detail.openAtStore", {
                      store: storeDisplayName(item.store_name, lang),
                    })}
                  >
                    {t("detail.openAtStoreGeneric")} <ExternalLink size={13} aria-hidden="true" />
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
