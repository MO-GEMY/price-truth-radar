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
