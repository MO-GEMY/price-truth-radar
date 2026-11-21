"use client";

import Link from "next/link";
import { ArrowRight, Flame, PackageX, ShieldAlert } from "lucide-react";
import type { Product } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { formatDate, formatPct, formatPctPlain, formatPrice } from "@/lib/format";
import { ProductImage } from "./ProductImage";
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

  const gap = product.claimed_discount_pct - Math.max(product.real_discount_pct, 0);
  const showInflation =
    product.claimed_discount_pct >= 10 && product.real_discount_pct < 3 && gap >= 10;

  return (
    <Link
      href={`/products/${product.product_sk}`}
      className="group glass relative flex min-w-0 flex-col overflow-hidden rounded-2xl transition-all duration-200 hover:-translate-y-0.5 hover:border-cyan-400/35 hover:shadow-[0_10px_40px_rgba(34,211,238,0.12)]"
    >
      {/* Image area with consistent 4:3 aspect ratio and legible overlays */}
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-slate-900/80">
        <ProductImage
          src={product.image_url}
          alt={product.product_title}
          category={product.category}
          subCategory={product.sub_category}
          brand={product.brand}
          fit="cover"
          dimmed={!product.in_stock}
          zoomOnGroupHover
          className="h-full w-full"
        />

        <div
          className="pointer-events-none absolute inset-0 bg-gradient-to-t from-[#05080f]/70 via-transparent to-[#05080f]/40"
          aria-hidden
        />

        <div className="pointer-events-none absolute inset-x-2.5 top-2.5 flex items-start justify-between gap-2">
          <div className="min-w-0 max-w-[46%]">
            <StoreBadge name={product.store_name} size="sm" />
          </div>
          <div className="shrink-0">
            <VerdictBadge verdict={product.discount_verdict} size="sm" />
          </div>
        </div>

        {product.scarcity_flag || !product.in_stock ? (
          <div className="pointer-events-none absolute inset-x-2.5 bottom-2.5 flex flex-wrap gap-1.5">
            {product.scarcity_flag ? (
              <span className="inline-flex max-w-full items-center gap-1 rounded-full border border-amber-500/45 bg-[#0a0f1c]/90 px-2 py-0.5 text-[10px] font-semibold text-amber-300 backdrop-blur-md">
                <Flame className="size-3 shrink-0" />
                <span className="truncate">{t("card.lowStock")}</span>
              </span>
            ) : null}
            {!product.in_stock ? (
              <span className="inline-flex max-w-full items-center gap-1 rounded-full border border-rose-500/45 bg-[#0a0f1c]/90 px-2 py-0.5 text-[10px] font-semibold text-rose-300 backdrop-blur-md">
                <PackageX className="size-3 shrink-0" />
                <span className="truncate">{t("card.outOfStock")}</span>
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* Body */}
      <div className="flex min-w-0 flex-1 flex-col gap-3 p-4">
        <div className="min-w-0">
          <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-snug text-slate-100 group-hover:text-white">
            {product.product_title}
          </h3>
          <p className="mt-1 truncate text-[11px] text-slate-500">
            {product.brand} · {product.sub_category.replace(/_/g, " ")}
          </p>
        </div>

        <div className="mt-auto space-y-2.5">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="num text-lg font-bold tracking-tight text-white sm:text-xl">
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
              <span className="num inline-flex items-center gap-1 rounded-md border border-slate-500/40 bg-slate-500/10 px-2 py-0.5 text-[11px] font-semibold text-slate-300">
                <span>{t("card.claimed")}</span>
                <span dir="ltr" className="inline-block">
                  −{formatPctPlain(product.claimed_discount_pct, lang)}
                </span>
              </span>
            ) : null}
            <span
              className={`num inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-bold ${realDiscountChipClass(
                product.real_discount_pct,
              )}`}
              title={t("card.realBaseline")}
            >
              <span>{t("card.real")}</span>
              <span dir="ltr" className="inline-block">
                {formatPct(product.real_discount_pct, lang)}
              </span>
            </span>
          </div>

          {showInflation ? (
            <p className="flex items-center gap-1.5 text-[11px] font-semibold text-rose-300">
              <ShieldAlert className="size-3.5 shrink-0" />
              <span className="min-w-0 truncate">
                {t("card.inflation", { pts: formatPctPlain(gap, lang) })}
              </span>
            </p>
          ) : null}

          <div className="flex items-center justify-between gap-2 border-t border-white/[0.06] pt-2.5 text-[11px] text-slate-500">
            <span className="min-w-0 truncate">
              {t("card.updated")} {formatDate(product.last_updated_at, lang)}
            </span>
            <span className="inline-flex shrink-0 items-center gap-1 font-semibold text-cyan-400/80 transition group-hover:text-cyan-300">
              {t("card.viewTruth")}
              <ArrowRight className="size-3 rtl:rotate-180" />
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
