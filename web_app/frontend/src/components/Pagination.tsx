"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useLanguage } from "@/lib/i18n";
import { formatNumber } from "@/lib/format";

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
  const { lang, t } = useLanguage();
  if (totalPages <= 1) return null;

  return (
    <nav
      aria-label={t("feed.pageInfo", { page, totalPages })}
      className="flex min-w-0 max-w-full flex-wrap items-center justify-center gap-2"
    >
      <button
        type="button"
        className="ptr-chip"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        aria-label={t("feed.prev")}
      >
        <ChevronLeft className="size-4 rtl:rotate-180" aria-hidden="true" />
      </button>

      {pageWindow(page, totalPages).map((p, i) =>
        p === "…" ? (
          <span key={`gap-${i}`} className="px-1 ptr-muted" aria-hidden="true">
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => onPage(p)}
            aria-current={p === page ? "page" : undefined}
            className="ptr-chip"
          >
            {formatNumber(p, lang)}
          </button>
        ),
      )}

      <button
        type="button"
        className="ptr-chip"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
        aria-label={t("feed.next")}
      >
        <ChevronRight className="size-4 rtl:rotate-180" aria-hidden="true" />
      </button>

      <span className="num basis-full text-center text-xs ptr-muted sm:ms-2 sm:basis-auto">
        {t("feed.pageInfo", { page, totalPages })}
      </span>
    </nav>
  );
}
