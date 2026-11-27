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

export function FeedResultSkeleton({ view = "grid" }: { view?: "list" | "grid" }) {
  const { t } = useLanguage();
  if (view === "grid") {
    return (
      <div className="asarak-product-grid" role="status">
        <span className="sr-only">{t("common.loading")}</span>
        {[0, 1, 2, 3, 4, 5].map((item) => (
          <div key={item} className="surface p-4 space-y-3" aria-hidden="true">
            <div className="skeleton aspect-[4/3] w-full rounded-xl" />
            <div className="skeleton h-4 w-3/4" />
            <div className="skeleton h-4 w-1/2" />
            <div className="skeleton h-6 w-1/3" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="surface ptr-list" role="status">
      <span className="sr-only">{t("common.loading")}</span>
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="ptr-list-skeleton" aria-hidden="true">
          <span className="skeleton" />
          <span className="skeleton" />
          <span className="skeleton" />
        </div>
      ))}
    </div>
  );
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
