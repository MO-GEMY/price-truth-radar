"use client";

import Link from "next/link";
import { Check, Crown, ExternalLink, X } from "lucide-react";
import type { AlternativeListing } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { formatPrice } from "@/lib/format";
import { storeDisplayName } from "@/lib/stores";
import { VerdictBadge } from "./VerdictBadge";
import { StoreBadge } from "./StoreBadge";

/** Cross-store alternatives for the same canonical product (§5.5). */
export function AlternativesTable({
  alternatives,
  currentPrice,
}: {
  alternatives: AlternativeListing[];
  currentPrice?: number;
}) {
  const { lang, t } = useLanguage();
  const allPrices = [
    ...alternatives.map((a) => a.price),
    ...(currentPrice !== undefined ? [currentPrice] : []),
  ];
  const minPrice = Math.min(...allPrices);
  const maxPrice = Math.max(...allPrices);
  const span = Math.max(maxPrice - minPrice, 0);

  return (
    <ul className="space-y-2.5">
      {alternatives.map((alt) => {
        const isCheapest = alt.price === minPrice;
        const delta = alt.price - minPrice;
        const pct =
          span > 0
            ? Math.max(8, Math.min(100, Math.round(((alt.price - minPrice) / span) * 100)))
            : 8;

        return (
          <li
            key={alt.product_sk}
            className={`grid grid-cols-1 gap-3 rounded-xl border p-3.5 transition sm:grid-cols-12 sm:items-center sm:gap-4 ${
              isCheapest
                ? "border-emerald-400/30 bg-emerald-500/[0.06]"
                : "border-white/[0.07] bg-white/[0.02] hover:border-white/15"
            }`}
          >
            {/* Price Position */}
            <div className="space-y-1.5 sm:col-span-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5">
                  <StoreBadge name={alt.store_name} size="sm" />
                  {isCheapest ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-400/45 bg-emerald-500/18 px-2 py-0.5 text-[10px] font-bold text-emerald-200">
                      <Crown className="size-3" />
                      {t("detail.cheapest")}
                    </span>
                  ) : null}
                </span>
                <span className="num text-sm font-extrabold text-white">
                  {formatPrice(alt.price, lang)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.08]">
                  <div
                    className={`h-full rounded-full ${
                      isCheapest ? "bg-emerald-400" : "bg-slate-400/70"
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                {delta > 0 ? (
                  <span className="num shrink-0 text-[10px] font-medium text-slate-400">
                    {t("compare.aboveLowest", {
                      amount: formatPrice(delta, lang, { maximumFractionDigits: 0 }),
                    })}
                  </span>
                ) : null}
              </div>
            </div>

            {/* Discount Honesty */}
            <div className="flex flex-wrap items-center gap-2 sm:col-span-4">
              <VerdictBadge verdict={alt.discount_verdict} size="sm" showInfo />
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-semibold ${
                  alt.in_stock ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {alt.in_stock ? (
                  <>
                    <Check className="size-3" />
                    {t("detail.inStock")}
                  </>
                ) : (
                  <>
                    <X className="size-3" />
                    {t("card.outOfStock")}
                  </>
                )}
              </span>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-2 sm:col-span-3">
              <Link
                href={`/products/${alt.product_sk}`}
                className="rounded-lg border border-teal-400/30 bg-teal-400/10 px-3 py-1.5 text-xs font-semibold text-teal-200 transition hover:bg-teal-400/20"
              >
                {t("detail.viewLocal")}
              </Link>
              <a
                href={alt.product_url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${storeDisplayName(alt.store_name, lang)} — ${t("detail.openAtStoreGeneric")}`}
                className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition hover:border-white/25 hover:text-white"
              >
                <ExternalLink className="size-3.5" />
              </a>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
