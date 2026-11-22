"use client";

import { useLanguage } from "@/lib/i18n";
import { storeAccent, storeDisplayName } from "@/lib/stores";

export function StoreBadge({
  name,
  size = "md",
}: {
  name: string;
  size?: "sm" | "md";
}) {
  const { lang } = useLanguage();
  const label = storeDisplayName(name, lang);
  const accent = storeAccent(name);

  return (
    <span
      className={`ptr-store ${size === "sm" ? "text-[11px]" : "text-xs"}`}
    >
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: accent }}
        aria-hidden
      />
      <bdi>{label}</bdi>
    </span>
  );
}
