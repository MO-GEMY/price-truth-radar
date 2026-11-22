"use client";

import { Radar } from "lucide-react";
import { useLanguage } from "@/lib/i18n";

export function Footer() {
  const { t } = useLanguage();
  return (
    <footer className="mt-16 border-t border-white/[0.06] bg-[#020408]/60 py-8">
      <div className="mx-auto flex max-w-7xl flex-col items-center gap-2 px-4 text-center text-xs text-slate-500 sm:px-6">
        <span className="flex items-center gap-2 font-semibold text-slate-300">
          <Radar className="size-3.5 text-teal-400" />
          {t("brand.name")}
        </span>
        <p>{t("footer.note")}</p>
      </div>
    </footer>
  );
}
