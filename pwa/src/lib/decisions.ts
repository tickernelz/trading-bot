import { clock } from "./format";
import { t } from "./i18n";
import type { Decision, DecisionOutcome } from "./types";

export type DecisionFilter = "all" | "skip" | "ok";

export interface OutcomeView {
  settled: boolean;
  headline: string;
  value: number | null;
  unit: "pct";
  note: string;
}

export function decisionsPath(filter: DecisionFilter, before: string | null, bot: string | null, limit = 30): string {
  const q = new URLSearchParams({ limit: String(limit) });
  if (filter !== "all") q.set("status", filter);
  if (before) q.set("before", before);
  if (bot) q.set("bot", bot);
  return "/gw/v1/decisions?" + q.toString();
}

export function outcomeView(o: DecisionOutcome | undefined): OutcomeView | null {
  if (!o) return null;
  if (o.basis === "trade") {
    if (o.is_open) return { settled: false, headline: t("out.trade_open", { id: o.trade_id ?? "-" }), value: o.profit_pct, unit: "pct", note: t("out.trade_open_note") };
    if (o.state !== "settled" || o.profit_pct === null) return { settled: false, headline: t("out.trade_pending"), value: null, unit: "pct", note: t("out.not_enough") };
    return { settled: true, headline: t("out.trade_closed", { id: o.trade_id ?? "-" }), value: o.profit_pct, unit: "pct", note: t("out.trade_closed_note") };
  }
  if (o.state === "pending") {
    return { settled: false, headline: t("out.skip_pending"), value: null, unit: "pct", note: o.settles_at ? t("out.skip_pending_at", { h: o.horizon_h, at: clock(o.settles_at) }) : t("out.skip_pending_later", { h: o.horizon_h }) };
  }
  if (o.state === "insufficient_data" || o.return_after_fees_pct === null) return { settled: false, headline: t("out.skip_nodata"), value: null, unit: "pct", note: t("out.skip_nodata_note") };
  return { settled: true, headline: t("out.skip_settled", { h: o.horizon_h }), value: o.return_after_fees_pct, unit: "pct", note: t("out.skip_settled_note") };
}
