import { randomBytes } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import webpush, { type PushSubscription } from "web-push";
import { WebSocket, WebSocketServer } from "ws";
import { buildCandles, buildDecision, COLUMNS, HOUR, iso, isoMs, PAIRS, rng, type Row, START_CAPITAL, STAKE_RATIO } from "./data";
import { createStage2, type MockTrade, type Session } from "./stage2";

type Scenario = "aman" | "ditahan" | "berhenti";

const PORT = Number(process.env.MOCK_GATEWAY_PORT ?? 8090);
const PASSWORD = process.env.MOCK_GATEWAY_PASSWORD ?? "contoh";
const random = rng(Number(process.env.MOCK_GATEWAY_SEED ?? 7));
const vapid = webpush.generateVAPIDKeys();
webpush.setVapidDetails("mailto:contoh@localhost", vapid.publicKey, vapid.privateKey);

const tokens = new Map<string, Session>();
let remote = process.env.MOCK_REMOTE === "1";
const scopeFor = (isRemote: boolean): Session["scope"] => (isRemote ? "read" : "control");
const subscriptions = new Map<string, PushSubscription>();
const buffer: { type: string; seq: number; ts: string; data: unknown }[] = [];
const clients = new Map<WebSocket, { candles: Set<string>; topics: Set<string> }>();
const ALWAYS = new Set(["gw.error"]);
const failing = new Map<string, number>();
let upstreamDownUntil = 0;
const upstreamDown = () => Date.now() < upstreamDownUntil;

function wants(ws: WebSocket, type: string): boolean {
  return ALWAYS.has(type) || (clients.get(ws)?.topics.has(type) ?? false);
}
let seq = 0;
let scenario: Scenario = (process.env.MOCK_SCENARIO as Scenario) ?? "aman";
let droppedUntil = 0;
const started = Date.now();

const hourNow = () => Math.floor(Date.now() / HOUR) * HOUR;
let lastHour = hourNow() - HOUR;
const candles = new Map<string, Row[]>(PAIRS.map((p) => [p.pair, buildCandles(p, lastHour, 300)]));
const prices = new Map<string, number>(PAIRS.map((p) => [p.pair, candles.get(p.pair)!.at(-1)![4]]));

const FEE = 0.002;
const trades: MockTrade[] = [];
const closedPlan = [
  { pair: "BTC/IDR", days: 6, change: -0.004, reason: "force_exit" },
  { pair: "ETH/IDR", days: 5, change: 0.0125, reason: "roi" },
  { pair: "SOL/IDR", days: 4, change: -0.0296, reason: "stop_loss" },
  { pair: "BTC/IDR", days: 3, change: 0.0071, reason: "exit_signal" },
  { pair: "ETH/IDR", days: 2, change: 0.0058, reason: "roi" },
  { pair: "SOL/IDR", days: 1, change: -0.0062, reason: "exit_signal" },
];
closedPlan.forEach((t, i) => {
  const open_ms = Date.now() - t.days * 24 * HOUR - 9 * HOUR;
  const price = prices.get(t.pair)! * (1 - 0.01 * (i % 3));
  trades.push({ trade_id: i + 1, pair: t.pair, open_ms, open_rate: price, stake_amount: 330000, enter_tag: "ema_cross_up", close_ms: open_ms + (5 + i) * HOUR, close_rate: price * (1 + t.change), exit_reason: t.reason });
});
trades.push({ trade_id: 7, pair: "BTC/IDR", open_ms: Date.now() - 3 * HOUR - 840000, open_rate: prices.get("BTC/IDR")! * 0.9962, stake_amount: 333322.9, enter_tag: "ema_cross_up" });
trades.push({ trade_id: 8, pair: "ETH/IDR", open_ms: Date.now() - 5 * HOUR - 120000, open_rate: prices.get("ETH/IDR")! * 1.0021, stake_amount: 331150.4, enter_tag: "ema_cross_up" });
let nextTradeId = 9;

