import { createHash, randomBytes } from "node:crypto";
import type { IncomingMessage } from "node:http";
import { anyNeedsConfirmation, diff, needsConfirmation, validate } from "../src/lib/settings";
import type { AuditRow, Decision, DecisionOutcome, Provider, ProviderTest, Settings } from "../src/lib/types";
import { HOUR, iso, isoMs, type Row } from "./data";

export interface MockTrade {
  trade_id: number;
  pair: string;
  open_ms: number;
  open_rate: number;
  stake_amount: number;
  enter_tag: string;
  close_ms?: number;
  close_rate?: number;
  exit_reason?: string;
}

export interface Session {
  scope: "control" | "read";
  expires_at: string;
}

interface Action {
  name: string;
  bot: string;
  targets: string[];
  summary: string;
  risky: boolean;
  params: Record<string, unknown>;
  precheck?: () => Reply | null;
  run: () => unknown;
  detail?: () => Record<string, unknown>;
}

export interface Ctx {
  trades: MockTrade[];
  prices: Map<string, number>;
  candles: Map<string, Row[]>;
  decisions: Decision[];
  fee: number;
  startCapital: number;
  started: number;
  emit: (type: string, data: unknown, bot?: string) => void;
  tradeJson: (t: MockTrade) => Record<string, unknown>;
  profitOf: (t: MockTrade, rate: number) => number;
  overview: () => Record<string, unknown>;
  riskSnapshot: () => { daily_loss_pct: number; drawdown_pct: number };
  equitySeries: (bot: string, label: string, strategy: string, from: number, step: number, start: number, end: number, seed: number, drift: number) => unknown;
}

type BotState = "running" | "paused" | "stopped";
type Reply = { status: number; body: unknown };

const BOTS = [
  { id: "A", label: "Bot A", strategy: "aturan saja" },
  { id: "B", label: "Bot B", strategy: "aturan + swarm bayangan" },
];

const FT = {
  pause: "paused, no more entries will occur from now. Run /start to enable entries.",
  start: "starting trader ...",
  running: "already running",
  stop: "stopping trader ...",
  stopped: "already stopped",
  reload: "Reloading config ...",
};

function voters(): Settings["swarm"]["voters"] {
  return Array.from({ length: 7 }, (_, i) => ({
    id: "v" + (i + 1),
    adapter: "llm_structured" as const,
    provider: "nutaraline",
    model: "deepseek-v4.1-flash-1017",
    variation: "option_order" as const,
    timeout_s: 30,
    weight: 1,
    enabled: true,
  }));
}

function baseSettings(): Settings {
  return {
    mode: "dry_run",
    capital: { initial_idr: 2000000, compounding: true },
    risk: { max_daily_loss_pct: 1.0, max_total_drawdown_pct: 10.0, risk_per_trade_pct: 0.5, max_open_trades: 3, leverage: "none", on_breach: "stop_new_entries", daily_reset_timezone: "Asia/Jakarta" },
    exchange: { name: "indodax", pairs: ["BTC/IDR", "ETH/IDR", "SOL/IDR"], timeframe: "1h", fee_pct: 0.2 },
    providers: [
      { id: "nutaraline", type: "openai-completions", base_url: "from_import", api_key_env: "NUTARALINE_API_KEY", api_key: null, api_key_configured: true, models: ["deepseek-v4.1-flash-1017"] },
      { id: "omniroute", type: "openai-completions", base_url: "from_import", api_key_env: null, api_key: null, api_key_configured: false, models: ["contoh-model-lokal"] },
    ],
    swarm: { enabled: true, mode: "shadow", shuffle_options: true, min_voters_answered: 5, max_spread: null, voters: voters() },
    llm: { backend: "deepagents", analyst_model: "nutaraline:deepseek-v4.1-flash-1017" },
    compute: { max_cost_idr_per_day: false, on_exceed: "skip_new_entries", log_cost: true },
    data: { news_rss: ["coindesk", "cointelegraph"], fear_greed: true, social: false },
    notify: { web_push: true },
    api: { listen: "127.0.0.1", port: 8080, username_env: "FT_API_USERNAME", password_env: "FT_API_PASSWORD", jwt_secret_env: "FT_API_JWT_SECRET", ws_token_env: "FT_API_WS_TOKEN", force_entry: false },
  };
}

const sha = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");

function tokens(key: string): (string | { id: string })[] {
  const out: (string | { id: string })[] = [];
  for (const m of key.matchAll(/([^.[\]]+)|\[([^\]]+)\]/g)) out.push(m[1] !== undefined ? m[1] : { id: m[2] });
  return out;
}

