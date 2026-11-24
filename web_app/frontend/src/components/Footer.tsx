"use client";

import Link from "next/link";
import { useLanguage } from "@/lib/i18n";
import { VerdictLegend } from "./VerdictLegend";

const LEGAL_LINKS = [
  { href: "/about", key: "footer.about" },
  { href: "/privacy", key: "footer.privacy" },
  { href: "/terms", key: "footer.terms" },
  { href: "/contact", key: "footer.contact" },
] as const;

export function Footer() {
  const { t } = useLanguage();
  return (
    <footer className="ptr-footer">
      <div className="ptr-wrap ptr-footer-inner">
        <div className="ptr-footer-meta">
          <p>{t("footer.note")}</p>
          <nav className="ptr-footer-links" aria-label={t("footer.about")}>
            {LEGAL_LINKS.map(({ href, key }) => (
              <Link key={href} href={href} className="ptr-link">
                {t(key)}
              </Link>
            ))}
          </nav>
        </div>
        <VerdictLegend />
      </div>
    </footer>
  );
}
