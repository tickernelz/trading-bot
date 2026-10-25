import { createApi, type Api } from "./api";
import { FeedClient, type LinkInfo } from "./feed";
import { describe, type FeedItem } from "./feedText";
import { parseTs } from "./format";
import type { CandleFrame, Decision, Equity, FeedEvent, Health, LogLine, Overview, Risk, Sysinfo, Trade } from "./types";

export const STALE_AFTER_MS = 90000;
const FEED_LIMIT = 200;
const TOKEN_KEY = "tb.session";
const BASE = (import.meta.env.VITE_GATEWAY_BASE as string | undefined) ?? "";

export type SafetyState = "aman" | "ditahan" | "berhenti";

export interface PendingOrder {
  trade_id: number;
  pair: string;
  side: "beli" | "jual";
  price: number;
  ts: string;
}

function wsUrl(token: string): string {
  const origin = BASE || location.origin;
  const url = new URL("/gw/v1/events", origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("token", token);
  return url.toString();
}

class Gateway {
  token = $state<string | null>(sessionStorage.getItem(TOKEN_KEY));
  now = $state(Date.now());
  link = $state<LinkInfo>({ state: "idle", retryAt: null, attempts: 0, openedAt: null, closedAt: null });
  lastDataAt = $state<number | null>(null);
  lastSeq: number | null = null;
  sampleData = $state(false);
  health = $state<Health | null>(null);
  overview = $state<Overview | null>(null);
  risk = $state<Risk | null>(null);
  openTrades = $state<Trade[]>([]);
  closedTrades = $state<Trade[]>([]);
  candles = $state<Record<string, CandleFrame>>({});
  equityDay = $state<Equity | null>(null);
  equityWeek = $state<Equity | null>(null);
  decisions = $state<Decision[]>([]);
  feed = $state<FeedItem[]>([]);
  sysinfo = $state<Sysinfo | null>(null);
  logs = $state<LogLine[]>([]);
  error = $state<string | null>(null);
  pending = $state<PendingOrder[]>([]);

  readonly api: Api;
  private client: FeedClient;
  private refreshTimer: ReturnType<typeof setInterval> | null = null;
  private tradeRefresh: ReturnType<typeof setTimeout> | null = null;
  private watchedPairs = new Set<string>();

  constructor() {
    this.api = createApi(BASE, () => this.token, () => this.logout());
    this.client = new FeedClient({
      url: () => wsUrl(this.token ?? ""),
      onEvent: (event) => this.apply(event),
      onLink: (info) => {
        this.link = info;
        if (info.state === "unauthorized") this.logout();
      },
      greeting: () => this.greeting(),
    });
    setInterval(() => (this.now = Date.now()), 1000);
    addEventListener("online", () => this.client.retryNow());
    addEventListener("offline", () => this.client.wentOffline());
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        this.client.retryNow();
        if (this.link.state === "open") void this.refresh();
      }
    });
  }

  get mode(): "dry_run" | "live" | null {
    if (this.overview) return this.overview.mode;
    if (this.health) return this.health.freqtrade.dry_run ? "dry_run" : "live";
    return null;
  }

  get dryRun(): boolean {
    return this.mode !== "live";
  }

  get dataAge(): number {
    return this.lastDataAt === null ? Number.POSITIVE_INFINITY : this.now - this.lastDataAt;
  }

  get stale(): boolean {
    return this.lastDataAt !== null && (this.link.state !== "open" || this.dataAge > STALE_AFTER_MS);
  }

  get safety(): SafetyState | null {
    if (!this.health || !this.risk) return null;
    if (this.health.freqtrade.state !== "running") return "berhenti";
    if (!this.risk.entries_allowed) return "ditahan";
    return "aman";
  }

  async login(password: string): Promise<void> {
    const session = await this.api.post<{ token: string; expires_at: string }>("/gw/v1/session", { password });
    this.token = session.token;
    sessionStorage.setItem(TOKEN_KEY, session.token);
    this.start();
  }

  reconnect(): void {
    this.client.retryNow();
  }

  logout(): void {
    this.token = null;
    sessionStorage.removeItem(TOKEN_KEY);
    this.client.stop();
    if (this.refreshTimer) clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  start(): void {
    if (!this.token) return;
    this.client.start();
    if (this.refreshTimer) clearInterval(this.refreshTimer);
    this.refreshTimer = setInterval(() => {
      if (this.link.state === "open") void this.refresh();
    }, 30000);
  }

  watchCandles(pair: string): void {
    if (this.watchedPairs.has(pair)) return;
    this.watchedPairs.add(pair);
    this.client.send({ type: "subscribe", topics: [], candles: [{ pair, timeframe: "1h", limit: 300 }] });
    if (!this.candles[pair]) void this.loadCandles(pair);
  }

  async loadCandles(pair: string): Promise<void> {
    try {
      const frame = await this.api.get<CandleFrame>("/gw/v1/candles?pair=" + encodeURIComponent(pair) + "&timeframe=1h&limit=300");
      this.candles = { ...this.candles, [pair]: frame };
    } catch (error) {
      this.fail(error);
    }
  }

  private greeting(): object[] {
    const messages: object[] = [];
    if (this.lastSeq !== null) messages.push({ type: "resume", last_seq: this.lastSeq });
    messages.push({
      type: "subscribe",
      topics: ["entry", "entry_fill", "exit", "exit_fill", "status", "warning", "whitelist", "gw.risk", "gw.risk_denied", "gw.decision", "gw.candles"],
      candles: [...this.watchedPairs].map((pair) => ({ pair, timeframe: "1h", limit: 300 })),
    });
    return messages;
  }

  async refresh(): Promise<void> {
    const get = this.api.get;
    try {
      const [health, overview, risk, open, closed, day, week, decisions, sysinfo, logs] = await Promise.all([
        get<Health>("/gw/v1/health"),
        get<Overview>("/gw/v1/overview"),
        get<Risk>("/gw/v1/risk"),
        get<Trade[]>("/gw/v1/trades/open"),
        get<Trade[]>("/gw/v1/trades?limit=50"),
        get<Equity>("/gw/v1/equity?window=day"),
        get<Equity>("/gw/v1/equity?window=7d&bots=A,B"),
        get<Decision[]>("/gw/v1/decisions?limit=20"),
        get<Sysinfo>("/gw/v1/sysinfo"),
        get<{ logs: (string | number)[][] }>("/gw/v1/logs?limit=30"),
      ]);
      this.health = health;
      this.overview = overview;
      this.risk = risk;
      this.openTrades = open;
      this.closedTrades = closed.filter((t) => !t.is_open);
      this.equityDay = day;
      this.equityWeek = week;
      this.decisions = decisions;
      this.sysinfo = sysinfo;
      this.logs = logs.logs.map((l) => ({ ts: String(l[0]), logger: String(l[2]), level: String(l[3]), message: String(l[4]) }));
      this.sampleData = Boolean(health.gateway.sample_data);
      this.lastDataAt = Math.max(this.lastDataAt ?? 0, parseTs(overview.as_of));
      this.error = null;
    } catch (error) {
      this.fail(error);
    }
  }

  private fail(error: unknown): void {
    this.error = error instanceof Error ? error.message : String(error);
  }

  private apply(event: FeedEvent): void {
    if (typeof event.seq === "number") this.lastSeq = event.seq;
    this.lastDataAt = this.now = Date.now();
    const data = event.data as Record<string, unknown>;
    switch (event.type) {
      case "gw.hello":
        this.sampleData = Boolean(data.sample_data);
        void this.refresh();
        for (const pair of this.watchedPairs) void this.loadCandles(pair);
        break;
      case "gw.resync":
        void this.refresh();
        break;
      case "gw.risk":
        if (this.risk) {
          this.risk = { ...this.risk, ...(data as Partial<Risk>) };
        }
        if (this.overview) {
          this.overview = {
            ...this.overview,
            risk: {
              ...this.overview.risk,
              daily_loss_pct: Number(data.daily_loss_pct),
              drawdown_pct: Number(data.drawdown_pct),
              entries_allowed: Boolean(data.entries_allowed),
              breaches: (data.breaches as string[]) ?? [],
            },
          };
        }
        if (this.equityDay && typeof data.equity === "number") {
          const [first, ...rest] = this.equityDay.series;
          if (first) this.equityDay = { ...this.equityDay, series: [{ ...first, points: [...first.points, [event.ts, data.equity]] }, ...rest] };
        }
        break;
      case "status":
        if (this.health) this.health = { ...this.health, freqtrade: { ...this.health.freqtrade, state: String(data.status) } };
        break;
      case "whitelist":
        if (this.overview && Array.isArray(event.data)) this.overview = { ...this.overview, pairs: { ...this.overview.pairs, whitelist: event.data as string[] } };
        break;
      case "gw.decision":
        this.decisions = [event.data as Decision, ...this.decisions].slice(0, 20);
        break;
      case "gw.candles":
        this.mergeCandles(data);
        break;
      case "entry":
      case "exit":
        this.pending = [
          ...this.pending.filter((o) => o.trade_id !== Number(data.trade_id)),
          { trade_id: Number(data.trade_id), pair: String(data.pair), side: event.type === "entry" ? "beli" : "jual", price: Number(data.limit), ts: event.ts },
        ];
        this.scheduleTradeRefresh();
        break;
      case "entry_fill":
      case "exit_fill":
        this.pending = this.pending.filter((o) => o.trade_id !== Number(data.trade_id));
        this.scheduleTradeRefresh();
        break;
    }
    const item = describe(event, this.dryRun);
    if (item) this.feed = [item, ...this.feed].slice(0, FEED_LIMIT);
  }

  private mergeCandles(data: Record<string, unknown>): void {
    const pair = String(data.pair);
    const rows = (data.candles as (string | number | null)[][]) ?? [];
    const current = this.candles[pair];
    if (!current || data.snapshot === true || data.reset === true) {
      if (current) this.candles = { ...this.candles, [pair]: { ...current, data: rows } };
      else void this.loadCandles(pair);
      return;
    }
    const merged = [...current.data];
    for (const row of rows) {
      const index = merged.findIndex((r) => r[0] === row[0]);
      if (index >= 0) merged[index] = row;
      else merged.push(row);
    }
    this.candles = { ...this.candles, [pair]: { ...current, data: merged.slice(-1500) } };
  }

  private scheduleTradeRefresh(): void {
    if (this.tradeRefresh) clearTimeout(this.tradeRefresh);
    this.tradeRefresh = setTimeout(async () => {
      try {
        const [open, closed] = await Promise.all([
          this.api.get<Trade[]>("/gw/v1/trades/open"),
          this.api.get<Trade[]>("/gw/v1/trades?limit=50"),
        ]);
        this.openTrades = open;
        this.closedTrades = closed.filter((t) => !t.is_open);
      } catch (error) {
        this.fail(error);
      }
    }, 400);
  }
}

export const gateway = new Gateway();
