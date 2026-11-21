"use client";

import Link from "next/link";
import { Check, Crown, ExternalLink, X } from "lucide-react";
import type { AlternativeListing } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { formatPrice } from "@/lib/format";
import { VerdictBadge } from "./VerdictBadge";
import { StoreBadge } from "./StoreBadge";

/** Cross-store alternatives for the same canonical product (§5.5). */
export function AlternativesTable({ alternatives }: { alternatives: AlternativeListing[] }) {
  const { lang, t } = useLanguage();
  const cheapest = Math.min(...alternatives.map((a) => a.price));

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-start text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-slate-500">
            <th className="px-3 py-2 text-start font-semibold">{t("detail.store")}</th>
            <th className="px-3 py-2 text-start font-semibold">{t("detail.price")}</th>
            <th className="px-3 py-2 text-start font-semibold">{t("filters.verdict")}</th>
            <th className="px-3 py-2 text-start font-semibold">{t("detail.stock")}</th>
            <th className="px-3 py-2 text-end font-semibold"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.06]">
          {alternatives.map((alt) => {
            const isCheapest = alt.price === cheapest;
            return (
              <tr
                key={alt.product_sk}
                className={`transition-colors hover:bg-white/[0.03] ${
                  isCheapest ? "bg-emerald-500/[0.05]" : ""
                }`}
              >
                <td className="px-3 py-3">
                  <span className="inline-flex items-center gap-2">
                    <StoreBadge name={alt.store_name} size="sm" />
                    {isCheapest ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/12 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                        <Crown className="size-3" />
                        {t("detail.cheapest")}
                      </span>
                    ) : null}
                  </span>
                </td>
                <td className="num px-3 py-3 font-bold text-white">
                  {formatPrice(alt.price, lang)}
                </td>
                <td className="px-3 py-3">
                  <VerdictBadge verdict={alt.discount_verdict} size="sm" />
                </td>
                <td className="px-3 py-3">
                  {alt.in_stock ? (
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                      <Check className="size-3.5" />
                      {t("detail.inStock")}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-rose-400">
                      <X className="size-3.5" />
                      {t("card.outOfStock")}
                    </span>
                  )}
                </td>
                <td className="px-3 py-3">
                  <span className="flex items-center justify-end gap-2">
                    <Link
                      href={`/products/${alt.product_sk}`}
                      className="rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-xs font-semibold text-cyan-300 transition hover:bg-cyan-400/20"
                    >
                      {t("detail.viewLocal")}
                    </Link>
                    <a
                      href={alt.product_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`${alt.store_name} — ${t("detail.openAtStore")}`}
                      className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition hover:border-white/25 hover:text-white"
                    >
                      <ExternalLink className="size-3.5" />
                    </a>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