const profitOf = (t: MockTrade, rate: number) => t.stake_amount * (rate / t.open_rate) * (1 - FEE) - t.stake_amount * (1 + FEE);
const realized = () => trades.filter((t) => t.close_ms).reduce((s, t) => s + profitOf(t, t.close_rate!), 0);
const unrealized = () => trades.filter((t) => !t.close_ms).reduce((s, t) => s + profitOf(t, prices.get(t.pair)!), 0);

function jakartaDayStart(ms: number): number {
  const offset = 7 * HOUR;
  return Math.floor((ms + offset) / (24 * HOUR)) * 24 * HOUR - offset;
}

function riskSnapshot() {
  const now = Date.now();
  const dayStart = jakartaDayStart(now);
  const before = trades.filter((t) => t.close_ms && t.close_ms < dayStart).reduce((s, t) => s + profitOf(t, t.close_rate!), 0);
  const dayStartEquity = START_CAPITAL + before;
  let equity = START_CAPITAL + realized() + unrealized();
  if (scenario === "ditahan") equity = Math.min(equity, dayStartEquity * (1 - 0.0102));
  const peak = Math.max(START_CAPITAL, dayStartEquity, equity);
  const dailyPnl = equity - dayStartEquity;
  const dailyLoss = Math.max(0, (-dailyPnl / dayStartEquity) * 100);
  const drawdown = Math.max(0, ((peak - equity) / peak) * 100);
  const breaches: string[] = [];
  if (dailyLoss >= 1.0) breaches.push("daily_loss");
  if (drawdown >= 10) breaches.push("total_drawdown");
  return {
    as_of: iso(now),
    equity: Number(equity.toFixed(2)),
    peak_equity: Number(peak.toFixed(2)),
    day_start: iso(dayStart),
    day_start_equity: Number(dayStartEquity.toFixed(2)),
    daily_pnl: Number(dailyPnl.toFixed(2)),
    daily_loss_pct: Number(dailyLoss.toFixed(3)),
    drawdown_pct: Number(drawdown.toFixed(3)),
    limits: { max_daily_loss_pct: 1.0, max_total_drawdown_pct: 10.0, risk_per_trade_pct: 0.5, on_breach: "stop_new_entries", timezone: "Asia/Jakarta" },
    breaches,
    entries_allowed: breaches.length === 0,
  };
}

const ftDate = (ms: number) => isoMs(ms).replace("T", " ").slice(0, 19);

function tradeJson(t: MockTrade) {
  const open = !t.close_ms;
  const rate = open ? prices.get(t.pair)! : t.close_rate!;
  const profit = profitOf(t, rate);
  const pct = Number(((profit / t.stake_amount) * 100).toFixed(2));
  return {
    trade_id: t.trade_id,
    pair: t.pair,
    is_open: open,
    is_short: false,
    exchange: "indodax",
    amount: Number((t.stake_amount / t.open_rate).toFixed(8)),
    stake_amount: t.stake_amount,
    strategy: "SwingEmaRsi",
    enter_tag: t.enter_tag,
    fee_open: FEE,
    open_date: ftDate(t.open_ms),
    open_timestamp: t.open_ms,
    open_rate: Math.round(t.open_rate),
    open_trade_value: Number((t.stake_amount * (1 + FEE)).toFixed(4)),
    stop_loss_pct: -3.0,
    stop_loss_abs: Math.round(t.open_rate * 0.97),
    profit_abs: Number(profit.toFixed(4)),
    ...(open
      ? { profit_pct_now: pct, age_s: Math.round((Date.now() - t.open_ms) / 1000), has_open_orders: false }
      : { profit_pct: pct, close_profit_abs: Number(profit.toFixed(4)), close_date: ftDate(t.close_ms!), close_timestamp: t.close_ms, close_rate: Math.round(t.close_rate!), exit_reason: t.exit_reason }),
  };
}

function equitySeries(bot: string, label: string, strategy: string, from: number, step: number, start: number, end: number, seed: number, drift: number) {
  const r = rng(seed);
  const n = Math.max(2, Math.floor((Date.now() - from) / step) + 1);
  const raw: number[] = [];
  let v = 0;
  for (let i = 0; i < n; i++) {
    v += (r() - 0.5) * 0.0016 + drift;
    raw.push(v);
  }
  const shift = end - start * (1 + raw[n - 1]);
  const points = raw.map((x, i) => [iso(Math.min(Date.now(), from + i * step)), Number((start * (1 + x) + shift * (i / (n - 1))).toFixed(2))]);
  points[0][1] = start;
  return { bot, label, strategy, points };
}

