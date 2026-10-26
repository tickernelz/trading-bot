import { parseTs } from "./format";
import type { Decision, NewsItem, SentimentPoint } from "./types";

export interface Timeline {
  steps: Decision[];
  older: number;
}

export function timeline(history: Decision[], firstCandleMs: number | null): Timeline {
  const unique = new Map<string, Decision>();
  for (const d of history) unique.set(d.decision_id, d);
  const ordered = [...unique.values()].sort((a, b) => parseTs(a.candle) - parseTs(b.candle) || parseTs(a.ts) - parseTs(b.ts));
  if (firstCandleMs === null) return { steps: [], older: ordered.length };
  const steps = ordered.filter((d) => parseTs(d.candle) >= firstCandleMs);
  return { steps, older: ordered.length - steps.length };
}

export function clampStep(index: number, length: number): number {
  if (length === 0) return 0;
  return Math.min(length - 1, Math.max(0, Math.round(index)));
}

export function newsByBar(items: NewsItem[], firstBarS: number, barS = 3600): Map<number, NewsItem[]> {
  const bars = new Map<number, NewsItem[]>();
  for (const item of items) {
    const bar = Math.floor(parseTs(item.published) / 1000 / barS) * barS;
    if (bar < firstBarS) continue;
    bars.set(bar, [...(bars.get(bar) ?? []), item]);
  }
  return bars;
}

export function sentimentLine(points: SentimentPoint[], firstBarS: number, lastBarS: number): { time: number; value: number }[] {
  const line: { time: number; value: number }[] = [];
  let carried: SentimentPoint | null = null;
  for (const p of points) {
    const time = Date.parse(p.date + "T00:00:00Z") / 1000;
    if (time > lastBarS) break;
    if (time < firstBarS) {
      carried = p;
      continue;
    }
    line.push({ time, value: p.value });
  }
  if (carried && (line.length === 0 || line[0].time > firstBarS)) line.unshift({ time: firstBarS, value: carried.value });
  const last = line.at(-1);
  if (last && last.time < lastBarS) line.push({ time: lastBarS, value: last.value });
  return line;
}
