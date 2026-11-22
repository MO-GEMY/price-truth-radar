"use client";

import Link from "next/link";
import { ArrowLeftRight, ArrowRight, PackageX, ShieldAlert } from "lucide-react";
import type { Product } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import {
  formatNumber,
  formatPackSize,
  formatPct,
  formatPctPlain,
  formatPrice,
  formatSubCategory,
} from "@/lib/format";
import { ProductImage } from "./ProductImage";
import { VerdictBadge } from "./VerdictBadge";
import { StoreBadge } from "./StoreBadge";

function realDiscountChipClass(real: number): string {
  if (real >= 10) return "border-emerald-400/35 bg-emerald-500/12 text-emerald-300";
  if (real >= 5) return "border-emerald-400/25 bg-emerald-500/10 text-emerald-200";
  if (real >= 0) return "border-slate-500/35 bg-slate-500/10 text-slate-300";
  return "border-rose-400/35 bg-rose-500/12 text-rose-300";
}

export function ProductCard({
  product,
  compareStoreCount,
}: {
  product: Product;
  /** Number of tracked stores carrying this canonical product (when matched in /compare). */
  compareStoreCount?: number;
}) {
  const { lang, t } = useLanguage();

  const gap = product.claimed_discount_pct - Math.max(product.real_discount_pct, 0);
  const showInflation =
    product.claimed_discount_pct >= 10 && product.real_discount_pct < 3 && gap >= 10;
  const isFashion = product.category === "fashion";
  const packSize = formatPackSize(product.attributes_json);

  const detailHref = `/products/${product.product_sk}`;

  return (
    <article className="group surface surface-hover relative flex min-w-0 flex-col overflow-hidden rounded-2xl">
      {/* Category-aware thumbnail framing:
          - fashion: full-bleed cover anchored top (no white sidebars or cropped heads)
          - electronics / home_appliances / groceries: crisp white studio frame for cutouts */}
      <Link href={detailHref} className={isFashion ? "relative block" : "relative block p-2.5 pb-0"}>
        <div
          className={`relative aspect-[4/3] w-full overflow-hidden ${
            isFashion ? "bg-[#111827]" : "rounded-xl"
          }`}
        >
          <ProductImage
            src={product.image_url}
            alt={product.product_title}
            category={product.category}
            subCategory={product.sub_category}
            brand={product.brand}
            fit={isFashion ? "cover" : "contain"}
            objectPosition={isFashion ? "top" : "center"}
            studio={!isFashion}
            dimmed={!product.in_stock}
            zoomOnGroupHover
            className="h-full w-full"
          />

          {!product.in_stock ? (
            <div className="pointer-events-none absolute inset-x-2.5 bottom-2.5 flex flex-wrap gap-1.5">
              <span className="inline-flex max-w-full items-center gap-1 rounded-full border border-rose-400/45 bg-[#090e18]/92 px-2.5 py-0.5 text-[10px] font-semibold text-rose-300 backdrop-blur-sm">
                <PackageX className="size-3 shrink-0" />
                <span className="truncate">{t("card.outOfStock")}</span>
              </span>
            </div>
          ) : null}
        </div>
      </Link>

      {/* Structured card body */}
      <div className="flex min-w-0 flex-1 flex-col gap-3 p-4 pt-3.5">
        {/* Store & Verdict row — never collides with photography */}
        <div className="flex flex-wrap items-center justify-between gap-1.5">
          <div className="min-w-0 max-w-[48%]">
            <StoreBadge name={product.store_name} size="sm" />
          </div>
          <div className="shrink-0">
            <VerdictBadge verdict={product.discount_verdict} size="sm" />
          </div>
        </div>

        {/* Title & category meta (groceries carry a compact pack-size chip) */}
        <Link href={detailHref} className="block min-w-0">
          <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-snug text-slate-100 transition group-hover:text-white">
            {product.product_title}
          </h3>
          <div className="mt-1 flex items-center justify-between gap-2">
            <p className="min-w-0 truncate text-xs font-medium text-slate-400">
              {product.brand} · {formatSubCategory(product.sub_category, lang)}
            </p>
            {packSize ? (
              <span className="num shrink-0 rounded-full border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-semibold text-slate-300">
                {packSize}
              </span>
            ) : null}
          </div>
        </Link>

        {/* Price + Claimed vs Real breakdown */}
        <div className="mt-auto space-y-2.5">
          <Link href={detailHref} className="block space-y-2">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="num text-lg font-extrabold tracking-tight text-white sm:text-xl">
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
                <span className="num inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] font-semibold text-slate-300">
                  <span>{t("card.claimed")}</span>
                  <span dir="ltr" className="inline-block">
                    −{formatPctPlain(product.claimed_discount_pct, lang, 0)}
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
                  {formatPct(product.real_discount_pct, lang, 0)}
                </span>
              </span>
            </div>

            {showInflation ? (
              <p className="flex items-center gap-1.5 text-[11px] font-semibold text-rose-300">
                <ShieldAlert className="size-3.5 shrink-0" />
                <span className="num min-w-0 truncate">
                  {t("card.inflation", { pts: formatPctPlain(gap, lang, 0) })}
                </span>
              </p>
            ) : null}
          </Link>

          {/* Footer: Cross-store compare pill (if matched) + Inspect link */}
          <div className="flex items-center justify-between gap-2 border-t border-white/[0.06] pt-2.5 text-[11px]">
            {compareStoreCount && compareStoreCount >= 2 ? (
              <Link
                href="/compare"
                className="inline-flex min-w-0 items-center gap-1 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 font-semibold text-emerald-300 transition hover:border-emerald-400/55 hover:bg-emerald-500/18"
              >
                <ArrowLeftRight className="size-3 shrink-0" />
                <span className="num truncate">
                  {t("card.compareStores", { count: formatNumber(compareStoreCount, lang) })}
                </span>
              </Link>
            ) : (
              <span className="truncate text-slate-500">
                {product.category === "electronics"
                  ? t("filters.catElectronics")
                  : product.category === "home_appliances"
                    ? t("filters.catHomeAppliances")
                    : product.category === "groceries"
                      ? t("filters.catGroceries")
                      : t("filters.catFashion")}
              </span>
            )}

            <Link
              href={detailHref}
              className="inline-flex shrink-0 items-center gap-1 font-semibold text-teal-300/90 transition hover:text-teal-200"
            >
              <span>{t("card.viewTruth")}</span>
              <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5 rtl:rotate-180 rtl:group-hover:-translate-x-0.5" />
            </Link>
          </div>
        </div>
      </div>
    </article>
  );
}
