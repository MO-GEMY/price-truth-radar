"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import type { AlternativeListing } from "@/types/contract";
import { productHref } from "@/lib/browse-state";
import { formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { buildAffiliateUrl, outboundLinkRel } from "@/lib/affiliate";
import { trackStoreOutbound } from "@/lib/analytics";
import { lowestAvailablePrice, retailerHref, sortOffers, type OfferPrice } from "@/lib/offers";
import { storeDisplayName } from "@/lib/stores";
import { StoreBadge } from "./StoreBadge";
import { VerdictBadge } from "./VerdictBadge";

export function AlternativesTable({
  alternatives, currentOffer, category, from, sample = false,
}: {
  alternatives: AlternativeListing[];
  currentOffer?: OfferPrice;
  category?: string;
  from?: string;
  sample?: boolean;
}) {
  const { lang, t } = useLanguage();
  const ordered = sortOffers(alternatives);
  const lowest = lowestAvailablePrice(currentOffer ? [...alternatives, currentOffer] : alternatives);
  return (
    <ul className="ptr-offers">
      {ordered.map((offer) => {
        const cheapest = offer.in_stock && offer.price === lowest;
        const delta = offer.in_stock && lowest !== null ? offer.price - lowest : null;
        const safeUrl = retailerHref(offer.product_url);
        const storeLink = safeUrl ? buildAffiliateUrl(safeUrl, offer.store_name) : null;
        return (
          <li key={offer.product_sk} className="ptr-offer">
            <div className="min-w-0 space-y-1">
              <StoreBadge name={offer.store_name} size="sm" />
              <p className="ptr-muted text-xs">{t(offer.in_stock ? "detail.inStock" : "card.outOfStock")}</p>
            </div>
            <div className="min-w-0 space-y-1">
              <p className="ptr-price"><bdi>{formatPrice(offer.price, lang)}</bdi></p>
              {offer.unit_price_egp != null && offer.unit_price_unit && (
                <p className="text-xs ptr-muted"><bdi>{formatPrice(offer.unit_price_egp, lang)} / {offer.unit_price_unit}</bdi></p>
              )}
              {cheapest && <span className="ptr-badge ptr-badge-good">{t("ui.lowestAvailable")}</span>}
              {delta !== null && delta > 0 && <p className="text-xs ptr-muted">
                {t("compare.aboveLowest", { amount: formatPrice(delta, lang) })}
              </p>}
            </div>
            <VerdictBadge verdict={offer.discount_verdict} size="sm" />
            <div className="ptr-controls">
              <Link className="ptr-button ptr-small-button" href={productHref(offer.product_sk, from, sample)}>{t("detail.viewLocal")}</Link>
              {!sample && storeLink && offer.in_stock && <a className="ptr-button ptr-small-button" href={storeLink.url}
                target="_blank" rel={outboundLinkRel(storeLink.isAffiliate)}
                onClick={() => trackStoreOutbound({
                  store: offer.store_name,
                  product_id: offer.product_sk,
                  price: offer.price,
                  category,
                  is_affiliate: storeLink.isAffiliate,
                  network: storeLink.network,
                  placement: "alternatives_table",
                })}
                aria-label={t("detail.openAtStore", { store: storeDisplayName(offer.store_name, lang) })}>
                {t("detail.openAtStoreGeneric")} <ExternalLink size={13} aria-hidden="true" />
              </a>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
