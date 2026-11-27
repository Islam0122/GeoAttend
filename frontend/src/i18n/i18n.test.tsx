import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Login } from "@/pages/public/Auth";
import { fmtMinutes, STATUS_LABEL, titleCase, WEEKDAYS } from "@/lib/format";
import { mockFetch, renderWithProviders } from "@/test/utils";
import { LanguageScope, t, useLangStore, type Lang } from "./index";
import { ky } from "./ky";
import { ru } from "./ru";

const sources = import.meta.glob(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}", "!/src/i18n/**", "!/src/test/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** Every literal passed to t("…") or msg("…") in the app. */
function usedKeys(): Set<string> {
  const keys = new Set<string>();
  const re = /\b(?:t|msg)\(\s*"((?:[^"\\]|\\.)*)"/g;
  for (const src of Object.values(sources)) for (const m of src.matchAll(re)) keys.add(JSON.parse(`"${m[1]}"`) as string);
  return keys;
}
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
const setLang = (l: Lang) => act(() => useLangStore.getState().setLang(l));

afterEach(() => setLang("en"));

describe("dictionaries", () => {
  const keys = usedKeys();

  it("finds the app's translation keys", () => {
    expect(keys.size).toBeGreaterThan(500);
  });

  it.each([["ru", ru], ["ky", ky]] as const)("%s translates every key used in the app", (_, dict) => {
    expect([...keys].filter((k) => !(k in dict))).toEqual([]);
  });

  it("ru and ky have the same keys", () => {
    expect(Object.keys(ky).sort()).toEqual(Object.keys(ru).sort());
  });

  it.each([["ru", ru], ["ky", ky]] as const)("%s keeps every {placeholder} and has no empty values", (_, dict) => {
    const broken = Object.entries(dict).filter(([en, tr]) => !tr.trim() || placeholders(en).join() !== placeholders(tr).join());
    expect(broken).toEqual([]);
  });
});

describe("t()", () => {
  it("falls back to the English key and fills placeholders", () => {
    expect(t("Some server text nobody translated")).toBe("Some server text nobody translated");
    expect(t("{n} min ago", { n: 5 })).toBe("5 min ago");
    setLang("ru");
    expect(t("{n} min ago", { n: 5 })).toBe("5 мин назад");
    expect(t("Some server text nobody translated")).toBe("Some server text nobody translated");
  });

  it("translates label tables, enum labels and durations on access", () => {
    setLang("ky");
    expect(STATUS_LABEL.LATE).toBe("Кечигүү");
    expect(Object.values(STATUS_LABEL)).toContain("Келди");
    expect(WEEKDAYS.map((d) => d)[0]).toBe("Дүй");
    expect(titleCase("MISSING_CHECK_IN")).toBe("Келүү белгиси жок");
    expect(fmtMinutes(75)).toBe("1 саат 15 мүн");
  });

  it("persists the choice and sets <html lang>", () => {
    setLang("ru");
    expect(localStorage.getItem("geoattend.lang")).toBe("ru");
    expect(document.documentElement.lang).toBe("ru");
  });
});

describe("LanguageScope", () => {
  it("re-renders the UI in the selected language", () => {
    mockFetch(() => ({ body: {} }));
    renderWithProviders(<LanguageScope><Login /></LanguageScope>);
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    setLang("ru");
    expect(screen.getByRole("button", { name: "Войти" })).toBeInTheDocument();
    expect(screen.getByLabelText("Рабочий email")).toBeInTheDocument();
    setLang("ky");
    expect(screen.getByRole("button", { name: "Кирүү" })).toBeInTheDocument();
  });
});
