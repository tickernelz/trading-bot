import { en, type Messages } from "./locales/en";
import { DEFAULT_LANG, LANGUAGES, type Language } from "./locales/index";

export type { Language, Messages };
export type Key = keyof Messages;
export type Params = Record<string, string | number>;

export const LANG_KEY = "tb.lang";

export function pickLanguage(stored: string | null | undefined, languages: readonly Language[] = LANGUAGES): Language {
  return languages.find((l) => l.code === stored) ?? languages.find((l) => l.code === DEFAULT_LANG)!;
}

export function withFallback(dict: Partial<Messages>): Messages {
  const merged: Messages = { ...en };
  for (const key of Object.keys(en) as Key[]) {
    const text = dict[key];
    if (typeof text === "string" && text !== "") merged[key] = text;
  }
  return merged;
}

export async function loadMessages(language: Language): Promise<Messages> {
  try {
    return withFallback(await language.load());
  } catch {
    return en;
  }
}

function storedLang(): string | null {
  try {
    return globalThis.localStorage?.getItem(LANG_KEY) ?? null;
  } catch {
    return null;
  }
}

export const language: Language = pickLanguage(storedLang());
export const lang = language.code;
export const locale = language.intlLocale;
const active: Messages = await loadMessages(language);

export function translate(dict: Messages, key: Key, params?: Params): string {
  const text = dict[key];
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

export function t(key: Key, params?: Params): string {
  return translate(active, key, params);
}

export function setLang(next: string): void {
  if (next === lang) return;
  localStorage.setItem(LANG_KEY, next);
  location.reload();
}
