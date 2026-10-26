import { clock } from "./format";
import type { Decision, DecisionOutcome } from "./types";

export type DecisionFilter = "semua" | "skip" | "ok";

export interface OutcomeView {
  settled: boolean;
  headline: string;
  value: number | null;
  unit: "pct";
  note: string;
}

export function decisionsPath(filter: DecisionFilter, before: string | null, bot: string | null, limit = 30): string {
  const q = new URLSearchParams({ limit: String(limit) });
  if (filter !== "semua") q.set("status", filter);
  if (before) q.set("before", before);
  if (bot) q.set("bot", bot);
  return "/gw/v1/decisions?" + q.toString();
}

export function tookEntry(d: Decision): boolean {
  return d.outcome?.basis === "trade";
}

export function outcomeView(o: DecisionOutcome | undefined): OutcomeView | null {
  if (!o) return null;
  if (o.basis === "trade") {
    if (o.is_open) {
      return { settled: false, headline: "Masuk, trade #" + o.trade_id + " masih terbuka", value: o.profit_pct, unit: "pct", note: "Angka sementara dari harga terakhir; belum hasil akhir." };
    }
    if (o.state !== "settled" || o.profit_pct === null) {
      return { settled: false, headline: "Masuk, hasil trade belum tercatat", value: null, unit: "pct", note: "Belum cukup data." };
    }
    return { settled: true, headline: "Masuk, trade #" + o.trade_id + " ditutup", value: o.profit_pct, unit: "pct", note: "Hasil trade sungguhan (dry-run), sesudah biaya." };
  }
  if (o.state === "pending") {
    return { settled: false, headline: "Dilewati, belum cukup data", value: null, unit: "pct", note: "Harga " + o.horizon_h + " jam sesudahnya baru ada " + (o.settles_at ? "pukul " + clock(o.settles_at) : "nanti") + "." };
  }
  if (o.state === "insufficient_data" || o.return_after_fees_pct === null) {
    return { settled: false, headline: "Dilewati, data harga sesudahnya tidak ada", value: null, unit: "pct", note: "Kandel sesudah horizon tidak tersedia; tidak dihitung." };
  }
  return {
    settled: true,
    headline: "Dilewati. Seandainya masuk, " + o.horizon_h + " jam kemudian",
    value: o.return_after_fees_pct,
    unit: "pct",
    note: "Pengandaian dari harga penutupan, sesudah biaya dua sisi; bukan trade.",
  };
}
