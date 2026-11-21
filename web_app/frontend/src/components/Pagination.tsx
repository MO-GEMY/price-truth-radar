"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useLanguage } from "@/lib/i18n";

/** Compact page-number window: 1 … c-1 c c+1 … N */
function pageWindow(page: number, totalPages: number): (number | "…")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const set = new Set<number>([1, totalPages, page - 1, page, page + 1]);
  const sorted = [...set].filter((p) => p >= 1 && p <= totalPages).sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}

export function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (page: number) => void;
}) {
  const { t } = useLanguage();
  if (totalPages <= 1) return null;

  const btn =
    "flex h-9 min-w-9 items-center justify-center rounded-lg border px-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <nav
      aria-label={t("feed.pageInfo", { page, totalPages })}
      className="flex flex-wrap items-center justify-center gap-2"
    >
      <button
        type="button"
        className={`${btn} border-white/10 bg-white/[0.04] text-slate-300 hover:border-white/25 hover:text-white`}
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        aria-label={t("feed.prev")}
      >
        <ChevronLeft className="size-4 rtl:rotate-180" />
      </button>

      {pageWindow(page, totalPages).map((p, i) =>
        p === "…" ? (
          <span key={`gap-${i}`} className="px-1 text-slate-500">
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => onPage(p)}
            aria-current={p === page ? "page" : undefined}
            className={`${btn} ${
              p === page
                ? "border-cyan-400/40 bg-cyan-400/15 text-cyan-200"
                : "border-white/10 bg-white/[0.04] text-slate-300 hover:border-white/25 hover:text-white"
            }`}
          >
            {p}
          </button>
        ),
      )}

      <button
        type="button"
        className={`${btn} border-white/10 bg-white/[0.04] text-slate-300 hover:border-white/25 hover:text-white`}
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
        aria-label={t("feed.next")}
      >
        <ChevronRight className="size-4 rtl:rotate-180" />
      </button>

      <span className="num ms-2 text-xs text-slate-500">
        {t("feed.pageInfo", { page, totalPages })}
      </span>
    </nav>
  );
}
