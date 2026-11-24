"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Copy, ExternalLink, Filter, Tag } from "lucide-react";
import type { CouponItem, CouponScope } from "@/types/contract";
import { fetchCoupons } from "@/lib/api";
import { outboundLinkRel } from "@/lib/affiliate";
import { categoryLabelKey } from "@/lib/browse-state";
import { isCouponExpired, isTrustedCoupon } from "@/lib/coupons";
import { useCairoToday } from "@/lib/use-cairo-today";
import { formatDate, formatNumber, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";
import { StoreBadge } from "@/components/StoreBadge";

const SCOPE_TABS: ReadonlyArray<{
  value: "all" | CouponScope;
  labelKey:
    | "coupons.scopeAll"
    | "coupons.scopeGeneral"
    | "coupons.scopeBank"
    | "coupons.scopeFirstOrder"
    | "coupons.scopeSeasonal";
}> = [
  { value: "all", labelKey: "coupons.scopeAll" },
  { value: "general", labelKey: "coupons.scopeGeneral" },
  { value: "bank", labelKey: "coupons.scopeBank" },
  { value: "first_order", labelKey: "coupons.scopeFirstOrder" },
  { value: "seasonal", labelKey: "coupons.scopeSeasonal" },
];

const SCOPE_LABEL_KEY: Record<
  CouponScope,
  | "coupons.scopeGeneral"
  | "coupons.scopeBank"
  | "coupons.scopeFirstOrder"
  | "coupons.scopeSeasonal"
> = {
  general: "coupons.scopeGeneral",
  bank: "coupons.scopeBank",
  first_order: "coupons.scopeFirstOrder",
  seasonal: "coupons.scopeSeasonal",
};

export function CouponsDirectory({
  initialCoupons,
}: {
  initialCoupons: CouponItem[];
}) {
  const { lang, t } = useLanguage();
  const [coupons, setCoupons] = useState<CouponItem[]>(initialCoupons);
  const [scope, setScope] = useState<"all" | CouponScope>("all");
  const [storeId, setStoreId] = useState<string>("all");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  useEffect(() => {
    if (initialCoupons.length > 0) return;
    const controller = new AbortController();
    fetchCoupons(undefined, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted && res?.items) {
          setCoupons(res.items);
        }
      })
      .catch(() => {
        /* Ignore fallback fetch errors */
      });
    return () => controller.abort();
  }, [initialCoupons.length]);

  const today = useCairoToday();
  // The API only publishes verified, unexpired codes; this also covers pages served from cache
  const live = useMemo(
    () => coupons.filter((c) => isTrustedCoupon(c) && !isCouponExpired(c, today)),
    [coupons, today],
  );

  const storeOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const coupon of live) {
      if (!map.has(coupon.store_id)) {
        map.set(
          coupon.store_id,
          lang === "ar"
            ? coupon.store_name_ar || storeDisplayName(coupon.store_id, "ar")
            : storeDisplayName(coupon.store_id, "en"),
        );
      }
    }
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [live, lang]);

  const filtered = useMemo(() => {
    return live.filter((c) => {
      if (scope !== "all" && c.scope !== scope) return false;
      if (storeId !== "all" && c.store_id !== storeId) return false;
      return true;
    });
  }, [live, scope, storeId]);

  async function handleCopy(coupon: CouponItem) {
    const key = `${coupon.store_id}:${coupon.code}`;
    try {
      await navigator.clipboard.writeText(coupon.code);
      setCopiedKey(key);
      window.setTimeout(() => {
        setCopiedKey((prev) => (prev === key ? null : prev));
      }, 2000);
    } catch {
      /* Clipboard unavailable */
    }
  }

  return (
    <div className="ptr-wrap ptr-page">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">{t("coupons.eyebrow")}</p>
        <h1>{t("coupons.title")}</h1>
        <p className="ptr-muted max-w-2xl">{t("coupons.subtitle")}</p>
      </header>

      <section
        className="surface p-4 sm:p-5 space-y-4"
        aria-label={t("filters.title")}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label={t("coupons.title")}
          >
            {SCOPE_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                className="ptr-chip"
                aria-pressed={scope === tab.value}
                onClick={() => setScope(tab.value)}
              >
                {t(tab.labelKey)}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 min-w-[200px]">
            <Filter size={15} className="ptr-muted shrink-0" aria-hidden="true" />
            <label htmlFor="coupons-store-filter" className="sr-only">
              {t("coupons.storeFilter")}
            </label>
            <select
              id="coupons-store-filter"
              className="ptr-field !mt-0 !min-h-[38px] !py-1.5 text-sm"
              value={storeId}
              onChange={(event) => setStoreId(event.target.value)}
            >
              <option value="all">{t("coupons.allStores")}</option>
              {storeOptions.map(([slug, label]) => (
                <option key={slug} value={slug}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <p className="text-xs ptr-muted">
          {t("coupons.count", {
            count: formatNumber(filtered.length, lang),
          })}
        </p>
      </section>

      {filtered.length === 0 ? (
        <section className="surface p-8 text-center space-y-2">
          <p className="font-bold text-base">
            {t(live.length === 0 ? "coupons.emptyNone" : "coupons.empty")}
          </p>
          <p className="text-sm ptr-muted">
            {t(live.length === 0 ? "coupons.emptyNoneHint" : "coupons.emptyHint")}
          </p>
        </section>
      ) : (
        <div className="ptr-coupons-grid">
          {filtered.map((coupon) => {
            const key = `${coupon.store_id}:${coupon.code}`;
            const isCopied = copiedKey === key;
            const discountLabel =
              coupon.discount_type === "percent"
                ? t("coupons.percentOff", {
                    value: formatNumber(coupon.value, lang),
                  })
                : t("coupons.fixedOff", {
                    amount: formatPrice(coupon.value, lang),
                  });

            return (
              <article key={key} className="surface ptr-coupon-card">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <StoreBadge name={coupon.store_id} size="sm" />
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="ptr-badge ptr-badge-good">
                      <Tag size={12} aria-hidden="true" />
                      {discountLabel}
                    </span>
                    <span className="ptr-badge">
                      {t(SCOPE_LABEL_KEY[coupon.scope])}
                    </span>
                    {categoryLabelKey(coupon.category) && (
                      <span className="ptr-badge">
                        {t(categoryLabelKey(coupon.category)!)}
                      </span>
                    )}
                  </div>
                </div>

                <h2 className="text-base font-bold leading-snug" dir="rtl">
                  {coupon.title_ar}
                </h2>

                {coupon.notes_ar && (
                  <p className="text-xs ptr-muted leading-relaxed" dir="rtl">
                    {coupon.notes_ar}
                  </p>
                )}

                <div className="flex flex-wrap gap-1.5 text-xs ptr-muted">
                  {coupon.min_order != null && coupon.min_order > 0 && (
                    <span className="ptr-badge">
                      {t("coupons.minOrder", {
                        amount: formatPrice(coupon.min_order, lang),
                      })}
                    </span>
                  )}
                  {coupon.max_discount != null && coupon.max_discount > 0 && (
                    <span className="ptr-badge">
                      {t("coupons.maxDiscount", {
                        amount: formatPrice(coupon.max_discount, lang),
                      })}
                    </span>
                  )}
                  {coupon.expires_at && (
                    <span className="ptr-badge">
                      {t("coupons.expires", {
                        date: formatDate(coupon.expires_at, lang),
                      })}
                    </span>
                  )}
                  {coupon.verified_at && (
                    <span className="ptr-badge ptr-badge-good">
                      {t("coupons.verifiedOn", {
                        date: formatDate(coupon.verified_at, lang),
                      })}
                    </span>
                  )}
                </div>

                <div className="ptr-coupon-actions">
                  <div className="ptr-coupon-code-box" dir="ltr">
                    <span className="ptr-mono font-bold tracking-wider">
                      {coupon.code}
                    </span>
                  </div>
                  <button
                    type="button"
                    className={`ptr-button ptr-small-button ${isCopied ? "ptr-primary" : ""}`}
                    onClick={() => void handleCopy(coupon)}
                  >
                    {isCopied ? (
                      <>
                        <Check size={14} aria-hidden="true" />
                        <span>{t("coupons.copied")}</span>
                      </>
                    ) : (
                      <>
                        <Copy size={14} aria-hidden="true" />
                        <span>{t("coupons.copyCode")}</span>
                      </>
                    )}
                  </button>
                  {coupon.affiliate_url && (
                    <a
                      href={coupon.affiliate_url}
                      target="_blank"
                      rel={outboundLinkRel(true)}
                      className="ptr-button ptr-primary ptr-small-button"
                    >
                      <span>{t("coupons.openStore")}</span>
                      <ExternalLink size={13} aria-hidden="true" />
                    </a>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <p className="text-xs ptr-muted leading-relaxed">
        {t("coupons.disclaimer")}
      </p>
    </div>
  );
}
