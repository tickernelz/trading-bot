import { createApi, type Api } from "./api";
import { FeedClient, type LinkInfo } from "./feed";
import { describe, type FeedItem } from "./feedText";
import { parseTs } from "./format";
import { decodeView, storeView, VIEW_KEY, type SavedView } from "./savedView";
import { carriesData, faultOf, greetingMessages, isStale, loadSnapshot, safetyOf, type Fault, type PanelName, type SafetyState } from "./state";
import type { AuditRow, BotInfo, CandleFrame, Decision, Equity, FeedEvent, Health, LogLine, News, Overview, Risk, Scope, SessionInfo, Sentiment, Sysinfo, Trade } from "./types";

const DEFAULT_BOTS: BotInfo[] = [
  { id: "A", label: "Bot A" },
  { id: "B", label: "Bot B" },
];

const FEED_LIMIT = 200;
const RECOVERY_REFRESH_MS = 10000;
const TOKEN_KEY = "tb.session";
const SCOPE_KEY = "tb.scope";
const OVERLAY_TTL_MS = 15 * 60 * 1000;
const HISTORY_LIMIT = 200;

export type LazyPanel = "candles" | "news" | "sentiment" | "history";

function savedViewFromStorage(): SavedView | null {
  try {
    return decodeView(localStorage.getItem(VIEW_KEY));
  } catch {
    return null;
  }
}

function clearAppBadge(): void {
  if ("clearAppBadge" in navigator) void navigator.clearAppBadge().catch(() => undefined);
}
const BASE = (import.meta.env.VITE_GATEWAY_BASE as string | undefined) ?? "";

export interface PendingOrder {
  trade_id: number;
  pair: string;
  side: "buy" | "sell";
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
  coreFault = $state<Fault | null>(null);
  upstreamFault = $state<Fault | null>(null);
  panelFaults = $state<Partial<Record<PanelName | LazyPanel, Fault>>>({});
  pending = $state<PendingOrder[]>([]);
  scope = $state<Scope | null>(sessionStorage.getItem(SCOPE_KEY) === "control" ? "control" : sessionStorage.getItem(TOKEN_KEY) ? "read" : null);
  bots = $state<BotInfo[]>(DEFAULT_BOTS);
  auditLive = $state<AuditRow[]>([]);
  stateTick = $state(0);
  news = $state<Record<string, News>>({});
  sentiment = $state<Sentiment | null>(null);
  history = $state<Record<string, Decision[]>>({});
  savedAt = $state<number | null>(null);
  viewingSaved = $state(false);

