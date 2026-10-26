export const HOUR = 3600000;
export const START_CAPITAL = 2000000;
export const STAKE_RATIO = 0.99;

export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface PairSpec {
  pair: string;
  price: number;
  vol: number;
  seed: number;
}

export const PAIRS: PairSpec[] = [
  { pair: "BTC/IDR", price: 1463933000, vol: 0.006, seed: 11 },
  { pair: "ETH/IDR", price: 62410000, vol: 0.008, seed: 23 },
  { pair: "SOL/IDR", price: 2951000, vol: 0.011, seed: 37 },
];

export const COLUMNS = ["date", "open", "high", "low", "close", "volume", "ema_fast", "ema_slow", "rsi", "enter_long", "exit_long"];

export type Row = [string, number, number, number, number, number, number, number, number | null, number | null, number | null];

function ema(prev: number | null, value: number, span: number): number {
  const k = 2 / (span + 1);
  return prev === null ? value : value * k + prev * (1 - k);
}

export function iso(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function isoMs(ms: number): string {
  return new Date(ms).toISOString();
}

export function buildCandles(spec: PairSpec, endHour: number, count: number): Row[] {
  const random = rng(spec.seed);
  const closes: number[] = [];
  let p = spec.price;
  for (let i = 0; i < count; i++) {
    p = p * (1 + (random() - 0.5) * spec.vol * 2 + Math.sin(i / 17) * spec.vol * 0.25);
    closes.push(p);
  }
  const scale = spec.price / closes[closes.length - 1];
  const rows: Row[] = [];
  let fast: number | null = null;
  let slow: number | null = null;
  let gain = 0;
  let loss = 0;
  let prevFastAbove: boolean | null = null;
  for (let i = 0; i < count; i++) {
    const close = closes[i] * scale;
    const open = i === 0 ? close : rows[i - 1][4];
    const wick = Math.abs(close - open) + spec.price * spec.vol * random() * 0.6;
    const high = Math.max(open, close) + wick * random();
    const low = Math.min(open, close) - wick * random();
    fast = ema(fast, close, 9);
    slow = ema(slow, close, 21);
    const change = i === 0 ? 0 : close - rows[i - 1][4];
    gain = (gain * 13 + Math.max(change, 0)) / 14;
    loss = (loss * 13 + Math.max(-change, 0)) / 14;
    const rsi = i < 14 ? null : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    const above = fast > slow;
    const enter = prevFastAbove === false && above && rsi !== null && rsi < 70 ? 1 : null;
    const exit = prevFastAbove === true && !above ? 1 : null;
    prevFastAbove = above;
    rows.push([
      iso(endHour - (count - 1 - i) * HOUR),
      round(open),
      round(high),
      round(low),
      round(close),
      Number((random() * 0.6 + 0.05).toFixed(5)),
      round(fast),
      round(slow),
      rsi === null ? null : Number(rsi.toFixed(2)),
      enter,
      exit,
    ]);
  }
  return rows;
}

function round(v: number): number {
  return v >= 1000 ? Math.round(v) : Number(v.toFixed(2));
}

export const VOTERS = [
  { voter_id: "v1", provider: "modelrouter", model: "jev-1.13" },
  { voter_id: "v2", provider: "experientiallabs", model: "clef" },
  { voter_id: "v3", provider: "experientiallabs", model: "jev-latest" },
  { voter_id: "v4", provider: "xai-hm", model: "model chat (contoh)" },
  { voter_id: "v5", provider: "tiprouter", model: "model chat (contoh)" },
  { voter_id: "v6", provider: "nutaraline", model: "deepseek-v4.1-flash-1017" },
  { voter_id: "v7", provider: "lucif", model: "model chat (contoh)" },
];

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function buildDecision(random: () => number, pair: string, candleMs: number, ts: number, quorumFail = false) {
  const voters = VOTERS.map((v, i) => {
    const timeout = quorumFail ? i >= 2 : i === 6 && random() < 0.7;
    if (timeout) {
      return { ...v, status: "timeout" as const, latency_s: 30, error_kind: "timeout", answers: null };
    }
    const allow = Math.min(0.95, Math.max(0.05, 0.62 + (random() - 0.5) * 0.4));
    const choice = allow >= 0.5 ? "izinkan" : "kecilkan";
    return {
      ...v,
      status: "ok" as const,
      latency_s: Number((0.6 + random() * 2.4).toFixed(2)),
      error_kind: null,
      answers: {
        news_aligned: { type: "noul" as const, noul: Number((0.4 + random() * 0.5).toFixed(2)) },
        sentiment: { type: "score" as const, score: Number((random() * 4 - 1).toFixed(1)), confidence: 0.6 },
        action: {
          type: "choice" as const,
          choice,
          confidence: 0.7,
          probabilities: { izinkan: Number(allow.toFixed(2)), kecilkan: Number(((1 - allow) * 0.7).toFixed(2)), lewati: Number(((1 - allow) * 0.3).toFixed(2)) },
        },
      },
    };
  });
  const answered = voters.filter((v) => v.status === "ok");
  const required = 5;
  const base = {
    decision_id: "dec_" + ts.toString(36),
    ts: isoMs(ts),
    pair,
    timeframe: "1h",
    candle: iso(candleMs),
    mode: "shadow" as const,
    required,
    answered: answered.length,
    iqr_limit: 0.25,
    voters,
  };
  if (answered.length < required) {
    return { ...base, status: "skip" as const, reason: "quorum_not_met", verdict: "lewati" as const, aggregate: null };
  }
  const allows = answered.map((v) => v.answers!.action.probabilities.izinkan).sort((a, b) => a - b);
  const q25 = quantile(allows, 0.25);
  const q75 = quantile(allows, 0.75);
  const median = quantile(allows, 0.5);
  const votes: Record<string, number> = { izinkan: 0, kecilkan: 0, lewati: 0 };
  for (const v of answered) votes[v.answers!.action.choice] += 1;
  const iqr = q75 - q25;
  const verdict = iqr > 0.25 ? "lewati" : median >= 0.5 ? "izinkan" : "kecilkan";
  return {
    ...base,
    status: iqr > 0.25 ? ("skip" as const) : ("ok" as const),
    reason: iqr > 0.25 ? "spread_too_wide" : null,
    verdict: verdict as "izinkan" | "kecilkan" | "lewati",
    aggregate: {
      voters: answered.length,
      questions: {
        action: {
          winner: median >= 0.5 ? "izinkan" : "kecilkan",
          tie: false,
          median_probabilities: { izinkan: Number(median.toFixed(3)) },
          agreement: Math.max(...Object.values(votes)) / answered.length,
          votes,
          spread: { q25, q75, iqr, minimum: allows[0], maximum: allows[allows.length - 1] },
        },
      },
    },
  };
}

const NEWS_SOURCES = [
  { id: "coindesk", name: "CoinDesk", url: "https://www.coindesk.com/", feed: "https://www.coindesk.com/arc/outboundfeeds/rss/" },
  { id: "cointelegraph", name: "Cointelegraph", url: "https://cointelegraph.com/", feed: "https://cointelegraph.com/rss" },
];

export function buildNews(random: () => number, pair: string, now: number) {
  const asset = pair.split("/")[0];
  const items = Array.from({ length: 10 }, (_, k) => {
    const source = NEWS_SOURCES[k % 2];
    const published = now - Math.round((k * 19 + random() * 14 + 2) * HOUR);
    return {
      id: "n_contoh_" + asset.toLowerCase() + "_" + k,
      source: source.id,
      title: "Judul berita contoh " + (k + 1) + " tentang " + asset + " (bukan berita sungguhan)",
      url: source.url,
      published: iso(published),
      assets: [asset],
    };
  });
  return {
    as_of: iso(now),
    enabled: true,
    sources: NEWS_SOURCES.map((s, i) => ({ ...s, ok: i === 0, error: i === 0 ? null : "contoh: HTTPError 503", fetched_at: iso(now - (i === 0 ? 4 : 47) * 60000) })),
    items,
  };
}

const FNG_CLASSES = [
  [25, "Extreme Fear"],
  [46, "Fear"],
  [55, "Neutral"],
  [75, "Greed"],
  [101, "Extreme Greed"],
] as const;

export function buildSentiment(random: () => number, now: number) {
  const today = Math.floor(now / (24 * HOUR)) * 24 * HOUR;
  let value = 48;
  const points = Array.from({ length: 60 }, (_, k) => {
    value = Math.max(5, Math.min(95, Math.round(value + (random() - 0.5) * 14)));
    const classification = FNG_CLASSES.find(([limit]) => value < limit)![1];
    return { date: iso(today - (59 - k) * 24 * HOUR).slice(0, 10), value, classification };
  });
  return {
    as_of: iso(now),
    enabled: true,
    source: { name: "Fear & Greed Index", provider: "alternative.me", url: "https://alternative.me/crypto/fear-and-greed-index/", ok: true, error: null, fetched_at: iso(now - 12 * 60000) },
    points,
  };
}
