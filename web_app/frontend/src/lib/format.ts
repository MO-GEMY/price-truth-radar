/**
 * Locale-aware formatting helpers (prices in EGP, percentages, dates).
 * Uses Latin digits even in Arabic (ar-EG-u-nu-latn) for readability of
 * financial figures.
 */

import type { Lang } from "./i18n";

export function formatPrice(
  value: number | null | undefined,
  lang: Lang,
  opts?: { maximumFractionDigits?: number },
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const formatter = new Intl.NumberFormat(
    lang === "ar" ? "ar-EG-u-nu-latn" : "en-EG",
    {
      style: "currency",
      currency: "EGP",
      maximumFractionDigits: opts?.maximumFractionDigits ?? 2,
      minimumFractionDigits: 0,
    },
  );
  return formatter.format(value);
}

export function formatNumber(value: number, lang: Lang): string {
  return new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US").format(value);
}

/** Signed percentage, e.g. "+12.4%" / "-2.8%". */
export function formatPct(value: number, lang: Lang, digits = 1): string {
  const formatter = new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
    signDisplay: "exceptZero",
  });
  return `${formatter.format(value)}%`;
}

export function formatPctPlain(value: number, lang: Lang, digits = 1): string {
  const formatter = new Intl.NumberFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
  return `${formatter.format(value)}%`;
}

export function formatDate(iso: string, lang: Lang): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn-ca-gregory" : "en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatDateTime(iso: string, lang: Lang): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn-ca-gregory" : "en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Africa/Cairo",
  }).format(date);
}

/** "2026-10-01" → "01 Oct" style axis ticks. */
export function formatChartTick(iso: string, lang: Lang): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn-ca-gregory" : "en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

