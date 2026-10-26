import { t } from "./i18n";
import type { Change, ProviderSetting, Settings, VoterFields } from "./types";

export interface FieldError {
  key: string;
  message: string;
}

export type Direction = "naik" | "turun" | "netral";

export const RISK_KEYS = ["risk.max_daily_loss_pct", "risk.max_total_drawdown_pct", "risk.risk_per_trade_pct", "risk.max_open_trades"] as const;
const CONFIRM_KEYS: readonly string[] = [...RISK_KEYS, "capital.initial_idr"];

export const EDITABLE = [
  "capital.initial_idr",
  "capital.compounding",
  "risk.max_daily_loss_pct",
  "risk.max_total_drawdown_pct",
  "risk.risk_per_trade_pct",
  "risk.max_open_trades",
  "exchange.pairs",
  "exchange.fee_pct",
  "swarm.enabled",
  "swarm.mode",
  "swarm.shuffle_options",
  "swarm.min_voters_answered",
  "swarm.max_spread",
  "compute.max_cost_idr_per_day",
  "compute.log_cost",
  "data.fear_greed",
  "data.social",
  "notify.web_push",
] as const;

const PAIR = /^[A-Z0-9]+\/[A-Z0-9]+$/;
const VOTER_ID = /^[a-z0-9][a-z0-9_-]*$/;

type Plain = Record<string, unknown>;

function isPlain(value: unknown): value is Plain {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function flatten(value: unknown, prefix = ""): Record<string, unknown> {
  if (isPlain(value)) {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) Object.assign(out, flatten(item, prefix ? prefix + "." + key : key));
    return out;
  }
  if (Array.isArray(value) && value.length > 0 && value.every(isPlain)) {
    const out: Record<string, unknown> = {};
    value.forEach((item, position) => Object.assign(out, flatten(item, prefix + "[" + String(item.id ?? position) + "]")));
    return out;
  }
  return { [prefix]: value };
}

