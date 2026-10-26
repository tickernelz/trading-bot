export type Mode = "dry_run" | "live";

export interface Health {
  gateway: { status: string; version: string; uptime_s: number; sample_data?: boolean };
  freqtrade: { version: string; state: string; last_process: string | null; bot_start: string | null; dry_run: boolean };
  exchange: { name: string; reachable: boolean; latency_ms: number | null };
  feed: { connected: boolean; last_event_at: string | null; sequence: number };
}

export interface RiskBlock {
  daily_loss_pct: number;
  daily_limit_pct: number;
  drawdown_pct: number;
  drawdown_limit_pct: number;
  entries_allowed: boolean;
  breaches: string[];
}

export type BotState = "running" | "paused" | "stopped";

export interface Overview {
  mode: Mode;
  state?: BotState;
  as_of: string;
  capital: { initial_idr: number; compounding: boolean; tradable_ratio: number };
  balance: { stake_currency: string; total: number; bot_owned: number; note?: string };
  profit: { abs: number; pct: number; trades_closed: number; winrate: number };
  open_trades: { count: number; max: number };
  risk: RiskBlock;
  pairs: { whitelist: string[]; blacklist: string[]; locks: number };
}

export interface Trade {
  trade_id: number;
  pair: string;
  is_open: boolean;
  is_short: boolean;
  amount: number;
  stake_amount: number;
  strategy: string;
  enter_tag: string | null;
  open_date: string;
  open_timestamp: number;
  open_rate: number;
  stop_loss_pct?: number | null;
  stop_loss_abs?: number | null;
  profit_abs: number;
  profit_pct?: number;
  profit_pct_now?: number;
  age_s?: number;
  close_date?: string | null;
  close_rate?: number | null;
  close_timestamp?: number | null;
  exit_reason?: string | null;
  has_open_orders?: boolean;
}

export interface Risk {
  as_of: string;
  equity: number;
  peak_equity: number;
  day_start: string;
  day_start_equity: number;
  daily_pnl: number;
  daily_loss_pct: number;
  drawdown_pct: number;
  limits: {
    max_daily_loss_pct: number;
    max_total_drawdown_pct: number;
    risk_per_trade_pct: number;
    on_breach: string;
    timezone: string;
  };
  breaches: string[];
  entries_allowed: boolean;
}

export interface CandleFrame {
  pair: string;
  timeframe: string;
  columns: string[];
  data: (string | number | null)[][];
  last_analyzed?: string;
}

export interface Sysinfo {
  cpu_pct: number[];
  ram_pct: number;
}

export interface LogLine {
  ts: string;
  logger: string;
  level: string;
  message: string;
}

export interface EquitySeries {
  bot: string;
  label: string;
  strategy: string;
  points: [string, number][];
}

export interface Equity {
  window: string;
  start_equity: number;
  series: EquitySeries[];
}

export type VoterStatus = "ok" | "timeout" | "failed" | "invalid";

export interface VoterAnswer {
  type: "noul" | "choice" | "score";
  noul?: number;
  choice?: string;
  score?: number;
  confidence?: number | null;
  probabilities?: Record<string, number> | null;
}

export interface VoterRecord {
  voter_id: string;
  provider: string;
  status: VoterStatus;
  latency_s: number;
  error_kind?: string | null;
  model?: string | null;
  answers?: Record<string, VoterAnswer> | null;
}

export interface Spread {
  q25: number;
  q75: number;
  iqr: number;
  minimum: number;
  maximum: number;
}

export interface QuestionResult {
  median?: number;
  winner?: string;
  tie?: boolean;
  median_probabilities?: Record<string, number>;
  agreement?: number;
  votes?: Record<string, number>;
  spread: Spread;
}

export interface Decision {
  decision_id: string;
  ts: string;
  pair: string;
  timeframe: string;
  candle: string;
  mode: "shadow" | "gate";
  status: "ok" | "skip";
  reason: string | null;
  required: number;
  answered: number;
  verdict: "izinkan" | "kecilkan" | "lewati";
  iqr_limit: number;
  aggregate: { questions: Record<string, QuestionResult>; voters: number } | null;
  voters: VoterRecord[];
  bot?: string;
  outcome?: DecisionOutcome;
}

export interface DecisionOutcome {
  state: "pending" | "insufficient_data" | "settled";
  basis: "trade" | "price";
  horizon_h: number;
  price_at: number | null;
  price_after: number | null;
  return_pct: number | null;
  return_after_fees_pct: number | null;
  trade_id: number | null;
  is_open: boolean | null;
  profit_abs: number | null;
  profit_pct: number | null;
  settles_at: string | null;
}

export interface FeedEvent<T = unknown> {
  type: string;
  bot?: string;
  seq: number;
  ts: string;
  data: T;
}

export interface ErrorEnvelope {
  error: { code: string; message: string; retry_after_ms?: number; [extra: string]: unknown };
}

export type PushKind = "fill" | "risk_breach" | "kill_switch" | "heartbeat_lost" | "quorum_failed" | "daily_summary";

export type Scope = "read" | "control";