const SUBCATEGORY_LABELS: Record<string, { en: string; ar: string }> = {
  smartphones: { en: "Smartphones", ar: "هواتف ذكية" },
  laptops: { en: "Laptops", ar: "لابتوب" },
  monitors: { en: "Monitors", ar: "شاشات" },
  tablets: { en: "Tablets", ar: "تابلت" },
  headphones: { en: "Headphones", ar: "سماعات" },
  wearables: { en: "Wearables", ar: "ساعات ذكية" },
  gaming: { en: "Gaming", ar: "ألعاب" },
  gaming_consoles: { en: "Gaming Consoles", ar: "أجهزة ألعاب" },
  peripherals: { en: "Peripherals", ar: "ملحقات كمبيوتر" },
  storage: { en: "Storage", ar: "وحدات تخزين" },
  memory: { en: "Memory", ar: "رامات" },
  gpus: { en: "Graphics Cards", ar: "كروت شاشة" },
  cpus: { en: "Processors", ar: "معالجات" },
  motherboards: { en: "Motherboards", ar: "لوحات أم" },
  cases: { en: "PC Cases", ar: "كيسات كمبيوتر" },
  cooling: { en: "Cooling", ar: "تبريد" },
  power_supplies: { en: "Power Supplies", ar: "باور سبلاي" },
  networking: { en: "Networking", ar: "شبكات" },
  printers: { en: "Printers", ar: "طابعات" },
  accessories: { en: "Accessories", ar: "إكسسوارات" },
  tvs: { en: "TVs", ar: "تلفزيونات" },
  air_conditioners: { en: "Air Conditioners", ar: "تكييفات" },
  refrigerators: { en: "Refrigerators", ar: "ثلاجات" },
  freezers: { en: "Freezers", ar: "ديب فريزر" },
  washing_machines: { en: "Washing Machines", ar: "غسالات" },
  dishwashers: { en: "Dishwashers", ar: "غسالات أطباق" },
  microwaves: { en: "Microwaves", ar: "ميكروويف" },
  ovens: { en: "Ovens", ar: "أفران" },
  cookers: { en: "Cookers", ar: "بوتاجازات" },
  vacuums: { en: "Vacuums", ar: "مكانس كهربائية" },
  water_heaters: { en: "Water Heaters", ar: "سخانات مياه" },
  fans: { en: "Fans", ar: "مراوح" },
  kitchen_appliances: { en: "Kitchen Appliances", ar: "أجهزة مطبخ" },
  large_appliances: { en: "Large Appliances", ar: "أجهزة كبيرة" },
  small_appliances: { en: "Small Appliances", ar: "أجهزة صغيرة" },
  tees: { en: "T-Shirts", ar: "تيشيرتات" },
  t_shirts: { en: "T-Shirts", ar: "تيشيرتات" },
  polos: { en: "Polos", ar: "بولو" },
  polo_shirts: { en: "Polos", ar: "بولو" },
  shirts: { en: "Shirts", ar: "قمصان" },
  tops: { en: "Tops", ar: "بلوزات وتوبات" },
  hoodies: { en: "Hoodies", ar: "هوديز" },
  sweatshirts: { en: "Sweatshirts", ar: "سويت شيرت" },
  knitwear: { en: "Knitwear", ar: "تريكو" },
  jackets: { en: "Jackets", ar: "جواكيت" },
  outerwear: { en: "Outerwear", ar: "ملابس خارجية" },
  jeans: { en: "Jeans", ar: "جينز" },
  pants: { en: "Pants", ar: "بنطلونات" },
  trousers: { en: "Trousers", ar: "بنطلونات" },
  shorts: { en: "Shorts", ar: "شورتات" },
  bottoms: { en: "Bottoms", ar: "بنطلونات" },
  dresses: { en: "Dresses", ar: "فساتين" },
  skirts: { en: "Skirts", ar: "جيبات" },
  clothing: { en: "Clothing", ar: "ملابس" },
  apparel: { en: "Apparel", ar: "ملابس" },
  shoes: { en: "Shoes", ar: "أحذية" },
  sneakers: { en: "Sneakers", ar: "سنيكرز" },
  footwear: { en: "Footwear", ar: "أحذية" },
  boots: { en: "Boots", ar: "بوت" },
  sandals: { en: "Sandals", ar: "صنادل" },
  heels: { en: "Heels", ar: "كعب عالي" },
  bags: { en: "Bags", ar: "شنط" },
  handbags: { en: "Handbags", ar: "شنط يد" },
  oils_ghee: { en: "Oils & Ghee", ar: "زيوت وسمن" },
  rice_pasta: { en: "Rice & Pasta", ar: "أرز ومكرونة" },
  dairy_cheese: { en: "Dairy & Cheese", ar: "ألبان وأجبان" },
  tea_coffee: { en: "Tea & Coffee", ar: "شاي وقهوة" },
  canned_sauces: { en: "Canned & Sauces", ar: "معلبات وصلصات" },
  beverages: { en: "Beverages", ar: "مشروبات" },
  detergents: { en: "Detergents", ar: "منظفات" },
};

