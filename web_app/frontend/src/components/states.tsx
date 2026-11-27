"use client";

import { RefreshCw } from "lucide-react";
import { useLanguage } from "@/lib/i18n";

function Skeleton({ className }: { className: string }) {
  return <div className={"skeleton " + className} aria-hidden="true" />;
}

export function CompareCardSkeletons() {
  return <div className="space-y-3">
    {[0, 1, 2, 3].map((item) => <div className="surface p-4 ptr-match-summary" key={item}>
      <Skeleton className="h-6" />
      <Skeleton className="h-10" />
    </div>)}
  </div>;
}

export function DetailSkeleton() {
  return <div className="space-y-4">
    <Skeleton className="h-5 w-32" />
    <div className="ptr-product-heading">
      <Skeleton className="ptr-product-photo" />
      <Skeleton className="h-8 w-2/3" />
    </div>
    <div className="grid gap-4 sm:grid-cols-2"><Skeleton className="h-44" /><Skeleton className="h-44" /></div>
    <Skeleton className="h-36" />
  </div>;
}

export function ErrorState({ onRetry, message }: { onRetry?: () => void; message?: string }) {
  const { t } = useLanguage();
  return (
    <div className="surface ptr-empty">
      <p role="alert">{message ?? t("common.error")}</p>
      {onRetry && <button type="button" className="ptr-button" onClick={onRetry}>
        <RefreshCw size={15} aria-hidden="true" />{t("common.retry")}
      </button>}
    </div>
  );
}
