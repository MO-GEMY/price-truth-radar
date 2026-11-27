"use client";

import { useMemo, useSyncExternalStore } from "react";
import type { FeedCategoryFilter } from "@/types/contract";
import type { TranslationKey } from "./translations";

const changeEvent = "ptr:browse-state";

export const categoryLabels = {
  all: "filters.catAll",
  electronics: "filters.catElectronics",
  home_appliances: "filters.catHomeAppliances",
  home_furniture: "filters.catHomeFurniture",
  fashion: "filters.catFashion",
  beauty: "filters.catBeauty",
  groceries: "filters.catGroceries",
  health: "filters.catHealth",
  sports: "filters.catSports",
  pet_care: "filters.catPetCare",
  baby_kids: "filters.catBabyKids",
} as const satisfies Record<FeedCategoryFilter, TranslationKey>;

export const categories = Object.keys(categoryLabels) as FeedCategoryFilter[];

export function parseCategory(value: string | null): FeedCategoryFilter {
  return categories.find((category) => category === value) ?? "all";
}

export function categoryLabelKey(category: string | null | undefined): TranslationKey | null {
  if (!category || category === "all") return null;
  const parsed = categories.find((c) => c === category);
  return parsed ? categoryLabels[parsed] : null;
}

/**
 * Filter visible category pills to categories that actually have >0 products
 * (always keeping "all" and the currently selected category). When counts have
 * not loaded yet or are empty, falls back to the full canonical list.
 */
export function visibleCategories(
  counts: Record<string, number> | null | undefined,
  selected: FeedCategoryFilter = "all",
): FeedCategoryFilter[] {
  if (!counts) return categories;
  const populated = categories.filter(
    (cat) => cat !== "all" && ((counts[cat] ?? 0) > 0 || cat === selected),
  );
  return populated.length > 0 ? ["all", ...populated] : categories;
}

export function parsePage(value: string | null): number {
  const page = Number(value);
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(changeEvent, callback);
  window.addEventListener("popstate", callback);
  return () => {
    window.removeEventListener(changeEvent, callback);
    window.removeEventListener("popstate", callback);
  };
}

export function useBrowseParams(): URLSearchParams {
  const value = useSyncExternalStore(subscribe, () => window.location.search, () => "");
  return useMemo(() => new URLSearchParams(value), [value]);
}

export function setBrowseParams(values: Record<string, string | number | undefined>, replace = false): void {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined) url.searchParams.delete(key);
    else url.searchParams.set(key, String(value));
  }
  if (url.href === window.location.href) return;
  if (replace) window.history.replaceState(null, "", url);
  else window.history.pushState(null, "", url);
  window.dispatchEvent(new Event(changeEvent));
}

export function browseHref(path: "/" | "/deals" | "/compare", params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function safeBrowseHref(value: string | null | undefined): string | null {
  if (!value?.startsWith("/") || value.startsWith("//")) return null;
  const url = new URL(value, "https://local.invalid");
  return url.origin === "https://local.invalid" && ["/", "/deals", "/compare"].includes(url.pathname)
    ? url.pathname + url.search
    : null;
}

export function productHref(id: string, from?: string, sample = false): string {
  const route = `/products/${encodeURIComponent(id)}`;
  const origin = safeBrowseHref(from);
  const query = new URLSearchParams();
  if (origin) query.set("from", origin);
  if (sample) query.set("sample", "1");
  return query.size ? `${route}?${query}` : route;
}
