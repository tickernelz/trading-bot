import { randomBytes } from "node:crypto";
import type { IncomingMessage } from "node:http";
import { flatten, validate } from "../src/lib/settings";
import type { AuditRow, Decision, DecisionOutcome, ProviderTest, Settings, VoterSetting } from "../src/lib/types";
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
  upstreamFailure: (path: string) => number | undefined;
}

type BotState = "running" | "paused" | "stopped";
type Reply = { status: number; body: unknown };
type Raw = Record<string, unknown>;

const BOTS = [
  { id: "A", label: "Bot A", strategy: "rules only" },
  { id: "B", label: "Bot B", strategy: "rules + shadow swarm" },
];

const FT = {
  pause: "paused, no more entries will occur from now. Run /start to enable entries.",
  start: "starting trader ...",
  running: "already running",
  stop: "stopping trader ...",
  stopped: "already stopped",
  reload: "Reloading config ...",
};

const FROZEN = ["mode", "bot_id", "api", "shadow", "providers"];
const RAISING = ["risk.max_daily_loss_pct", "risk.max_total_drawdown_pct", "risk.risk_per_trade_pct", "risk.max_open_trades", "capital.initial_idr"];
const IDEMPOTENCY = /^[A-Za-z0-9_-]{8,128}$/;
const ENV_SET = new Set(["NUTARALINE_API_KEY"]);
const MODELS_YML = [
  { name: "nutaraline", type: "openai-completions", base_url: "https://api.example.invalid/v1", models: ["deepseek-v4.1-flash-1017"], key_source: "env" as const },
  { name: "modelrouter", type: "openai-completions", base_url: "https://router.example.invalid/v1", models: ["jev-example", "clef-example"], key_source: "literal" as const },
  { name: "omniroute", type: "openai-completions", base_url: "http://127.0.0.1:20128/v1", models: ["example-local-model"], key_source: "none" as const },
  { name: "shellkey", type: "openai-completions", base_url: "https://shell.example.invalid/v1", models: ["m1"], key_source: "command" as const },
  { name: "Odd Name", type: "openai-completions", base_url: "https://odd.example.invalid/v1", models: ["m1"], key_source: "none" as const },
];

interface StoredProvider {
  id: string;
  type: string;
  base_url: string;
  api_key_env: string | null;
  api_key: string | null;
  models: string[];
}