const decisions: ReturnType<typeof buildDecision>[] = [];
for (let i = 40; i >= 1; i--) {
  const pair = PAIRS[i % 3].pair;
  decisions.unshift(buildDecision(random, pair, lastHour - i * 3 * HOUR, lastHour - i * 3 * HOUR + 125000, i % 9 === 4));
}

function health() {
  const last = buffer.at(-1);
  return {
    gateway: { status: "ok", version: "0.1.0-contoh", uptime_s: Math.round((Date.now() - started) / 1000), sample_data: true },
    freqtrade: { version: "2026.9", state: scenario === "berhenti" ? "stopped" : "running", last_process: iso(Date.now() - 4000), bot_start: iso(started - 26 * HOUR), dry_run: true },
    exchange: { name: "indodax", reachable: true, latency_ms: 1843 },
    feed: { connected: true, last_event_at: last?.ts ?? null, sequence: seq },
  };
}

function overview() {
  const risk = riskSnapshot();
  const closed = trades.filter((t) => t.close_ms);
  const wins = closed.filter((t) => profitOf(t, t.close_rate!) > 0).length;
  const total = START_CAPITAL + realized() + unrealized();
  return {
    mode: "dry_run",
    as_of: iso(Date.now()),
    capital: { initial_idr: START_CAPITAL, compounding: true, tradable_ratio: STAKE_RATIO },
    balance: { stake_currency: "IDR", total: Number(total.toFixed(2)), bot_owned: Number((total * STAKE_RATIO).toFixed(2)), note: "Simulated balances" },
    profit: { abs: Number(realized().toFixed(2)), pct: Number(((realized() / START_CAPITAL) * 100).toFixed(2)), trades_closed: closed.length, winrate: Number((wins / Math.max(1, closed.length)).toFixed(2)) },
    open_trades: { count: trades.filter((t) => !t.close_ms).length, max: 3 },
    risk: { daily_loss_pct: risk.daily_loss_pct, daily_limit_pct: 1.0, drawdown_pct: risk.drawdown_pct, drawdown_limit_pct: 10.0, entries_allowed: risk.entries_allowed, breaches: risk.breaches },
    pairs: { whitelist: PAIRS.map((p) => p.pair), blacklist: [], locks: 0 },
  };
}

const LOGS = [
  ["freqtrade.worker", "INFO", "Bot heartbeat. PID=1, version='2026.9', state='RUNNING'"],
  ["freqtrade.rpc.api_server.ws", "INFO", "Consumer subscribed to ['entry', 'exit', 'status']"],
  ["freqtrade.exchange.exchange", "WARNING", "indodax: fetchMyTrades is not supported, using database history"],
];

