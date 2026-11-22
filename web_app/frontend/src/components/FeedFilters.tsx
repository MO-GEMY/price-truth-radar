"use client";

import { useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import type { DiscountVerdict, FeedCategoryFilter, FeedSort } from "@/types/contract";
import { categories, categoryLabels } from "@/lib/browse-state";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";

export const verdictOptions: DiscountVerdict[] = ["FAKE_DISCOUNT", "ALL_TIME_LOW", "GENUINE_DEAL", "PRESALE_HIKE", "NORMAL_PRICE"];
export const sortOptions: FeedSort[] = ["claimed_vs_real_gap_desc", "real_discount_pct_desc", "price_asc", "price_desc"];

export interface FeedFilterState {
  category: FeedCategoryFilter;
  verdict: DiscountVerdict | "";
  store: string;
  sort: FeedSort;
}

export const defaultFilters: FeedFilterState = { category: "all", verdict: "", store: "", sort: "claimed_vs_real_gap_desc" };

export function FeedFilters({ value, stores, onChange }: {
  value: FeedFilterState; stores: string[]; onChange: (next: FeedFilterState) => void;
}) {
  const { lang, t } = useLanguage();
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const [draft, setDraft] = useState(value);
  const available = [...new Set([...stores, ...(value.store ? [value.store] : [])])].sort((a, b) =>
    storeDisplayName(a, lang).localeCompare(storeDisplayName(b, lang), lang),
  );
  const active = [
    value.verdict && t(`verdict.${value.verdict}`),
    value.store && storeDisplayName(value.store, lang),
    value.sort !== defaultFilters.sort && t(`sort.${value.sort}`),
  ].filter(Boolean);

  function close() {
    dialog.current?.close();
    opener.current?.focus({ preventScroll: true });
  }

  return (
    <div className="space-y-2">
      <div className="ptr-toolbar">
        <div className="ptr-controls" role="group" aria-label={t("filters.category")}>
          {categories.map((category) => <button className="ptr-chip" key={category} type="button"
            aria-pressed={value.category === category} onClick={() => onChange({ ...value, category })}>
            {t(categoryLabels[category])}
          </button>)}
        </div>
        <button ref={opener} type="button" className="ptr-button" onClick={() => {
          setDraft(value);
          dialog.current?.showModal();
        }}><SlidersHorizontal size={15} aria-hidden="true" />{t("filters.title")}{active.length > 0 && ` (${active.length})`}</button>
      </div>
      {(active.length > 0 || value.category !== "all") && <div className="ptr-controls text-sm ptr-muted">
        {active.length > 0 && <span>{active.join(" · ")}</span>}
        <button type="button" className="ptr-link" onClick={() => onChange(defaultFilters)}>{t("filters.reset")}</button>
      </div>}
      <dialog ref={dialog} className="surface ptr-dialog" aria-labelledby="ptr-filters-title"
        onCancel={(event) => { event.preventDefault(); close(); }}>
        <h2 id="ptr-filters-title" className="text-xl font-bold">{t("filters.title")}</h2>
        <form className="mt-4 space-y-4" onSubmit={(event) => { event.preventDefault(); onChange(draft); close(); }}>
          <label className="ptr-control-label">{t("filters.store")}
            <select className="ptr-field" value={draft.store} onChange={(event) => setDraft({ ...draft, store: event.target.value })}>
              <option value="">{t("filters.storeAll")}</option>
              {available.map((store) => <option key={store} value={store}>{storeDisplayName(store, lang)}</option>)}
            </select>
          </label>
          <label className="ptr-control-label">{t("filters.verdict")}
            <select className="ptr-field" value={draft.verdict} onChange={(event) => setDraft({
              ...draft, verdict: verdictOptions.find((item) => item === event.target.value) ?? "",
            })}>
              <option value="">{t("filters.verdictAll")}</option>
              {verdictOptions.map((verdict) => <option key={verdict} value={verdict}>{t(`verdict.${verdict}`)}</option>)}
            </select>
          </label>
          <label className="ptr-control-label">{t("filters.sort")}
            <select className="ptr-field" value={draft.sort} onChange={(event) => setDraft({
              ...draft, sort: sortOptions.find((item) => item === event.target.value) ?? defaultFilters.sort,
            })}>
              {sortOptions.map((sort) => <option key={sort} value={sort}>{t(`sort.${sort}`)}</option>)}
            </select>
          </label>
          <div className="ptr-controls">
            <button type="submit" className="ptr-button ptr-primary">{t("ui.applyFilters")}</button>
            <button type="button" className="ptr-button" onClick={() => { onChange(defaultFilters); close(); }}>{t("filters.reset")}</button>
            <button type="button" className="ptr-button" onClick={close}>{t("ui.close")}</button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
