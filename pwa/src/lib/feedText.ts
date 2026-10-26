import { decimal, MINUS, outcomeWord, price, rupiah, signedPercent } from "./format";
import { t, type Key } from "./i18n";
import type { Decision, FeedEvent } from "./types";
import { choiceText } from "./words";

export type FeedKind = "order" | "swarm" | "risk" | "system";

export const FEED_KINDS: Record<FeedKind, Key> = { order: "feed.kind_order", swarm: "feed.kind_swarm", risk: "feed.kind_risk", system: "feed.kind_system" };

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

const STATUS_WORD: Record<string, Key> = {
  running: "status.running",
  stopped: "status.stopped",
  paused: "status.paused",
  reload_config: "status.reload_config",
};

const EXIT_REASON: Record<string, Key> = {
  roi: "exit.roi",
  stop_loss: "exit.stop_loss",
  stoploss_on_exchange: "exit.stop_loss",
  trailing_stop_loss: "exit.trailing_stop_loss",
  exit_signal: "exit.exit_signal",
  force_exit: "exit.force_exit",
  emergency_exit: "exit.emergency_exit",
};

export function exitReason(value: string | null | undefined): string {
  if (!value) return "-";
  const key = EXIT_REASON[value];
  return key ? t(key) : value;
}

export function statusWord(value: string | null | undefined): string {
  if (!value) return t("status.unknown");
  const key = STATUS_WORD[value];
  return key ? t(key) : value;
}

export function describe(event: FeedEvent, dryRun: boolean): FeedItem | null {
  const d = (event.data ?? {}) as Data;
  const tail = dryRun ? " (dry-run)" : "";
  const base = { seq: event.seq, ts: event.ts, warn: false };
  switch (event.type) {
    case "entry":
      return { ...base, kind: "order", text: t("feed.entry", { pair: str(d.pair), price: price(num(d.limit)) }) + tail };
    case "entry_fill":
      return { ...base, kind: "order", text: t("feed.entry_fill", { pair: str(d.pair), price: price(num(d.open_rate)), stake: rupiah(num(d.stake_amount)) }) + tail };
    case "exit":
      return { ...base, kind: "order", text: t("feed.exit", { pair: str(d.pair), reason: exitReason(str(d.exit_reason)) }) + tail };
    case "exit_fill": {
      const pct = num(d.profit_ratio) * 100;
      return { ...base, kind: "order", text: t("feed.exit_fill", { pair: str(d.pair), pct: signedPercent(pct), word: outcomeWord(pct) }) + tail, outcome: pct };
    }
    case "status":
      return { ...base, kind: "system", text: t("feed.status", { status: statusWord(str(d.status)) }) };
    case "warning":
      return { ...base, kind: "system", text: str(d.status), warn: true };
    case "whitelist":
      return { ...base, kind: "system", text: t("feed.whitelist", { pairs: Array.isArray(event.data) ? event.data.join(", ") : "" }) };
    case "gw.risk_denied": {
      const breaches = Array.isArray(d.breaches) ? (d.breaches as string[]) : [];
      const reason = breaches.includes("total_drawdown") ? t("feed.breach_total") : t("feed.breach_daily");
      return { ...base, kind: "risk", text: t("feed.risk_denied", { pair: str(d.pair), reason, loss: MINUS + decimal(num(d.daily_loss_pct)) + "%" }), warn: true };
    }
    case "gw.decision": {
      const dec = event.data as Decision;
      const quorum = dec.status === "skip" && dec.reason === "quorum_not_met";
      return {
        ...base,
        kind: "swarm",
        text: t(dec.mode === "shadow" ? "feed.decision_shadow" : "feed.decision", {
          pair: dec.pair,
          verdict: quorum ? t("feed.quorum_failed") : choiceText(dec.verdict),
          answered: dec.answered,
          total: dec.voters.length,
        }),
        warn: quorum,
      };
    }
    case "gw.error":
      return { ...base, kind: "system", text: t("feed.gw_error", { message: str(d.message) }), warn: true };
    default:
      return null;
  }
}