function send(ws: WebSocket, msg: object) {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function emit(type: string, data: unknown, bot?: string) {
  const event = { type, seq: ++seq, ts: isoMs(Date.now()), data, ...(bot ? { bot } : {}) };
  buffer.push(event);
  if (buffer.length > 200) buffer.shift();
  for (const [ws] of clients) if (wants(ws, type)) send(ws, event);
  return event;
}

function hello(ws: WebSocket) {
  send(ws, { type: "gw.hello", seq, ts: isoMs(Date.now()), data: { gateway_version: "0.1.0-contoh", freqtrade_version: "2026.9", dry_run: true, whitelist: PAIRS.map((p) => p.pair), sequence_resume_window: 200, sample_data: true, bots: stage2.bots } });
}

const PUSH_SAMPLES: Record<string, { title: string; body: string; url: string }> = {
  fill: { title: "Beli BTC/IDR terisi", body: "Dry-run: Rp 333.323 di 1.463.933.000. Contoh data.", url: "/#aksi" },
  risk_breach: { title: "Batas rugi harian terlewati", body: "Rugi hari ini \u22121,02% dari batas 1,0%. Entry baru ditahan sampai besok. Contoh data.", url: "/#ringkas" },
  kill_switch: { title: "Kill switch aktif", body: "Bot berhenti membuka posisi baru. Posisi terbuka tetap dijaga stop loss. Contoh data.", url: "/#ringkas" },
  heartbeat_lost: { title: "Heartbeat bot hilang", body: "Tidak ada kabar dari bot selama 3 menit. Periksa PC. Contoh data.", url: "/#sistem" },
  quorum_failed: { title: "Kuorum swarm gagal", body: "ETH/IDR: 2 dari 7 voter menjawab (minimal 5). Entry dilewati. Contoh data.", url: "/#swarm" },
  daily_summary: { title: "Ringkasan hari ini", body: "Dry-run: \u22120,31% rugi, 2 trade ditutup, batas tidak tersentuh. Contoh data.", url: "/#ringkas" },
};

async function push(kind: string) {
  const sample = PUSH_SAMPLES[kind];
  if (!sample) return { sent: 0, failed: 0 };
  const payload = JSON.stringify({ kind, ...sample, ts: isoMs(Date.now()), id: randomBytes(4).toString("hex"), sample_data: true });
  let sent = 0;
  let failed = 0;
  for (const [endpoint, sub] of subscriptions) {
    try {
      await webpush.sendNotification(sub, payload, { TTL: 600, urgency: kind === "daily_summary" ? "normal" : "high" });
      sent++;
    } catch (error) {
      failed++;
      const status = (error as { statusCode?: number }).statusCode;
      if (status === 404 || status === 410) subscriptions.delete(endpoint);
    }
  }
  return { sent, failed };
}

function json(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify(body));
}

function fail(res: ServerResponse, status: number, code: string, message: string) {
  json(res, status, { error: { code, message } });
}

async function body(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  const text = Buffer.concat(chunks).toString("utf8");
  return text ? (JSON.parse(text) as Record<string, unknown>) : {};
}

const stage2 = createStage2({
  trades,
  prices,
  candles,
  decisions,
  fee: FEE,
  startCapital: START_CAPITAL,
  started,
  emit,
  tradeJson,
  profitOf,
  overview,
  riskSnapshot,
  equitySeries,
});

