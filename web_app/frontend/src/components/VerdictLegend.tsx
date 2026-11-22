"use client";

import { useLanguage } from "@/lib/i18n";
import { VERDICT_ORDER } from "@/lib/verdicts";
import { VerdictBadge } from "./VerdictBadge";

export function VerdictLegend() {
  const { t } = useLanguage();
  return (
    <details className="ptr-method">
      <summary className="ptr-link">{t("verdict.legendToggle")}</summary>
      <div className="space-y-3 pt-3">
        <p className="ptr-muted">{t("verdict.fakeDiscountNote")}</p>
        {VERDICT_ORDER.map((verdict) => <div key={verdict}>
          <VerdictBadge verdict={verdict} />
          <p className="ptr-muted mt-1">{t(`explain.${verdict}`)}</p>
        </div>)}
      </div>
    </details>
  );
}
