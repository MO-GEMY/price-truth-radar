"use client";

import { Store } from "lucide-react";

export function StoreBadge({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-cyan-400/25 bg-cyan-400/10 font-semibold text-cyan-200 ${
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs"
      }`}
    >
      <Store className={size === "sm" ? "size-3" : "size-3.5"} />
      {name}
    </span>
  );
}
