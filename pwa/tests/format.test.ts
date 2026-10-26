import { describe, expect, it } from "vitest";
import { describe as feedText } from "../src/lib/feedText";
import { age, MINUS, outcomeWord, signedPercent, signedRupiah } from "../src/lib/format";

describe("signed values", () => {
  it("always carries a sign and a word, never colour alone", () => {
    expect(signedPercent(0.4)).toBe("+0,40%");
    expect(signedPercent(-0.067)).toBe(MINUS + "0,07%");
    expect(signedPercent(-0.001)).toBe("0,00%");
    expect(outcomeWord(-0.2)).toBe("rugi");
    expect(outcomeWord(0)).toBe("impas");
    expect(signedRupiah(-1333.52).replace(/\s/g, " ")).toBe(MINUS + "Rp 1.334");
    expect(signedRupiah(0.4).replace(/\s/g, " ")).toBe("Rp 0");
  });

  it("reads ages in Indonesian units", () => {
    expect(age(4000)).toBe("4 dtk lalu");
    expect(age(185000)).toBe("3 mnt lalu");
    expect(age(Number.POSITIVE_INFINITY)).toBe("belum ada data");
  });
});

describe("feed text", () => {
  it("labels a losing exit fill with sign, word, and dry-run", () => {
    const item = feedText({ type: "exit_fill", seq: 4, ts: "2026-10-25T17:07:12.401Z", data: { pair: "BTC/IDR", profit_ratio: -0.004000681725188243 } }, true);
    expect(item).toMatchObject({ kind: "Order", text: "Jual BTC/IDR terisi, " + MINUS + "0,40% rugi (dry-run)" });
  });

  it("flags a quorum failure as a warning", () => {
    const item = feedText(
      {
        type: "gw.decision",
        seq: 9,
        ts: "",
        data: { pair: "ETH/IDR", status: "skip", reason: "quorum_not_met", verdict: "lewati", mode: "shadow", answered: 2, voters: [{}, {}, {}, {}, {}, {}, {}] },
      },
      true,
    );
    expect(item).toMatchObject({ kind: "Swarm", warn: true, text: "ETH/IDR: kuorum gagal, entry dilewati (bayangan), 2 dari 7 voter menjawab" });
  });
});
