import { describe, expect, it } from "vitest";
import { inLang } from "./lang";

const load = async () => ({ ...(await import("../src/lib/format")), feedText: (await import("../src/lib/feedText")).describe });

const CASES = {
  en: {
    up: "+0.40%",
    down: "0.07%",
    zero: "0.00%",
    loss: "loss",
    flat: "break-even",
    rupiah: "Rp 1,334",
    big: "Rp 1,463,933,000",
    price: "1,463,933,000",
    decimal: "0.62",
    ages: ["4 s ago", "3 min ago", "no data yet"],
    clock: "14:05",
    day: "26 Oct, 14:05",
    exit: "Sell BTC/IDR filled, \u22120.40% loss (dry-run)",
    quorum: "ETH/IDR: quorum failed, entry skipped (shadow), 2 of 7 voters answered",
  },
  id: {
    up: "+0,40%",
    down: "0,07%",
    zero: "0,00%",
    loss: "rugi",
    flat: "impas",
    rupiah: "Rp 1.334",
    big: "Rp 1.463.933.000",
    price: "1.463.933.000",
    decimal: "0,62",
    ages: ["4 dtk lalu", "3 mnt lalu", "belum ada data"],
    clock: "14.05",
    day: "26 Okt, 14.05",
    exit: "Jual BTC/IDR terisi, \u22120,40% rugi (dry-run)",
    quorum: "ETH/IDR: kuorum gagal, entry dilewati (bayangan), 2 dari 7 voter menjawab",
  },
} as const;

const space = (text: string) => text.replace(/\s/g, " ");

describe.each(Object.entries(CASES))("formatting in %s", (code, want) => {
  it("formats signed percents and rupiah with the active locale", async () => {
    const f = await inLang(code, load);
    expect(f.signedPercent(0.4)).toBe(want.up);
    expect(f.signedPercent(-0.067)).toBe(f.MINUS + want.down);
    expect(f.signedPercent(-0.001)).toBe(want.zero);
    expect(f.outcomeWord(-0.2)).toBe(want.loss);
    expect(f.outcomeWord(0)).toBe(want.flat);
    expect(space(f.signedRupiah(-1333.52))).toBe(f.MINUS + want.rupiah);
    expect(space(f.rupiah(1463933000))).toBe(want.big);
    expect(space(f.signedRupiah(0.4))).toBe("Rp 0");
    expect(f.price(1463933000)).toBe(want.price);
    expect(f.decimal(0.6219)).toBe(want.decimal);
  });

  it("formats ages, clocks, and dates with the active locale", async () => {
    const f = await inLang(code, load);
    expect([f.age(4000), f.age(185000), f.age(Number.POSITIVE_INFINITY)]).toEqual(want.ages);
    const at = new Date(2026, 9, 26, 14, 5).getTime();
    expect(f.clock(at)).toBe(want.clock);
    expect(space(f.dayClock(at))).toBe(want.day);
  });

  it("labels a losing exit fill with sign, word, and dry-run", async () => {
    const f = await inLang(code, load);
    const item = f.feedText({ type: "exit_fill", seq: 4, ts: "2026-10-25T17:07:12.401Z", data: { pair: "BTC/IDR", profit_ratio: -0.004000681725188243 } }, true);
    expect(item).toMatchObject({ kind: "order", text: want.exit });
  });

  it("flags a quorum failure as a warning", async () => {
    const f = await inLang(code, load);
    const item = f.feedText(
      {
        type: "gw.decision",
        seq: 9,
        ts: "",
        data: { pair: "ETH/IDR", status: "skip", reason: "quorum_not_met", verdict: "skip", mode: "shadow", answered: 2, voters: [{}, {}, {}, {}, {}, {}, {}] },
      },
      true,
    );
    expect(item).toMatchObject({ kind: "swarm", warn: true, text: want.quorum });
  });
});
