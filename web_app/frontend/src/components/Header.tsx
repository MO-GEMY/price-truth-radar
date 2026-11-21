"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeftRight, Languages, Radar } from "lucide-react";
import { useLanguage } from "@/lib/i18n";

export function Header() {
  const { t, toggleLang, lang } = useLanguage();
  const pathname = usePathname();

  const navLink = (href: string, label: string, icon: React.ReactNode) => {
    const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
    return (
      <Link
        href={href}
        className={`flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-medium transition-colors ${
          active
            ? "bg-cyan-400/15 text-cyan-300 ring-1 ring-cyan-400/30"
            : "text-slate-300 hover:bg-white/5 hover:text-white"
        }`}
      >
        {icon}
        <span className="hidden sm:inline">{label}</span>
      </Link>
    );
  };

  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-[#05080f]/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-emerald-500 text-[#04121a] shadow-[0_0_24px_rgba(34,211,238,0.35)]">
            <Radar className="size-5" strokeWidth={2.4} />
          </span>
          <span className="leading-tight">
            <span className="block text-sm font-bold tracking-tight text-white sm:text-base">
              {t("brand.name")}
            </span>
            <span className="hidden text-[11px] text-slate-400 md:block">
              {t("brand.tagline")}
            </span>
          </span>
        </Link>

        <div className="flex items-center gap-2">
          <nav className="flex items-center gap-1.5">
            {navLink("/", t("nav.feed"), <Radar className="size-4" />)}
            {navLink(
              "/compare",
              t("nav.compare"),
              <ArrowLeftRight className="size-4" />,
            )}
          </nav>
          <button
            type="button"
            onClick={toggleLang}
            aria-label={lang === "en" ? "Switch to Arabic" : "التبديل إلى الإنجليزية"}
            title={t("lang.toggle")}
            className="ms-1 flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-semibold text-slate-200 transition-colors hover:border-cyan-400/40 hover:text-cyan-300"
          >
            <Languages className="size-4" />
            <span>{t("lang.toggle")}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
