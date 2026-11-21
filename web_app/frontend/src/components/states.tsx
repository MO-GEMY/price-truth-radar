"use client";

import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { useLanguage } from "@/lib/i18n";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function KpiSkeletons({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="glass rounded-2xl p-4">
          <Skeleton className="size-8 rounded-lg" />
          <Skeleton className="mt-3 h-6 w-16" />
          <Skeleton className="mt-2 h-3 w-24" />
        </div>
      ))}
    </div>
  );
}

export function ProductCardSkeletons({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="glass overflow-hidden rounded-2xl">
          <Skeleton className="h-40 rounded-none" />
          <div className="space-y-3 p-4">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-3 w-full" />
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
        <div key={i} className="glass rounded-2xl p-5">
          <Skeleton className="h-5 w-1/2" />
          <div className="mt-4 grid grid-cols-3 gap-4">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-48" />
      <div className="glass rounded-2xl p-6">
        <div className="flex flex-wrap items-center gap-4">
          <Skeleton className="size-24 rounded-xl" />
          <div className="space-y-3">
            <Skeleton className="h-6 w-80 max-w-full" />
            <Skeleton className="h-4 w-52" />
            <Skeleton className="h-7 w-40" />
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {Array.from({ length: 7 }).map((_, i) => (
          <Skeleton key={i} className="h-20 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-80 rounded-2xl" />
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
    <div className="glass mx-auto flex max-w-md flex-col items-center gap-3 rounded-2xl px-6 py-10 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-rose-500/12 text-rose-300">
        <AlertTriangle className="size-6" />
      </span>
      <p className="text-sm text-slate-300">{message ?? t("common.error")}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-300 transition hover:bg-cyan-400/20"
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
      <Loader2 className="size-4 animate-spin text-cyan-400" />
      {label ?? t("common.loading")}
    </span>
  );
}
