"use client";

import type { DiscountVerdict } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import {
  DEFAULT_VERDICT_TONE,
  getVerdictTone,
  normalizeVerdict,
} from "@/lib/verdicts";

export function VerdictBadge({
  verdict,
  size = "md",
}: {
  verdict: DiscountVerdict | string | null | undefined;
  size?: "sm" | "md";
}) {
  const { t } = useLanguage();
  const safeVerdict = normalizeVerdict(verdict);
  const { icon: Icon, className } = getVerdictTone(safeVerdict) ?? DEFAULT_VERDICT_TONE;
  return (
    <span className={`ptr-badge ${className}`}>
      <Icon size={size === "sm" ? 12 : 14} aria-hidden="true" />
      {t(`verdict.${safeVerdict}`)}
    </span>
  );
}
