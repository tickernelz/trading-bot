import type { CandleFrame, Decision, Equity, Health, News, Overview, Risk, Sentiment, Trade } from "./types";

export const VIEW_KEY = "tb.lastView";
export const VIEW_VERSION = 1;
export const SAVED_CANDLES = 300;

export interface SavedView {
  version: typeof VIEW_VERSION;
  saved_at: number;
  health: Health;
  overview: Overview;
  risk: Risk;
  openTrades: Trade[];
  closedTrades: Trade[];
  equityDay: Equity | null;
  equityWeek: Equity | null;
  decisions: Decision[];
  candles: Record<string, CandleFrame>;
  news: Record<string, News>;
  sentiment: Sentiment | null;
}

export function encodeView(view: Omit<SavedView, "version">): string {
  const candles: Record<string, CandleFrame> = {};
  for (const [pair, frame] of Object.entries(view.candles)) candles[pair] = { ...frame, data: frame.data.slice(-SAVED_CANDLES) };
  return JSON.stringify({ ...view, version: VIEW_VERSION, candles });
}

export function decodeView(raw: string | null): SavedView | null {
  if (!raw) return null;
  try {
    const view = JSON.parse(raw) as Partial<SavedView>;
    if (view.version !== VIEW_VERSION || typeof view.saved_at !== "number" || !view.health || !view.overview || !view.risk) return null;
    return {
      ...view,
      openTrades: view.openTrades ?? [],
      closedTrades: view.closedTrades ?? [],
      equityDay: view.equityDay ?? null,
      equityWeek: view.equityWeek ?? null,
      decisions: view.decisions ?? [],
      candles: view.candles ?? {},
      news: view.news ?? {},
      sentiment: view.sentiment ?? null,
    } as SavedView;
  } catch {
    return null;
  }
}

export function storeView(storage: Pick<Storage, "setItem">, view: Omit<SavedView, "version">): boolean {
  try {
    storage.setItem(VIEW_KEY, encodeView(view));
    return true;
  } catch {
    return false;
  }
}