  readonly api: Api;
  private client: FeedClient;
  private refreshTimer: ReturnType<typeof setInterval> | null = null;
  private tradeRefresh: ReturnType<typeof setTimeout> | null = null;
  private watchedPairs = new Set<string>();
  private refreshing = false;
  private lastRefreshAt = 0;
  private overlayAt = new Map<string, number>();

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
    const saved = savedViewFromStorage();
    this.savedAt = saved?.saved_at ?? null;
    if (saved && this.token) this.applySaved(saved);
    clearAppBadge();
    setInterval(() => (this.now = Date.now()), 1000);
    addEventListener("online", () => this.client.retryNow());
    addEventListener("offline", () => this.client.wentOffline());
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        clearAppBadge();
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
    return this.mode === "dry_run";
  }

  get dataAge(): number {
    return this.lastDataAt === null ? Number.POSITIVE_INFINITY : this.now - this.lastDataAt;
  }

  get stale(): boolean {
    return isStale({ linkOpen: this.link.state === "open", lastDataAt: this.lastDataAt, now: this.now, upstream: this.upstreamFault, core: this.coreFault });
  }

  get safety(): SafetyState | null {
    return safetyOf(this.health, this.risk);
  }

  get canControl(): boolean {
    return this.scope === "control";
  }

  openSaved(): void {
    const saved = savedViewFromStorage();
    if (saved) this.applySaved(saved);
  }

  closeSaved(): void {
    if (!this.token) this.viewingSaved = false;
  }

  private applySaved(saved: SavedView): void {
    this.health = saved.health;
    this.overview = saved.overview;
    this.risk = saved.risk;
    this.openTrades = saved.openTrades;
    this.closedTrades = saved.closedTrades;
    this.equityDay = saved.equityDay;
    this.equityWeek = saved.equityWeek;
    this.decisions = saved.decisions;
    this.candles = saved.candles;
    this.news = saved.news;
    this.sentiment = saved.sentiment;
    this.sampleData = Boolean(saved.health.gateway.sample_data);
    this.lastDataAt = parseTs(saved.overview.as_of);
    this.savedAt = saved.saved_at;
    this.viewingSaved = true;
  }

  private persist(): void {
    if (!this.health || !this.overview || !this.risk) return;
    const at = Date.now();
    const stored = storeView(localStorage, {
      saved_at: at,
      health: this.health,
      overview: this.overview,
      risk: this.risk,
      openTrades: this.openTrades,
      closedTrades: this.closedTrades,
      equityDay: this.equityDay,
      equityWeek: this.equityWeek,
      decisions: this.decisions,
      candles: this.candles,
      news: this.news,
      sentiment: this.sentiment,
    });
    if (stored) this.savedAt = at;
  }

  async login(password: string): Promise<void> {
    const session = await this.api.post<SessionInfo>("/gw/v1/session", { password });
    this.token = session.token;
    this.scope = session.scope === "control" ? "control" : "read";
    sessionStorage.setItem(TOKEN_KEY, session.token);
    sessionStorage.setItem(SCOPE_KEY, this.scope);
    this.start();
  }

  touchState(): void {
    this.stateTick++;
  }

  reconnect(): void {
    this.client.retryNow();
  }

  logout(): void {
    this.token = null;
    this.scope = null;
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(SCOPE_KEY);
    localStorage.removeItem(VIEW_KEY);
    this.savedAt = null;
    this.viewingSaved = false;
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
    this.client.send(this.subscription());
    if (!this.candles[pair]) void this.loadCandles(pair);
  }

  async loadCandles(pair: string): Promise<void> {
    try {
      const frame = await this.api.get<CandleFrame>("/gw/v1/candles?pair=" + encodeURIComponent(pair) + "&timeframe=1h&limit=300");
      this.candles = { ...this.candles, [pair]: frame };
      this.clearPanelFault("candles");
    } catch (error) {
      this.panelFaults = { ...this.panelFaults, candles: faultOf(error, Date.now()) };
    }
  }

  private fresh(key: string): boolean {
    const at = this.overlayAt.get(key);
    return at !== undefined && Date.now() - at < OVERLAY_TTL_MS;
  }

  async loadNews(pair: string, force = false): Promise<void> {
    if (!force && this.fresh("news:" + pair)) return;
    try {
      const news = await this.api.get<News>("/gw/v1/news?pair=" + encodeURIComponent(pair) + "&limit=50");
      this.news = { ...this.news, [pair]: news };
      this.overlayAt.set("news:" + pair, Date.now());
      this.clearPanelFault("news");
    } catch (error) {
      this.panelFaults = { ...this.panelFaults, news: faultOf(error, Date.now()) };
    }
  }

  async loadSentiment(force = false): Promise<void> {
    if (!force && this.fresh("sentiment")) return;
    try {
      this.sentiment = await this.api.get<Sentiment>("/gw/v1/sentiment?days=30");
      this.overlayAt.set("sentiment", Date.now());
      this.clearPanelFault("sentiment");
    } catch (error) {
      this.panelFaults = { ...this.panelFaults, sentiment: faultOf(error, Date.now()) };
    }
  }

  async loadHistory(pair: string): Promise<void> {
    try {
      const rows = await this.api.get<Decision[]>("/gw/v1/decisions?pair=" + encodeURIComponent(pair) + "&limit=" + HISTORY_LIMIT);
      this.history = { ...this.history, [pair]: rows };
      this.clearPanelFault("history");
    } catch (error) {
      this.panelFaults = { ...this.panelFaults, history: faultOf(error, Date.now()) };
    }
  }

  private greeting(): object[] {
    return greetingMessages(this.lastSeq, this.watchedPairs);
  }

  private subscription(): object {
    return greetingMessages(null, this.watchedPairs)[0];
  }

  private clearPanelFault(name: PanelName | LazyPanel): void {
    if (!this.panelFaults[name]) return;
    const rest = { ...this.panelFaults };
    delete rest[name];
    this.panelFaults = rest;
  }

  async refresh(): Promise<void> {
    if (this.refreshing) return;
    this.refreshing = true;
    this.lastRefreshAt = Date.now();
    try {
      await this.load();
    } finally {
      this.refreshing = false;
    }
  }

  private async load(): Promise<void> {
    const snap = await loadSnapshot(this.api.get, Date.now);
    if (snap.core) {
      this.health = snap.core.health;
      this.overview = snap.core.overview;
      this.risk = snap.core.risk;
      this.sampleData = Boolean(snap.core.health.gateway.sample_data);
      this.lastDataAt = Math.max(this.lastDataAt ?? 0, parseTs(snap.core.overview.as_of));
      this.coreFault = null;
      this.upstreamFault = null;
      this.viewingSaved = false;
    } else {
      this.coreFault = snap.coreFault;
    }
    const p = snap.panels;
    if (p.open) this.openTrades = p.open;
    if (p.closed) this.closedTrades = p.closed;
    if (p.equityDay) this.equityDay = p.equityDay;
    if (p.equityWeek) this.equityWeek = p.equityWeek;
    if (p.decisions) this.decisions = p.decisions;
    if (p.sysinfo) this.sysinfo = p.sysinfo;
    if (p.logs) this.logs = p.logs;
    const lazy: Partial<Record<LazyPanel, Fault>> = {};
    for (const name of ["candles", "news", "sentiment", "history"] as const) if (this.panelFaults[name]) lazy[name] = this.panelFaults[name];
    this.panelFaults = { ...snap.panelFaults, ...lazy };
    if (snap.core) this.persist();
  }

  private apply(event: FeedEvent): void {
    if (typeof event.seq === "number") this.lastSeq = event.seq;
    this.now = Date.now();
    if (carriesData(event.type)) {
      this.lastDataAt = this.now;
      const recovering = this.upstreamFault !== null || this.coreFault !== null;
      this.upstreamFault = null;
      if (recovering && this.now - this.lastRefreshAt >= RECOVERY_REFRESH_MS) void this.refresh();
    }
    const data = event.data as Record<string, unknown>;
    switch (event.type) {
      case "gw.error":
        this.upstreamFault = { code: String(data.code ?? "upstream_error"), message: String(data.message ?? ""), at: this.now };
        break;
      case "gw.hello":
        this.sampleData = Boolean(data.sample_data);
        if (Array.isArray(data.bots) && data.bots.length > 0) this.bots = data.bots as BotInfo[];
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
        if (this.health && (!event.bot || event.bot === this.bots[0]?.id)) this.health = { ...this.health, freqtrade: { ...this.health.freqtrade, state: String(data.status) } };
        this.stateTick++;
        break;
      case "gw.audit":
        this.auditLive = [event.data as AuditRow, ...this.auditLive.filter((r) => r.id !== (event.data as AuditRow).id)].slice(0, 50);
        break;
      case "whitelist":
        if (this.overview && Array.isArray(event.data)) this.overview = { ...this.overview, pairs: { ...this.overview.pairs, whitelist: event.data as string[] } };
        break;
      case "gw.decision":
        this.decisions = [event.data as Decision, ...this.decisions].slice(0, 20);
        this.prependHistory(event.data as Decision);
        break;
      case "gw.candles":
        this.mergeCandles(data);
        break;
      case "entry":
      case "exit":
        this.pending = [
          ...this.pending.filter((o) => o.trade_id !== Number(data.trade_id)),
          { trade_id: Number(data.trade_id), pair: String(data.pair), side: event.type === "entry" ? "buy" : "sell", price: Number(data.limit), ts: event.ts },
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

  private prependHistory(decision: Decision): void {
    const rows = this.history[decision.pair];
    if (!rows || rows.some((d) => d.decision_id === decision.decision_id)) return;
    this.history = { ...this.history, [decision.pair]: [decision, ...rows].slice(0, HISTORY_LIMIT) };
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
        this.clearPanelFault("open");
      } catch (error) {
        this.panelFaults = { ...this.panelFaults, open: faultOf(error, Date.now()) };
      }
    }, 400);
  }
}

export const gateway = new Gateway();
