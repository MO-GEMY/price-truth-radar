/**
 * Display metadata for tracked Egyptian retailers. API payloads always carry
 * the raw `store_name` slug (CONTRACTS.md); this module only maps slugs to
 * polished, bilingual display names and a subtle brand accent dot.
 */

import type { Lang } from "./i18n";

export interface StoreMeta {
  name: { en: string; ar: string };
  domain: string;
  /** Brand accent used only for a small identity dot. */
  accent: string;
  /** Whether pasted product links from this store are matched by direct lookup. */
  urlLookup: boolean;
}

export const STORE_META: Record<string, StoreMeta> = {
  noon: { name: { en: "Noon", ar: "نون" }, domain: "noon.com", accent: "#f5e400", urlLookup: true },
  amazon_eg: {
    name: { en: "Amazon.eg", ar: "أمازون مصر" },
    domain: "amazon.eg",
    accent: "#ff9900",
    urlLookup: true,
  },
  btech: { name: { en: "B.Tech", ar: "بي تك" }, domain: "btech.com", accent: "#ef4444", urlLookup: true },
  "2b": { name: { en: "2B", ar: "2B" }, domain: "2b.com.eg", accent: "#3b82f6", urlLookup: true },
  sigma: {
    name: { en: "Sigma", ar: "سيجما" },
    domain: "sigma-computer.com",
    accent: "#22d3ee",
    urlLookup: true,
  },
  town_team: {
    name: { en: "Town Team", ar: "تاون تيم" },
    domain: "townteam.com",
    accent: "#cbd5e1",
    urlLookup: true,
  },
  dejavu: { name: { en: "Dejavu", ar: "ديجافو" }, domain: "dejavu.shoes", accent: "#e879f9", urlLookup: true },
  dalydress: {
    name: { en: "Daly Dress", ar: "دالي دريس" },
    domain: "dalydress.com",
    accent: "#f9a8d4",
    urlLookup: true,
  },
  spinneys: {
    name: { en: "Spinneys", ar: "سبينيس" },
    domain: "spinneys-egypt.com",
    accent: "#10b981",
    urlLookup: true,
  },
  hyperone: {
    name: { en: "HyperOne", ar: "هايبر وان" },
    domain: "hyperone.com.eg",
    accent: "#e11d48",
    urlLookup: true,
  },
};

/** Stores highlighted in the direct-link guidance (largest catalogs first). */
export const FEATURED_LINK_STORES = ["noon", "amazon_eg", "btech", "2b", "sigma"] as const;

function prettifySlug(slug: string): string {
  return slug
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function storeDisplayName(slug: string, lang: Lang): string {
  const meta = STORE_META[slug];
  if (meta) return meta.name[lang];
  return prettifySlug(slug) || slug;
}

export function storeAccent(slug: string): string {
  return STORE_META[slug]?.accent ?? "#64748b";
}