export interface SessionInfo {
  token: string;
  scope: Scope;
  expires_at: string;
}

export interface Confirmation {
  id: string;
  action: string;
  targets: string[];
  summary: string;
  expires_at: string;
}

export interface ControlResult {
  status?: string;
  result?: string;
  [field: string]: unknown;
}

export interface Lock {
  id: number;
  pair: string;
  side: string;
  active: boolean;
  reason: string | null;
  lock_time: string;
  lock_end_time: string;
}

export interface Pairs {
  whitelist: { pairs: string[] };
  blacklist: { pairs: string[] };
  locks: { lock_count: number; locks: Lock[] };
}

export interface ProviderSetting {
  id: string;
  type: "openai-completions" | "openai-responses" | "anthropic-messages";
  base_url: string;
  api_key_env: string | null;
  api_key: null;
  api_key_configured: boolean;
  models: string[];
  enabled?: boolean;
}

export interface VoterSetting {
  id: string;
  adapter: "llm_structured" | "systemone" | "openrouter_decisions" | "openai_decisions";
  provider: string;
  model: string;
  variation: "option_order" | "temperature" | "prompt_variant";
  timeout_s: number;
  weight: number;
  enabled: boolean;
}

export interface Settings {
  mode: "dry_run";
  capital: { initial_idr: number; compounding: boolean };
  risk: {
    max_daily_loss_pct: number;
    max_total_drawdown_pct: number;
    risk_per_trade_pct: number;
    max_open_trades: number;
    leverage: "none";
    on_breach: "stop_new_entries";
    daily_reset_timezone: string;
  };
  exchange: { name: string; pairs: string[]; timeframe: "1h"; fee_pct: number };
  providers: ProviderSetting[];
  swarm: {
    enabled: boolean;
    mode: "shadow" | "veto";
    shuffle_options: boolean;
    min_voters_answered: number;
    max_spread: number | null;
    voters: VoterSetting[];
  };
  llm: { backend: "deepagents"; analyst_model: string };
  compute: { max_cost_idr_per_day: false | number; on_exceed: "skip_new_entries"; log_cost: boolean };
  data: { news_rss: string[]; fear_greed: boolean; social: boolean };
  notify: { web_push: boolean };
  api: {
    listen: string;
    port: number;
    username_env: string;
    password_env: string;
    jwt_secret_env: string;
    ws_token_env: string;
    force_entry: boolean;
  };
}

export interface SettingsDoc extends Settings {
  revision: string;
}

export interface Change {
  key: string;
  old: unknown;
  new: unknown;
}

export interface SettingsSaved {
  revision: string;
  applied: Change[];
  restart_required: boolean;
}

export interface ProviderTest {
  at: string;
  ok: boolean;
  latency_ms: number | null;
  model: string | null;
  error_kind: string | null;
}

export interface Provider {
  id: string;
  type: ProviderSetting["type"];
  base_url: string;
  host: string | null;
  models: string[];
  enabled: boolean;
  api_key_configured: boolean;
  api_key_source: "env" | "config" | null;
  api_key_env: string | null;
  api_key_last4: string | null;
  used_by: { analyst: boolean; voters: string[] };
  last_test: ProviderTest | null;
  health: { calls: number; ok: number; latency_p50_s: number | null; latency_max_s: number | null; last_status: string | null } | null;
}

export interface ImportCandidate {
  id: string;
  type: ProviderSetting["type"];
  base_url: string;
  models: string[];
  has_key: boolean;
  exists: boolean;
}

export interface AuditRow {
  id: number;
  ts: string;
  actor: string;
  ip: string | null;
  action: string;
  targets: string[];
  idempotency_key: string | null;
  result: string;
  detail: Record<string, unknown> | null;
}

export interface ProfitTotal {
  window: "total";
  stake_currency: string;
  profit_closed_coin: number;
  profit_closed_percent: number;
  profit_all_coin?: number;
  profit_all_percent: number;
  trade_count: number;
  closed_trade_count: number;
  winning_trades: number;
  losing_trades: number;
  best_pair: string | null;
  worst_pair: string | null;
  max_drawdown?: number;
  max_drawdown_abs?: number;
}

export interface ProfitPeriod {
  date: string;
  abs_profit: number;
  rel_profit: number;
  starting_balance: number;
  trade_count: number;
}

export interface ProfitWindow {
  window: "daily" | "weekly" | "monthly";
  stake_currency: string;
  data: ProfitPeriod[];
}

export interface Stats {
  durations: { wins: number | null; draws: number | null; losses: number | null };
  exit_reasons: Record<string, { wins: number; losses: number; draws: number }>;
}

export interface PerformanceRow {
  profit_pct: number;
  profit_abs: number;
  count: number;
}

export interface Performance {
  per_pair: (PerformanceRow & { pair: string; profit_ratio?: number })[];
  by_enter_tag: (PerformanceRow & { enter_tag: string })[];
  by_exit_reason: (PerformanceRow & { exit_reason: string })[];
}

export interface BotInfo {
  id: string;
  label: string;
  strategy?: string;
}
