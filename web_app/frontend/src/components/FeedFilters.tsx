"use client";

import { SlidersHorizontal } from "lucide-react";
import type {
  DiscountVerdict,
  FeedCategoryFilter,
  FeedSort,
} from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";
import { storeDisplayName } from "@/lib/stores";

const CATEGORIES: FeedCategoryFilter[] = [
  "all",
  "electronics",
  "home_appliances",
  "groceries",
  "fashion",
];

export const CATEGORY_LABEL_KEY: Record<FeedCategoryFilter, TranslationKey> = {
  all: "filters.catAll",
  electronics: "filters.catElectronics",
  home_appliances: "filters.catHomeAppliances",
  groceries: "filters.catGroceries",
  fashion: "filters.catFashion",
};

const VERDICTS: DiscountVerdict[] = [
  "FAKE_DISCOUNT",
  "ALL_TIME_LOW",
  "GENUINE_DEAL",
  "PRESALE_HIKE",
  "NORMAL_PRICE",
];

const SORTS: FeedSort[] = [
  "claimed_vs_real_gap_desc",
  "real_discount_pct_desc",
  "price_asc",
  "price_desc",
];

const selectClass =
  "h-10 min-w-0 rounded-xl border border-white/10 bg-[#050912] px-3 text-xs font-medium text-slate-200 outline-none transition hover:border-white/20 focus:border-teal-400/50 sm:text-sm";

export interface FeedFilterState {
  category: FeedCategoryFilter;
  verdict: DiscountVerdict | "";
  store: string;
  sort: FeedSort;
}

export function FeedFilters({
  value,
  stores,
  onChange,
}: {
  value: FeedFilterState;
  stores: string[];
  onChange: (next: FeedFilterState) => void;
}) {
  const { lang, t } = useLanguage();

  // Alphabetical by localized display name so a 30-store dropdown stays scannable.
  const sortedStores = [...stores].sort((a, b) =>
    storeDisplayName(a, lang).localeCompare(storeDisplayName(b, lang), lang === "ar" ? "ar" : "en"),
  );

  return (
    <section
      aria-label={t("filters.title")}
      className="surface flex flex-col gap-4 rounded-2xl p-4 lg:flex-row lg:items-end lg:justify-between"
    >
      {/* Category segmented control */}
      <div className="min-w-0">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {t("filters.category")}
        </p>
        <div className="well inline-flex max-w-full flex-wrap gap-1 rounded-xl p-1">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => onChange({ ...value, category: cat })}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition sm:px-3.5 sm:text-sm ${
                value.category === cat
                  ? "bg-teal-400/18 text-teal-200 ring-1 ring-teal-400/35"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {t(CATEGORY_LABEL_KEY[cat])}
            </button>
          ))}
        </div>
      </div>

      {/* Verdict, Store, and Sort selects */}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3 lg:flex lg:flex-wrap lg:items-end">
        <label className="flex min-w-0 flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            {t("filters.verdict")}
          </span>
          <select
            className={selectClass}
            value={value.verdict}
            onChange={(e) =>
              onChange({ ...value, verdict: e.target.value as DiscountVerdict | "" })
            }
          >
            <option value="">{t("filters.verdictAll")}</option>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {t(`verdict.${v}`)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex min-w-0 flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            {t("filters.store")}
          </span>
          <select
            className={selectClass}
            value={value.store}
            onChange={(e) => onChange({ ...value, store: e.target.value })}
          >
            <option value="">{t("filters.storeAll")}</option>
            {sortedStores.map((s) => (
              <option key={s} value={s}>
                {storeDisplayName(s, lang)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex min-w-0 flex-col gap-1.5">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            <SlidersHorizontal className="size-3" />
            {t("filters.sort")}
          </span>
          <select
            className={selectClass}
            value={value.sort}
            onChange={(e) => onChange({ ...value, sort: e.target.value as FeedSort })}
          >
            {SORTS.map((s) => (
              <option key={s} value={s}>
                {t(`sort.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
    </section>
  );
}
