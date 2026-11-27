"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  List,
  ShieldAlert,
  SlidersHorizontal,
  TrendingDown,
  X,
} from "lucide-react";
import type {
  CategoryFacetsResponse,
  FeedCategoryFilter,
  FeedSort,
  StatsOverview,
  VerdictFilter,
} from "@/types/contract";
import { categoryLabels, visibleCategories } from "@/lib/browse-state";
import { formatNumber, formatSubCategory } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";
import { getScopedDealsCount, getScopedHikesCount } from "@/lib/verdicts";

export const verdictOptions: VerdictFilter[] = [
  "ALL_DEALS",
  "ALL_HIKES",
  "FAKE_DISCOUNT",
  "ALL_TIME_LOW",
  "GENUINE_DEAL",
  "PRESALE_HIKE",
  "RECENT_DROP",
  "RECENT_HIKE",
  "NEWLY_TRACKED",
  "NORMAL_PRICE",
];

export const sortOptions: FeedSort[] = [
  "real_discount_pct_desc",
  "claimed_vs_real_gap_desc",
  "price_asc",
  "price_desc",
];

export interface FeedFilterState {
  category: FeedCategoryFilter;
  subcategory: string;
  brand: string;
  verdict: VerdictFilter | "";
  store: string;
  sort: FeedSort;
}

export const defaultFilters: FeedFilterState = {
  category: "all",
  subcategory: "",
  brand: "",
  verdict: "",
  store: "",
  sort: "real_discount_pct_desc",
};

interface RemovableChip {
  key: string;
  label: string;
  onRemove: () => void;
}

