"use client";

import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { useLanguage } from "@/lib/i18n";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function KpiSkeletons({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className="surface rounded-2xl p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="size-8 rounded-lg" />
            </div>
            <Skeleton className="mt-3.5 h-8 w-24" />
            <Skeleton className="mt-2.5 h-3.5 w-32" />
          </div>
        ))}
      </div>
      <Skeleton className="h-9 w-full rounded-xl" />
    </div>
  );
}

export function ProductCardSkeletons({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="surface overflow-hidden rounded-2xl">
          <div className="p-2.5 pb-0">
            <Skeleton className="aspect-[4/3] w-full rounded-xl" />
          </div>
          <div className="space-y-3 p-4 pt-3.5">
            <div className="flex items-center justify-between gap-2">
              <Skeleton className="h-5 w-16 rounded-full" />
              <Skeleton className="h-5 w-24 rounded-full" />
            </div>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-6 w-28" />
            <div className="flex gap-2">
              <Skeleton className="h-5 w-20 rounded-md" />
              <Skeleton className="h-5 w-16 rounded-md" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function CompareCardSkeletons({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="surface rounded-2xl p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Skeleton className="h-5 w-2/3 sm:w-1/2" />
            <Skeleton className="h-8 w-36 rounded-xl" />
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-6 w-40" />
      <div className="surface rounded-2xl p-6">
        <div className="flex flex-col gap-6 md:flex-row">
          <Skeleton className="aspect-square w-full max-w-[260px] shrink-0 rounded-2xl md:w-60" />
          <div className="min-w-0 flex-1 space-y-4">
            <div className="flex gap-2">
              <Skeleton className="h-6 w-20 rounded-full" />
              <Skeleton className="h-6 w-28 rounded-full" />
            </div>
            <Skeleton className="h-7 w-4/5" />
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-9 w-48" />
            <div className="flex gap-3">
              <Skeleton className="h-11 w-40 rounded-xl" />
              <Skeleton className="h-11 w-44 rounded-xl" />
            </div>
          </div>
        </div>
      </div>
      <Skeleton className="h-72 rounded-2xl" />
      <Skeleton className="h-56 rounded-2xl" />
    </div>
  );
}

export function ErrorState({
  onRetry,
  message,
}: {
  onRetry?: () => void;
  message?: string;
}) {
  const { t } = useLanguage();
  return (
    <div className="surface mx-auto flex max-w-md flex-col items-center gap-3 rounded-2xl px-6 py-10 text-center">
      <span className="flex size-12 items-center justify-center rounded-full border border-rose-400/25 bg-rose-500/12 text-rose-300">
        <AlertTriangle className="size-6" />
      </span>
      <p className="text-sm text-slate-300">{message ?? t("common.error")}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-2 rounded-full border border-teal-400/30 bg-teal-400/10 px-4 py-2 text-sm font-semibold text-teal-200 transition hover:bg-teal-400/20"
        >
          <RefreshCw className="size-4" />
          {t("common.retry")}
        </button>
      ) : null}
    </div>
  );
}

export function InlineSpinner({ label }: { label?: string }) {
  const { t } = useLanguage();
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-400">
      <Loader2 className="size-4 animate-spin text-teal-400" />
      {label ?? t("common.loading")}
    </span>
  );
}
