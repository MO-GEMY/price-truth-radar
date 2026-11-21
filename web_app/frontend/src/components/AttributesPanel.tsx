"use client";

import { Cpu, Shirt } from "lucide-react";
import type { Product } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";
import { formatNumber } from "@/lib/format";

const ATTR_LABEL_KEYS: Record<string, TranslationKey> = {
  ram_gb: "attr.ram_gb",
  storage_gb: "attr.storage_gb",
  screen_size_inch: "attr.screen_size_inch",
  screen_inches: "attr.screen_size_inch",
  refresh_hz: "attr.refresh_hz",
  refresh_rate_hz: "attr.refresh_hz",
  panel: "attr.panel",
  anc: "attr.anc",
  battery_hours: "attr.battery_hours",
  warranty: "attr.warranty",
  two_b_category: "attr.store_category",
  btech_category: "attr.store_category",
  sigma_category: "attr.store_category",
  noon_category: "attr.store_category",
  jumia_category: "attr.store_category",
  shopify_product_type: "attr.store_category",
  store_category: "attr.store_category",
};

function prettify(value: string): string {
  const cleaned = value.replace(/_/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function attributeLabel(key: string, t: (k: TranslationKey) => string): string {
  const known = ATTR_LABEL_KEYS[key];
  if (known) return t(known);
  if (key.endsWith("_category")) return t("attr.store_category");
  return prettify(key);
}

export function AttributesPanel({ product }: { product: Product }) {
  const { lang, t } = useLanguage();
  const attrs = product.attributes_json ?? {};

  /* -------- Fashion: available-sizes pill grid -------- */
  if (product.category === "fashion") {
    const available = (attrs["available_sizes"] as string[] | undefined) ?? [];
    const total = (attrs["total_sizes"] as number | undefined) ?? available.length;

    return (
      <div className="glass rounded-2xl p-5">
        <h3 className="flex items-center gap-2 text-sm font-bold text-white">
          <Shirt className="size-4 text-emerald-400" />
          {t("detail.sizes")}
        </h3>
        {available.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {available.map((size) => (
              <span
                key={size}
                className="flex size-11 items-center justify-center rounded-xl border border-emerald-500/40 bg-emerald-500/12 text-sm font-bold text-emerald-300"
              >
                {size}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm font-semibold text-rose-300">{t("card.outOfStock")}</p>
        )}
        <p className="num mt-4 text-xs text-slate-400">
          {t("detail.sizesSummary", { available: formatNumber(available.length, lang), total: formatNumber(total, lang) })}
        </p>
        {product.scarcity_flag ? (
          <p className="mt-2 text-xs font-semibold text-amber-300">{t("card.lowStock")}</p>
        ) : null}
      </div>
    );
  }

const HIDDEN_INTERNAL_KEYS = new Set([
  "product_id",
  "variant_id",
  "offer_id",
  "magento_product_id",
  "amazon_query",
]);

  /* -------- Electronics: specification rows -------- */
  const entries = Object.entries(attrs).filter(
    ([key, value]) => !HIDDEN_INTERNAL_KEYS.has(key) && value !== null && value !== undefined && value !== "",
  );
  if (entries.length === 0) return null;

  const renderValue = (key: string, value: unknown): string => {
    if (typeof value === "boolean") return value ? t("common.yes") : t("common.no");
    if (typeof value === "number") {
      if (key === "warranty") return String(value);
      return formatNumber(value, lang);
    }
    if (Array.isArray(value)) {
      return value.map((item) => prettify(String(item))).join(", ");
    }
    const str = String(value);
    if (key === "warranty" && (str === "local" || str === "international")) {
      return t(`detail.warranty.${str}`);
    }
    return str.includes("_") ? prettify(str) : str;
  };

  return (
    <div className="glass rounded-2xl p-5">
      <h3 className="flex items-center gap-2 text-sm font-bold text-white">
        <Cpu className="size-4 text-cyan-400" />
        {t("detail.attributes")}
      </h3>
      <dl className="mt-4 divide-y divide-white/[0.06]">
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-4 py-2.5">
            <dt className="shrink-0 text-xs font-medium text-slate-400">{attributeLabel(key, t)}</dt>
            <dd className="num min-w-0 break-words text-end text-sm font-semibold text-slate-100">
              {renderValue(key, value)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
