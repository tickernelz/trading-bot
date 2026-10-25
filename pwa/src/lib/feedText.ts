import { MINUS, outcomeWord, price, rupiah, signedPercent } from "./format";
import type { Decision, FeedEvent } from "./types";

export type FeedKind = "Order" | "Swarm" | "Risiko" | "Sistem";

export interface FeedItem {
  seq: number;
  ts: string;
  kind: FeedKind;
  text: string;
  warn: boolean;
  outcome?: number;
}

type Data = Record<string, unknown>;

const num = (v: unknown): number => (typeof v === "number" ? v : Number(v));
const str = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

const STATUS_WORD: Record<string, string> = {
  running: "berjalan",
  stopped: "berhenti",
  paused: "dijeda",
  reload_config: "memuat ulang konfigurasi",
};

const EXIT_REASON: Record<string, string> = {
  roi: "target ROI",
  stop_loss: "stop loss",
  stoploss_on_exchange: "stop loss",
  trailing_stop_loss: "trailing stop",
  exit_signal: "sinyal keluar",
  force_exit: "keluar paksa",
  emergency_exit: "keluar darurat",
};

export function exitReason(value: string | null | undefined): string {
  if (!value) return "-";
  return EXIT_REASON[value] ?? value;
}

export function statusWord(value: string | null | undefined): string {
  if (!value) return "tidak diketahui";
  return STATUS_WORD[value] ?? value;
}

export function describe(event: FeedEvent, dryRun: boolean): FeedItem | null {
  const d = (event.data ?? {}) as Data;
  const tail = dryRun ? " (dry-run)" : "";
  const base = { seq: event.seq, ts: event.ts, warn: false };
  switch (event.type) {
    case "entry":
      return { ...base, kind: "Order", text: "Order beli " + str(d.pair) + " dikirim di " + price(num(d.limit)) + tail };
    case "entry_fill":
      return { ...base, kind: "Order", text: "Beli " + str(d.pair) + " terisi di " + price(num(d.open_rate)) + ", " + rupiah(num(d.stake_amount)) + tail };
    case "exit":
      return { ...base, kind: "Order", text: "Order jual " + str(d.pair) + " dikirim, alasan " + exitReason(str(d.exit_reason)) + tail };
    case "exit_fill": {
      const pct = num(d.profit_ratio) * 100;
      return {
        ...base,
        kind: "Order",
        text: "Jual " + str(d.pair) + " terisi, " + signedPercent(pct) + " " + outcomeWord(pct) + tail,
        outcome: pct,
      };
    }
    case "status":
      return { ...base, kind: "Sistem", text: "Status bot: " + statusWord(str(d.status)) };
    case "warning":
      return { ...base, kind: "Sistem", text: str(d.status), warn: true };
    case "whitelist":
      return { ...base, kind: "Sistem", text: "Daftar pair: " + (Array.isArray(event.data) ? event.data.join(", ") : "") };
    case "gw.risk_denied": {
      const breaches = Array.isArray(d.breaches) ? (d.breaches as string[]) : [];
      const reason = breaches.includes("total_drawdown") ? "rugi total melewati batas" : "rugi harian melewati batas";
      return { ...base, kind: "Risiko", text: "Entry " + str(d.pair) + " ditolak: " + reason + " (" + MINUS + num(d.daily_loss_pct).toFixed(2).replace(".", ",") + "%)", warn: true };
    }
    case "gw.decision": {
      const dec = event.data as Decision;
      const quorum = dec.status === "skip" && dec.reason === "quorum_not_met";
      return {
        ...base,
        kind: "Swarm",
        text: dec.pair + ": " + (quorum ? "kuorum gagal, entry dilewati" : dec.verdict) + (dec.mode === "shadow" ? " (bayangan)" : "") + ", " + dec.answered + " dari " + dec.voters.length + " voter menjawab",
        warn: quorum,
      };
    }
    case "gw.error":
      return { ...base, kind: "Sistem", text: "Gateway: " + str(d.message), warn: true };
    default:
      return null;
  }
}
