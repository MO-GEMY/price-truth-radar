"use client";

import { CloudOff } from "lucide-react";
import { isApiConfigured, type DataSource } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

/**
 * Subtle indicator shown ONLY while the UI is serving contract-matching mock
 * data (i.e. `NEXT_PUBLIC_API_URL` is empty or the backend is unreachable).
 */
export function MockBanner({ source, onRetry }: { source: DataSource | null; onRetry?: () => void }) {
  const { t } = useLanguage();
  if (source !== "mock") return null;

  return (
    <div className="ptr-notice ptr-warning flex-wrap">
      <CloudOff className="size-4 shrink-0" aria-hidden="true" />
      <p role="status">{t(isApiConfigured() ? "mock.banner" : "ui.sample")}</p>
      {onRetry && isApiConfigured() && <button type="button" className="ptr-link" onClick={onRetry}>{t("common.retry")}</button>}
    </div>
  );
}