function setPath(root: Record<string, unknown>, key: string, value: unknown): void {
  const parts = tokens(key);
  let node: unknown = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i];
    const next = parts[i + 1];
    if (typeof part === "string") {
      const obj = node as Record<string, unknown>;
      if (obj[part] === undefined) obj[part] = typeof next === "string" ? {} : [];
      node = obj[part];
    } else {
      const list = node as Record<string, unknown>[];
      let item = list.find((x) => String(x.id) === part.id);
      if (!item) {
        item = { id: part.id };
        list.push(item);
      }
      node = item;
    }
  }
  const last = parts.at(-1)!;
  if (typeof last === "string") (node as Record<string, unknown>)[last] = value;
}

function prune(value: unknown): unknown {
  if (Array.isArray(value)) return value.filter((x) => !(x && typeof x === "object" && Object.values(x as object).every((v) => v === null))).map(prune);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, prune(v)]));
  return value;
}

function err(status: number, code: string, message: string, extra: Record<string, unknown> = {}): Reply {
  return { status, body: { error: { code, message, ...extra } } };
}

export function createStage2(ctx: Ctx) {
  const state: Record<string, BotState> = { A: "running", B: "running" };
  const settings: Record<string, Settings> = { A: baseSettings(), B: baseSettings() };
  const locks: Record<string, { id: number; pair: string; side: string; active: boolean; reason: string | null; lock_time: string; lock_end_time: string }[]> = { A: [], B: [] };
  const blacklist: Record<string, string[]> = { A: [], B: [] };
  const extra: Record<string, { enabled: boolean; last_test: ProviderTest | null; last4: string | null; source: "env" | "config" | null }> = {
    nutaraline: { enabled: true, last_test: { at: iso(Date.now() - 2 * HOUR), ok: true, latency_ms: 1840, model: "deepseek-v4.1-flash-1017", error_kind: null }, last4: null, source: "env" },
    omniroute: { enabled: false, last_test: null, last4: null, source: null },
  };
  const audit: AuditRow[] = [];
  const confirmations = new Map<string, { request: string; session: Session; expires: number }>();
  const replies = new Map<string, { request: string; reply: Reply }>();
  let auditId = 0;
  let lockId = 0;
  const IDEMPOTENCY = /^[A-Za-z0-9_-]{8,128}$/;

  function record(row: Omit<AuditRow, "id" | "ts">, bot?: string): AuditRow {
    const full: AuditRow = { id: ++auditId, ts: isoMs(Date.now()), ...row };
    audit.unshift(full);
    ctx.emit("gw.audit", full, bot);
    return full;
  }

  const ftDate = (ms: number) => isoMs(ms).replace("T", " ").slice(0, 19);
  record({ actor: "file", ip: null, action: "config.observed", targets: ["A"], idempotency_key: null, result: "ok", detail: { file: "config/config.yaml", new_sha256: sha(settings.A), valid: true, error: null, changes: [] } });
  record({ actor: "file", ip: null, action: "config.observed", targets: ["B"], idempotency_key: null, result: "ok", detail: { file: "config/config.bot-b.yaml", new_sha256: sha(settings.B), valid: true, error: null, changes: [] } });
  record({ actor: "anonymous", ip: "127.0.0.1", action: "session.create", targets: [], idempotency_key: null, result: "denied", detail: null });
  record({ actor: "owner", ip: "127.0.0.1", action: "session.create", targets: [], idempotency_key: null, result: "ok", detail: null });
  record({ actor: "owner", ip: "127.0.0.1", action: "config.changed", targets: ["A"], idempotency_key: "4f0c2a7e-0d3b-4c51-9e7a-3a1f2b6c9d10", result: "ok", detail: { note: "Contoh data: kuorum awal 5 dari 7", changes: [{ key: "swarm.min_voters_answered", old: 4, new: 5 }] } });

  const ipOf = (session: Session) => (session.scope === "control" ? "127.0.0.1" : "203.0.113.7");

  function controlRow(session: Session, a: Action, key: string | undefined, result: string, extra: Record<string, unknown> = {}): AuditRow {
    const actor = result === "forbidden" ? session.scope + "_session" : "owner";
    return record({ actor, ip: ipOf(session), action: a.name, targets: [a.bot, ...a.targets], idempotency_key: key ?? null, result, detail: { params: a.params, summary: a.summary, ...extra } }, a.bot);
  }

  function execute(session: Session, key: string | undefined, request: string, a: Action, confirm: unknown): Reply {
    if (session.scope !== "control") {
      controlRow(session, a, key, "forbidden");
      return err(403, "forbidden_local_only", "control actions are accepted only from loopback");
    }
    if (!key || !IDEMPOTENCY.test(key)) return err(400, "invalid_request", "Idempotency-Key header (8-128 of [A-Za-z0-9_-]) is required");
    const stored = replies.get(key);
    if (stored) {
      if (stored.request !== request) return err(409, "invalid_request", "Idempotency-Key was used for another request");
      controlRow(session, a, key, "replayed");
      return stored.reply;
    }
    const reject = (reply: Reply) => {
      const e = (reply.body as { error: { code: string; message: string } }).error;
      controlRow(session, a, key, "rejected", { error: e.code, message: e.message });
      return reply;
    };
    const pre = a.precheck?.();
    if (pre) return reject(pre);
    if (a.risky) {
      if (typeof confirm !== "string") {
        const id = "cf_" + randomBytes(5).toString("hex").toUpperCase();
        const expires = Date.now() + 60000;
        confirmations.set(id, { request, session, expires });
        controlRow(session, a, key, "confirmation_required");
        return err(409, "confirmation_required", a.name + " needs confirmation", { confirmation: { id, action: a.name, targets: [a.bot, ...a.targets], summary: a.summary, expires_at: iso(expires) } });
      }
      const pending = confirmations.get(confirm);
      if (!pending || pending.request !== request || pending.session !== session) return reject(err(409, "confirmation_invalid", "confirmation is unknown, used, or for another action"));
      confirmations.delete(confirm);
      if (pending.expires < Date.now()) return reject(err(409, "confirmation_expired", "confirmation expired; ask for a new one"));
    }
    const body = a.run();
    controlRow(session, a, key, "ok", a.detail?.() ?? {});
    const reply = { status: 200, body };
    replies.set(key, { request, reply });
    return reply;
  }

  function closeTrade(t: MockTrade, reason: string, bot: string) {
    const rate = ctx.prices.get(t.pair)!;
    const exit = { trade_id: t.trade_id, pair: t.pair, exit_reason: reason, limit: Math.round(rate), order_type: "market", open_rate: Math.round(t.open_rate) };
    ctx.emit("exit", exit, bot);
    t.close_ms = Date.now();
    t.close_rate = rate;
    t.exit_reason = reason;
    const profit = ctx.profitOf(t, rate);
    ctx.emit("exit_fill", { ...exit, close_rate: Math.round(rate), profit_amount: Number(profit.toFixed(4)), profit_ratio: Number((profit / t.stake_amount).toFixed(6)), is_final_exit: true }, bot);
  }

  function redacted(bot: string) {
    const s = structuredClone(settings[bot]);
    s.providers = s.providers.map((p) => ({ ...p, api_key: null }));
    return { ...s, revision: sha(settings[bot]) };
  }

  function providerHealth(id: string) {
    const lat: number[] = [];
    let calls = 0;
    let ok = 0;
    let last: string | null = null;
    for (const d of ctx.decisions.slice(0, 20)) {
      for (const v of d.voters) {
        if (v.provider !== id) continue;
        calls++;
        last = last ?? v.status;
        if (v.status === "ok") {
          ok++;
          lat.push(v.latency_s);
        }
      }
    }
    if (calls === 0) return null;
    lat.sort((a, b) => a - b);
    return { calls, ok, last_status: last, latency_p50_s: lat.length ? lat[Math.floor(lat.length / 2)] : null, latency_max_s: lat.length ? lat.at(-1)! : null };
  }

  function provider(id: string, session: Session): Provider {
    const s = settings.A.providers.find((p) => p.id === id)!;
    const x = extra[id] ?? { enabled: true, last_test: null, last4: null, source: null };
    const users = settings.A.swarm.voters.filter((v) => v.provider === id).map((v) => v.id);
    return {
      id,
      type: s.type,
      base_url: s.base_url,
      host: s.base_url === "from_import" ? null : new URL(s.base_url).host,
      models: s.models,
      enabled: x.enabled,
      api_key_configured: s.api_key_configured,
      api_key_source: x.source,
      api_key_env: s.api_key_env,
      api_key_last4: session.scope === "control" ? x.last4 : null,
      used_by: { analyst: settings.A.llm.analyst_model.startsWith(id + ":"), voters: users },
      last_test: x.last_test,
      health: providerHealth(id),
    };
  }

  function outcome(d: Decision): DecisionOutcome {
    const ts = Date.parse(d.candle);
    const settles = ts + 5 * HOUR;
    const rows = ctx.candles.get(d.pair) ?? [];
    const at = rows.find((r) => Date.parse(r[0]) === ts);
    const after = rows.find((r) => Date.parse(r[0]) === ts + 4 * HOUR);
    const base = { horizon_h: 4, settles_at: iso(settles), trade_id: null, is_open: null, profit_abs: null, profit_pct: null };
    if (d.status === "ok" && d.verdict === "izinkan") {
      const t = ctx.trades.find((x) => x.pair === d.pair && Math.abs(x.open_ms - ts) < 6 * HOUR);
      if (t) {
        const rate = t.close_ms ? t.close_rate! : ctx.prices.get(t.pair)!;
        const p = ctx.profitOf(t, rate);
        return { ...base, state: t.close_ms ? "settled" : "pending", basis: "trade", price_at: Math.round(t.open_rate), price_after: Math.round(rate), return_pct: null, return_after_fees_pct: null, trade_id: t.trade_id, is_open: !t.close_ms, profit_abs: Number(p.toFixed(2)), profit_pct: Number(((p / t.stake_amount) * 100).toFixed(2)) };
      }
    }
    if (Date.now() < settles) return { ...base, state: "pending", basis: "price", price_at: at ? Math.round(at[4]) : null, price_after: null, return_pct: null, return_after_fees_pct: null };
    if (!at || !after) return { ...base, state: "insufficient_data", basis: "price", price_at: at ? Math.round(at[4]) : null, price_after: null, return_pct: null, return_after_fees_pct: null };
    const gross = (after[4] / at[4] - 1) * 100;
    const net = ((after[4] * (1 - ctx.fee)) / (at[4] * (1 + ctx.fee)) - 1) * 100;
    return { ...base, state: "settled", basis: "price", price_at: Math.round(at[4]), price_after: Math.round(after[4]), return_pct: Number(gross.toFixed(2)), return_after_fees_pct: Number(net.toFixed(2)) };
  }

  const decorate = (d: Decision): Decision => ({ ...d, bot: d.bot ?? "B", outcome: outcome(d) });

  function closedFor(bot: string) {
    return ctx.trades.filter((t) => t.close_ms && (bot === "A" || t.trade_id % 3 !== 0));
  }

  function profitTotal(bot: string) {
    const closed = closedFor(bot);
    const profits = closed.map((t) => ({ t, p: ctx.profitOf(t, t.close_rate!) }));
    const sum = profits.reduce((s, x) => s + x.p, 0);
    const byPair = new Map<string, number>();
    for (const x of profits) byPair.set(x.t.pair, (byPair.get(x.t.pair) ?? 0) + x.p);
    const ranked = [...byPair.entries()].sort((a, b) => b[1] - a[1]);
    let peak = 0;
    let run = 0;
    let dd = 0;
    for (const x of [...profits].sort((a, b) => a.t.close_ms! - b.t.close_ms!)) {
      run += x.p;
      peak = Math.max(peak, run);
      dd = Math.max(dd, peak - run);
    }
    return {
      window: "total",
      stake_currency: "IDR",
      profit_closed_coin: Number(sum.toFixed(4)),
      profit_closed_percent: Number(((sum / ctx.startCapital) * 100).toFixed(2)),
      profit_all_percent: Number(((sum / ctx.startCapital) * 100).toFixed(2)),
      trade_count: closed.length + ctx.trades.filter((t) => !t.close_ms).length,
      closed_trade_count: closed.length,
      winning_trades: profits.filter((x) => x.p > 0).length,
      losing_trades: profits.filter((x) => x.p < 0).length,
      best_pair: ranked[0]?.[0] ?? null,
      worst_pair: ranked.at(-1)?.[0] ?? null,
      max_drawdown: Number((dd / ctx.startCapital).toFixed(6)),
      max_drawdown_abs: Number(dd.toFixed(2)),
    };
  }

  function profitWindow(bot: string, window: string, count: number) {
    const unit = window === "daily" ? 24 * HOUR : window === "weekly" ? 7 * 24 * HOUR : 30 * 24 * HOUR;
    const offset = 7 * HOUR;
    const now = Date.now();
    const startOf = (ms: number) => Math.floor((ms + offset) / unit) * unit - offset;
    let balance = ctx.startCapital;
    const data = [];
    for (let i = count - 1; i >= 0; i--) {
      const from = startOf(now) - i * unit;
      const rows = closedFor(bot).filter((t) => t.close_ms! >= from && t.close_ms! < from + unit);
      const abs = rows.reduce((s, t) => s + ctx.profitOf(t, t.close_rate!), 0);
      data.push({ date: iso(from + offset).slice(0, 10), abs_profit: Number(abs.toFixed(4)), rel_profit: Number((abs / balance).toFixed(8)), starting_balance: Number(balance.toFixed(2)), trade_count: rows.length });
      balance += abs;
    }
    return { window, stake_currency: "IDR", data };
  }

  function group<K extends string>(bot: string, keyOf: (t: MockTrade) => string, name: K) {
    const out = new Map<string, { abs: number; pct: number; count: number }>();
    for (const t of closedFor(bot)) {
      const p = ctx.profitOf(t, t.close_rate!);
      const e = out.get(keyOf(t)) ?? { abs: 0, pct: 0, count: 0 };
      e.abs += p;
      e.pct += (p / t.stake_amount) * 100;
      e.count++;
      out.set(keyOf(t), e);
    }
    return [...out.entries()].map(([k, e]) => ({ [name]: k, profit_abs: Number(e.abs.toFixed(4)), profit_pct: Number(e.pct.toFixed(2)), count: e.count }));
  }

  async function route(req: IncomingMessage, url: URL, session: Session, readBody: () => Promise<Record<string, unknown>>): Promise<Reply | null> {
    const path = url.pathname;
    const method = req.method ?? "GET";
    const bot = url.searchParams.get("bot") ?? "A";
    if (!(bot in state)) return err(404, "not_found", "unknown bot " + bot);
    const key = (req.headers["idempotency-key"] as string | undefined) ?? undefined;
    const owner = session.scope === "control";

    if (method === "GET") {
      if (path === "/gw/v1/overview") return { status: 200, body: { ...ctx.overview(), state: state[bot], pairs: { whitelist: settings[bot].exchange.pairs, blacklist: blacklist[bot], locks: locks[bot].filter((l) => l.active).length } } };
      if (path === "/gw/v1/pairs") return { status: 200, body: { whitelist: { pairs: settings[bot].exchange.pairs, length: settings[bot].exchange.pairs.length, method: ["StaticPairList"] }, blacklist: { pairs: blacklist[bot], length: blacklist[bot].length, method: ["StaticPairList"] }, locks: { lock_count: locks[bot].length, locks: locks[bot] } } };
      if (path === "/gw/v1/trades" && (url.searchParams.has("offset") || url.searchParams.get("state") === "closed")) {
        const limit = Number(url.searchParams.get("limit") ?? 50);
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const rows = (url.searchParams.get("state") === "closed" ? closedFor(bot) : ctx.trades).slice().sort((a, b) => (b.close_ms ?? Infinity) - (a.close_ms ?? Infinity));
        return { status: 200, body: rows.slice(offset, offset + limit).map(ctx.tradeJson) };
      }
      if (path === "/gw/v1/decisions") {
        const limit = Number(url.searchParams.get("limit") ?? 20);
        const before = url.searchParams.get("before");
        const status = url.searchParams.get("status");
        const rows = ctx.decisions.filter((d) => (!before || d.ts < before) && (!status || d.status === status) && (!url.searchParams.get("bot") || (d.bot ?? "B") === bot));
        return { status: 200, body: rows.slice(0, limit).map(decorate) };
      }
      const decisionMatch = path.match(/^\/gw\/v1\/decisions\/([^/]+)$/);
      if (decisionMatch) {
        const d = ctx.decisions.find((x) => x.decision_id === decisionMatch[1]);
        return d ? { status: 200, body: decorate(d) } : err(404, "not_found", "no decision");
      }
      if (path === "/gw/v1/equity" && url.searchParams.get("window") === "total") {
        const from = ctx.started - 9 * 24 * HOUR;
        const risk = ctx.overview() as { balance: { total: number } };
        return { status: 200, body: { window: "total", start_equity: ctx.startCapital, series: [ctx.equitySeries("A", "Bot A", "aturan saja", from, HOUR, ctx.startCapital, risk.balance.total, 41, 0.000004), ctx.equitySeries("B", "Bot B", "aturan + swarm bayangan", from, HOUR, ctx.startCapital, risk.balance.total + 3820, 43, 0.00001)] } };
      }
      if (path === "/gw/v1/profit") {
        const window = url.searchParams.get("window") ?? "total";
        if (window === "total") return { status: 200, body: profitTotal(bot) };
        return { status: 200, body: profitWindow(bot, window, Number(url.searchParams.get("timescale") ?? 7)) };
      }
      if (path === "/gw/v1/stats") {
        const reasons: Record<string, { wins: number; losses: number; draws: number }> = {};
        const dur = { wins: [] as number[], losses: [] as number[], draws: [] as number[] };
        for (const t of closedFor(bot)) {
          const p = ctx.profitOf(t, t.close_rate!);
          const r = (reasons[t.exit_reason!] ??= { wins: 0, losses: 0, draws: 0 });
          const k = p > 0 ? "wins" : p < 0 ? "losses" : "draws";
          r[k]++;
          dur[k].push((t.close_ms! - t.open_ms) / 60000);
        }
        const avg = (xs: number[]) => (xs.length ? Number((xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(2)) : null);
        return { status: 200, body: { durations: { wins: avg(dur.wins), draws: avg(dur.draws), losses: avg(dur.losses) }, exit_reasons: reasons } };
      }
      if (path === "/gw/v1/performance") {
        return { status: 200, body: { per_pair: group(bot, (t) => t.pair, "pair"), by_enter_tag: group(bot, (t) => t.enter_tag, "enter_tag"), by_exit_reason: group(bot, (t) => t.exit_reason!, "exit_reason") } };
      }
      if (path === "/gw/v1/settings") return { status: 200, body: redacted(bot) };
      if (path === "/gw/v1/providers") return { status: 200, body: settings.A.providers.map((p) => provider(p.id, session)) };
      if (path === "/gw/v1/providers/import") {
        if (!owner) return err(403, "forbidden_local_only", "import only from loopback");
        const have = new Set(settings.A.providers.map((p) => p.id));
        return { status: 200, body: { source: "~/.omp/agent/models.yml", candidates: [
          { id: "nutaraline", type: "openai-completions", base_url: "https://api.contoh.invalid/v1", models: ["deepseek-v4.1-flash-1017"], has_key: true, exists: have.has("nutaraline") },
          { id: "modelrouter", type: "openai-completions", base_url: "https://router.contoh.invalid/v1", models: ["jev-contoh", "clef-contoh"], has_key: true, exists: have.has("modelrouter") },
          { id: "omniroute", type: "openai-completions", base_url: "http://127.0.0.1:20128/v1", models: ["contoh-model-lokal"], has_key: false, exists: have.has("omniroute") },
        ] } };
      }
      if (path === "/gw/v1/audit") {
        const limit = Number(url.searchParams.get("limit") ?? 50);
        const before = url.searchParams.get("before_id");
        const action = url.searchParams.get("action") ?? "";
        const result = url.searchParams.get("result") ?? "";
        const target = url.searchParams.get("target") ?? "";
        const actor = url.searchParams.get("actor") ?? "";
        const since = url.searchParams.get("since");
        const until = url.searchParams.get("until");
        const rows = audit.filter((r) => (!before || r.id < Number(before)) && r.action.startsWith(action) && (!result || r.result === result) && (!target || r.targets.includes(target)) && (!actor || r.actor === actor) && (!since || Date.parse(r.ts) >= Date.parse(since)) && (!until || Date.parse(r.ts) < Date.parse(until)));
        return { status: 200, body: rows.slice(0, limit) };
      }
      return null;
    }

    const b = await readBody();
    const { confirm, ...params } = b;
    const request = method + " " + path + "?" + [...url.searchParams].sort().map(([k, v]) => k + "=" + v).join("&") + " " + JSON.stringify(params);
    const act = (a: Omit<Action, "bot" | "params">) => execute(session, key, request, { ...a, bot, params }, confirm);
    const ft = (status: string) => ({ status });
    const pairsOf = () => ({ blacklist: blacklist[bot], blacklist_expanded: blacklist[bot], errors: {}, length: blacklist[bot].length, method: ["StaticPairList"] });
    const locksOf = () => ({ lock_count: locks[bot].length, locks: locks[bot] });

    const control = path.match(/^\/gw\/v1\/control\/(pause|stop-entry|resume|stop|reload-config)$/);
    if (method === "POST" && control) {
      const name = control[1];
      return act({
        name: "control." + name.replace("-", "_"),
        targets: [],
        summary: name === "stop" ? "Stop " + bot + ": bot stops, open trades are not managed" : "",
        risky: name === "stop",
        run: () => {
          let reply = ft(FT.reload);
          if (name === "pause" || name === "stop-entry") {
            reply = ft(FT.pause);
            state[bot] = "paused";
          } else if (name === "resume") {
            reply = ft(state[bot] === "running" ? FT.running : FT.start);
            state[bot] = "running";
          } else if (name === "stop") {
            reply = ft(state[bot] === "stopped" ? FT.stopped : FT.stop);
            state[bot] = "stopped";
          }
          ctx.emit("status", { status: state[bot] }, bot);
          return reply;
        },
      });
    }
    const exit = path === "/gw/v1/trades/exit-all" ? "all" : path.match(/^\/gw\/v1\/trades\/(\d+)\/exit$/)?.[1];
    if (method === "POST" && exit) {
      const open = ctx.trades.filter((t) => !t.close_ms && (exit === "all" || t.trade_id === Number(exit)));
      return act({
        name: exit === "all" ? "trade.exit_all" : "trade.exit",
        targets: exit === "all" ? ["all"] : [String(exit)],
        summary: exit === "all" ? "Exit every open trade on Bot " + bot + " at market" : "Exit trade " + exit + " on Bot " + bot + " at market",
        risky: true,
        precheck: () => (open.length === 0 ? err(404, "not_found", "no open trade " + exit) : null),
        run: () => {
          for (const t of open) closeTrade(t, "force_exit", bot);
          return { result: exit === "all" ? "Created exit orders for all open trades." : "Created exit order for trade " + exit + "." };
        },
      });
    }
    if (method === "POST" && path === "/gw/v1/locks") {
      const pair = String(b.pair ?? "");
      return act({
        name: "pair.lock",
        targets: [pair],
        summary: "Lock " + pair + " on Bot " + bot + " until " + String(b.until),
        risky: false,
        precheck: () => (!settings[bot].exchange.pairs.includes(pair) ? err(422, "invalid_request", "pair not in whitelist") : Number.isNaN(Date.parse(String(b.until))) || Date.parse(String(b.until)) <= Date.now() ? err(400, "invalid_request", "until must be in the future") : null),
        run: () => {
          locks[bot].push({ id: ++lockId, pair, side: String(b.side ?? "*"), active: true, reason: (b.reason as string) ?? null, lock_time: ftDate(Date.now()), lock_end_time: ftDate(Date.parse(String(b.until))) });
          return locksOf();
        },
      });
    }
    const unlock = path.match(/^\/gw\/v1\/locks\/(\d+)$/);
    if (method === "DELETE" && unlock) {
      const lock = locks[bot].find((l) => l.id === Number(unlock[1]));
      return act({
        name: "pair.unlock",
        targets: ["lock:" + unlock[1]],
        summary: "Remove lock " + unlock[1] + " on Bot " + bot,
        risky: true,
        precheck: () => (lock ? null : err(404, "not_found", "no lock " + unlock[1])),
        run: () => {
          locks[bot] = locks[bot].filter((l) => l !== lock);
          return locksOf();
        },
      });
    }
    if (method === "POST" && path === "/gw/v1/blacklist") {
      const add = Array.isArray(b.pairs) ? (b.pairs as string[]) : [];
      return act({
        name: "pair.blacklist",
        targets: add,
        summary: "Blacklist " + add.join(", ") + " on Bot " + bot,
        risky: false,
        precheck: () => (add.length === 0 ? err(400, "invalid_request", "pairs is required") : null),
        run: () => {
          blacklist[bot] = [...new Set([...blacklist[bot], ...add])];
          return pairsOf();
        },
      });
    }
    if (method === "DELETE" && path === "/gw/v1/blacklist") {
      const pairs = (url.searchParams.get("pairs") ?? "").split(",").filter(Boolean);
      return act({
        name: "pair.unblacklist",
        targets: pairs,
        summary: "Remove " + pairs.join(", ") + " from the blacklist of Bot " + bot,
        risky: true,
        run: () => {
          blacklist[bot] = blacklist[bot].filter((x) => !pairs.includes(x));
          return pairsOf();
        },
      });
    }
    if (method === "PATCH" && path === "/gw/v1/settings") {
      const changes = (b.changes as { key: string; value: unknown }[]) ?? [];
      const note = String(b.note ?? "").trim();
      const next = structuredClone(settings[bot]) as unknown as Record<string, unknown>;
      for (const c of changes) setPath(next, c.key, c.value);
      const candidate = prune(next) as Settings;
      const applied = diff(settings[bot], candidate);
      const masked = applied.map((c) => (c.key.endsWith(".api_key") ? { ...c, old: c.old ? "<set>" : null, new: c.new ? "<set>" : null } : c));
      const old = sha(settings[bot]);
      return act({
        name: "config.changed",
        targets: [],
        summary: applied.filter(needsConfirmation).map((c) => c.key + " " + String(c.old) + " -> " + String(c.new)).join("; "),
        risky: anyNeedsConfirmation(applied),
        precheck: () => {
          if (!note || note.length > 500) return err(400, "invalid_request", "note is required", { fields: [{ key: "note", message: "Catatan wajib, 1 sampai 500 karakter" }] });
          if (b.revision !== old) return err(409, "stale_revision", "config changed since it was read");
          const fields = validate(candidate);
          if (fields.length > 0) return err(400, "invalid_request", "settings failed schema validation", { fields });
          const risk = ctx.riskSnapshot();
          if (candidate.risk.max_daily_loss_pct <= risk.daily_loss_pct || candidate.risk.max_total_drawdown_pct <= risk.drawdown_pct) return err(409, "risk_limit_breached", "new limit is below the loss already running");
          return null;
        },
        run: () => {
          settings[bot] = candidate;
          return { revision: sha(candidate), applied: masked, restart_required: false };
        },
        detail: () => ({ params: undefined, note, changes: masked, old_sha256: old, new_sha256: sha(candidate), valid: true }),
      });
    }
    const test = path.match(/^\/gw\/v1\/providers\/([^/]+)\/(test|state)$/);
    if (method === "POST" && test) {
      const id = test[1];
      const p = settings.A.providers.find((x) => x.id === id);
      if (!p) return err(404, "not_found", "no provider " + id);
      extra[id] ??= { enabled: true, last_test: null, last4: null, source: null };
      if (test[2] === "state") {
        extra[id].enabled = Boolean(b.enabled);
        record({ actor: "owner", ip: ipOf(session), action: "provider.state", targets: [id], idempotency_key: key ?? null, result: "ok", detail: { changes: [{ key: "providers[" + id + "].enabled", old: !b.enabled, new: Boolean(b.enabled) }] } });
        return { status: 200, body: provider(id, session) };
      }
      await new Promise((r) => setTimeout(r, 700));
      const t: ProviderTest = p.api_key_configured
        ? { at: iso(Date.now()), ok: true, latency_ms: 900 + Math.round(Math.random() * 1600), model: String(b.model ?? p.models[0]), error_kind: null }
        : { at: iso(Date.now()), ok: false, latency_ms: null, model: null, error_kind: "auth" };
      extra[id].last_test = t;
      record({ actor: "owner", ip: ipOf(session), action: "provider.test", targets: [id], idempotency_key: key ?? null, result: t.ok ? "ok" : "failed", detail: { summary: t.ok ? "OK " + t.latency_ms + " ms" : "gagal: " + t.error_kind } });
      return { status: 200, body: t };
    }
    const write = method === "POST" && path === "/gw/v1/providers" ? "create" : method === "PUT" && path.match(/^\/gw\/v1\/providers\/[^/]+$/) ? "update" : method === "POST" && path === "/gw/v1/providers/import" ? "import" : null;
    if (write) {
      if (!owner) return err(403, "forbidden_local_only", "provider keys are managed from loopback only");
      if (write === "import") {
        const items = (b.items as { id: string; include_key: boolean }[]) ?? [];
        const imported: Provider[] = [];
        for (const item of items) {
          const known = { nutaraline: ["deepseek-v4.1-flash-1017"], modelrouter: ["jev-contoh", "clef-contoh"], omniroute: ["contoh-model-lokal"] }[item.id];
          if (!known) continue;
          const existing = settings.A.providers.find((p) => p.id === item.id);
          const entry = { id: item.id, type: "openai-completions" as const, base_url: "from_import", api_key_env: existing?.api_key_env ?? null, api_key: null, api_key_configured: Boolean(existing?.api_key_configured) || item.include_key, models: known };
          for (const bot of Object.keys(settings)) settings[bot].providers = [...settings[bot].providers.filter((p) => p.id !== item.id), entry];
          extra[item.id] = { ...(extra[item.id] ?? { enabled: true, last_test: null }), enabled: extra[item.id]?.enabled ?? true, last_test: extra[item.id]?.last_test ?? null, last4: item.include_key ? "x9Qa" : (extra[item.id]?.last4 ?? null), source: item.include_key ? "config" : (extra[item.id]?.source ?? null) };
          imported.push(provider(item.id, session));
        }
        record({ actor: "owner", ip: "127.0.0.1", action: "provider.import", targets: items.map((i) => i.id), idempotency_key: key ?? null, result: "ok", detail: { changes: items.map((i) => ({ key: "providers[" + i.id + "].api_key", old: null, new: i.include_key ? "<set>" : null })) } });
        return { status: 200, body: { imported } };
      }
      const id = write === "create" ? String(b.id) : decodeURIComponent(path.split("/").at(-1)!);
      const existing = settings.A.providers.find((p) => p.id === id);
      if (write === "create" && existing) return err(400, "invalid_request", "provider exists", { fields: [{ key: "id", message: "Id sudah dipakai" }] });
      if (write === "update" && !existing) return err(404, "not_found", "no provider " + id);
      const hadKey = Boolean(existing?.api_key_configured);
      const key4 = typeof b.api_key === "string" && b.api_key ? b.api_key.slice(-4) : null;
      const hasKey = b.api_key_clear ? Boolean(b.api_key_env) : Boolean(key4) || hadKey || Boolean(b.api_key_env);
      const entry = { id, type: b.type as Settings["providers"][number]["type"], base_url: String(b.base_url), api_key_env: (b.api_key_env as string | null) ?? null, api_key: null, api_key_configured: hasKey, models: (b.models as string[]) ?? [] };
      for (const bot of Object.keys(settings)) settings[bot].providers = [...settings[bot].providers.filter((p) => p.id !== id), entry];
      extra[id] = { enabled: extra[id]?.enabled ?? true, last_test: extra[id]?.last_test ?? null, last4: b.api_key_clear ? null : (key4 ?? extra[id]?.last4 ?? null), source: key4 ? "config" : entry.api_key_env ? "env" : b.api_key_clear ? null : (extra[id]?.source ?? null) };
      record({ actor: "owner", ip: "127.0.0.1", action: "provider." + write, targets: [id], idempotency_key: key ?? null, result: "ok", detail: { changes: [{ key: "providers[" + id + "].api_key", old: hadKey ? "<set>" : null, new: hasKey ? "<set>" : null }] } });
      return { status: 200, body: provider(id, session) };
    }
    return null;
  }

  return { route, bots: BOTS, decorate };
}
