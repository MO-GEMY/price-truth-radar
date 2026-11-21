"use client";

import { CloudOff } from "lucide-react";
import type { DataSource } from "@/lib/api";
import { isApiConfigured } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

/**
 * Subtle indicator shown ONLY while the UI is serving contract-matching mock
 * data (i.e. `NEXT_PUBLIC_API_URL` is empty or the backend is unreachable).
 */
export function MockBanner({ source }: { source: DataSource | null }) {
  const { t } = useLanguage();
  if (source !== "mock") return null;

  return (
    <div className="border-b border-amber-400/20 bg-amber-400/[0.07]">
      <p className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-2 text-xs font-medium text-amber-300/90 sm:px-6">
        <CloudOff className="size-3.5 shrink-0" />
        <span>
          {t("mock.banner")}
          {!isApiConfigured() ? "" : ""}
        </span>
      </p>
    </div>
  );
}
