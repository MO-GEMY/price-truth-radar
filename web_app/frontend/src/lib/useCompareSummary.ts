"use client";

/**
 * Shared, session-cached summary of the `/api/v1/compare` cross-store set.
 * Powers the header match-count badge, the home KPI + spotlight, and the
 * "Compare X stores" pill on feed cards — with a single network round-trip
 * (plus a few parallel pages) per session.
 */

import { useEffect, useState } from "react";
import type { CrossStoreMatch } from "@/types/contract";
import { fetchCompare, type DataSource } from "./api";

export interface CompareSummary {
  total: number;
  /** Top matches by absolute EGP savings (largest first). */
  topBySavings: CrossStoreMatch[];
  /** canonical_product_key → number of stores carrying it. */
  storesByKey: Record<string, number>;
  source: DataSource;
}

const PAGE_LIMIT = 50; // backend max (CONTRACTS.md §5.6)
const MAX_PAGES = 6;
const TTL_MS = 5 * 60 * 1000;

let cached: { at: number; promise: Promise<CompareSummary> } | null = null;

async function loadSummary(): Promise<CompareSummary> {
  const first = await fetchCompare({ category: "all", page: 1, limit: PAGE_LIMIT });
  const items: CrossStoreMatch[] = [...first.data.items];
  let source: DataSource = first.source;

  const pages = Math.min(MAX_PAGES, Math.ceil(first.data.total / PAGE_LIMIT));
  if (pages > 1) {
    const rest = await Promise.allSettled(
      Array.from({ length: pages - 1 }, (_, i) =>
        fetchCompare({ category: "all", page: i + 2, limit: PAGE_LIMIT }),
      ),
    );
    for (const res of rest) {
      if (res.status === "fulfilled") {
        items.push(...res.value.data.items);
        if (res.value.source === "mock") source = "mock";
      }
    }
  }

  const storesByKey: Record<string, number> = {};
  for (const match of items) {
    storesByKey[match.canonical_product_key] = match.stores_count;
  }

  const topBySavings = [...items]
    .sort((a, b) => b.price_spread_egp - a.price_spread_egp)
    .slice(0, 3);

  return { total: first.data.total, topBySavings, storesByKey, source };
}

function getSummary(): Promise<CompareSummary> {
  const now = Date.now();
  if (!cached || now - cached.at > TTL_MS) {
    const promise = loadSummary();
    cached = { at: now, promise };
    promise.catch(() => {
      if (cached?.promise === promise) cached = null;
    });
  }
  return cached.promise;
}

export function useCompareSummary(): {
  summary: CompareSummary | null;
  error: boolean;
} {
  const [summary, setSummary] = useState<CompareSummary | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    getSummary()
      .then((value) => {
        if (alive) setSummary(value);
      })
      .catch(() => {
        if (alive) setError(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  return { summary, error };
}
