import { Fragment, type ReactNode } from "react";
import { create } from "zustand";
import { ky } from "./ky";
import { ru } from "./ru";

/**
 * Lightweight i18n.
 *
 * Keys are the English source strings, so English needs no dictionary and a missing translation
 * falls back to readable English. Placeholders use `{name}` and are filled from `vars`.
 *
 * Changing the language remounts the app tree (see `LanguageScope`), so `t()` may be called
 * anywhere during render — components, hooks, toasts — without subscribing to the store.
 * Module-level constants must keep English text (wrap it in `msg()` so tooling can find it)
 * and translate it with `t()` when rendered.
 */
export type Lang = "en" | "ru" | "ky";

export const LANGUAGES: { code: Lang; label: string; short: string }[] = [
  { code: "en", label: "English", short: "EN" },
  { code: "ru", label: "Русский", short: "RU" },
  { code: "ky", label: "Кыргызча", short: "KY" },
];

export type Dictionary = Record<string, string>;
const DICTS: Record<Lang, Dictionary> = { en: {}, ru, ky };
const KEY = "geoattend.lang";

const isLang = (v: unknown): v is Lang => v === "en" || v === "ru" || v === "ky";

function detect(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (isLang(saved)) return saved;
  } catch {
    /* storage unavailable */
  }
  const prefs = typeof navigator === "undefined" ? [] : (navigator.languages?.length ? navigator.languages : [navigator.language]);
  for (const p of prefs) {
    const base = (p ?? "").toLowerCase().split("-")[0];
    if (isLang(base)) return base;
  }
  return "en";
}

function applyDocumentLang(lang: Lang) {
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

interface LangState {
  lang: Lang;
  setLang(l: Lang): void;
}

export const useLangStore = create<LangState>((set) => ({
  lang: detect(),
  setLang: (lang) => {
    try {
      localStorage.setItem(KEY, lang);
    } catch {
      /* ignore */
    }
    applyDocumentLang(lang);
    set({ lang });
  },
}));
applyDocumentLang(useLangStore.getState().lang);

export const getLang = (): Lang => useLangStore.getState().lang;

/** Translate an English source string. Unknown keys (e.g. free-form server text) are returned as-is. */
export function t(key: string, vars?: Record<string, string | number>): string {
  const s = DICTS[getLang()][key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : s;
}

/** Marks an English string for translation without translating it (for module-level constants). */
export const msg = <T extends string>(s: T): T => s;

/** Read-only view of a table of English labels that translates each value on access. */
export function translated<T extends object>(table: T): T {
  return new Proxy(table, {
    get(target, prop, receiver) {
      const v = Reflect.get(target, prop, receiver);
      return typeof v === "string" ? t(v) : v;
    },
  });
}

/** BCP 47 locale for Intl formatting. English keeps the browser's own English variant. */
export function intlLocale(): string | undefined {
  const lang = getLang();
  if (lang === "ru") return "ru-RU";
  if (lang === "ky") return "ky-KG";
  const nav = typeof navigator === "undefined" ? "" : navigator.language ?? "";
  return nav.toLowerCase().startsWith("en") ? undefined : "en-US";
}

/** Remounts its children when the language changes so every `t()` call re-runs. */
export function LanguageScope({ children }: { children: ReactNode }) {
  const lang = useLangStore((s) => s.lang);
  return <Fragment key={lang}>{children}</Fragment>;
}
