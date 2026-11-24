"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeftRight,
  Globe,
  Moon,
  Search,
  Sparkles,
  Store,
  Sun,
} from "lucide-react";
import { browseHref, safeBrowseHref, useBrowseParams } from "@/lib/browse-state";
import { useLanguage } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import { AsarakLogo } from "./AsarakLogo";

// `wideOnly` tabs do not fit beside the brand and the toggles on tablets and
// are hidden there by `.ptr-nav-secondary` (they still show in the mobile tab bar).
const destinations = [
  { href: "/", text: "nav.feed", icon: Search, wideOnly: false },
  { href: "/deals", text: "nav.deals", icon: Sparkles, wideOnly: false },
  { href: "/compare", text: "nav.compare", icon: ArrowLeftRight, wideOnly: false },
  { href: "/add-store", text: "nav.addStore", icon: Store, wideOnly: true },
] as const;

export function Header() {
  const { lang, ready, t, toggleLang } = useLanguage();
  const { theme, ready: themeReady, toggleTheme } = useTheme();
  const pathname = usePathname();
  const query = useBrowseParams();
  const origin = pathname.startsWith("/products/")
    ? safeBrowseHref(query.get("from"))?.split("?")[0]
    : null;
  const active = origin ?? pathname;

  return (
    <header className="ptr-mast">
      <a href="#main-content" className="ptr-skip">
        {t("ui.skip")}
      </a>
      <div className="ptr-wrap ptr-mast-inner">
        <Link
          href={pathname === "/" ? browseHref("/", query) : "/"}
          className="ptr-brand"
          aria-label="أسعارك | Asarak"
        >
          <AsarakLogo variant="auto" size="md" />
        </Link>

        <nav className="ptr-nav" aria-label={t("ui.navigation")}>
          {destinations.map(({ href, text, icon: Icon, wideOnly }) => (
            <Link
              key={href}
              className={wideOnly ? "ptr-nav-secondary" : undefined}
              // Only browse tabs carry filters; "/add-store" links to itself as-is.
              href={pathname === href && href !== "/add-store" ? browseHref(href, query) : href}
              aria-current={active === href ? "page" : undefined}
            >
              <Icon size={16} strokeWidth={2.1} aria-hidden="true" />
              <span>{t(text)}</span>
            </Link>
          ))}
        </nav>

        <div className="ptr-mast-actions">
          <button
            type="button"
            className="ptr-theme-toggle"
            disabled={!themeReady}
            onClick={toggleTheme}
            aria-label={t(theme === "dark" ? "theme.toLight" : "theme.toDark")}
            title={t(theme === "dark" ? "theme.toLight" : "theme.toDark")}
          >
            {theme === "dark" ? (
              <Sun size={18} strokeWidth={2} aria-hidden="true" />
            ) : (
              <Moon size={18} strokeWidth={2} aria-hidden="true" />
            )}
          </button>

          <button
            className="ptr-button ptr-language"
            type="button"
            lang={lang === "en" ? "ar" : "en"}
            disabled={!ready}
            onClick={toggleLang}
            aria-label={
              lang === "en" ? "Switch to Arabic" : "التبديل إلى الإنجليزية"
            }
          >
            <Globe size={15} strokeWidth={2} aria-hidden="true" />
            <span>{t("lang.toggle")}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
