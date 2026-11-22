"use client";

import { useLanguage } from "@/lib/i18n";
import { storeAccent, storeDisplayName } from "@/lib/stores";

export function StoreBadge({
  name,
  size = "md",
  variant = "dark",
}: {
  name: string;
  size?: "sm" | "md";
  /** Use `light` when docked directly over a white studio thumbnail frame. */
  variant?: "dark" | "light";
}) {
  const { lang } = useLanguage();
  const label = storeDisplayName(name, lang);
  const accent = storeAccent(name);

  const tone =
    variant === "light"
      ? "border-slate-900/10 bg-white/95 text-slate-800 shadow-sm backdrop-blur-sm"
      : "border-white/10 bg-white/[0.05] text-slate-200";

  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-full border font-semibold ${tone} ${
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"
      }`}
    >
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: accent }}
        aria-hidden
      />
      <span className="truncate">{label}</span>
    </span>
  );
}
