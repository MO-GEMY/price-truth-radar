"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeftRight,
  BellRing,
  Globe,
  Moon,
  Search,
  Sparkles,
  Store,
  Sun,
  Tag,
} from "lucide-react";
import {
  browseHref,
  safeBrowseHref,
  setBrowseParams,
  useBrowseParams,
} from "@/lib/browse-state";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { useSavedAlerts } from "@/lib/saved-alerts";
import { useTheme } from "@/lib/theme";
import { AsarakLogo } from "./AsarakLogo";

// `wideOnly` tabs hide below 1120px (and remain accessible via the footer)
// so the 4 primary tabs fit cleanly beside the brand & actions on laptops/tablets.
const destinations = [
  { href: "/", text: "nav.feed", icon: Search, wideOnly: false },
  { href: "/deals", text: "nav.deals", icon: Sparkles, wideOnly: false },
  { href: "/compare", text: "nav.compare", icon: ArrowLeftRight, wideOnly: false },
  { href: "/coupons", text: "nav.coupons", icon: Tag, wideOnly: false },
  { href: "/add-store", text: "nav.addStore", icon: Store, wideOnly: true },
] as const;

export function Header() {
  const { lang, ready, t, toggleLang } = useLanguage();
  const { theme, ready: themeReady, toggleTheme } = useTheme();
  const { count: alertsCount, hydrated: alertsHydrated } = useSavedAlerts();
  const pathname = usePathname();
  const query = useBrowseParams();
  const origin = pathname.startsWith("/products/")
    ? safeBrowseHref(query.get("from"))?.split("?")[0]
    : null;
  const active = origin ?? pathname;

  return (
    <header className="ptr-mast" data-tour="mast">
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

        <nav className="ptr-nav" aria-label={t("ui.navigation")} data-tour="nav">
          {destinations.map(({ href, text, icon: Icon, wideOnly }) => (
            <Link
              key={href}
              className={wideOnly ? "ptr-nav-secondary" : undefined}
              // Only browse tabs carry filters; "/add-store" and "/coupons" link cleanly as-is.
              href={
                pathname === href && href !== "/add-store" && href !== "/coupons"
                  ? browseHref(href, query)
                  : href
              }
              aria-current={active === href ? "page" : undefined}
            >
              <Icon size={16} strokeWidth={2.1} aria-hidden="true" />
              <span>{t(text)}</span>
            </Link>
          ))}
        </nav>

        <div className="ptr-mast-actions">
          <Link
            href="/my-alerts"
            className="ptr-alerts-nav-btn"
            aria-current={pathname === "/my-alerts" ? "page" : undefined}
            aria-label={
              alertsHydrated && alertsCount > 0
                ? `${t("nav.myAlerts")} (${formatNumber(alertsCount, lang)})`
                : t("nav.myAlerts")
            }
            title={t("nav.myAlerts")}
          >
            <BellRing size={17} strokeWidth={2} aria-hidden="true" />
            <span className="ptr-alerts-nav-label">{t("nav.myAlerts")}</span>
            {alertsHydrated && alertsCount > 0 && (
              <span className="ptr-alerts-nav-badge" aria-hidden="true">
                <bdi>{alertsCount > 99 ? "99+" : formatNumber(alertsCount, lang)}</bdi>
              </span>
            )}
          </Link>
          <Link
            href="/?tour=1"
            className="ptr-button ptr-tour-replay"
            data-tour="tour-replay"
            aria-label={t("tour.replay")}
            title={t("tour.replay")}
            onClick={
              pathname === "/"
                ? (event) => {
                    // Already on the homepage: set the param through the
                    // browse-state store so the tour opens without a reload.
                    event.preventDefault();
                    setBrowseParams({ tour: "1" });
                  }
                : undefined
            }
          >
            <Sparkles size={15} strokeWidth={2} aria-hidden="true" />
            <span className="ptr-tour-replay-label">{t("tour.replay")}</span>
          </Link>
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
