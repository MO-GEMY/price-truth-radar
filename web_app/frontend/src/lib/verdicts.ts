import { BadgeCheck, MinusCircle, ShieldAlert, TrendingDown, TrendingUp, type LucideIcon } from "lucide-react";
import type { DiscountVerdict } from "@/types/contract";

export const VERDICT_TONES: Record<DiscountVerdict, { icon: LucideIcon; className: string }> = {
  FAKE_DISCOUNT: { icon: ShieldAlert, className: "ptr-badge-warning" },
  ALL_TIME_LOW: { icon: TrendingDown, className: "ptr-badge-good" },
  GENUINE_DEAL: { icon: BadgeCheck, className: "ptr-badge-good" },
  PRESALE_HIKE: { icon: TrendingUp, className: "ptr-badge-amber" },
  NORMAL_PRICE: { icon: MinusCircle, className: "" },
};

export const VERDICT_ORDER = Object.keys(VERDICT_TONES) as DiscountVerdict[];
