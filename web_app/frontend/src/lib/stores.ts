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
  /* ---- Verified (Wave 3 candidates) ---- */
  seoudi: {
    name: { en: "Seoudi", ar: "سعودي" },
    domain: "seoudisupermarket.com",
    accent: "#f97316",
    urlLookup: true,
  },
  raneen: {
    name: { en: "Raneen", ar: "رنين" },
    domain: "raneen.com",
    accent: "#8b5cf6",
    urlLookup: true,
  },
  rayashop: {
    name: { en: "Raya Shop", ar: "راية شوب" },
    domain: "rayashop.com",
    accent: "#0ea5e9",
    urlLookup: true,
  },
  /* ---- Fashion & footwear candidates ---- */
  ravin: { name: { en: "Ravin", ar: "رافين" }, domain: "ravin.eg", accent: "#f43f5e", urlLookup: true },
  activ: {
    name: { en: "Activ Abou Alaa", ar: "أكتيف أبو علاء" },
    domain: "activaboualaa.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  mobaco: { name: { en: "Mobaco", ar: "موباكو" }, domain: "mobaco.com", accent: "#84cc16", urlLookup: true },
  concrete: {
    name: { en: "Concrete", ar: "كونكريت" },
    domain: "concrete.com.eg",
    accent: "#64748b",
    urlLookup: true,
  },
  tiehouse: {
    name: { en: "Tie House", ar: "تاي هاوس" },
    domain: "tiehouse.com",
    accent: "#a16207",
    urlLookup: true,
  },
  khotwh: { name: { en: "Khotwh", ar: "خطوة" }, domain: "khotwh.com", accent: "#059669", urlLookup: true },
  carina: { name: { en: "Carina", ar: "كارينا" }, domain: "carinawear.com", accent: "#ec4899", urlLookup: true },
  tomato: { name: { en: "Tomato", ar: "توماتو" }, domain: "tomato.com.eg", accent: "#dc2626", urlLookup: true },
  mitcha: { name: { en: "Mitcha", ar: "ميتشا" }, domain: "mitcha.com", accent: "#c084fc", urlLookup: true },
  lcwaikiki: {
    name: { en: "LC Waikiki", ar: "إل سي وايكيكي" },
    domain: "lcwaikiki.eg",
    accent: "#2563eb",
    urlLookup: true,
  },
  defacto: {
    name: { en: "DeFacto", ar: "ديفاكتو" },
    domain: "defacto.com",
    accent: "#475569",
    urlLookup: true,
  },
  /* ---- Groceries & food candidates ---- */
  gourmet: {
    name: { en: "Gourmet Egypt", ar: "جورميه مصر" },
    domain: "gourmetegypt.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  metro_market: {
    name: { en: "Metro Market", ar: "مترو ماركت" },
    domain: "metro-markets.com",
    accent: "#eab308",
    urlLookup: true,
  },
  oscar: { name: { en: "Oscar", ar: "أوسكار" }, domain: "oscarstores.com", accent: "#14b8a6", urlLookup: true },
  abu_auf: { name: { en: "Abu Auf", ar: "أبو عوف" }, domain: "abuauf.com", accent: "#92400e", urlLookup: true },
  imtenan: { name: { en: "Imtenan", ar: "امتنان" }, domain: "imtenan.com", accent: "#65a30d", urlLookup: true },
  fathalla: {
    name: { en: "Fathalla Market", ar: "فتح الله ماركت" },
    domain: "fathallamarket.com",
    accent: "#0891b2",
    urlLookup: true,
  },
  breadfast: {
    name: { en: "Breadfast", ar: "بريدفاست" },
    domain: "breadfast.com",
    accent: "#fb923c",
    urlLookup: false,
  },
  talabat_eg: {
    name: { en: "Talabat Egypt", ar: "طلبات مصر" },
    domain: "talabat.com",
    accent: "#ff5a00",
    urlLookup: true,
  },
  /* ---- Electronics, PC & appliances candidates ---- */
  elaraby: {
    name: { en: "El Araby", ar: "العربي جروب" },
    domain: "elarabygroup.com",
    accent: "#b91c1c",
    urlLookup: true,
  },
  compuscience: {
    name: { en: "CompuScience", ar: "كومبيوساينس" },
    domain: "compuscience.com.eg",
    accent: "#7c3aed",
    urlLookup: true,
  },
  elbadr: {
    name: { en: "El Badr Group", ar: "البدر جروب" },
    domain: "elbadrgroupeg.store",
    accent: "#facc15",
    urlLookup: true,
  },
  compumarts: {
    name: { en: "CompuMarts", ar: "كومبيومارتس" },
    domain: "compumarts.com",
    accent: "#0e7490",
    urlLookup: true,
  },
  egyptlaptop: {
    name: { en: "Egypt Laptop", ar: "إيجيبت لابتوب" },
    domain: "egyptlaptop.com",
    accent: "#334155",
    urlLookup: true,
  },
  dubaiphone: {
    name: { en: "Dubai Phone", ar: "دبي فون" },
    domain: "dubaiphone.net",
    accent: "#ea580c",
    urlLookup: true,
  },
  tradeline: {
    name: { en: "Tradeline", ar: "تريدلاين" },
    domain: "tradelineegypt.com",
    accent: "#16a34a",
    urlLookup: true,
  },
  cairosales: {
    name: { en: "Cairo Sales", ar: "كايرو سيلز" },
    domain: "cairosales.com",
    accent: "#db2777",
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
