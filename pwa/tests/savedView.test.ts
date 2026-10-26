import { describe, expect, it } from "vitest";
import { decodeView, encodeView, SAVED_CANDLES, storeView, VIEW_KEY, type SavedView } from "../src/lib/savedView";

function view(rows = 500): Omit<SavedView, "version"> {
  return {
    saved_at: 1_792_990_000_000,
    health: { gateway: { sample_data: false } } as unknown as SavedView["health"],
    overview: { as_of: "2026-10-26T05:00:00Z" } as unknown as SavedView["overview"],
    risk: { entries_allowed: true } as unknown as SavedView["risk"],
    openTrades: [],
    closedTrades: [],
    equityDay: null,
    equityWeek: null,
    decisions: [],
    candles: {
      "BTC/IDR": {
        pair: "BTC/IDR",
        timeframe: "1h",
        columns: ["date", "close"],
        data: Array.from({ length: rows }, (_, i) => [String(i), i]),
      } as unknown as SavedView["candles"][string],
    },
    news: {},
    sentiment: null,
  };
}

describe("saved view", () => {
  it("round-trips and keeps only the newest candles", () => {
    const decoded = decodeView(encodeView(view()))!;
    expect(decoded.saved_at).toBe(1_792_990_000_000);
    expect(decoded.candles["BTC/IDR"].data).toHaveLength(SAVED_CANDLES);
    expect(decoded.candles["BTC/IDR"].data[0][0]).toBe("200");
  });

  it("rejects missing, corrupt, foreign-version and partial payloads", () => {
    expect(decodeView(null)).toBeNull();
    expect(decodeView("{not json")).toBeNull();
    expect(decodeView(JSON.stringify({ ...JSON.parse(encodeView(view())), version: 2 }))).toBeNull();
    const partial = JSON.parse(encodeView(view()));
    delete partial.risk;
    expect(decodeView(JSON.stringify(partial))).toBeNull();
  });

  it("fills panels an older save did not carry", () => {
    const old = JSON.parse(encodeView(view()));
    delete old.news;
    delete old.sentiment;
    delete old.decisions;
    const decoded = decodeView(JSON.stringify(old))!;
    expect(decoded.news).toEqual({});
    expect(decoded.sentiment).toBeNull();
    expect(decoded.decisions).toEqual([]);
  });

  it("reports a full storage instead of throwing", () => {
    const full = { setItem: () => { throw new DOMException("quota", "QuotaExceededError"); } };
    expect(storeView(full, view())).toBe(false);
    const kept = new Map<string, string>();
    expect(storeView({ setItem: (k, v) => void kept.set(k, v) }, view())).toBe(true);
    expect(kept.has(VIEW_KEY)).toBe(true);
  });
});
