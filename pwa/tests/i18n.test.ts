import { afterEach, describe, expect, it, vi } from "vitest";
import { pickLanguage, translate, withFallback } from "../src/lib/i18n";
import { en, type Messages } from "../src/lib/locales/en";
import { LANGUAGES, type Language } from "../src/lib/locales/index";
import { inLang } from "./lang";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

const FAKE: Language = {
  code: "xx",
  nativeName: "Fakish",
  htmlLang: "x-fake",
  intlLocale: "de-DE",
  load: async () => ({ "app.name": "Fakebot", "lang.label": "" }) as unknown as Messages,
};

const withFakeRow = () =>
  vi.doMock("../src/lib/locales/index", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../src/lib/locales/index")>();
    return { ...actual, LANGUAGES: [...actual.LANGUAGES, FAKE] };
  });

const loadAll = async () => ({
  i18n: await import("../src/lib/i18n"),
  format: await import("../src/lib/format"),
  Switch: (await import("../src/components/LangSwitch.svelte")).default,
  render: (await import("svelte/server")).render,
});

afterEach(() => {
  vi.doUnmock("../src/lib/locales/index");
});

describe("language choice", () => {
  it("uses a valid stored choice and falls back to English otherwise", () => {
    expect(pickLanguage(null).code).toBe("en");
    expect(pickLanguage("").code).toBe("en");
    expect(pickLanguage("fr").code).toBe("en");
    expect(pickLanguage("ID").code).toBe("en");
    expect(pickLanguage("id").code).toBe("id");
    expect(pickLanguage("en").code).toBe("en");
  });

  it("starts in English without reading the browser language", async () => {
    vi.stubGlobal("navigator", { language: "id-ID", languages: ["id-ID", "id"] });
    const { i18n } = await inLang(null, loadAll);
    expect(i18n.lang).toBe("en");
    expect(i18n.locale).toBe("en-GB");
    expect(i18n.t("app.name")).toBe("Trading Bot");
  });

  it("loads the Indonesian catalogue, locale, and html lang from the registry", async () => {
    const { i18n } = await inLang("id", loadAll);
    expect(i18n.language).toMatchObject({ code: "id", htmlLang: "id", intlLocale: "id-ID" });
    expect(i18n.t("app.name")).toBe("Bot Trading");
  });

  it("drops an unknown stored code to English", async () => {
    const { i18n } = await inLang("xx", loadAll);
    expect(i18n.lang).toBe("en");
  });
});

describe("catalogues", () => {
  it("gives every key the same placeholders in every registered language", async () => {
    for (const language of LANGUAGES) {
      const dict = await language.load();
      const mismatched = (Object.keys(en) as (keyof Messages)[]).filter((key) => placeholders(dict[key]).join() !== placeholders(en[key]).join());
      expect(mismatched, language.code).toEqual([]);
      expect(Object.keys(dict).sort(), language.code).toEqual(Object.keys(en).sort());
      expect(Object.entries(dict).filter(([, text]) => text.trim() === ""), language.code).toEqual([]);
    }
  });

  it("registers English first and every code once", () => {
    expect(LANGUAGES[0].code).toBe("en");
    expect(new Set(LANGUAGES.map((l) => l.code)).size).toBe(LANGUAGES.length);
  });

  it("fills named parameters and keeps unknown ones visible", async () => {
    const id = await LANGUAGES.find((l) => l.code === "id")!.load();
    expect(translate(en, "tm.position", { i: 3, n: 40, at: "26 Oct, 14:00" })).toBe("Decision 3 of 40 · candle 26 Oct, 14:00");
    expect(translate(id, "tm.position", { i: 3 })).toBe("Keputusan 3 dari {n} · kandel {at}");
  });

  it("shows English text for a key a catalogue lacks or leaves empty", () => {
    const merged = withFallback({ "app.name": "Fakebot", "lang.label": "" });
    expect(merged["app.name"]).toBe("Fakebot");
    expect(merged["lang.label"]).toBe(en["lang.label"]);
    expect(merged["nav.summary"]).toBe("Summary");
  });
});

describe("adding a language through the registry only", () => {
  it("offers, selects, and formats with a third language from one registry row", async () => {
    withFakeRow();
    const { i18n, format, Switch, render } = await inLang("xx", loadAll);
    expect(i18n.language).toMatchObject({ code: "xx", htmlLang: "x-fake", intlLocale: "de-DE" });
    expect(i18n.t("app.name")).toBe("Fakebot");
    expect(i18n.t("lang.label")).toBe(en["lang.label"]);
    expect(i18n.t("nav.summary")).toBe("Summary");
    expect(format.decimal(1234.5)).toBe("1.234,50");
    const html = render(Switch).body;
    expect(html).toContain('lang="x-fake"');
    expect(html).toMatch(/aria-pressed="true"[^>]*>Fakish</);
    expect(html).toContain(">English<");
  });

  it("neither offers nor selects that language without the registry row", async () => {
    const { i18n, format, Switch, render } = await inLang("xx", loadAll);
    expect(i18n.lang).toBe("en");
    expect(i18n.t("app.name")).toBe("Trading Bot");
    expect(format.decimal(1234.5)).toBe("1,234.50");
    const html = render(Switch).body;
    expect(html).not.toContain("Fakish");
    expect(html).toMatch(/aria-pressed="true"[^>]*>English</);
  });
});
