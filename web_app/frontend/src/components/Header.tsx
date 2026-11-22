"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Radar } from "lucide-react";
import { browseHref, safeBrowseHref, useBrowseParams } from "@/lib/browse-state";
import { useLanguage } from "@/lib/i18n";

const destinations = [
  { href: "/", text: "nav.feed" },
  { href: "/deals", text: "nav.deals" },
  { href: "/compare", text: "nav.compare" },
] as const;

export function Header() {
  const { lang, ready, t, toggleLang } = useLanguage();
  const pathname = usePathname();
  const query = useBrowseParams();
  const origin = pathname.startsWith("/products/") ? safeBrowseHref(query.get("from"))?.split("?")[0] : null;
  const active = origin ?? pathname;

  return (
    <header className="ptr-mast">
      <a href="#main-content" className="ptr-skip">{t("ui.skip")}</a>
      <div className="ptr-wrap ptr-mast-inner">
        <Link href={pathname === "/" ? browseHref("/", query) : "/"} className="ptr-brand">
          <span className="ptr-mark"><Radar size={20} strokeWidth={2.1} aria-hidden="true" /></span>
          <span>{t("brand.name")}</span>
        </Link>
        <nav className="ptr-nav" aria-label={t("ui.navigation")}>
          {destinations.map(({ href, text }) => (
            <Link key={href} href={pathname === href ? browseHref(href, query) : href}
              aria-current={active === href ? "page" : undefined}>{t(text)}</Link>
          ))}
        </nav>
        <button className="ptr-button ptr-language" type="button" lang={lang === "en" ? "ar" : "en"}
          disabled={!ready} onClick={toggleLang} aria-label={lang === "en" ? "Switch to Arabic" : "التبديل إلى الإنجليزية"}>
          {t("lang.toggle")}
        </button>
      </div>
    </header>
  );
}
