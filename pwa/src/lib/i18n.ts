import { en } from "./locales/en";
import { id, type Messages } from "./locales/id";

export type Lang = "id" | "en";
export type Key = keyof Messages;
export type Params = Record<string, string | number>;

export const LANGS: readonly Lang[] = ["id", "en"];
export const LANG_KEY = "tb.lang";
export const DICTS: Record<Lang, Messages> = { id, en };

export function pickLang(stored: string | null | undefined): Lang {
  return stored === "en" ? "en" : "id";
}

function storedLang(): string | null {
  try {
    return globalThis.localStorage?.getItem(LANG_KEY) ?? null;
  } catch {
    return null;
  }
}

export const lang: Lang = pickLang(storedLang());
export const locale = lang === "en" ? "en-GB" : "id-ID";

export function translate(dict: Messages, key: Key, params?: Params): string {
  const text = dict[key];
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

export function t(key: Key, params?: Params): string {
  return translate(DICTS[lang], key, params);
}

export function setLang(next: Lang): void {
  if (next === lang) return;
  localStorage.setItem(LANG_KEY, next);
  location.reload();
}
