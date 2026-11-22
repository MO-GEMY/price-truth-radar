"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeftRight, Flame, Languages, Radar } from "lucide-react";
import { useLanguage } from "@/lib/i18n";
import { formatNumber } from "@/lib/format";
import { useCompareSummary } from "@/lib/useCompareSummary";

export function Header() {
  const { t, toggleLang, lang } = useLanguage();
  const pathname = usePathname();
  const { summary } = useCompareSummary();

  const isFeed = pathname === "/";
  const isCompare = pathname.startsWith("/compare");
  const isDeals = pathname.startsWith("/deals");

  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.07] bg-[#03060b]/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
        <Link href="/" className="group flex min-w-0 items-center gap-2.5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-teal-400 to-emerald-500 text-[#031214] shadow-[0_0_24px_rgba(20,184,166,0.3)] transition group-hover:brightness-110">
            <Radar className="size-5" strokeWidth={2.4} />
          </span>
          <span className="min-w-0 leading-tight">
            <span className="block truncate text-sm font-bold tracking-tight text-white sm:text-[15px]">
              {t("brand.name")}
            </span>
            <span className="hidden truncate text-[11px] text-slate-400 lg:block">
              {t("brand.tagline")}
            </span>
          </span>
        </Link>

        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <nav className="flex items-center gap-1" aria-label="Primary">
            <Link
              href="/"
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition sm:px-3.5 sm:py-2 sm:text-sm ${
                isFeed
                  ? "bg-teal-400/14 text-teal-200 ring-1 ring-teal-400/30"
                  : "text-slate-300 hover:bg-white/[0.05] hover:text-white"
              }`}
            >
              <Radar className="size-4 shrink-0" />
              <span className="hidden sm:inline">{t("nav.feed")}</span>
            </Link>

            <Link
              href="/deals"
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition sm:px-3.5 sm:py-2 sm:text-sm ${
                isDeals
                  ? "bg-rose-400/14 text-rose-200 ring-1 ring-rose-400/30"
                  : "text-slate-300 hover:bg-white/[0.05] hover:text-white"
              }`}
            >
              <Flame className="size-4 shrink-0 text-rose-400" />
              <span className="hidden sm:inline">{t("nav.deals")}</span>
            </Link>

            <Link
              href="/compare"
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition sm:px-3.5 sm:py-2 sm:text-sm ${
                isCompare
                  ? "bg-emerald-400/14 text-emerald-200 ring-1 ring-emerald-400/30"
                  : "text-slate-300 hover:bg-white/[0.05] hover:text-white"
              }`}
            >
              <ArrowLeftRight className="size-4 shrink-0" />
              <span className="hidden sm:inline">{t("nav.compare")}</span>
              {summary && summary.total > 0 ? (
                <span className="num rounded-full border border-emerald-400/35 bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-bold leading-none text-emerald-300">
                  {formatNumber(summary.total, lang)}
                </span>
              ) : null}
            </Link>
          </nav>

          <button
            type="button"
            onClick={toggleLang}
            aria-label={lang === "en" ? "Switch to Arabic" : "التبديل إلى الإنجليزية"}
            title={t("lang.toggle")}
            className="ms-1 inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-teal-400/40 hover:text-teal-200 sm:py-2 sm:text-sm"
          >
            <Languages className="size-3.5 shrink-0 sm:size-4" />
            <span>{t("lang.toggle")}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
