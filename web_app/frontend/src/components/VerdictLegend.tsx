"use client";

import { useState } from "react";
import { ChevronDown, HelpCircle, Info } from "lucide-react";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";
import { VERDICT_ORDER, VERDICT_TONES } from "@/lib/verdicts";

/**
 * Unobtrusive, scannable verdict legend bar for both the Radar Feed and
 * `/compare`. Always surfaces the key Fake Discount vs. Cheapest distinction,
 * with a 1-click expandable breakdown of all 5 verdicts.
 */
export function VerdictLegend({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-white/[0.08] bg-[#070c15]/90 px-3.5 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <p className="flex min-w-0 flex-1 items-start gap-2 text-xs leading-relaxed text-slate-400">
          <Info className="mt-0.5 size-3.5 shrink-0 text-teal-400/90" />
          <span>{t("verdict.fakeDiscountNote")}</span>
        </p>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] font-semibold text-slate-300 transition hover:border-teal-400/35 hover:text-white"
        >
          <HelpCircle className="size-3.5 text-teal-400" />
          <span>{open ? t("verdict.legendClose") : t("verdict.legendToggle")}</span>
          <ChevronDown
            className={`size-3 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {open ? (
        <div className="mt-3 grid gap-2 border-t border-white/[0.07] pt-3 sm:grid-cols-2 lg:grid-cols-5">
          {VERDICT_ORDER.map((verdict) => {
            const tone = VERDICT_TONES[verdict];
            const Icon = tone.icon;
            return (
              <div
                key={verdict}
                className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5"
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={`inline-flex size-5 shrink-0 items-center justify-center rounded-md border ${tone.chip}`}
                  >
                    <Icon className="size-3" strokeWidth={2.2} />
                  </span>
                  <span className={`text-xs font-bold ${tone.text}`}>
                    {t(`verdict.${verdict}`)}
                  </span>
                </div>
                <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
                  {t(`explain.${verdict}` as TranslationKey)}
                </p>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