const server = createServer(async (req, res) => {
  if (Date.now() < droppedUntil && !req.url?.startsWith("/gw/v1/dev/")) {
    req.socket.destroy();
    return;
  }
  const url = new URL(req.url ?? "/", "http://localhost");
  const path = url.pathname;
  let cached: Promise<Record<string, unknown>> | null = null;
  const readBody = () => (cached ??= body(req));
  try {
    if (req.method === "POST" && path === "/gw/v1/session") {
      const b = await readBody();
      if (b.password !== PASSWORD) return fail(res, 401, "unauthorized", "Kata sandi salah");
      const token = randomBytes(24).toString("hex");
      const session: Session = { scope: scopeFor(remote), expires_at: iso(Date.now() + 30 * 24 * HOUR) };
      tokens.set(token, session);
      return json(res, 200, { token, expires_at: session.expires_at, scope: session.scope });
    }
    if (path.startsWith("/gw/v1/dev/")) {
      const b = req.method === "POST" ? await readBody() : {};
      if (path === "/gw/v1/dev/scenario") {
        scenario = (b.name as Scenario) ?? "aman";
        emit("status", { status: scenario === "berhenti" ? "stopped" : "running" });
        emit("gw.risk", riskSnapshot());
        return json(res, 200, { scenario });
      }
      if (path === "/gw/v1/dev/drop") {
        droppedUntil = Date.now() + Number(b.seconds ?? 20) * 1000;
        for (const [ws] of clients) ws.terminate();
        return json(res, 200, { dropped_until: iso(droppedUntil) });
      }
      if (path === "/gw/v1/dev/push") return json(res, 200, await push(String(b.kind)));
      if (path === "/gw/v1/dev/remote") {
        remote = Boolean(b.remote);
        for (const session of tokens.values()) session.scope = scopeFor(remote);
        return json(res, 200, { remote });
      }
      if (path === "/gw/v1/dev/upstream") {
        upstreamDownUntil = Date.now() + Number(b.seconds ?? 30) * 1000;
        emit("gw.error", { code: "upstream_unavailable", message: "Freqtrade websocket closed", retry_ms: 5000 });
        return json(res, 200, { down_until: iso(upstreamDownUntil) });
      }
      if (path === "/gw/v1/dev/fail") {
        const status = Number(b.status ?? 0);
        if (status > 0) failing.set(String(b.path), status);
        else failing.delete(String(b.path));
        return json(res, 200, { failing: Object.fromEntries(failing) });
      }
      return fail(res, 404, "not_found", "unknown dev route");
    }
    const auth = req.headers.authorization?.replace(/^Bearer /, "");
    const session = auth ? tokens.get(auth) : undefined;
    if (!auth || !session) return fail(res, 401, "unauthorized", "Token tidak sah");
    const forced = failing.get(path);
    if (forced) return fail(res, forced, forced === 404 ? "not_found" : "upstream_error", "Gagal dipaksa oleh rute dev");
    if (upstreamDown() && ["/gw/v1/health", "/gw/v1/overview", "/gw/v1/risk"].includes(path)) {
      return fail(res, 503, "upstream_unavailable", "Freqtrade API did not answer within 5s");
    }
    if (path === "/gw/v1/session" && req.method === "DELETE") {
      tokens.delete(auth);
      return json(res, 200, { revoked: true });
    }
    const reply = await stage2.route(req, url, session, readBody);
    if (reply) return json(res, reply.status, reply.body);
    if (req.method === "GET") {
      switch (path) {
        case "/gw/v1/health":
          return json(res, 200, health());
        case "/gw/v1/overview":
          return json(res, 200, overview());
        case "/gw/v1/risk":
          return json(res, 200, riskSnapshot());
        case "/gw/v1/trades/open":
          return json(res, 200, trades.filter((t) => !t.close_ms).map(tradeJson));
        case "/gw/v1/trades": {
          const pair = url.searchParams.get("pair");
          const limit = Number(url.searchParams.get("limit") ?? 100);
          const rows = trades.filter((t) => !pair || t.pair === pair).sort((a, b) => (b.close_ms ?? Infinity) - (a.close_ms ?? Infinity));
          return json(res, 200, rows.slice(0, limit).map(tradeJson));
        }
        case "/gw/v1/pairs":
          return json(res, 200, { whitelist: { pairs: PAIRS.map((p) => p.pair), length: 3, method: ["StaticPairList"] }, blacklist: { pairs: [], length: 0, method: ["StaticPairList"] }, locks: { lock_count: 0, locks: [] } });
        case "/gw/v1/candles": {
          const pair = url.searchParams.get("pair") ?? "";
          const rows = candles.get(pair);
          if (!rows) return fail(res, 404, "not_found", "Pair tidak ada di whitelist");
          if (url.searchParams.get("timeframe") !== "1h") return fail(res, 400, "invalid_request", "Hanya timeframe 1h");
          const limit = Math.min(1500, Number(url.searchParams.get("limit") ?? 300));
          return json(res, 200, { pair, timeframe: "1h", strategy: "SwingEmaRsi", columns: COLUMNS, length: Math.min(limit, rows.length), last_analyzed: ftDate(lastHour + 60000), data: rows.slice(-limit) });
        }
        case "/gw/v1/equity": {
          const window = url.searchParams.get("window") ?? "day";
          const risk = riskSnapshot();
          if (window === "day") {
            const from = jakartaDayStart(Date.now());
            return json(res, 200, { window, start_equity: risk.day_start_equity, series: [equitySeries("A", "Bot A", "aturan saja", from, 300000, risk.day_start_equity, risk.equity, 5, scenario === "ditahan" ? -0.00012 : -0.00002)] });
          }
          const from = Date.now() - 7 * 24 * HOUR;
          return json(res, 200, {
            window: "7d",
            start_equity: START_CAPITAL,
            series: [
              equitySeries("A", "Bot A", "aturan saja", from, HOUR, START_CAPITAL, risk.equity, 13, 0.00001),
              equitySeries("B", "Bot B", "aturan + swarm bayangan", from, HOUR, START_CAPITAL, risk.equity + 5150, 29, 0.00003),
            ],
          });
        }
        case "/gw/v1/sysinfo":
          return json(res, 200, { cpu_pct: [12 + random() * 20, 8 + random() * 15, 20 + random() * 30, 5 + random() * 10].map((v) => Number(v.toFixed(1))), ram_pct: Number((38 + random() * 6).toFixed(1)) });
        case "/gw/v1/logs":
          return json(res, 200, { log_count: LOGS.length, logs: LOGS.map((l, i) => [ftDate(Date.now() - i * 61000), Date.now() - i * 61000, ...l]) });
        case "/gw/v1/push/key":
          return json(res, 200, { public_key: vapid.publicKey });
      }
    }
    if (path === "/gw/v1/push/subscriptions") {
      const b = await readBody();
      const sub = b.subscription as PushSubscription | undefined;
      if (req.method === "POST" && sub?.endpoint) {
        subscriptions.set(sub.endpoint, sub);
        return json(res, 201, { endpoint: sub.endpoint, kinds: b.kinds ?? [] });
      }
      if (req.method === "DELETE" && typeof b.endpoint === "string") {
        subscriptions.delete(b.endpoint);
        return json(res, 200, { removed: true });
      }
      return fail(res, 400, "invalid_request", "subscription atau endpoint wajib");
    }
    if (req.method === "POST" && path === "/gw/v1/push/test") return json(res, 200, await push("daily_summary"));
    return fail(res, 404, "not_found", "Tidak ada endpoint " + path);
  } catch (error) {
    return fail(res, 500, "upstream_error", error instanceof Error ? error.message : "error");
  }
});

