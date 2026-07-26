"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  DEFAULT_LOCALE,
  LOCALE_NAMES,
  MESSAGES,
  isLocale,
  type Locale,
} from "./messages";

export const LOCALE_COOKIE = "lifetree.locale";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year

type Vars = Record<string, string | number>;

type TFunc = (key: string, vars?: Vars) => string;

interface I18nContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: TFunc;
}

const I18nContext = createContext<I18nContextValue | null>(null);

/** Parse a cookie value, returning null if missing. */
function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const parts = document.cookie.split(";");
  for (const raw of parts) {
    const idx = raw.indexOf("=");
    if (idx === -1) continue;
    const k = raw.slice(0, idx).trim();
    if (k === name) {
      try {
        return decodeURIComponent(raw.slice(idx + 1).trim());
      } catch {
        return raw.slice(idx + 1).trim();
      }
    }
  }
  return null;
}

function writeCookie(name: string, value: string, maxAge: number) {
  if (typeof document === "undefined") return;
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "; Secure"
      : "";
  document.cookie = `${name}=${encodeURIComponent(
    value
  )}; Max-Age=${maxAge}; Path=/; SameSite=Lax${secure}`;
}

/**
 * Resolve the initial locale from (1) cookie, (2) navigator.language, (3) English.
 *
 * Per user requirement: if the browser/system language is not one of the
 * supported LifeTree locales, fall back to English rather than zh-CN.
 */
function resolveInitialLocale(): Locale {
  if (typeof document !== "undefined") {
    const stored = readCookie(LOCALE_COOKIE);
    if (isLocale(stored)) return stored;
  }
  if (typeof navigator !== "undefined") {
    const nav = navigator.language;
    if (isLocale(nav)) return nav;
    // Match prefix (e.g. "en-US" → "en", "zh-HK" → "zh-CN", "de-AT" → "de")
    const prefix = nav.split("-")[0];
    if (prefix === "zh") return "zh-CN";
    if (prefix === "en") return "en";
    if (prefix === "es") return "es";
    if (prefix === "de") return "de";
    if (prefix === "fr") return "fr";
  }
  // Browser language not supported → English.
  return "en";
}

/** Pure translate: looks up `key` in `locale`, falls back to zh-CN, then key. */
export function translate(locale: Locale, key: string, vars?: Vars): string {
  const dict = MESSAGES[locale] ?? MESSAGES[DEFAULT_LOCALE];
  let raw = dict[key];
  if (raw === undefined) {
    raw = MESSAGES[DEFAULT_LOCALE][key] ?? key;
  }
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (_match, name: string) => {
    const v = vars[name];
    return v === undefined || v === null ? `{${name}}` : String(v);
  });
}

export function I18nProvider({ children }: { children: ReactNode }) {
  // Start with default on SSR; reconcile on mount.
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  const [hydrated, setHydrated] = useState(false);

  // On mount, read cookie/navigator.
  useEffect(() => {
    setLocaleState(resolveInitialLocale());
    setHydrated(true);
  }, []);

  // Reflect changes to <html lang> and cookie.
  useEffect(() => {
    if (!hydrated) return;
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
    writeCookie(LOCALE_COOKIE, locale, COOKIE_MAX_AGE);
  }, [locale, hydrated]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
  }, []);

  const t = useCallback<TFunc>(
    (key, vars) => translate(locale, key, vars),
    [locale]
  );

  const value = useMemo<I18nContextValue>(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used inside <I18nProvider>");
  }
  return ctx;
}

/** Convenience hook returning just the translate function. */
export function useT(): TFunc {
  return useI18n().t;
}

export { LOCALE_NAMES };
export type { Locale };
