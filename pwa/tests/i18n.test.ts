import { describe, expect, it } from "vitest";
import { lang, pickLang, translate } from "../src/lib/i18n";
import { en } from "../src/lib/locales/en";
import { id } from "../src/lib/locales/id";

const DICTS = { id, en };

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("i18n", () => {
  it("defaults to Indonesian unless English was chosen", () => {
    expect(lang).toBe("id");
    expect(pickLang(null)).toBe("id");
    expect(pickLang("fr")).toBe("id");
    expect(pickLang("en")).toBe("en");
  });

  it("gives every key the same placeholders in both languages", () => {
    const mismatched = Object.keys(DICTS.id).filter(
      (key) => placeholders(DICTS.id[key as keyof typeof DICTS.id]).join() !== placeholders(DICTS.en[key as keyof typeof DICTS.en]).join(),
    );
    expect(mismatched).toEqual([]);
    expect(Object.keys(DICTS.en).sort()).toEqual(Object.keys(DICTS.id).sort());
    expect(Object.entries(DICTS.en).filter(([, text]) => text.trim() === "")).toEqual([]);
  });

  it("fills named parameters and keeps unknown ones visible", () => {
    expect(translate(DICTS.en, "tm.position", { i: 3, n: 40, at: "26 Oct, 14:00" })).toBe("Decision 3 of 40 · candle 26 Oct, 14:00");
    expect(translate(DICTS.id, "tm.position", { i: 3 })).toBe("Keputusan 3 dari {n} · kandel {at}");
  });
});
