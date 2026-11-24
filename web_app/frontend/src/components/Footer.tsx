"use client";

import Link from "next/link";
import { useLanguage } from "@/lib/i18n";
import { translations } from "@/lib/translations";
import { AsarakLogo } from "./AsarakLogo";
import { VerdictLegend } from "./VerdictLegend";

const LEGAL_LINKS = [
  { href: "/coupons", key: "footer.coupons" },
  { href: "/about", key: "footer.about" },
  { href: "/privacy", key: "footer.privacy" },
  { href: "/terms", key: "footer.terms" },
  { href: "/disclaimer", key: "footer.disclaimer" },
  { href: "/contact", key: "footer.contact" },
  { href: "/add-store", key: "footer.addStore" },
] as const;

export function Footer() {
  const { lang, t } = useLanguage();
  return (
    <footer className="ptr-footer">
      <div className="ptr-wrap ptr-footer-inner">
        <div className="ptr-footer-meta">
          <Link href="/" className="w-fit" aria-label="أسعارك | Asarak">
            <AsarakLogo variant="dark" size="sm" />
          </Link>
          <p className="text-slate-200 font-medium">{t("footer.note")}</p>
          <div className="ptr-footer-disclaimer">
            {lang === "en" && (
              <p className="ptr-footer-disclosure" lang="en">
                {t("footer.independenceDisclaimer")}
              </p>
            )}
            {/* Arabic is the authoritative wording: it stays on every page in every language. */}
            <p className="ptr-footer-disclosure" dir="rtl" lang="ar">
              {translations.ar["footer.independenceDisclaimer"]}
            </p>
          </div>
          <nav className="ptr-footer-links" aria-label={t("footer.linksLabel")}>
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
