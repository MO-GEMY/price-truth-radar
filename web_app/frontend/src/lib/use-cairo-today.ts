"use client";

import { useSyncExternalStore } from "react";

/** Coupons stay valid through the end of their expiry date in Africa/Cairo (backend rule). */
const CAIRO_TZ = "Africa/Cairo";

const cairoDate = new Intl.DateTimeFormat("en-US", {
  timeZone: CAIRO_TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function cairoToday(): string {
  const parts: Record<string, string> = {};
  for (const { type, value } of cairoDate.formatToParts(new Date())) parts[type] = value;
  return `${parts.year}-${parts.month}-${parts.day}`;
}

const subscribeToNothing = () => () => {};

/**
 * Today's date in Cairo once the page has hydrated; `null` on the server and during
 * hydration so the first client render matches HTML that may have been cached a day earlier.
 */
export function useCairoToday(): string | null {
  return useSyncExternalStore(subscribeToNothing, cairoToday, () => null);
}
