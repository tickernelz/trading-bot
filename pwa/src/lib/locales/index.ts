import { en, type Messages } from "./en";

export interface Language {
  code: string;
  nativeName: string;
  htmlLang: string;
  intlLocale: string;
  load: () => Promise<Messages>;
}

export const DEFAULT_LANG = "en";

export const LANGUAGES: readonly Language[] = [
  { code: "en", nativeName: "English", htmlLang: "en", intlLocale: "en-GB", load: async () => en },
  { code: "id", nativeName: "Bahasa Indonesia", htmlLang: "id", intlLocale: "id-ID", load: async () => (await import("./id")).id },
];
