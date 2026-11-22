"use client";

import Link from "next/link";
import { ArrowRight, ArrowLeftRight, Crown, PiggyBank } from "lucide-react";
import type { CrossStoreMatch } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { formatNumber, formatPctPlain, formatPrice } from "@/lib/format";
import { storeDisplayName } from "@/lib/stores";
import { StoreBadge } from "./StoreBadge";

function SpotlightCard({ match }: { match: CrossStoreMatch }) {
  const { lang, t } = useLanguage();
  const highestStore =
    match.listings_json.find((l) => l.price === match.highest_price)?.store_name ?? "";

  return (
    <Link
      href="/compare"
      className="surface surface-hover group flex min-w-0 flex-col justify-between rounded-2xl p-4 sm:p-5"
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5 text-[11px] font-semibold text-slate-300">
            <span className="num text-emerald-300">
              {t("compare.storesCount", { count: formatNumber(match.stores_count, lang) })}
            </span>
          </span>
          <span className="num inline-flex items-center gap-1 rounded-full border border-emerald-400/35 bg-emerald-500/14 px-2.5 py-0.5 text-xs font-bold text-emerald-300">
            <PiggyBank className="size-3.5 shrink-0" />
            {t("spotlight.save", {
              amount: formatPrice(match.price_spread_egp, lang, { maximumFractionDigits: 0 }),
            })}
            <span className="text-emerald-200/80">
              ({formatPctPlain(match.price_spread_pct, lang, 0)})
            </span>
          </span>
        </div>

        <h3
          dir="auto"
          className="line-clamp-2 min-h-10 text-sm font-bold leading-snug text-slate-100 transition group-hover:text-white"
        >
          {match.product_title_clean}
        </h3>
      </div>

      {/* Lowest vs Highest compact comparison well */}
      <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl border border-white/[0.06] bg-[#040810]/70 p-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-emerald-400">
            <Crown className="size-3 shrink-0" />
            {t("spotlight.from")}
          </p>
          <p className="num mt-1 truncate text-base font-extrabold text-emerald-300">
            {formatPrice(match.lowest_price, lang, { maximumFractionDigits: 0 })}
          </p>
          <div className="mt-1.5">
            <StoreBadge name={match.lowest_price_store} size="sm" />
          </div>
        </div>

        <div className="min-w-0 border-s border-white/[0.07] ps-2.5">
          <p className="text-[10px] font-bold uppercase tracking-wide text-slate-500">
            {t("spotlight.upTo")}
          </p>
          <p className="num mt-1 truncate text-base font-bold text-slate-300">
            {formatPrice(match.highest_price, lang, { maximumFractionDigits: 0 })}
          </p>
          <p className="mt-2 truncate text-[11px] font-medium text-slate-400">
            {highestStore ? storeDisplayName(highestStore, lang) : "—"}
          </p>
        </div>
      </div>
    </Link>
  );
}

export function CompareSpotlight({
  matches,
  total,
}: {
  matches: CrossStoreMatch[];
  total: number;
}) {
  const { lang, t } = useLanguage();
  if (matches.length === 0) return null;

  return (
    <section aria-labelledby="spotlight-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.16em] text-emerald-400">
            <ArrowLeftRight className="size-3.5" />
            {t("spotlight.overline")}
          </p>
          <h2
            id="spotlight-heading"
            className="mt-1 text-lg font-extrabold tracking-tight text-white sm:text-xl"
          >
            {t("spotlight.title")}
          </h2>
        </div>

        <Link
          href="/compare"
          className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3.5 py-1.5 text-xs font-bold text-emerald-300 transition hover:border-emerald-400/50 hover:bg-emerald-500/18 sm:text-sm"
        >
          <span>{t("spotlight.cta", { count: formatNumber(total, lang) })}</span>
          <ArrowRight className="size-3.5 shrink-0 rtl:rotate-180" />
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
        {matches.map((match) => (
          <SpotlightCard key={match.canonical_product_key} match={match} />
        ))}
      </div>
    </section>
  );
}
