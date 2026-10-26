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

export interface Overview {
  mode: Mode;
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
}

export interface FeedEvent<T = unknown> {
  type: string;
  seq: number;
  ts: string;
  data: T;
}

export interface ErrorEnvelope {
  error: { code: string; message: string; retry_after_ms?: number };
}

export interface NewsSource {
  id: string;
  name: string;
  url: string;
  feed: string;
  ok: boolean;
  error: string | null;
  fetched_at: string | null;
}

export interface NewsItem {
  id: string;
  source: string;
  title: string;
  url: string;
  published: string;
  assets: string[];
}

export interface News {
  as_of: string;
  enabled: boolean;
  sources: NewsSource[];
  items: NewsItem[];
}

export type FearGreedClass = "Extreme Fear" | "Fear" | "Neutral" | "Greed" | "Extreme Greed";

export interface SentimentPoint {
  date: string;
  value: number;
  classification: FearGreedClass;
}

export interface Sentiment {
  as_of: string;
  enabled: boolean;
  source: { name: string; provider: string; url: string; ok?: boolean; error?: string | null; fetched_at?: string | null };
  points: SentimentPoint[];
}

export type PushKind = "fill" | "risk_breach" | "kill_switch" | "heartbeat_lost" | "quorum_failed" | "daily_summary";