export function FeedFilters({
  value,
  stores,
  stats,
  categoryCounts,
  facets,
  facetsLoading = false,
  view = "grid",
  onViewChange,
  onChange,
}: {
  value: FeedFilterState;
  stores: string[];
  stats?: StatsOverview | null;
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
      ? formatSubCategory(value.subcategory, lang)
      : "";

  // Dynamically scoped quick verdict counts (global for "all", exact per category/subcategory otherwise)
  const dropVerdict: VerdictFilter = "ALL_DEALS";
  const dropCount = getScopedDealsCount(stats, value.category, value.subcategory, facets);
  const reviewVerdict: VerdictFilter = "ALL_HIKES";
  const reviewCount = getScopedHikesCount(stats, value.category, value.subcategory, facets);
  const scopedCountsPending =
    value.category !== "all" && (dropCount === null || reviewCount === null);

  const modalActiveCount = [
    value.brand,
    value.verdict,
    value.store,
  ].filter(Boolean).length;

  const removableChips: RemovableChip[] = [];
  if (value.category !== "all") {
    removableChips.push({
      key: "category",
      label: t(categoryLabels[value.category] ?? "filters.catAll"),
      onRemove: () =>
        onChange({
          ...value,
          category: "all",
          subcategory: "",
          brand: "",
          store: "",
        }),
    });
  }
  if (activeSubcatLabel) {
    removableChips.push({
      key: "subcategory",
      label: activeSubcatLabel,
      onRemove: () => onChange({ ...value, subcategory: "", brand: "" }),
    });
  }
  if (value.brand) {
    removableChips.push({
      key: "brand",
      label: value.brand,
      onRemove: () => onChange({ ...value, brand: "" }),
    });
  }
  if (value.store) {
    removableChips.push({
      key: "store",
      label: storeDisplayName(value.store, lang),
      onRemove: () => onChange({ ...value, store: "" }),
    });
  }
  if (value.verdict) {
    removableChips.push({
      key: "verdict",
      label: t(`verdict.${value.verdict}`),
      onRemove: () => onChange({ ...value, verdict: "" }),
    });
  }
  if (value.sort !== defaultFilters.sort) {
    removableChips.push({
      key: "sort",
      label: t(`sort.${value.sort}`),
      onRemove: () => onChange({ ...value, sort: defaultFilters.sort }),
    });
  }

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
    <div className="min-w-0 max-w-full space-y-3" data-tour="filters">
      {/* Row 1: Category Pills (with mobile scroll edge cue) */}
      <div className="ptr-category-shell">
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
                <span>{t(categoryLabels[category] ?? "filters.catAll")}</span>
                {typeof catCount === "number" && catCount > 0 && (
                  <span className="ptr-chip-count">
                    <bdi>{formatNumber(catCount, lang)}</bdi>
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Row 2: Subcategories (when a specific category is selected) */}
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
                      category: t(categoryLabels[value.category] ?? "filters.catAll"),
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

      {/* Row 3: Quick Signal Tabs + Visible Inline Sort + View Toggle + Deep Filters */}
      <div className="asarak-feed-deck surface">
        <div
          className="asarak-segmented asarak-feed-signals"
          role="group"
          aria-label={t("filters.verdict")}
        >
          <button
            type="button"
            aria-pressed={value.verdict === ""}
            onClick={() => onChange({ ...value, verdict: "" })}
          >
            <span>{t("feed.quickAll")}</span>
          </button>

          {(dropCount === null || dropCount > 0 || value.verdict === dropVerdict) && (
            <button
              type="button"
              className="is-deal"
              aria-pressed={value.verdict === dropVerdict}
              onClick={() => {
                const togglingOff = value.verdict === dropVerdict;
                onChange({
                  ...value,
                  verdict: togglingOff ? "" : dropVerdict,
                  sort: togglingOff ? value.sort : "real_discount_pct_desc",
                });
              }}
            >
              <TrendingDown size={14} aria-hidden="true" />
              <span>{t("feed.quickDrops")}</span>
              {typeof dropCount === "number" ? (
                <span className="ptr-chip-count">
                  <bdi>{formatNumber(dropCount, lang)}</bdi>
                </span>
              ) : scopedCountsPending ? (
                <span
                  className="ptr-chip-count opacity-60"
                  aria-hidden="true"
                >
                  …
                </span>
              ) : null}
            </button>
          )}

          {(reviewCount === null || reviewCount > 0 || value.verdict === reviewVerdict) && (
            <button
              type="button"
              className="is-scandal"
              aria-pressed={value.verdict === reviewVerdict}
              onClick={() => {
                const togglingOff = value.verdict === reviewVerdict;
                onChange({
                  ...value,
                  verdict: togglingOff ? "" : reviewVerdict,
                  sort: togglingOff ? value.sort : "claimed_vs_real_gap_desc",
                });
              }}
            >
              <ShieldAlert size={14} aria-hidden="true" />
              <span>{t("feed.quickHikes")}</span>
              {typeof reviewCount === "number" ? (
                <span className="ptr-chip-count">
                  <bdi>{formatNumber(reviewCount, lang)}</bdi>
                </span>
              ) : scopedCountsPending ? (
                <span
                  className="ptr-chip-count opacity-60"
                  aria-hidden="true"
                >
                  …
                </span>
              ) : null}
            </button>
          )}
        </div>

        <div className="asarak-feed-deck__actions">
          {/* Visible Inline Sort Selector */}
          <label className="asarak-inline-sort">
            <ArrowUpDown size={14} aria-hidden="true" className="shrink-0 ptr-muted" />
            <span className="sr-only">{t("filters.sort")}</span>
            <select
              value={value.sort}
              aria-label={t("filters.sort")}
              onChange={(event) => {
                const nextSort =
                  sortOptions.find((item) => item === event.target.value) ??
                  defaultFilters.sort;
                onChange({ ...value, sort: nextSort });
              }}
            >
              {sortOptions.map((sortOpt) => (
                <option key={sortOpt} value={sortOpt}>
                  {t(`sort.${sortOpt}`)}
                </option>
              ))}
            </select>
          </label>

          {onViewChange && (
            <div className="asarak-segmented" role="group" aria-label={t("view.toggle")}>
              <button
                type="button"
                aria-pressed={view === "grid"}
                aria-label={t("view.grid")}
                title={t("view.grid")}
                onClick={() => onViewChange("grid")}
              >
                <LayoutGrid size={15} aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-pressed={view === "list"}
                aria-label={t("view.list")}
                title={t("view.list")}
                onClick={() => onViewChange("list")}
              >
                <List size={15} aria-hidden="true" />
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
            {modalActiveCount > 0 && (
              <span className="ptr-badge ptr-badge-variant">
                {formatNumber(modalActiveCount, lang)}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Row 4: Individually Removable Active Filter Chips */}
      {removableChips.length > 0 && (
        <div className="asarak-active-filters" role="status">
          {removableChips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              className="asarak-active-pill"
              onClick={chip.onRemove}
              aria-label={t("feed.removeFilter", { label: chip.label })}
            >
              <span>{chip.label}</span>
              <X size={12} aria-hidden="true" />
            </button>
          ))}
          <button
            type="button"
            className="ptr-link text-xs"
            onClick={() => onChange(defaultFilters)}
          >
            {t("feed.resetAll")}
          </button>
        </div>
      )}

      {/* Deep Filters Modal (Store, Brand, Verdict, Sort) */}
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
