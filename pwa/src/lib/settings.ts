import type { Change, Settings, SettingsDoc } from "./types";

export interface FieldError {
  key: string;
  message: string;
}

export type Direction = "naik" | "turun" | "netral";

export const RISK_KEYS = ["risk.max_daily_loss_pct", "risk.max_total_drawdown_pct", "risk.risk_per_trade_pct", "risk.max_open_trades"] as const;

const RAISE_WHEN_TRUE = new Set(["api.force_entry"]);
const ID = /^[a-z0-9][a-z0-9_-]*$/;
const PAIR = /^[A-Z0-9]+\/[A-Z0-9]+$/;

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

export function strip(doc: SettingsDoc): Settings {
  const { revision: _revision, ...settings } = doc;
  return settings;
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function diff(before: Settings, after: Settings): Change[] {
  const old = flatten(before);
  const now = flatten(after);
  const keys = [...new Set([...Object.keys(old), ...Object.keys(now)])].sort();
  return keys.filter((key) => !same(old[key], now[key])).map((key) => ({ key, old: old[key] ?? null, new: now[key] ?? null }));
}

export function direction(change: Change): Direction {
  if ((RISK_KEYS as readonly string[]).includes(change.key) && typeof change.old === "number" && typeof change.new === "number") {
    if (change.new > change.old) return "naik";
    if (change.new < change.old) return "turun";
    return "netral";
  }
  if (RAISE_WHEN_TRUE.has(change.key)) return change.new === true ? "naik" : "turun";
  return "netral";
}

export function needsConfirmation(change: Change): boolean {
  return change.key === "mode" || direction(change) === "naik";
}

export function anyNeedsConfirmation(changes: Change[]): boolean {
  return changes.some(needsConfirmation);
}

function percent(errors: FieldError[], key: string, value: number): void {
  if (!Number.isFinite(value) || value <= 0 || value > 100) errors.push({ key, message: "Harus lebih dari 0 dan paling besar 100" });
}

export function validate(s: Settings): FieldError[] {
  const errors: FieldError[] = [];
  const add = (key: string, message: string) => errors.push({ key, message });
  if (!Number.isFinite(s.capital.initial_idr) || s.capital.initial_idr <= 0) add("capital.initial_idr", "Modal harus lebih dari Rp 0");
  percent(errors, "risk.max_daily_loss_pct", s.risk.max_daily_loss_pct);
  percent(errors, "risk.max_total_drawdown_pct", s.risk.max_total_drawdown_pct);
  percent(errors, "risk.risk_per_trade_pct", s.risk.risk_per_trade_pct);
  const trades = s.risk.max_open_trades;
  if (!Number.isInteger(trades) || trades < 1 || trades > 20) add("risk.max_open_trades", "Bilangan bulat 1 sampai 20");
  if (!errors.some((e) => e.key.startsWith("risk."))) {
    if (s.risk.risk_per_trade_pct > s.risk.max_daily_loss_pct) add("risk.risk_per_trade_pct", "Tidak boleh melebihi batas rugi harian");
    if (s.risk.max_daily_loss_pct > s.risk.max_total_drawdown_pct) add("risk.max_daily_loss_pct", "Tidak boleh melebihi batas rugi total");
  }
  if (!Number.isFinite(s.exchange.fee_pct) || s.exchange.fee_pct < 0 || s.exchange.fee_pct >= 5) add("exchange.fee_pct", "Paling kecil 0 dan kurang dari 5");
  const pairs = s.exchange.pairs;
  if (pairs.length === 0) add("exchange.pairs", "Minimal satu pair");
  else if (pairs.some((p) => !PAIR.test(p))) add("exchange.pairs", "Format pair BASE/IDR, huruf besar");
  else if (new Set(pairs).size !== pairs.length) add("exchange.pairs", "Pair tidak boleh ganda");
  else if (pairs.some((p) => p.split("/")[1] !== "IDR")) add("exchange.pairs", "Semua pair harus berakhiran IDR, sama dengan mata uang modal");
  const providers = new Map(s.providers.map((p) => [p.id, p]));
  const ids = s.swarm.voters.map((v) => v.id);
  for (const v of s.swarm.voters) {
    const base = "swarm.voters[" + v.id + "]";
    if (!ID.test(v.id)) add(base + ".id", "Huruf kecil, angka, - atau _");
    if (ids.indexOf(v.id) !== ids.lastIndexOf(v.id)) add(base + ".id", "Id voter ganda");
    if (!Number.isFinite(v.timeout_s) || v.timeout_s <= 0 || v.timeout_s > 600) add(base + ".timeout_s", "Lebih dari 0 dan paling lama 600 detik");
    if (!Number.isFinite(v.weight) || v.weight <= 0) add(base + ".weight", "Bobot harus lebih dari 0");
    const provider = providers.get(v.provider);
    if (!provider) add(base + ".provider", "Provider tidak ada di daftar");
    else if (!provider.models.includes(v.model)) add(base + ".model", "Model tidak terdaftar di provider " + provider.id);
  }
  const enabled = s.swarm.voters.filter((v) => v.enabled).length;
  const quorum = s.swarm.min_voters_answered;
  if (!Number.isInteger(quorum) || quorum < 1) add("swarm.min_voters_answered", "Bilangan bulat minimal 1");
  else if (s.swarm.enabled && quorum > enabled) add("swarm.min_voters_answered", "Lebih besar dari " + enabled + " voter aktif");
  if (s.swarm.max_spread !== null && (!Number.isFinite(s.swarm.max_spread) || s.swarm.max_spread <= 0)) add("swarm.max_spread", "Kosongkan atau isi angka lebih dari 0");
  const [analystProvider, analystModel] = splitModel(s.llm.analyst_model);
  const analyst = providers.get(analystProvider);
  if (!analyst) add("llm.analyst_model", "Provider agen analis tidak ada di daftar");
  else if (!analyst.models.includes(analystModel)) add("llm.analyst_model", "Model tidak terdaftar di provider " + analyst.id);
  const cap = s.compute.max_cost_idr_per_day;
  if (cap !== false && (!Number.isFinite(cap) || cap <= 0)) add("compute.max_cost_idr_per_day", "Matikan atau isi angka lebih dari Rp 0");
  return errors;
}

export function splitModel(value: string): [string, string] {
  const at = value.indexOf(":");
  return at < 0 ? [value, ""] : [value.slice(0, at), value.slice(at + 1)];
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
