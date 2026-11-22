"use client";

import { useEffect, useRef, useState } from "react";
import { HelpCircle } from "lucide-react";
import type { DiscountVerdict } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";
import { VERDICT_TONES } from "@/lib/verdicts";

export function VerdictBadge({
  verdict,
  size = "md",
  showInfo = false,
}: {
  verdict: DiscountVerdict;
  size?: "sm" | "md";
  /** Renders an interactive `?` info popover beside the badge (ideal on /compare). */
  showInfo?: boolean;
}) {
  const { t } = useLanguage();
  const tone = VERDICT_TONES[verdict];
  const Icon = tone.icon;

  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const explainText =
    verdict === "FAKE_DISCOUNT"
      ? t("verdict.honestyTooltip")
      : t(`explain.${verdict}` as TranslationKey);

  const badge = (
    <span
      title={explainText}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-semibold ${tone.badge} ${
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"
      }`}
    >
      <Icon className={size === "sm" ? "size-3 shrink-0" : "size-3.5 shrink-0"} strokeWidth={2.2} />
      <span>{t(`verdict.${verdict}`)}</span>
    </span>
  );

  if (!showInfo) return badge;

  return (
    <span ref={wrapRef} className="relative inline-flex items-center gap-1">
      {badge}
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-label={t("verdict.honestyAria")}
        aria-expanded={open}
        className="inline-flex size-5 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/10 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/60"
      >
        <HelpCircle className="size-3.5" />
      </button>

      {open ? (
        <span
          role="tooltip"
          className="surface absolute bottom-full end-0 z-50 mb-2 w-64 rounded-xl p-3 text-start text-xs leading-relaxed text-slate-200 shadow-2xl sm:w-72"
        >
          <span className={`mb-1 block text-[11px] font-bold ${tone.text}`}>
            {t(`verdict.${verdict}`)}
          </span>
          {explainText}
        </span>
      ) : null}
    </span>
  );
}