const wss = new WebSocketServer({ noServer: true });
server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  if (url.pathname !== "/gw/v1/events" || Date.now() < droppedUntil) {
    socket.destroy();
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => {
    if (!tokens.has(url.searchParams.get("token") ?? "")) {
      ws.close(4401, "unauthorized");
      return;
    }
    clients.set(ws, { candles: new Set(), topics: new Set() });
    hello(ws);
    ws.on("message", (raw) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(String(raw)) as Record<string, unknown>;
      } catch {
        return;
      }
      if (msg.type === "ping") return send(ws, { type: "pong", ts: isoMs(Date.now()) });
      if (msg.type === "resume") {
        const last = Number(msg.last_seq);
        const first = buffer[0]?.seq ?? seq + 1;
        if (last + 1 >= first) {
          for (const e of buffer) if (e.seq > last && wants(ws, e.type)) send(ws, e);
        } else {
          hello(ws);
          send(ws, { type: "gw.resync", seq, ts: isoMs(Date.now()), data: { whitelist: PAIRS.map((p) => p.pair), open_trades: trades.filter((t) => !t.close_ms).map(tradeJson), balance: overview().balance } });
        }
        return;
      }
      if (msg.type === "subscribe") {
        const state = clients.get(ws);
        if (!state) return;
        const previous = state.candles;
        state.topics = new Set(Array.isArray(msg.topics) ? (msg.topics as string[]) : []);
        state.candles = new Set();
        for (const c of (Array.isArray(msg.candles) ? msg.candles : []) as { pair: string; limit?: number }[]) {
          const rows = candles.get(c.pair);
          if (!rows) continue;
          state.candles.add(c.pair);
          if (!previous.has(c.pair) && state.topics.has("gw.candles")) {
            send(ws, { type: "gw.candles", seq, ts: isoMs(Date.now()), data: { pair: c.pair, timeframe: "1h", snapshot: true, candles: rows.slice(-(c.limit ?? 300)) } });
          }
        }
      }
    });
    ws.on("close", () => clients.delete(ws));
  });
});

const heartbeat = setInterval(() => {
  for (const [ws] of clients) ws.ping();
}, 20000);

