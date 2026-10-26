import { ApiError } from "./api";
import type { Decision, Equity, Health, LogLine, Overview, Risk, Sysinfo, Trade } from "./types";

export const STALE_AFTER_MS = 90000;

export type SafetyState = "safe" | "held" | "stopped";

export const FEED_TOPICS = [
  "entry",
  "entry_fill",
  "exit",
  "exit_fill",
  "status",
  "warning",
  "whitelist",
  "gw.risk",
  "gw.risk_denied",
  "gw.decision",
  "gw.audit",
  "gw.candles",
] as const;

const NOT_MARKET = new Set<string>(["gw.decision", "gw.audit"]);
const FRESHNESS_EVENTS = new Set<string>(FEED_TOPICS.filter((type) => !NOT_MARKET.has(type)));

export function carriesData(type: string): boolean {
  return FRESHNESS_EVENTS.has(type);
}

export function greetingMessages(lastSeq: number | null, pairs: Iterable<string>): object[] {
  const subscribe = {
    type: "subscribe",
    topics: [...FEED_TOPICS],
    candles: [...pairs].map((pair) => ({ pair, timeframe: "1h", limit: 300 })),
  };
  return lastSeq === null ? [subscribe] : [subscribe, { type: "resume", last_seq: lastSeq }];
}

export interface Fault {
  code: string;
  message: string;
  at: number;
}

export interface Freshness {
  linkOpen: boolean;
  lastDataAt: number | null;
  now: number;
  upstream: Fault | null;
  core: Fault | null;
}

export function isStale(f: Freshness): boolean {
  if (f.lastDataAt === null) return false;
  if (!f.linkOpen || f.upstream !== null || f.core !== null) return true;
  return f.now - f.lastDataAt > STALE_AFTER_MS;
}

export function safetyOf(health: Health | null, risk: Risk | null): SafetyState | null {
  if (!health || !risk) return null;
  if (health.freqtrade.state !== "running") return "stopped";
  if (!risk.entries_allowed) return "held";
  return "safe";
}

export function faultOf(error: unknown, at: number): Fault {
  if (error instanceof ApiError) return { code: error.code, message: error.message, at };
  return { code: "client", message: error instanceof Error ? error.message : String(error), at };
}

export interface Core {
  health: Health;
  overview: Overview;
  risk: Risk;
}

export interface Panels {
  open: Trade[];
  closed: Trade[];
  equityDay: Equity;
  equityWeek: Equity;
  decisions: Decision[];
  sysinfo: Sysinfo;
  logs: LogLine[];
}

export type PanelName = keyof Panels;

export interface Snapshot {
  core: Core | null;
  coreFault: Fault | null;
  panels: Partial<Panels>;
  panelFaults: Partial<Record<PanelName, Fault>>;
}

type Get = <T>(path: string) => Promise<T>;

const PANEL_REQUESTS: { [K in PanelName]: (get: Get) => Promise<Panels[K]> } = {
  open: (get) => get<Trade[]>("/gw/v1/trades/open"),
  closed: (get) => get<Trade[]>("/gw/v1/trades?limit=50").then((rows) => rows.filter((t) => !t.is_open)),
  equityDay: (get) => get<Equity>("/gw/v1/equity?window=day"),
  equityWeek: (get) => get<Equity>("/gw/v1/equity?window=7d&bots=A,B"),
  decisions: (get) => get<Decision[]>("/gw/v1/decisions?limit=20"),
  sysinfo: (get) => get<Sysinfo>("/gw/v1/sysinfo"),
  logs: (get) =>
    get<{ logs: (string | number)[][] }>("/gw/v1/logs?limit=30").then((r) =>
      r.logs.map((l) => ({ ts: String(l[0]), logger: String(l[2]), level: String(l[3]), message: String(l[4]) })),
    ),
};

export async function loadSnapshot(get: Get, now: () => number): Promise<Snapshot> {
  const names = Object.keys(PANEL_REQUESTS) as PanelName[];
  const [core, ...panels] = await Promise.allSettled([
    Promise.all([get<Health>("/gw/v1/health"), get<Overview>("/gw/v1/overview"), get<Risk>("/gw/v1/risk")]),
    ...names.map((name) => PANEL_REQUESTS[name](get)),
  ]);
  const snapshot: Snapshot = { core: null, coreFault: null, panels: {}, panelFaults: {} };
  if (core.status === "fulfilled") {
    const [health, overview, risk] = core.value;
    snapshot.core = { health, overview, risk };
  } else {
    snapshot.coreFault = faultOf(core.reason, now());
  }
  panels.forEach((result, i) => {
    const name = names[i];
    if (result.status === "fulfilled") (snapshot.panels as Record<string, unknown>)[name] = result.value;
    else snapshot.panelFaults[name] = faultOf(result.reason, now());
  });
  return snapshot;
}