function voters(): VoterSetting[] {
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

function baseRaw(bot: string): Raw {
  return {
    mode: "dry_run",
    bot_id: bot,
    capital: { initial_idr: 2000000, compounding: true },
    risk: { max_daily_loss_pct: 1.0, max_total_drawdown_pct: 10.0, risk_per_trade_pct: 0.5, max_open_trades: 3, leverage: "none", on_breach: "stop_new_entries", daily_reset_timezone: "Asia/Jakarta" },
    exchange: { name: "indodax", pairs: ["BTC/IDR", "ETH/IDR", "SOL/IDR"], timeframe: "1h", fee_pct: 0.2 },
    providers: [
      { id: "nutaraline", type: "openai-completions", base_url: "https://api.example.invalid/v1", api_key_env: "NUTARALINE_API_KEY", api_key: null, models: ["deepseek-v4.1-flash-1017"] },
      { id: "omniroute", type: "openai-completions", base_url: "from_import", api_key_env: "OMNIROUTE_API_KEY", api_key: null, models: ["example-local-model"] },
    ],
    swarm: { enabled: true, mode: "shadow", shuffle_options: true, min_voters_answered: 5, max_spread: null, voters: voters() },
    llm: { backend: "deepagents", analyst_model: "nutaraline:deepseek-v4.1-flash-1017" },
    compute: { max_cost_idr_per_day: false, on_exceed: "skip_new_entries", log_cost: true },
    data: { news_rss: ["coindesk", "cointelegraph"], fear_greed: true, social: false },
    notify: { web_push: true },
    api: { listen: "127.0.0.1", port: 8080, username_env: "FT_API_USERNAME", password_env: "FT_API_PASSWORD", jwt_secret_env: "FT_API_JWT_SECRET", force_entry: false },
  };
}

function err(status: number, code: string, message: string, extra: Record<string, unknown> = {}): Reply {
  return { status, body: { error: { code, message, ...extra } } };
}

function isPlain(v: unknown): v is Raw {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function merge(target: Raw, patch: Raw): void {
  for (const [k, v] of Object.entries(patch)) {
    if (isPlain(v) && isPlain(target[k])) merge(target[k] as Raw, v);
    else target[k] = v;
  }
}

function lookup(raw: Raw, dotted: string): unknown {
  return dotted.split(".").reduce<unknown>((n, part) => (isPlain(n) ? n[part] : undefined), raw);
}

function last4(key: string | null): string | null {
  return key && key.length >= 12 ? key.slice(-4) : null;
}

function masked(key: string, value: unknown): unknown {
  if (!key.endsWith(".api_key") || value === null || value === undefined) return value;
  const tail = last4(String(value));
  return tail ? "****" + tail : "<set>";
}

function changesOf(oldRaw: Raw, newRaw: Raw) {
  const a = flatten(oldRaw);
  const b = flatten(newRaw);
  return [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .sort()
    .filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
    .map((k) => ({ key: k, old: masked(k, a[k] ?? null), new: masked(k, b[k] ?? null) }));
}

function schemaMessage(raw: Raw): string | null {
  const s = raw as unknown as Settings;
  const errors = validate(s, s.swarm.voters.filter((v) => v.enabled).length).map((e) => e.key + ": " + e.message);
  const providers = new Map(s.providers.map((p) => [p.id, p]));
  for (const v of s.swarm.voters) {
    const p = providers.get(v.provider);
    if (!p) errors.push("swarm: voter " + v.id + " references unknown provider " + v.provider);
    else if (!p.models.includes(v.model)) errors.push("swarm: voter " + v.id + " model " + v.model + " is not listed by provider " + p.id);
  }
  const [ap, am] = s.llm.analyst_model.split(":");
  if (!providers.get(ap)?.models.includes(am)) errors.push("llm.analyst_model: not listed by its provider");
  return errors.length ? errors.slice(0, 5).join("; ") : null;
}

export function createStage2(ctx: Ctx) {
  const state: Record<string, BotState> = { A: "running", B: "running" };
  const configs: Record<string, Raw> = { A: baseRaw("A"), B: baseRaw("B") };
  const locks: Record<string, { id: number; pair: string; side: string; active: boolean; reason: string | null; lock_time: string; lock_end_time: string }[]> = { A: [], B: [] };
  const blacklist: Record<string, string[]> = { A: [], B: [] };
  const tests = new Map<string, ProviderTest>();
  const lastTestAt = new Map<string, number>();
  const audit: AuditRow[] = [];
  const confirmations = new Map<string, { request: string; session: Session; expires: number }>();
  const replies = new Map<string, { request: string; reply: Reply }>();
  let auditId = 0;
  let lockId = 0;

  function record(row: Omit<AuditRow, "id" | "ts">, bot?: string): AuditRow {
    const full: AuditRow = { id: ++auditId, ts: isoMs(Date.now()), ...row };
    audit.unshift(full);
    ctx.emit("gw.audit", full, bot);
    return full;
  }

  const ftDate = (ms: number) => isoMs(ms).replace("T", " ").slice(0, 19);
  tests.set("A:nutaraline", { tested_at: iso(Date.now() - 2 * HOUR), model: "deepseek-v4.1-flash-1017", ok: true, status: 200, latency_ms: 1840, error: null, detail: null });
  record({ actor: "file", ip: null, action: "config.observed", targets: ["A"], idempotency_key: null, result: "ok", detail: { file: "config/config.yaml", valid: true, error: null, changes: [] } });
  record({ actor: "file", ip: null, action: "config.observed", targets: ["B"], idempotency_key: null, result: "ok", detail: { file: "config/config.bot-b.yaml", valid: true, error: null, changes: [] } });
  record({ actor: "anonymous", ip: "127.0.0.1", action: "session.create", targets: [], idempotency_key: null, result: "denied", detail: null });
  record({ actor: "owner", ip: "127.0.0.1", action: "session.create", targets: [], idempotency_key: null, result: "ok", detail: null });
  record({ actor: "owner", ip: "127.0.0.1", action: "config.update", targets: ["A"], idempotency_key: "4f0c2a7e-0d3b-4c51-9e7a-3a1f2b6c9d10", result: "ok", detail: { params: { changes: { swarm: { min_voters_answered: 5 } } }, changes: [{ key: "swarm.min_voters_answered", old: 4, new: 5 }] } });

  const ipOf = (session: Session) => (session.scope === "control" ? "127.0.0.1" : "203.0.113.7");
  const loggable = (key: string | undefined) => (key && IDEMPOTENCY.test(key) ? key : null);

  function controlRow(session: Session, a: Action, key: string | undefined, result: string, extra: Record<string, unknown> = {}): AuditRow {
    const actor = result === "forbidden" ? session.scope + "_session" : "owner";
    return record({ actor, ip: ipOf(session), action: a.name, targets: [a.bot, ...a.targets], idempotency_key: loggable(key), result, detail: { params: a.params, summary: a.summary, ...extra } }, a.bot);
  }

  function execute(session: Session, key: string | undefined, request: string, path: string, a: Action, confirm: unknown): Reply {
    if (session.scope !== "control") {
      controlRow(session, a, key, "forbidden");
      return err(403, "forbidden_local_only", "control actions are accepted only from loopback");
    }
    const reject = (reply: Reply) => {
      const e = (reply.body as { error: { code: string; message: string } }).error;
      controlRow(session, a, key, "rejected", { error: e.code, message: e.message });
      return reply;
    };
    if (!key || !IDEMPOTENCY.test(key)) return reject(err(400, "invalid_request", "Idempotency-Key header (8-128 of [A-Za-z0-9_-]) is required"));
    const stored = replies.get(key);
    if (stored) {
      if (stored.request !== request) return reject(err(409, "invalid_request", "Idempotency-Key was used for another request"));
      controlRow(session, a, key, "replayed");
      return stored.reply;
    }
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
    const failure = ctx.upstreamFailure(path);
    if (failure) {
      const reply = err(failure, failure === 503 ? "upstream_unavailable" : "upstream_error", "Freqtrade answered " + failure);
      controlRow(session, a, key, "failed", { error: "upstream_error", message: "Freqtrade answered " + failure });
      replies.set(key, { request, reply });
      return reply;
    }
    const result = a.run();
    controlRow(session, a, key, "ok", a.detail?.() ?? {});
    const reply = { status: 200, body: result };
    replies.set(key, { request, reply });
    return reply;
  }

  function adminDenied(session: Session, bot: string, method: string, path: string): Reply {
    record({ actor: session.scope + "_session", ip: ipOf(session), action: "admin.denied", targets: [bot], idempotency_key: null, result: "forbidden", detail: { method, path, reason: "not_local" } }, bot);
    return err(403, "forbidden_local_only", "configuration writes are accepted only from loopback");
  }

  function write(session: Session, key: string | undefined, request: string, bot: string, action: string, params: Raw, edit: (raw: Raw) => Reply | null, confirm: unknown, render?: (raw: Raw) => Raw): Reply {
    const auditRow = (result: string, detail: Raw) => record({ actor: "owner", ip: ipOf(session), action, targets: [bot], idempotency_key: loggable(key), result, detail: { params, ...detail } }, bot);
    if (!key || !IDEMPOTENCY.test(key)) return err(400, "invalid_request", "Idempotency-Key header (8-128 of [A-Za-z0-9_-]) is required");
    const stored = replies.get(key);
    if (stored) {
      if (stored.request !== request) return err(409, "invalid_request", "Idempotency-Key was used for another request");
      auditRow("replayed", {});
      return stored.reply;
    }
    const oldRaw = configs[bot];
    const next = structuredClone(oldRaw);
    const refused = edit(next);
    if (refused) {
      const e = (refused.body as { error: { code: string; message: string } }).error;
      if (refused.status === 400) auditRow("rejected", { error: e.code, message: e.message });
      return refused;
    }
    const problem = schemaMessage(next);
    if (problem) {
      auditRow("rejected", { error: "invalid_request", message: problem });
      return err(400, "invalid_request", problem);
    }
    const changes = changesOf(oldRaw, next);
    if (changes.length === 0) return { status: 200, body: { bot, changes: [], restart_required: false, ...(render ? render(next) : {}) } };
    const risk = ctx.riskSnapshot();
    const reached: [string, number][] = [["risk.max_daily_loss_pct", risk.daily_loss_pct], ["risk.max_total_drawdown_pct", risk.drawdown_pct]];
    const hits = reached.filter(([k, current]) => changes.some((c) => c.key === k) && current > 0 && (lookup(next, k) as number) <= current);
    if (hits.length) {
      auditRow("rejected", { error: "risk_limit_breached" });
      return err(409, "risk_limit_breached", hits.map(([k, c]) => k + " " + String(lookup(next, k)) + " is not above the loss already reached (" + c + ")").join("; "));
    }
    const raising = RAISING.filter((k) => typeof lookup(next, k) === "number" && (lookup(next, k) as number) > (lookup(oldRaw, k) as number));
    if (raising.length) {
      if (typeof confirm !== "string") {
        const id = "cf_" + randomBytes(8).toString("hex").toUpperCase();
        const expires = Date.now() + 60000;
        confirmations.set(id, { request, session, expires });
        auditRow("confirmation_required", { keys: raising });
        const summary = "Raise " + raising.map((k) => k + " " + String(lookup(oldRaw, k)) + " -> " + String(lookup(next, k))).join("; ");
        return err(409, "confirmation_required", "raising risk limits needs a second step", { confirmation: { id, action, targets: [bot], summary, expires_at: iso(expires) } });
      }
      const pending = confirmations.get(confirm);
      if (!pending || pending.request !== request || pending.session !== session) {
        auditRow("rejected", { error: "confirmation_invalid", keys: raising });
        return err(409, "confirmation_invalid", "confirmation is unknown, used, or for another change");
      }
      confirmations.delete(confirm);
      if (pending.expires < Date.now()) {
        auditRow("rejected", { error: "confirmation_expired", keys: raising });
        return err(409, "confirmation_expired", "confirmation expired; ask for a new one");
      }
    }
    configs[bot] = next;
    const row = auditRow("ok", { changes, confirmed: raising.length > 0, restart_required: true });
    const reply = { status: 200, body: { bot, changes, restart_required: true, audit_id: row.id, ...(render ? render(next) : {}) } };
    replies.set(key, { request, reply });
    return reply;
  }

  const providersOf = (bot: string) => configs[bot].providers as StoredProvider[];
  const swarmOf = (bot: string) => configs[bot].swarm as Settings["swarm"];

  function keyState(p: StoredProvider) {
    if (p.api_key) return { source: "config", configured: true, last4: last4(p.api_key), env_name: null, env_set: null };
    if (p.api_key_env) {
      const present = ENV_SET.has(p.api_key_env);
      return { source: "env", configured: present, last4: null, env_name: p.api_key_env, env_set: present };
    }
    return { source: "none", configured: false, last4: null, env_name: null, env_set: null };
  }

  function providerView(bot: string, p: StoredProvider) {
    const used = new Set(swarmOf(bot).voters.filter((v) => v.enabled && v.provider === p.id).map((v) => v.model));
    const [ap, am] = String((configs[bot].llm as Raw).analyst_model).split(":");
    if (ap === p.id) used.add(am);
    return { id: p.id, type: p.type, base_url: p.base_url, host: p.base_url === "from_import" ? null : new URL(p.base_url).host, models: p.models, active_models: [...used].sort(), key: keyState(p), last_test: tests.get(bot + ":" + p.id) ?? null };
  }

  function redacted(bot: string) {
    const raw = structuredClone(configs[bot]);
    raw.providers = providersOf(bot).map((p) => ({ ...p, api_key: null, api_key_configured: p.api_key !== null, api_key_last4: last4(p.api_key) }));
    return raw;
  }

  const voterList = (bot: string) => swarmOf(bot).voters.map((v) => ({ ...v, last_test: tests.get(bot + ":" + v.provider) ?? null }));

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

  function outcome(d: Decision): DecisionOutcome {
    const ts = Date.parse(d.candle);
    const settles = ts + 5 * HOUR;
    const rows = ctx.candles.get(d.pair) ?? [];
    const at = rows.find((r) => Date.parse(r[0]) === ts);
    const after = rows.find((r) => Date.parse(r[0]) === ts + 4 * HOUR);
    const base = { horizon_h: 4, settles_at: iso(settles), trade_id: null, is_open: null, profit_abs: null, profit_pct: null };
    if (d.status === "ok" && d.verdict === "allow") {
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
    const local = session.scope === "control";
    const settingsOf = () => configs[bot] as unknown as Settings;

    if (method === "GET") {
      if (path === "/gw/v1/overview") return { status: 200, body: { ...ctx.overview(), state: state[bot], pairs: { whitelist: settingsOf().exchange.pairs, blacklist: blacklist[bot], locks: locks[bot].filter((l) => l.active).length } } };
      if (path === "/gw/v1/pairs") return { status: 200, body: { whitelist: { pairs: settingsOf().exchange.pairs, length: settingsOf().exchange.pairs.length, method: ["StaticPairList"] }, blacklist: { pairs: blacklist[bot], length: blacklist[bot].length, method: ["StaticPairList"] }, locks: { lock_count: locks[bot].length, locks: locks[bot] } } };
      if (path === "/gw/v1/trades" && (url.searchParams.has("offset") || url.searchParams.get("state") === "closed")) {
        const limit = Number(url.searchParams.get("limit") ?? 50);
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const rows = (url.searchParams.get("state") === "closed" ? closedFor(bot) : ctx.trades).slice().sort((a, b) => (b.close_ms ?? Infinity) - (a.close_ms ?? Infinity));
        return { status: 200, body: rows.slice(offset, offset + limit).map(ctx.tradeJson) };
      }
      if (path === "/gw/v1/decisions") {
        const limit = Math.min(500, Math.max(1, Number(url.searchParams.get("limit") ?? 20)));
        const before = url.searchParams.get("before");
        const status = url.searchParams.get("status");
        const pair = url.searchParams.get("pair");
        const rows = ctx.decisions.filter((d) => (!pair || d.pair === pair) && (!before || Date.parse(d.candle) < Date.parse(before)) && (!status || d.status === status) && (!url.searchParams.get("bot") || (d.bot ?? "B") === bot));
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
        return { status: 200, body: { window: "total", start_equity: ctx.startCapital, series: [ctx.equitySeries("A", "Bot A", "rules only", from, HOUR, ctx.startCapital, risk.balance.total, 41, 0.000004), ctx.equitySeries("B", "Bot B", "rules + shadow swarm", from, HOUR, ctx.startCapital, risk.balance.total + 3820, 43, 0.00001)] } };
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
      if (path === "/gw/v1/settings/changes") {
        const limit = Math.min(500, Math.max(1, Number(url.searchParams.get("limit") ?? 50)));
        const wanted = url.searchParams.get("bot");
        const out: Raw[] = [];
        for (const row of audit.filter((r) => r.action.startsWith("config.") && (!wanted || r.targets.includes(wanted)))) {
          for (const c of (row.detail?.changes as { key: string; old: unknown; new: unknown }[] | undefined) ?? []) out.push({ audit_id: row.id, ts: row.ts, actor: row.actor, ip: row.ip, action: row.action, bot: row.targets[0] ?? null, ...c });
        }
        return { status: 200, body: out.slice(0, limit) };
      }
      if (path === "/gw/v1/audit") {
        const limit = Math.min(500, Math.max(1, Number(url.searchParams.get("limit") ?? 50)));
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
      if (path === "/gw/v1/providers") return { status: 200, body: { bot, providers: providersOf(bot).map((p) => providerView(bot, p)) } };
      if (path === "/gw/v1/providers/import") {
        if (!local) return adminDenied(session, bot, method, path);
        const have = new Set(providersOf(bot).map((p) => p.id));
        const providers = MODELS_YML.map((m) => {
          const id = m.name.toLowerCase();
          const blocker = /^[a-z0-9][a-z0-9_-]*$/.test(id) ? null : "name cannot be used as a provider id";
          return { name: m.name, id, type: m.type, base_url: m.base_url, host: new URL(m.base_url).host, models: m.models, key_source: m.key_source, exists: have.has(id), blocker };
        });
        return { status: 200, body: { bot, providers } };
      }
      if (path === "/gw/v1/voters") {
        const s = swarmOf(bot);
        return { status: 200, body: { bot, swarm: { enabled: s.enabled, mode: s.mode, min_voters_answered: s.min_voters_answered, enabled_voters: s.voters.filter((v) => v.enabled).length }, voters: voterList(bot) } };
      }
      if (path === "/gw/v1/roles") {
        const [provider, model] = String((configs[bot].llm as Raw).analyst_model).split(":");
        return { status: 200, body: { bot, analyst: { provider, model }, voters: swarmOf(bot).voters.map((v) => ({ id: v.id, provider: v.provider, model: v.model, enabled: v.enabled })) } };
      }
      return null;
    }

    const b = await readBody();
    const { confirm, ...params } = b;
    const request = method + " " + path + "?" + [...url.searchParams].sort().map(([k, v]) => k + "=" + v).join("&") + " " + JSON.stringify(params);
    const act = (a: Omit<Action, "bot" | "params">) => execute(session, key, request, path, { ...a, bot, params }, confirm);
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
        precheck: () => (!settingsOf().exchange.pairs.includes(pair) ? err(422, "invalid_request", "pair not in whitelist") : Number.isNaN(Date.parse(String(b.until))) || Date.parse(String(b.until)) <= Date.now() ? err(400, "invalid_request", "until must be in the future") : null),
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
    const test = path.match(/^\/gw\/v1\/providers\/([^/]+)\/test$/);
    if (method === "POST" && test) {
      const id = decodeURIComponent(test[1]);
      const p = providersOf(bot).find((x) => x.id === id);
      if (!p) return err(404, "not_found", "unknown provider " + id);
      const model = typeof b.model === "string" ? b.model : p.models[0];
      if (!p.models.includes(model)) return err(400, "invalid_request", "model " + model + " is not listed by provider " + id);
      const slot = bot + ":" + id;
      const since = Date.now() - (lastTestAt.get(slot) ?? 0);
      if (since < 5000) return err(429, "rate_limited", "one test per provider every 5 s", { retry_after_ms: 5000 - since });
      lastTestAt.set(slot, Date.now());
      await new Promise((r) => setTimeout(r, 400));
      const k = keyState(p);
      const at = isoMs(Date.now());
      const result: ProviderTest =
        p.base_url === "from_import"
          ? { tested_at: at, model, ok: false, status: null, latency_ms: null, error: "base_url_unresolved", detail: null }
          : !k.configured
            ? { tested_at: at, model, ok: false, status: null, latency_ms: null, error: "no_key", detail: null }
            : { tested_at: at, model, ok: true, status: 200, latency_ms: 700 + Math.round(Math.random() * 1500), error: null, detail: null };
      tests.set(slot, result);
      record({ actor: local ? "owner" : "remote", ip: ipOf(session), action: "provider.test", targets: [bot, id], idempotency_key: loggable(key), result: result.ok ? "ok" : "failed", detail: { ...result } }, bot);
      return { status: 200, body: { bot, provider: id, ...result } };
    }

    const adminPath = path === "/gw/v1/settings" || path.startsWith("/gw/v1/providers") || path.startsWith("/gw/v1/voters") || path === "/gw/v1/roles";
    if (!adminPath) return null;
    if (!local) return adminDenied(session, bot, method, path);
    const providerRender = (id: string) => (raw: Raw) => {
      const p = (raw.providers as StoredProvider[]).find((x) => x.id === id);
      return p ? { provider: providerView(bot, p) } : {};
    };
    const votersRender = () => ({ voters: voterList(bot) });

    if (method === "PATCH" && path === "/gw/v1/settings") {
      const changes = b.changes;
      if (!isPlain(changes)) return err(400, "invalid_request", "body.changes: Input should be a valid dictionary");
      const frozen = FROZEN.find((k) => k in changes);
      if (frozen) return err(400, "invalid_request", frozen + " cannot be changed through settings");
      if (isPlain(changes.swarm) && "voters" in changes.swarm) return err(400, "invalid_request", "swarm.voters cannot be changed through settings (use the voters endpoints)");
      return write(session, key, request, bot, "config.update", { changes }, (raw) => {
        merge(raw, changes);
        return null;
      }, confirm);
    }
    const prov = path.match(/^\/gw\/v1\/providers\/([^/]+)(\/key)?$/);
    if (prov && prov[1] !== "import") {
      const id = decodeURIComponent(prov[1]);
      if (!prov[2] && method === "PUT") {
        if ("api_key" in b) return err(400, "invalid_request", "api_key is not accepted here; use the key endpoint");
        if (!/^[a-z0-9][a-z0-9_-]*$/.test(id)) return err(400, "invalid_request", "invalid provider id " + id);
        if (!/^https?:\/\/\S+$/.test(String(b.base_url)) || /^https?:\/\/[^/]*@/.test(String(b.base_url))) return err(400, "invalid_request", "base_url: must be http(s) without user or password");
        if (!Array.isArray(b.models) || b.models.length === 0) return err(400, "invalid_request", "models: List should have at least 1 item after validation");
        return write(session, key, request, bot, "config.provider.upsert", { provider: id, type: b.type, base_url: b.base_url, models: b.models }, (raw) => {
          const list = raw.providers as StoredProvider[];
          const found = list.find((x) => x.id === id);
          if (found) Object.assign(found, { type: b.type, base_url: b.base_url, models: b.models });
          else list.push({ id, type: String(b.type), base_url: String(b.base_url), api_key_env: id.toUpperCase().replace(/-/g, "_") + "_API_KEY", api_key: null, models: b.models as string[] });
          return null;
        }, undefined, providerRender(id));
      }
      if (!prov[2] && method === "DELETE") {
        return write(session, key, request, bot, "config.provider.delete", { provider: id }, (raw) => {
          const list = raw.providers as StoredProvider[];
          if (!list.some((x) => x.id === id)) return err(404, "not_found", "unknown provider " + id);
          raw.providers = list.filter((x) => x.id !== id);
          return null;
        }, undefined);
      }
      if (prov[2] && method === "PUT") {
        const hasKey = typeof b.api_key === "string";
        const hasEnv = typeof b.api_key_env === "string";
        if (hasKey === hasEnv) return err(400, "invalid_request", "send exactly one of api_key or api_key_env");
        if (hasKey && !/^\S{8,1024}$/.test(String(b.api_key))) return err(400, "invalid_request", "api_key: 8 to 1024 characters without spaces");
        if (hasEnv && !/^[A-Z][A-Z0-9_]*$/.test(String(b.api_key_env))) return err(400, "invalid_request", "api_key_env: upper case letters, digits, _");
        const shown = hasKey ? { provider: id, api_key: "<set>" } : { provider: id, api_key_env: b.api_key_env };
        return write(session, key, request, bot, "config.provider.key", shown, (raw) => {
          const p = (raw.providers as StoredProvider[]).find((x) => x.id === id);
          if (!p) return err(404, "not_found", "unknown provider " + id);
          p.api_key = hasKey ? String(b.api_key) : null;
          p.api_key_env = hasEnv ? String(b.api_key_env) : null;
          return null;
        }, undefined, providerRender(id));
      }
      if (prov[2] && method === "DELETE") {
        return write(session, key, request, bot, "config.provider.key", { provider: id, clear: true }, (raw) => {
          const p = (raw.providers as StoredProvider[]).find((x) => x.id === id);
          if (!p) return err(404, "not_found", "unknown provider " + id);
          p.api_key = null;
          p.api_key_env = null;
          return null;
        }, undefined, providerRender(id));
      }
    }
    if (method === "POST" && path === "/gw/v1/providers/import") {
      const items = Array.isArray(b.providers) ? (b.providers as { name: string; with_key?: boolean; models?: string[] | null; replace?: boolean }[]) : [];
      if (items.length === 0) return err(400, "invalid_request", "providers: List should have at least 1 item after validation");
      const results: Raw[] = [];
      const reply = write(session, key, request, bot, "config.provider.import", { providers: items }, (raw) => {
        const list = raw.providers as StoredProvider[];
        for (const item of items) {
          const m = MODELS_YML.find((x) => x.name === item.name);
          if (!m) return err(400, "invalid_request", "unknown provider " + item.name + " in models.yml");
          const id = m.name.toLowerCase();
          if (!/^[a-z0-9][a-z0-9_-]*$/.test(id)) return err(400, "invalid_request", "name cannot be used as a provider id: " + m.name);
          if (item.with_key && (m.key_source === "command" || m.key_source === "none")) return err(400, "invalid_request", m.name + ": key source " + m.key_source + " cannot be imported");
          const models = item.models ?? m.models;
          const found = list.find((x) => x.id === id);
          if (found && !item.replace) {
            results.push({ name: m.name, id, result: "skipped", reason: "exists", with_key: false });
            continue;
          }
          const entry: StoredProvider = found ?? { id, type: m.type, base_url: m.base_url, api_key_env: id.toUpperCase() + "_API_KEY", api_key: null, models };
          Object.assign(entry, { type: m.type, base_url: m.base_url, models });
          if (item.with_key) {
            entry.api_key = m.key_source === "literal" ? "sk-example-import-" + id + "-x9Qa" : null;
            entry.api_key_env = m.key_source === "env" ? id.toUpperCase() + "_API_KEY" : null;
          }
          if (!found) list.push(entry);
          results.push({ name: m.name, id, result: found ? "updated" : "created", with_key: Boolean(item.with_key) });
        }
        return null;
      }, undefined);
      if (reply.status !== 200) return reply;
      return { status: 200, body: { ...(reply.body as Raw), results } };
    }
    const voter = path.match(/^\/gw\/v1\/voters\/([^/]+)$/);
    if (voter) {
      const id = decodeURIComponent(voter[1]);
      if (!/^[a-z0-9][a-z0-9_-]*$/.test(id)) return err(400, "invalid_request", "invalid voter id " + id);
      if (method === "PUT") {
        const fields = { adapter: b.adapter, provider: b.provider, model: b.model, variation: b.variation, timeout_s: b.timeout_s, weight: b.weight, enabled: b.enabled };
        return write(session, key, request, bot, "config.voter.upsert", { voter: id, ...fields }, (raw) => {
          const list = (raw.swarm as Raw).voters as Raw[];
          const at = list.findIndex((v) => v.id === id);
          if (at >= 0) list[at] = { id, ...fields };
          else list.push({ id, ...fields });
          return null;
        }, undefined, votersRender);
      }
      if (method === "DELETE") {
        return write(session, key, request, bot, "config.voter.delete", { voter: id }, (raw) => {
          const s = raw.swarm as Raw;
          const list = s.voters as Raw[];
          if (!list.some((v) => v.id === id)) return err(404, "not_found", "unknown voter " + id);
          s.voters = list.filter((v) => v.id !== id);
          return null;
        }, undefined, votersRender);
      }
    }
    if (method === "PUT" && path === "/gw/v1/roles") {
      const analyst = b.analyst as { provider: string; model: string } | undefined;
      const roleVoters = (b.voters ?? {}) as Record<string, { provider: string; model: string }>;
      return write(session, key, request, bot, "config.roles", { analyst: analyst ?? null, voters: roleVoters }, (raw) => {
        if (analyst) (raw.llm as Raw).analyst_model = analyst.provider + ":" + analyst.model;
        const list = (raw.swarm as Raw).voters as Raw[];
        for (const [vid, role] of Object.entries(roleVoters)) {
          const v = list.find((x) => x.id === vid);
          if (!v) return err(404, "not_found", "unknown voter " + vid);
          Object.assign(v, role);
        }
        return null;
      }, undefined, votersRender);
    }
    return null;
  }

  return { route, bots: BOTS, decorate };
}
