"use client";

import { useLanguage } from "@/lib/i18n";
import { VerdictLegend } from "./VerdictLegend";

export function Footer() {
  const { t } = useLanguage();
  return (
    <footer className="ptr-footer">
      <div className="ptr-wrap ptr-footer-inner">
        <p>{t("footer.note")}</p>
        <VerdictLegend />
      </div>
    </footer>
  );
}
