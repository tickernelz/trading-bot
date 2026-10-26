import { describe, expect, it } from "vitest";
import { clampStep, newsByBar, sentimentLine, timeline } from "../src/lib/timeMachine";
import type { Decision, NewsItem, SentimentPoint } from "../src/lib/types";

const H = 3_600_000;
const T0 = Date.parse("2026-10-20T00:00:00Z");
const iso = (ms: number) => new Date(ms).toISOString();
const decision = (id: string, candleMs: number, tsMs = candleMs + 120_000) => ({ decision_id: id, candle: iso(candleMs), ts: iso(tsMs) }) as Decision;

describe("timeline", () => {
  it("orders oldest first, drops duplicates, and counts decisions before the loaded candles", () => {
    const rows = [decision("c", T0 + 9 * H), decision("a", T0 - 5 * H), decision("b", T0 + 3 * H), decision("b", T0 + 3 * H)];
    const result = timeline(rows, T0);
    expect(result.steps.map((d) => d.decision_id)).toEqual(["b", "c"]);
    expect(result.older).toBe(1);
  });

  it("has no steps until candles are loaded", () => {
    expect(timeline([decision("a", T0)], null)).toEqual({ steps: [], older: 1 });
  });

  it("clamps the step into range", () => {
    expect(clampStep(-3, 4)).toBe(0);
    expect(clampStep(9, 4)).toBe(3);
    expect(clampStep(1.6, 4)).toBe(2);
    expect(clampStep(5, 0)).toBe(0);
  });
});

describe("overlay placement", () => {
  it("groups headlines into their hourly candle and skips ones before the chart", () => {
    const item = (id: string, ms: number) => ({ id, published: iso(ms) }) as NewsItem;
    const bars = newsByBar([item("x", T0 + 10 * 60_000), item("y", T0 + 50 * 60_000), item("z", T0 + H + 1), item("old", T0 - 1)], T0 / 1000);
    expect([...bars.entries()].map(([bar, items]) => [bar, items.map((i) => i.id)])).toEqual([
      [T0 / 1000, ["x", "y"]],
      [T0 / 1000 + 3600, ["z"]],
    ]);
  });

  it("carries the day before the chart start in and extends the last value to the newest candle", () => {
    const points: SentimentPoint[] = [
      { date: "2026-10-19", value: 30, classification: "Fear" },
      { date: "2026-10-21", value: 60, classification: "Greed" },
      { date: "2026-10-23", value: 70, classification: "Greed" },
    ];
    const first = T0 / 1000 + 5 * 3600;
    const last = Date.parse("2026-10-22T12:00:00Z") / 1000;
    expect(sentimentLine(points, first, last)).toEqual([
      { time: first, value: 30 },
      { time: Date.parse("2026-10-21T00:00:00Z") / 1000, value: 60 },
      { time: last, value: 60 },
    ]);
  });
});
