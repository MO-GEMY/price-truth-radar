"use client";

import type { DiscountVerdict } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import { VERDICT_TONES } from "@/lib/verdicts";

export function VerdictBadge({ verdict, size = "md" }: { verdict: DiscountVerdict; size?: "sm" | "md" }) {
  const { t } = useLanguage();
  const { icon: Icon, className } = VERDICT_TONES[verdict];
  return (
    <span className={`ptr-badge ${className}`}>
      <Icon size={size === "sm" ? 12 : 14} aria-hidden="true" />
      {t(`verdict.${verdict}`)}
    </span>
  );
}
