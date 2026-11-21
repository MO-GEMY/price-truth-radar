"use client";

import {
  BadgeCheck,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  MinusCircle,
  type LucideIcon,
} from "lucide-react";
import type { DiscountVerdict } from "@/types/contract";
import { useLanguage } from "@/lib/i18n";

/**
 * Color-coded verdict badges (design direction):
 *  FAKE_DISCOUNT → red/crimson · PRESALE_HIKE → amber · ALL_TIME_LOW → emerald
 *  GENUINE_DEAL → teal · NORMAL_PRICE → slate
 */
const VERDICT_STYLES: Record<
  DiscountVerdict,
  { icon: LucideIcon; className: string; glow: string }
> = {
  FAKE_DISCOUNT: {
    icon: ShieldAlert,
    className: "border-rose-500/35 bg-rose-500/12 text-rose-300",
    glow: "shadow-[0_0_16px_rgba(244,63,94,0.18)]",
  },
  PRESALE_HIKE: {
    icon: TrendingUp,
    className: "border-amber-500/35 bg-amber-500/12 text-amber-300",
    glow: "shadow-[0_0_16px_rgba(245,158,11,0.16)]",
  },
  ALL_TIME_LOW: {
    icon: TrendingDown,
    className: "border-emerald-500/35 bg-emerald-500/12 text-emerald-300",
    glow: "shadow-[0_0_16px_rgba(16,185,129,0.18)]",
  },
  GENUINE_DEAL: {
    icon: BadgeCheck,
    className: "border-teal-500/35 bg-teal-500/12 text-teal-300",
    glow: "shadow-[0_0_16px_rgba(20,184,166,0.16)]",
  },
  NORMAL_PRICE: {
    icon: MinusCircle,
    className: "border-slate-500/35 bg-slate-500/12 text-slate-300",
    glow: "",
  },
};

export function VerdictBadge({
  verdict,
  size = "md",
}: {
  verdict: DiscountVerdict;
  size?: "sm" | "md";
}) {
  const { t } = useLanguage();
  const style = VERDICT_STYLES[verdict];
  const Icon = style.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-semibold ${style.className} ${style.glow} ${
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs"
      }`}
    >
      <Icon className={size === "sm" ? "size-3" : "size-3.5"} strokeWidth={2.2} />
      {t(`verdict.${verdict}`)}
    </span>
  );
}
