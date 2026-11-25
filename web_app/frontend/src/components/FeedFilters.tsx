"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  List,
  SlidersHorizontal,
} from "lucide-react";
import type {
  CategoryFacetsResponse,
  DiscountVerdict,
  FeedCategoryFilter,
  FeedSort,
} from "@/types/contract";
import { categoryLabels, visibleCategories } from "@/lib/browse-state";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";

export const verdictOptions: DiscountVerdict[] = [
  "FAKE_DISCOUNT",
  "ALL_TIME_LOW",
  "GENUINE_DEAL",
  "PRESALE_HIKE",
  "NORMAL_PRICE",
];
export const sortOptions: FeedSort[] = [
  "claimed_vs_real_gap_desc",
  "real_discount_pct_desc",
  "price_asc",
  "price_desc",
];

export interface FeedFilterState {
  category: FeedCategoryFilter;
  subcategory: string;
  brand: string;
  verdict: DiscountVerdict | "";
  store: string;
  sort: FeedSort;
}

export const defaultFilters: FeedFilterState = {
  category: "all",
  subcategory: "",
  brand: "",
  verdict: "",
  store: "",
  sort: "claimed_vs_real_gap_desc",
};

export function FeedFilters({
  value,
  stores,
  categoryCounts,
  facets,
  facetsLoading = false,
  view = "list",
  onViewChange,
  onChange,
}: {
  value: FeedFilterState;
  stores: string[];
  categoryCounts?: Record<string, number> | null;
  facets?: CategoryFacetsResponse | null;
  facetsLoading?: boolean;
  view?: "list" | "grid";
  onViewChange?: (view: "list" | "grid") => void;
  onChange: (next: FeedFilterState) => void;
}) {
  const { lang, dir, t } = useLanguage();
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const subBarRef = useRef<HTMLDivElement>(null);
  const subAnimRef = useRef<number>(0);
  const [draft, setDraft] = useState(value);
  const [subScroll, setSubScroll] = useState({ start: false, end: false });
  const shownCategories = visibleCategories(categoryCounts, value.category);

  const scopedStoreCounts = new Map<string, number>();
  if (value.category !== "all" && facets?.stores?.length) {
    for (const s of facets.stores) {
      scopedStoreCounts.set(s.slug, s.count);
    }
  }

  const baseStores =
    value.category !== "all" && facets?.stores?.length
      ? facets.stores.map((s) => s.slug)
      : stores;

  const availableStores = [
    ...new Set([...baseStores, ...(value.store ? [value.store] : [])]),
  ].sort((a, b) => {
    const ca = scopedStoreCounts.get(a) ?? 0;
    const cb = scopedStoreCounts.get(b) ?? 0;
    if (ca !== cb) return cb - ca;
    return storeDisplayName(a, lang).localeCompare(storeDisplayName(b, lang), lang);
  });

  const availableBrands = facets?.brands ?? [];
  const hasSelectedBrandInList =
    !value.brand ||
    availableBrands.some(
      (b) => b.name.toLowerCase() === value.brand.toLowerCase(),
    );

  const subcategories = value.category !== "all" ? (facets?.subcategories ?? []) : [];
  const activeSubcatObj = subcategories.find((s) => s.slug === value.subcategory);
  const activeSubcatLabel = activeSubcatObj
    ? lang === "ar"
      ? activeSubcatObj.label_ar
      : activeSubcatObj.label_en
    : value.subcategory
      ? value.subcategory.replace(/_/g, " ")
      : "";

  const active = [
    activeSubcatLabel,
    value.brand,
    value.verdict && t(`verdict.${value.verdict}`),
    value.store && storeDisplayName(value.store, lang),
    value.sort !== defaultFilters.sort && t(`sort.${value.sort}`),
  ].filter(Boolean);

  function close() {
    dialog.current?.close();
    opener.current?.focus({ preventScroll: true });
  }

  function selectCategory(nextCat: FeedCategoryFilter) {
    if (nextCat === value.category) return;
    onChange({
      ...value,
      category: nextCat,
      subcategory: "",
      brand: "",
      store: "",
    });
  }

  function selectSubcategory(nextSub: string) {
    onChange({
      ...value,
      subcategory: nextSub === value.subcategory ? "" : nextSub,
      brand: "",
    });
  }

  const syncSubScroll = useCallback(() => {
    const el = subBarRef.current;
    if (!el) {
      setSubScroll((prev) =>
        prev.start || prev.end ? { start: false, end: false } : prev,
      );
      return;
    }
    const maxScroll = el.scrollWidth - el.clientWidth;
    if (maxScroll <= 4) {
      setSubScroll((prev) =>
        prev.start || prev.end ? { start: false, end: false } : prev,
      );
      return;
    }
    const scrolled = Math.abs(el.scrollLeft);
    const start = scrolled > 2;
    const end = scrolled < maxScroll - 2;
    setSubScroll((prev) =>
      prev.start === start && prev.end === end ? prev : { start, end },
    );
  }, []);

  useEffect(() => {
    syncSubScroll();
    const el = subBarRef.current;
    if (!el) return;
    const onResize = () => syncSubScroll();
    window.addEventListener("resize", onResize, { passive: true });
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(syncSubScroll);
      ro.observe(el);
    }
    return () => {
      window.removeEventListener("resize", onResize);
      ro?.disconnect();
      window.cancelAnimationFrame(subAnimRef.current);
    };
  }, [syncSubScroll, value.category, subcategories.length, facetsLoading, lang]);

  function scrollSubBar(direction: "start" | "end") {
    const el = subBarRef.current;
    if (!el) return;
    const maxScroll = Math.max(0, el.scrollWidth - el.clientWidth);
    if (maxScroll <= 1) return;

    const step = Math.max(160, Math.round(el.clientWidth * 0.65));
    const from = el.scrollLeft;
    let to: number;
    if (dir === "rtl") {
      to =
        direction === "end"
          ? Math.max(-maxScroll, from - step)
          : Math.min(0, from + step);
    } else {
      to =
        direction === "end"
          ? Math.min(maxScroll, from + step)
          : Math.max(0, from - step);
    }
    if (Math.abs(to - from) < 1) return;

    window.cancelAnimationFrame(subAnimRef.current);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.scrollLeft = to;
      syncSubScroll();
      return;
    }

    const duration = 200;
    const startedAt = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - (1 - progress) ** 3;
      el.scrollLeft = from + (to - from) * eased;
      if (progress < 1) {
        subAnimRef.current = window.requestAnimationFrame(tick);
      } else {
        el.scrollLeft = to;
        syncSubScroll();
      }
    };
    subAnimRef.current = window.requestAnimationFrame(tick);
  }

  const StartChevron = dir === "rtl" ? ChevronRight : ChevronLeft;
  const EndChevron = dir === "rtl" ? ChevronLeft : ChevronRight;

  return (
    <div className="min-w-0 max-w-full space-y-2.5" data-tour="filters">
      <div className="ptr-toolbar">
        <div
          className="ptr-category-bar"
          role="group"
          aria-label={t("filters.category")}
        >
          {shownCategories.map((category) => {
            const catCount =
              category === "all" ? null : categoryCounts?.[category];
            return (
              <button
                className="ptr-chip"
                key={category}
                type="button"
                aria-pressed={value.category === category}
                onClick={() => selectCategory(category)}
              >
                <span>{t(categoryLabels[category])}</span>
                {typeof catCount === "number" && catCount > 0 && (
                  <span className="ptr-chip-count">
                    <bdi>{formatNumber(catCount, lang)}</bdi>
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="ptr-controls shrink-0">
          {onViewChange && (
            <div className="asarak-segmented" role="group" aria-label={t("view.list")}>
              <button
                type="button"
                aria-pressed={view === "list"}
                aria-label={t("view.list")}
                title={t("view.list")}
                onClick={() => onViewChange("list")}
              >
                <List size={15} aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-pressed={view === "grid"}
                aria-label={t("view.grid")}
                title={t("view.grid")}
                onClick={() => onViewChange("grid")}
              >
                <LayoutGrid size={15} aria-hidden="true" />
              </button>
            </div>
          )}

          <button
            ref={opener}
            type="button"
            className="ptr-button"
            onClick={() => {
              setDraft(value);
              dialog.current?.showModal();
            }}
          >
            <SlidersHorizontal size={15} aria-hidden="true" />
            <span>{t("filters.title")}</span>
            {active.length > 0 && (
              <span className="ptr-badge ptr-badge-variant">
                {formatNumber(active.length, lang)}
              </span>
            )}
          </button>
        </div>
      </div>

      {value.category !== "all" && (subcategories.length > 0 || facetsLoading) && (
        <div
          className="ptr-subcategory-shell"
          data-can-scroll-start={subScroll.start ? "true" : undefined}
          data-can-scroll-end={subScroll.end ? "true" : undefined}
        >
          {subScroll.start && (
            <button
              type="button"
              className="ptr-subscroll-btn ptr-subscroll-btn--start"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => scrollSubBar("start")}
              aria-label={t("filters.scrollBack")}
            >
              <StartChevron size={16} aria-hidden="true" />
            </button>
          )}

          <div
            ref={subBarRef}
            className="ptr-subcategory-bar"
            role="group"
            aria-label={t("filters.subcategory")}
            onScroll={syncSubScroll}
          >
            {facetsLoading && subcategories.length === 0 ? (
              [0, 1, 2, 3, 4].map((idx) => (
                <span
                  key={idx}
                  className="skeleton"
                  style={{ width: 92, height: 32, borderRadius: 999, flex: "none" }}
                  aria-hidden="true"
                />
              ))
            ) : (
              <>
                <button
                  type="button"
                  className="ptr-subchip"
                  aria-pressed={value.subcategory === ""}
                  onClick={() =>
                    onChange({ ...value, subcategory: "", brand: "" })
                  }
                >
                  <span>
                    {t("filters.subcatAll", {
                      category: t(categoryLabels[value.category]),
                    })}
                  </span>
                </button>
                {subcategories.map((sub) => (
                  <button
                    key={sub.slug}
                    type="button"
                    className="ptr-subchip"
                    aria-pressed={value.subcategory === sub.slug}
                    onClick={() => selectSubcategory(sub.slug)}
                  >
                    <span>{lang === "ar" ? sub.label_ar : sub.label_en}</span>
                    <span className="ptr-chip-count">
                      <bdi>{formatNumber(sub.count, lang)}</bdi>
                    </span>
                  </button>
                ))}
              </>
            )}
          </div>

          {subScroll.end && (
            <button
              type="button"
              className="ptr-subscroll-btn ptr-subscroll-btn--end"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => scrollSubBar("end")}
              aria-label={t("filters.scrollMore")}
            >
              <EndChevron size={16} aria-hidden="true" />
            </button>
          )}
        </div>
      )}

      {(active.length > 0 || value.category !== "all") && (
        <div className="ptr-controls text-sm ptr-muted">
          {active.length > 0 && <span>{active.join(" · ")}</span>}
          <button
            type="button"
            className="ptr-link"
            onClick={() => onChange(defaultFilters)}
          >
            {t("filters.reset")}
          </button>
        </div>
      )}

      <dialog
        ref={dialog}
        className="surface ptr-dialog"
        aria-labelledby="ptr-filters-title"
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
      >
        <h2 id="ptr-filters-title" className="text-xl font-bold">
          {t("filters.title")}
        </h2>
        <form
          className="mt-4 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            onChange(draft);
            close();
          }}
        >
          <label className="ptr-control-label">
            {t("filters.store")}
            <select
              className="ptr-field"
              value={draft.store}
              onChange={(event) =>
                setDraft({ ...draft, store: event.target.value })
              }
            >
              <option value="">{t("filters.storeAll")}</option>
              {availableStores.map((store) => {
                const cnt = scopedStoreCounts.get(store);
                return (
                  <option key={store} value={store}>
                    {storeDisplayName(store, lang)}
                    {typeof cnt === "number" && cnt > 0
                      ? ` (${formatNumber(cnt, lang)})`
                      : ""}
                  </option>
                );
              })}
            </select>
          </label>

          {value.category !== "all" && (availableBrands.length > 0 || draft.brand) && (
            <label className="ptr-control-label">
              {t("filters.brand")}
              <select
                className="ptr-field"
                value={draft.brand}
                onChange={(event) =>
                  setDraft({ ...draft, brand: event.target.value })
                }
              >
                <option value="">{t("filters.brandAll")}</option>
                {!hasSelectedBrandInList && draft.brand && (
                  <option value={draft.brand}>{draft.brand}</option>
                )}
                {availableBrands.map((brand) => (
                  <option key={brand.name} value={brand.name}>
                    {brand.name} ({formatNumber(brand.count, lang)})
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="ptr-control-label">
            {t("filters.verdict")}
            <select
              className="ptr-field"
              value={draft.verdict}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  verdict:
                    verdictOptions.find(
                      (item) => item === event.target.value,
                    ) ?? "",
                })
              }
            >
              <option value="">{t("filters.verdictAll")}</option>
              {verdictOptions.map((verdict) => (
                <option key={verdict} value={verdict}>
                  {t(`verdict.${verdict}`)}
                </option>
              ))}
            </select>
          </label>

          <label className="ptr-control-label">
            {t("filters.sort")}
            <select
              className="ptr-field"
              value={draft.sort}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  sort:
                    sortOptions.find((item) => item === event.target.value) ??
                    defaultFilters.sort,
                })
              }
            >
              {sortOptions.map((sort) => (
                <option key={sort} value={sort}>
                  {t(`sort.${sort}`)}
                </option>
              ))}
            </select>
          </label>

          <div className="ptr-controls pt-2">
            <button type="submit" className="ptr-button ptr-primary">
              {t("ui.applyFilters")}
            </button>
            <button
              type="button"
              className="ptr-button"
              onClick={() => {
                onChange(defaultFilters);
                close();
              }}
            >
              {t("filters.reset")}
            </button>
            <button type="button" className="ptr-button" onClick={close}>
              {t("ui.close")}
            </button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
