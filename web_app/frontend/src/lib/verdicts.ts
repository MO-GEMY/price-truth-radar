/**
 * Semantic verdict tone system.
 *  Emerald → ALL_TIME_LOW / GENUINE_DEAL (buy signals)
 *  Rose/Coral → FAKE_DISCOUNT / PRESALE_HIKE (honesty warnings)
 *  Slate → NORMAL_PRICE (baseline)
 */

import {
  BadgeCheck,
  MinusCircle,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import type { DiscountVerdict } from "@/types/contract";

export interface VerdictTone {
  icon: LucideIcon;
  /** Compact pill badge */
  badge: string;
  /** Full-width explanatory banner */
  banner: string;
  /** Icon chip inside banners / legends */
  chip: string;
  /** Text accent */
  text: string;
}

export const VERDICT_TONES: Record<DiscountVerdict, VerdictTone> = {
  ALL_TIME_LOW: {
    icon: TrendingDown,
    badge: "border-emerald-400/40 bg-emerald-950/90 text-emerald-200",
    banner: "border-emerald-400/25 bg-emerald-500/[0.07]",
    chip: "border-emerald-400/30 bg-emerald-500/15 text-emerald-300",
    text: "text-emerald-300",
  },
  GENUINE_DEAL: {
    icon: BadgeCheck,
    badge: "border-emerald-400/30 bg-emerald-950/80 text-emerald-200",
    banner: "border-emerald-400/20 bg-emerald-500/[0.05]",
    chip: "border-emerald-400/25 bg-emerald-500/10 text-emerald-300",
    text: "text-emerald-300",
  },
  FAKE_DISCOUNT: {
    icon: ShieldAlert,
    badge: "border-rose-400/45 bg-rose-950/90 text-rose-200",
    banner: "border-rose-400/25 bg-rose-500/[0.07]",
    chip: "border-rose-400/30 bg-rose-500/15 text-rose-300",
    text: "text-rose-300",
  },
  PRESALE_HIKE: {
    icon: TrendingUp,
    badge: "border-coral-400/40 bg-[#2a0d14]/90 text-coral-300",
    banner: "border-coral-400/25 bg-coral-400/[0.06]",
    chip: "border-coral-400/30 bg-coral-400/12 text-coral-300",
    text: "text-coral-300",
  },
  NORMAL_PRICE: {
    icon: MinusCircle,
    badge: "border-slate-500/40 bg-slate-900/90 text-slate-200",
    banner: "border-slate-500/25 bg-slate-500/[0.06]",
    chip: "border-slate-500/30 bg-slate-500/12 text-slate-300",
    text: "text-slate-300",
  },
};

export const VERDICT_ORDER: DiscountVerdict[] = [
  "FAKE_DISCOUNT",
  "PRESALE_HIKE",
  "NORMAL_PRICE",
  "GENUINE_DEAL",
  "ALL_TIME_LOW",
];