export function formatSubCategory(slug: string, lang: Lang): string {
  const key = slug.trim().toLowerCase().replace(/[\s-]+/g, "_");
  const mapped = SUBCATEGORY_LABELS[key];
  if (mapped) return mapped[lang];
  return slug
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

/**
 * Compact grocery size chip from `attributes_json` — e.g. "1L", "500g",
 * "6 × 1L". Reads `pack_size` (verbatim string) first, then derives a short
 * label from `net_weight_g` / `net_volume_ml`. Returns null when the product
 * carries no size info, so non-grocery cards stay uncluttered.
 */
export function formatPackSize(
  attrs: Record<string, unknown> | null | undefined,
): string | null {
  if (!attrs) return null;
  const packSize = attrs["pack_size"];
  if (typeof packSize === "string" && packSize.trim().length > 0) {
    return packSize.trim();
  }
  const weight = attrs["net_weight_g"];
  if (typeof weight === "number" && Number.isFinite(weight) && weight > 0) {
    return weight >= 1000 ? `${trimZeros(weight / 1000)}kg` : `${trimZeros(weight)}g`;
  }
  const volume = attrs["net_volume_ml"];
  if (typeof volume === "number" && Number.isFinite(volume) && volume > 0) {
    return volume >= 1000 ? `${trimZeros(volume / 1000)}L` : `${trimZeros(volume)}ml`;
  }
  return null;
}

function trimZeros(value: number): string {
  return String(Math.round(value * 100) / 100);
}

/* ------------------------------------------------------------------ */
/* Unit price (EGP/kg, EGP/L) — shrinkflation transparency             */
/* ------------------------------------------------------------------ */

export interface UnitPriceInput {
  unit_price_egp?: number | null;
  unit_price_unit?: "kg" | "L" | string | null;
  current_price?: number;
  attributes_json?: Record<string, unknown> | null;
}

const AR_UNIT: Record<string, string> = { kg: "كجم", L: "لتر" };

/**
 * Bilingual unit-price caption — e.g. "EGP 35.5 / kg" (EN) or "35.5 ج.م./كجم" (AR).
 *
 * Resolution order:
 *  1. backend-provided `unit_price_egp` (+ `unit_price_unit`, defaulting to kg);
 *  2. graceful client-side fallback from `current_price` ÷ `net_weight_g` (kg)
 *     or `net_volume_ml` (L) in `attributes_json`;
 *  3. null when nothing is derivable, so non-grocery products stay uncluttered.
 */
export function formatUnitPrice(
  input: UnitPriceInput | null | undefined,
  lang: Lang,
): string | null {
  if (!input) return null;

  let value: number | null = null;
  let unit: string | null = null;

  const provided = input.unit_price_egp;
  if (typeof provided === "number" && Number.isFinite(provided) && provided > 0) {
    value = provided;
    unit =
      input.unit_price_unit && String(input.unit_price_unit).trim().length > 0
        ? String(input.unit_price_unit).trim().toLowerCase() === "l"
          ? "L"
          : String(input.unit_price_unit).trim().toLowerCase()
        : "kg";
  } else {
    const price = input.current_price;
    const attrs = input.attributes_json;
    if (typeof price !== "number" || !Number.isFinite(price) || price <= 0 || !attrs) {
      return null;
    }
    const weight = attrs["net_weight_g"];
    const volume = attrs["net_volume_ml"];
    if (typeof weight === "number" && Number.isFinite(weight) && weight > 0) {
      value = (price * 1000) / weight;
      unit = "kg";
    } else if (typeof volume === "number" && Number.isFinite(volume) && volume > 0) {
      value = (price * 1000) / volume;
      unit = "L";
    }
  }

  if (value === null || unit === null || !Number.isFinite(value) || value <= 0) return null;

  const digits = value >= 100 ? 0 : 1;
  const formatted = new Intl.NumberFormat(
    lang === "ar" ? "ar-EG-u-nu-latn" : "en-US",
    { maximumFractionDigits: digits, minimumFractionDigits: 0 },
  ).format(value);

  if (lang === "ar") {
    const unitAr = AR_UNIT[unit] ?? unit;
    return `${formatted} ج.م./${unitAr}`;
  }
  return `EGP ${formatted} / ${unit}`;
}

/* ------------------------------------------------------------------ */
/* Bilingual (AR/EN) search query normalization                        */
/* ------------------------------------------------------------------ */

/** Arabic diacritics (harakat) + tatweel — pure noise for search matching. */
const AR_DIACRITICS_RE = /[\u064B-\u0652\u0670\u0640]/g;

/**
 * Light cleaning for the PRIMARY search attempt: trim, collapse internal
 * whitespace, strip diacritics/tatweel. Letters are left untouched so the
 * user's spelling matches store titles exactly (ILIKE substring semantics).
 */
export function cleanSearchQuery(raw: string): string {
  return raw
    .replace(AR_DIACRITICS_RE, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Aggressive Arabic normalization for the SECOND search attempt (only used
 * when the primary query returns zero results). Unifies the letters Egyptian
 * retailers spell inconsistently across stores:
 * - alef variants (أ إ آ ٱ) → ا
 * - alef maksura ى → ي
 * - teh marbuta ة → ه
 * - thaa ث → ت (تلاجة / ثلاجة are the same product informally)
 */
export function normalizeArabicAggressive(raw: string): string {
  return cleanSearchQuery(raw)
    .replace(/[أإآٱ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/ث/g, "ت");
}

/** True when the query contains Arabic-script characters. */
export function hasArabicChars(raw: string): boolean {
  return /[\u0600-\u06FF]/.test(raw);
}