function read(source: unknown, key: string): unknown {
  return key.split(".").reduce<unknown>((node, part) => (isPlain(node) ? node[part] : undefined), source);
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function diff(before: Settings, after: Settings): Change[] {
  return EDITABLE.filter((key) => !same(read(before, key), read(after, key))).map((key) => ({ key, old: read(before, key) ?? null, new: read(after, key) ?? null }));
}

export function patchBody(changes: Change[]): Plain {
  const out: Plain = {};
  for (const change of changes) {
    const parts = change.key.split(".");
    let node = out;
    for (const part of parts.slice(0, -1)) node = (node[part] ??= {}) as Plain;
    node[parts.at(-1)!] = change.new;
  }
  return out;
}

export function direction(change: Change): Direction {
  if (CONFIRM_KEYS.includes(change.key) && typeof change.old === "number" && typeof change.new === "number") {
    if (change.new > change.old) return "naik";
    if (change.new < change.old) return "turun";
  }
  return "netral";
}

export function needsConfirmation(change: Change): boolean {
  return direction(change) === "naik";
}

export function anyNeedsConfirmation(changes: Change[]): boolean {
  return changes.some(needsConfirmation);
}

export function schemaErrors(message: string, known: readonly string[]): { fields: FieldError[]; rest: string[] } {
  const fields: FieldError[] = [];
  const rest: string[] = [];
  for (const part of message.split("; ")) {
    const at = part.indexOf(": ");
    const loc = at < 0 ? "" : part.slice(0, at);
    if (loc && known.includes(loc)) fields.push({ key: loc, message: part.slice(at + 2) });
    else rest.push(part);
  }
  return { fields, rest };
}

function percent(errors: FieldError[], key: string, value: number): void {
  if (!Number.isFinite(value) || value <= 0 || value > 100) errors.push({ key, message: t("cfg.err_percent") });
}

export function validate(s: Settings, enabledVoters: number): FieldError[] {
  const errors: FieldError[] = [];
  const add = (key: string, message: string) => errors.push({ key, message });
  if (!Number.isFinite(s.capital.initial_idr) || s.capital.initial_idr <= 0) add("capital.initial_idr", t("cfg.err_capital"));
  percent(errors, "risk.max_daily_loss_pct", s.risk.max_daily_loss_pct);
  percent(errors, "risk.max_total_drawdown_pct", s.risk.max_total_drawdown_pct);
  percent(errors, "risk.risk_per_trade_pct", s.risk.risk_per_trade_pct);
  const trades = s.risk.max_open_trades;
  if (!Number.isInteger(trades) || trades < 1 || trades > 20) add("risk.max_open_trades", t("cfg.err_open_trades"));
  if (!errors.some((e) => e.key.startsWith("risk."))) {
    if (s.risk.risk_per_trade_pct > s.risk.max_daily_loss_pct) add("risk.risk_per_trade_pct", t("cfg.err_per_trade"));
    if (s.risk.max_daily_loss_pct > s.risk.max_total_drawdown_pct) add("risk.max_daily_loss_pct", t("cfg.err_daily"));
  }
  if (!Number.isFinite(s.exchange.fee_pct) || s.exchange.fee_pct < 0 || s.exchange.fee_pct >= 5) add("exchange.fee_pct", t("cfg.err_fee"));
  const pairs = s.exchange.pairs;
  if (pairs.length === 0) add("exchange.pairs", t("cfg.err_pairs_empty"));
  else if (pairs.some((p) => !PAIR.test(p))) add("exchange.pairs", t("cfg.err_pairs_format"));
  else if (new Set(pairs).size !== pairs.length) add("exchange.pairs", t("cfg.err_pairs_dup"));
  else if (pairs.some((p) => p.split("/")[1] !== "IDR")) add("exchange.pairs", t("cfg.err_pairs_idr"));
  const quorum = s.swarm.min_voters_answered;
  if (!Number.isInteger(quorum) || quorum < 1) add("swarm.min_voters_answered", t("cfg.err_quorum_int"));
  else if (s.swarm.enabled && quorum > enabledVoters) add("swarm.min_voters_answered", t("cfg.err_quorum_voters", { n: enabledVoters }));
  if (s.swarm.max_spread !== null && (!Number.isFinite(s.swarm.max_spread) || s.swarm.max_spread <= 0)) add("swarm.max_spread", t("cfg.err_spread"));
  const cap = s.compute.max_cost_idr_per_day;
  if (cap !== false && (!Number.isFinite(cap) || cap <= 0)) add("compute.max_cost_idr_per_day", t("cfg.err_cost"));
  return errors;
}

export function validateVoter(id: string, v: VoterFields, providers: ProviderSetting[], ids: string[]): FieldError[] {
  const errors: FieldError[] = [];
  if (!VOTER_ID.test(id)) errors.push({ key: "id", message: t("cfg.err_voter_id") });
  else if (ids.includes(id)) errors.push({ key: "id", message: t("cfg.err_voter_dup") });
  const provider = providers.find((p) => p.id === v.provider);
  if (!provider) errors.push({ key: "provider", message: t("cfg.err_voter_provider") });
  else if (!provider.models.includes(v.model)) errors.push({ key: "model", message: t("cfg.err_voter_model", { provider: provider.id }) });
  if (!Number.isFinite(v.timeout_s) || v.timeout_s <= 0 || v.timeout_s > 600) errors.push({ key: "timeout_s", message: t("cfg.err_timeout") });
  if (!Number.isFinite(v.weight) || v.weight <= 0) errors.push({ key: "weight", message: t("cfg.err_weight") });
  return errors;
}

export function nextVoterId(ids: string[]): string {
  let n = ids.length + 1;
  while (ids.includes("v" + n)) n++;
  return "v" + n;
}

export function errorsFor(errors: FieldError[], key: string): string | null {
  return errors.find((e) => e.key === key)?.message ?? null;
}

export function rupiahOf(capital: number, pct: number): number {
  return (capital * pct) / 100;
}
