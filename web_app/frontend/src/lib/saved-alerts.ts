"use client";

/**
 * Hydration-safe persistent local storage & cross-component sync for
 * user-activated price drop alerts (`asarak_saved_alerts_v1` & `asarak_alert_prefs_v1`).
 *
 * - Never reads `localStorage` during SSR or initial render (zero hydration mismatch).
 * - Syncs instantaneously across components via `asarak-alerts-updated` custom event
 *   and across browser tabs via the native `storage` event.
 * - Supports both Email and Telegram alert channels.
 */

import { useCallback, useEffect, useState } from "react";
import type { AlertChannel, Category } from "@/types/contract";

export const SAVED_ALERTS_STORAGE_KEY = "asarak_saved_alerts_v1";
export const ALERT_PREFS_STORAGE_KEY = "asarak_alert_prefs_v1";
export const ALERTS_UPDATED_EVENT = "asarak-alerts-updated";

export interface SavedPriceAlert {
  alert_id: string;
  product_sk: string;
  product_key: string;
  title: string;
  image_url: string | null;
  store_name: string;
  category?: Category;
  price_when_set: number;
  target_price: number;
  channel: AlertChannel;
  destination: string;
  cancel_token: string | null;
  created_at: string;
}

export interface AlertUserPrefs {
  lastChannel: AlertChannel;
  email: string;
  telegramChatId: string;
}

const DEFAULT_PREFS: AlertUserPrefs = {
  lastChannel: "email",
  email: "",
  telegramChatId: "",
};

const CHAT_ID_RE = /^-?\d{5,20}$/;

export function maskAlertDestination(destination: string, channel: AlertChannel): string {
  const clean = destination.trim();
  if (!clean) return "";
  if (channel === "email") {
    const parts = clean.split("@");
    if (parts.length === 2) {
      return `${parts[0].charAt(0)}•••@${parts[1]}`;
    }
    return `${clean.slice(0, 2)}•••`;
  }
  return CHAT_ID_RE.test(clean)
    ? `•••${clean.slice(-3)}`
    : `${clean.slice(0, 3)}•••`;
}

function isValidSavedAlert(value: unknown): value is SavedPriceAlert {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.alert_id === "string" &&
    v.alert_id.length > 0 &&
    typeof v.product_sk === "string" &&
    v.product_sk.length > 0 &&
    typeof v.product_key === "string" &&
    typeof v.title === "string" &&
    typeof v.store_name === "string" &&
    typeof v.target_price === "number" &&
    Number.isFinite(v.target_price) &&
    (v.channel === "email" || v.channel === "telegram") &&
    typeof v.destination === "string" &&
    typeof v.created_at === "string"
  );
}

export function readSavedAlerts(): SavedPriceAlert[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(SAVED_ALERTS_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidSavedAlert);
  } catch {
    return [];
  }
}

export function readAlertPrefs(): AlertUserPrefs {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(ALERT_PREFS_STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return DEFAULT_PREFS;
    const p = parsed as Record<string, unknown>;
    return {
      lastChannel: p.lastChannel === "telegram" ? "telegram" : "email",
      email: typeof p.email === "string" ? p.email : "",
      telegramChatId: typeof p.telegramChatId === "string" ? p.telegramChatId : "",
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

function writeSavedAlerts(items: SavedPriceAlert[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SAVED_ALERTS_STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Private browsing or quota exceeded — ignore gracefully.
  }
}

function writeAlertPrefs(prefs: AlertUserPrefs): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ALERT_PREFS_STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // Ignore storage errors in private mode.
  }
}

function notifyAlertsUpdated(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(ALERTS_UPDATED_EVENT));
}

function sameStore(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

export function findSavedAlert(
  alerts: readonly SavedPriceAlert[],
  target: { product_sk?: string; product_key?: string | null; store_name?: string },
): SavedPriceAlert | null {
  if (target.product_sk) {
    const bySk = alerts.find((item) => item.product_sk === target.product_sk);
    if (bySk) return bySk;
  }
  if (target.product_key && target.store_name) {
    const byKeyStore = alerts.find(
      (item) =>
        item.product_key === target.product_key &&
        sameStore(item.store_name, target.store_name!),
    );
    if (byKeyStore) return byKeyStore;
  }
  return null;
}

export function saveAlertLocally(entry: SavedPriceAlert): SavedPriceAlert[] {
  const existing = readSavedAlerts();
  const filtered = existing.filter(
    (item) =>
      item.alert_id !== entry.alert_id &&
      item.product_sk !== entry.product_sk &&
      !(item.product_key === entry.product_key && sameStore(item.store_name, entry.store_name)),
  );
  const next = [entry, ...filtered].slice(0, 50);
  writeSavedAlerts(next);

  const prevPrefs = readAlertPrefs();
  const nextPrefs: AlertUserPrefs = {
    lastChannel: entry.channel,
    email: entry.channel === "email" ? entry.destination : prevPrefs.email,
    telegramChatId: entry.channel === "telegram" ? entry.destination : prevPrefs.telegramChatId,
  };
  writeAlertPrefs(nextPrefs);
  notifyAlertsUpdated();
  return next;
}

export function removeAlertLocally(matcher: {
  alert_id?: string;
  product_sk?: string;
  product_key?: string;
  store_name?: string;
}): SavedPriceAlert[] {
  const existing = readSavedAlerts();
  const next = existing.filter((item) => {
    if (matcher.alert_id && item.alert_id === matcher.alert_id) return false;
    if (matcher.product_sk && item.product_sk === matcher.product_sk) return false;
    if (
      matcher.product_key &&
      matcher.store_name &&
      item.product_key === matcher.product_key &&
      sameStore(item.store_name, matcher.store_name)
    ) {
      return false;
    }
    return true;
  });
  writeSavedAlerts(next);
  notifyAlertsUpdated();
  return next;
}

export function useSavedAlerts() {
  const [alerts, setAlerts] = useState<SavedPriceAlert[]>([]);
  const [prefs, setPrefs] = useState<AlertUserPrefs>(DEFAULT_PREFS);
  const [hydrated, setHydrated] = useState(false);

  const syncFromStorage = useCallback(() => {
    setAlerts(readSavedAlerts());
    setPrefs(readAlertPrefs());
    setHydrated(true);
  }, []);

  useEffect(() => {
    syncFromStorage();
    const onCustom = () => syncFromStorage();
    const onStorage = (event: StorageEvent) => {
      if (
        event.key === null ||
        event.key === SAVED_ALERTS_STORAGE_KEY ||
        event.key === ALERT_PREFS_STORAGE_KEY
      ) {
        syncFromStorage();
      }
    };
    window.addEventListener(ALERTS_UPDATED_EVENT, onCustom);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(ALERTS_UPDATED_EVENT, onCustom);
      window.removeEventListener("storage", onStorage);
    };
  }, [syncFromStorage]);

  const getAlertForProduct = useCallback(
    (target: { product_sk?: string; product_key?: string | null; store_name?: string }) =>
      findSavedAlert(alerts, target),
    [alerts],
  );

  const saveAlert = useCallback((entry: SavedPriceAlert) => {
    const next = saveAlertLocally(entry);
    setAlerts(next);
    setPrefs(readAlertPrefs());
  }, []);

  const removeAlert = useCallback(
    (matcher: {
      alert_id?: string;
      product_sk?: string;
      product_key?: string;
      store_name?: string;
    }) => {
      const next = removeAlertLocally(matcher);
      setAlerts(next);
    },
    [],
  );

  return {
    alerts,
    count: alerts.length,
    prefs,
    hydrated,
    getAlertForProduct,
    saveAlert,
    removeAlert,
  };
}
