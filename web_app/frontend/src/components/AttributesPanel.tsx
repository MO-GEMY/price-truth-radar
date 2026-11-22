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
  pack_size: "attr.pack_size",
  net_weight_g: "attr.net_weight_g",
  net_volume_ml: "attr.net_volume_ml",
  two_b_category: "attr.store_category",
  btech_category: "attr.store_category",
  sigma_category: "attr.store_category",
  noon_category: "attr.store_category",
  jumia_category: "attr.store_category",
  shopify_product_type: "attr.store_category",
  store_category: "attr.store_category",
};

const HIDDEN_INTERNAL_KEYS = new Set([
  "product_id",
  "variant_id",
  "offer_id",
  "magento_product_id",
  "amazon_query",
]);

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
    const rawSizes = attrs.available_sizes;
    const available = Array.isArray(rawSizes)
      ? [...new Set(rawSizes.filter((size): size is string => typeof size === "string" && Boolean(size.trim())))]
      : [];
    const total = typeof attrs.total_sizes === "number" && attrs.total_sizes > 0 ? attrs.total_sizes : null;

    return (
      <section className="surface ptr-section">
        <h2 className="flex items-center gap-2">
          <Shirt className="size-4" aria-hidden="true" />
          {t("detail.sizes")}
        </h2>
        {available.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {available.map((size) => (
              <span
                key={size}
                className="ptr-badge ptr-badge-good"
              >
                {size}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm ptr-muted">{t(product.in_stock ? "ui.sizesUnavailable" : "card.outOfStock")}</p>
        )}
        {total !== null && Array.isArray(rawSizes) && <p className="num mt-4 text-xs ptr-muted">
          {t("detail.sizesSummary", {
            available: formatNumber(available.length, lang),
            total: formatNumber(total, lang),
          })}
        </p>}
        {product.scarcity_flag ? (
          <p className="mt-2 text-xs ptr-error">{t("card.lowStock")}</p>
        ) : null}
      </section>
    );
  }

  /* -------- Electronics & Home Appliances: crisp 2-column spec sheet -------- */
  const labels = new Set<string>();
  const entries = Object.entries(attrs).filter(([key, value]) => {
    if (HIDDEN_INTERNAL_KEYS.has(key) || value == null || value === "" ||
      (typeof value === "object" && (!Array.isArray(value) || !value.length ||
        value.some((item) => item == null || typeof item === "object")))) return false;
    const label = attributeLabel(key, t);
    if (labels.has(label)) return false;
    labels.add(label);
    return true;
  });
  if (entries.length === 0) return null;

  const renderValue = (key: string, value: unknown): string => {
    if (typeof value === "boolean") return value ? t("common.yes") : t("common.no");
    if (typeof value === "number") {
      if (key === "ram_gb" || key === "storage_gb") return `${formatNumber(value, lang)} GB`;
      if (key === "refresh_hz" || key === "refresh_rate_hz")
        return `${formatNumber(value, lang)} Hz`;
      if (key === "screen_size_inch" || key === "screen_inches")
        return `${formatNumber(value, lang)}"`;
      if (key === "net_weight_g") return `${formatNumber(value, lang)} g`;
      if (key === "net_volume_ml") return `${formatNumber(value, lang)} ml`;
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
    <section className="surface ptr-section">
      <h2 className="flex items-center gap-2">
        <Cpu className="size-4" aria-hidden="true" />
        {t("detail.attributes")}
      </h2>
      <dl className="ptr-specs">
        {entries.map(([key, value]) => (
          <div
            key={key}
          >
            <dt className="text-sm ptr-muted">
              {attributeLabel(key, t)}
            </dt>
            <dd className="num min-w-0 break-words text-end text-sm font-semibold">
              <bdi>{renderValue(key, value)}</bdi>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