function tick() {
  if (Date.now() < droppedUntil) return;
  if (upstreamDown()) {
    emit("gw.error", { code: "upstream_unavailable", message: "Freqtrade websocket closed", retry_ms: 5000 });
    return;
  }
  for (const p of PAIRS) prices.set(p.pair, prices.get(p.pair)! * (1 + (random() - 0.5) * p.vol * 0.15));
  const h = hourNow() - HOUR;
  if (h > lastHour) {
    lastHour = h;
    for (const p of PAIRS) {
      const rows = candles.get(p.pair)!;
      const prev = rows.at(-1)!;
      const close = prices.get(p.pair)!;
      const row: Row = [iso(h), prev[4], Math.max(prev[4], close) * 1.001, Math.min(prev[4], close) * 0.999, Math.round(close), 0.2, prev[6], prev[7], prev[8], null, null];
      rows.push(row);
      for (const [ws, c] of clients) if (c.candles.has(p.pair) && c.topics.has("gw.candles")) send(ws, { type: "gw.candles", seq: ++seq, ts: isoMs(Date.now()), data: { pair: p.pair, timeframe: "1h", candles: [row] } });
    }
  }
  emit("gw.risk", (({ equity, daily_loss_pct, drawdown_pct, entries_allowed, breaches }) => ({ equity, daily_loss_pct, drawdown_pct, entries_allowed, breaches }))(riskSnapshot()));
}

let step = 0;
function script() {
  if (Date.now() < droppedUntil || upstreamDown()) return;
  const pair = PAIRS[step % 3].pair;
  const phase = step % 4;
  step++;
  if (scenario === "ditahan") {
    const r = riskSnapshot();
    emit("gw.risk_denied", { pair, breaches: r.breaches, daily_loss_pct: r.daily_loss_pct, drawdown_pct: r.drawdown_pct, equity: r.equity });
    return;
  }
  if (scenario === "berhenti") return;
  if (phase === 0 || phase === 2) {
    const d = buildDecision(random, pair, lastHour, Date.now(), phase === 2 && random() < 0.3);
    decisions.unshift(d);
    decisions.splice(200);
    emit("gw.decision", stage2.decorate(d), "B");
    return;
  }
  if (phase === 1) {
    const open = trades.find((t) => !t.close_ms && t.trade_id >= 9);
    if (open) {
      const rate = prices.get(open.pair)!;
      const exit = { trade_id: open.trade_id, pair: open.pair, exit_reason: "exit_signal", limit: Math.round(rate), order_type: "limit", open_rate: Math.round(open.open_rate) };
      emit("exit", exit);
      setTimeout(() => {
        open.close_ms = Date.now();
        open.close_rate = rate;
        open.exit_reason = "exit_signal";
        const profit = profitOf(open, rate);
        emit("exit_fill", { ...exit, close_rate: Math.round(rate), profit_amount: Number(profit.toFixed(4)), profit_ratio: Number((profit / open.stake_amount).toFixed(6)), is_final_exit: true });
      }, 2000);
    } else if (trades.filter((t) => !t.close_ms).length < 3) {
      const rate = prices.get("SOL/IDR")!;
      const t: MockTrade = { trade_id: nextTradeId++, pair: "SOL/IDR", open_ms: Date.now(), open_rate: rate, stake_amount: 329500, enter_tag: "ema_cross_up" };
      const entry = { trade_id: t.trade_id, pair: t.pair, enter_tag: t.enter_tag, direction: "long", limit: Math.round(rate), order_type: "limit", stake_amount: t.stake_amount, stake_currency: "IDR", amount: Number((t.stake_amount / rate).toFixed(8)) };
      emit("entry", entry);
      setTimeout(() => {
        trades.push(t);
        emit("entry_fill", { ...entry, open_rate: Math.round(rate), open_date: ftDate(t.open_ms) });
      }, 2000);
    }
    return;
  }
  emit("warning", { status: "nutaraline membalas 429; voter v6 dibuang untuk keputusan ini." });
}

const tickTimer = setInterval(tick, 5000);
const scriptTimer = setInterval(script, Number(process.env.MOCK_SCRIPT_MS ?? 20000));
emit("status", { status: scenario === "berhenti" ? "stopped" : "running" });
emit("warning", { status: "Dry run is enabled. All trades are simulated." });

server.listen(PORT, "127.0.0.1", () => {
  process.stdout.write("mock gateway (contoh data) on http://127.0.0.1:" + PORT + "\n");
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    clearInterval(heartbeat);
    clearInterval(tickTimer);
    clearInterval(scriptTimer);
    wss.close();
    server.close(() => process.exit(0));
  });
}
