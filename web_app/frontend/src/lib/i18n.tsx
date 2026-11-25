"use client";

/**
 * Bilingual (EN/AR) language context. Persists the choice to localStorage,
 * drives <html lang/dir> and the Arabic font class, and exposes a `t()`
 * helper with `{var}` interpolation.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { translations, type TranslationKey } from "./translations";

export type Lang = "en" | "ar";

const STORAGE_KEY = "ptr-lang";

interface LanguageContextValue {
  lang: Lang;
  dir: "ltr" | "rtl";
  ready: boolean;
  setLang: (lang: Lang) => void;
  toggleLang: () => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

function applyDocumentAttrs(lang: Lang): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.lang = lang;
  root.dir = lang === "ar" ? "rtl" : "ltr";
  root.classList.toggle("lang-ar", lang === "ar");
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ar");
  const [ready, setReady] = useState(false);

  // Restore the persisted language after mount (defaults to Arabic RTL).
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      stored = null;
    }
    const resolved: Lang = stored === "en" ? "en" : "ar";
    setLangState(resolved);
    applyDocumentAttrs(resolved);
    setReady(true);
  }, []);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    applyDocumentAttrs(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage unavailable (private mode) — language still applies this session.
    }
  }, []);

  const toggleLang = useCallback(() => {
    setLang(lang === "en" ? "ar" : "en");
  }, [lang, setLang]);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>): string => {
      const template: string =
        (translations[lang] as Record<TranslationKey, string>)[key] ??
        (translations.en as Record<TranslationKey, string>)[key] ??
        key;
      if (!vars) return template;
      return template.replace(/\{(\w+)\}/g, (match, name: string) =>
        name in vars ? String(vars[name]) : match,
      );
    },
    [lang],
  );

  const value = useMemo<LanguageContextValue>(
    () => ({ lang, dir: lang === "ar" ? "rtl" : "ltr", ready, setLang, toggleLang, t }),
    [lang, ready, setLang, toggleLang, t],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error("useLanguage must be used inside <LanguageProvider>");
  }
  return ctx;
}
