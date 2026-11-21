"use client";

import { SlidersHorizontal } from "lucide-react";
import type {
  DiscountVerdict,
  FeedCategoryFilter,
  FeedSort,
} from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";

const CATEGORIES: FeedCategoryFilter[] = ["all", "electronics", "home_appliances", "fashion"];

const CATEGORY_LABEL_KEY: Record<FeedCategoryFilter, TranslationKey> = {
  all: "filters.catAll",
  electronics: "filters.catElectronics",
  home_appliances: "filters.catHomeAppliances",
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
  "h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-slate-200 outline-none transition focus:border-cyan-400/50 hover:border-white/20";

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
  const { t } = useLanguage();

  return (
    <section
      aria-label={t("filters.title")}
      className="glass flex flex-col gap-4 rounded-2xl p-4 lg:flex-row lg:items-end lg:justify-between"
    >
      {/* Category segmented control */}
      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {t("filters.category")}
        </p>
        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => onChange({ ...value, category: cat })}
              className={`rounded-lg px-3.5 py-1.5 text-sm font-semibold transition ${
                value.category === cat
                  ? "bg-gradient-to-r from-cyan-500/25 to-emerald-500/25 text-cyan-200 ring-1 ring-cyan-400/40"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {t(CATEGORY_LABEL_KEY[cat])}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5">
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

        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            {t("filters.store")}
          </span>
          <select
            className={selectClass}
            value={value.store}
            onChange={(e) => onChange({ ...value, store: e.target.value })}
          >
            <option value="">{t("filters.storeAll")}</option>
            {stores.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
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
