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
    className: "border-rose-500/45 bg-rose-950/85 text-rose-200 backdrop-blur-md",
    glow: "shadow-[0_0_16px_rgba(244,63,94,0.22)]",
  },
  PRESALE_HIKE: {
    icon: TrendingUp,
    className: "border-amber-500/45 bg-amber-950/85 text-amber-200 backdrop-blur-md",
    glow: "shadow-[0_0_16px_rgba(245,158,11,0.2)]",
  },
  ALL_TIME_LOW: {
    icon: TrendingDown,
    className: "border-emerald-500/45 bg-emerald-950/85 text-emerald-200 backdrop-blur-md",
    glow: "shadow-[0_0_16px_rgba(16,185,129,0.22)]",
  },
  GENUINE_DEAL: {
    icon: BadgeCheck,
    className: "border-teal-500/45 bg-teal-950/85 text-teal-200 backdrop-blur-md",
    glow: "shadow-[0_0_16px_rgba(20,184,166,0.2)]",
  },
  NORMAL_PRICE: {
    icon: MinusCircle,
    className: "border-slate-500/45 bg-slate-900/85 text-slate-200 backdrop-blur-md",
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
      title={t(`explain.${verdict}`)}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-semibold ${style.className} ${style.glow} ${
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs"
      }`}
    >
      <Icon className={size === "sm" ? "size-3" : "size-3.5"} strokeWidth={2.2} />
      {t(`verdict.${verdict}`)}
    </span>
  );
}
