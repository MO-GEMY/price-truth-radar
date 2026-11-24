"use client";

import { useState } from "react";
import { Check, Copy, Tag } from "lucide-react";
import type { ApplicableCoupon } from "@/types/contract";
import { formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { isCouponExpired } from "@/lib/coupons";
import { useCairoToday } from "@/lib/use-cairo-today";

export function CouponPill({
  coupons,
  estimatedPrice,
  compact = false,
}: {
  coupons?: ApplicableCoupon[];
  estimatedPrice?: number | null;
  compact?: boolean;
}) {
  const { lang, t } = useLanguage();
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  // Product pages are cached for a day: retire codes that expired since the page was rendered
  const today = useCairoToday();
  const live = (coupons ?? []).filter((coupon) => !isCouponExpired(coupon, today));

  if (live.length === 0) return null;
  const best = live[0];
  const displayEst =
    typeof estimatedPrice === "number" && estimatedPrice > 0
      ? estimatedPrice
      : best.estimated_price;

  async function copy(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedCode(code);
      window.setTimeout(() => {
        setCopiedCode((prev) => (prev === code ? null : prev));
      }, 1800);
    } catch {
      /* Clipboard unavailable */
    }
  }

  return (
    <div
      className={`ptr-coupon-inline ${compact ? "ptr-coupon-inline--compact" : ""}`}
      title={best.title_ar}
    >
      <button
        type="button"
        className="ptr-coupon-code-pill"
        onClick={(event) => {
          event.stopPropagation();
          void copy(best.code);
        }}
        aria-label={`${t("coupons.copyCode")} ${best.code}`}
      >
        <Tag size={12} aria-hidden="true" />
        <span className="ptr-mono font-bold" dir="ltr">
          {best.code}
        </span>
        {copiedCode === best.code ? (
          <Check size={12} aria-hidden="true" />
        ) : (
          <Copy size={11} aria-hidden="true" />
        )}
      </button>
      <span className="ptr-coupon-est">
        {t("coupons.estAfterCode")}:{" "}
        <bdi className="ptr-mono font-bold">{formatPrice(displayEst, lang)}</bdi>
      </span>
    </div>
  );
}
