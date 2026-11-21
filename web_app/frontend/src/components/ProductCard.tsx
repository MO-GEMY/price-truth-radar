"use client";

/* eslint-disable @next/next/no-img-element */

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Flame, PackageOpen, PackageX, ShieldAlert } from "lucide-react";
import type { Product } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { formatDate, formatPct, formatPctPlain, formatPrice } from "@/lib/format";
import { VerdictBadge } from "./VerdictBadge";
import { StoreBadge } from "./StoreBadge";

/** Chip style for the real-discount figure vs the 60-day median. */
function realDiscountChipClass(real: number): string {
  if (real >= 10) return "border-emerald-500/40 bg-emerald-500/12 text-emerald-300";
  if (real >= 5) return "border-teal-500/40 bg-teal-500/12 text-teal-300";
  if (real >= 0) return "border-slate-500/40 bg-slate-500/10 text-slate-300";
  return "border-rose-500/40 bg-rose-500/12 text-rose-300";
}

export function ProductCard({ product }: { product: Product }) {
  const { lang, t } = useLanguage();
  const [imgError, setImgError] = useState(false);
  const showImg = product.image_url !== null && !imgError;

  const gap = product.claimed_discount_pct - Math.max(product.real_discount_pct, 0);
  const showInflation =
    product.claimed_discount_pct >= 10 && product.real_discount_pct < 3 && gap >= 10;

  return (
    <Link
      href={`/products/${product.product_sk}`}
      className="group glass relative flex flex-col overflow-hidden rounded-2xl transition-all duration-200 hover:-translate-y-0.5 hover:border-cyan-400/35 hover:shadow-[0_10px_40px_rgba(34,211,238,0.12)]"
    >
      {/* Image area with overlays */}
      <div className="relative h-40 overflow-hidden bg-slate-800/40">
        {showImg ? (
          <img
            src={product.image_url as string}
            alt={product.product_title}
            loading="lazy"
            onError={() => setImgError(true)}
            className={`h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04] ${
              product.in_stock ? "" : "opacity-40 saturate-0"
            }`}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-slate-800/60 to-slate-900/60">
            <PackageOpen className="size-10 text-slate-600" />
          </div>
        )}

        <span className="absolute start-2.5 top-2.5">
          <StoreBadge name={product.store_name} size="sm" />
        </span>
        <span className="absolute end-2.5 top-2.5">
          <VerdictBadge verdict={product.discount_verdict} size="sm" />
        </span>

        <span className="absolute bottom-2.5 start-2.5 flex flex-wrap gap-1.5">
          {product.scarcity_flag ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-[#0a0f1c]/90 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
              <Flame className="size-3" />
              {t("card.lowStock")}
            </span>
          ) : null}
          {!product.in_stock ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/40 bg-[#0a0f1c]/90 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
              <PackageX className="size-3" />
              {t("card.outOfStock")}
            </span>
          ) : null}
        </span>
      </div>

      {/* Body */}
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-snug text-slate-100 group-hover:text-white">
            {product.product_title}
          </h3>
          <p className="mt-1 text-[11px] text-slate-500">
            {product.brand} · {product.sub_category.replace(/_/g, " ")}
          </p>
        </div>

        <div className="mt-auto space-y-2.5">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="num text-xl font-bold tracking-tight text-white">
              {formatPrice(product.current_price, lang)}
            </span>
            {product.claimed_original_price !== null ? (
              <span className="num text-xs font-medium text-slate-500 line-through">
                {formatPrice(product.claimed_original_price, lang)}
              </span>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {product.claimed_discount_pct > 0 ? (
              <span className="num inline-flex items-center rounded-md border border-slate-500/40 bg-slate-500/10 px-2 py-0.5 text-[11px] font-semibold text-slate-300">
                {t("card.claimed")} −{formatPctPlain(product.claimed_discount_pct, lang)}
              </span>
            ) : null}
            <span
              className={`num inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-bold ${realDiscountChipClass(
                product.real_discount_pct,
              )}`}
              title={t("card.realBaseline")}
            >
              {t("card.real")} {formatPct(product.real_discount_pct, lang)}
            </span>
          </div>

          {showInflation ? (
            <p className="flex items-center gap-1.5 text-[11px] font-semibold text-rose-300">
              <ShieldAlert className="size-3.5 shrink-0" />
              {t("card.inflation", { pts: formatPctPlain(gap, lang) })}
            </p>
          ) : null}

          <div className="flex items-center justify-between border-t border-white/[0.06] pt-2.5 text-[11px] text-slate-500">
            <span>
              {t("card.updated")} {formatDate(product.last_updated_at, lang)}
            </span>
            <span className="inline-flex items-center gap-1 font-semibold text-cyan-400/80 transition group-hover:text-cyan-300">
              {t("card.viewTruth")}
              <ArrowRight className="size-3 rtl:rotate-180" />
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
