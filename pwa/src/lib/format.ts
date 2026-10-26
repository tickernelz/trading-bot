import { locale, t } from "./i18n";

export const MINUS = "\u2212";

const idr = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
const pct2 = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct1 = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const hm = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const hms = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const dayHm = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export type Direction = "up" | "down" | "flat";

export function direction(value: number, epsilon = 1e-9): Direction {
  if (value > epsilon) return "up";
  if (value < -epsilon) return "down";
  return "flat";
}

function signed(value: string, dir: Direction): string {
  if (dir === "up") return "+" + value;
  if (dir === "down") return MINUS + value;
  return value;
}

export function rupiah(value: number): string {
  return "Rp " + idr.format(Math.round(Math.abs(value)));
}

export function signedRupiah(value: number): string {
  return signed(rupiah(value), direction(Math.round(value)));
}

export function percent(value: number, digits: 1 | 2 = 2): string {
  return (digits === 1 ? pct1 : pct2).format(Math.abs(value)) + "%";
}

export function signedPercent(value: number, digits: 1 | 2 = 2): string {
  const rounded = Number(value.toFixed(digits));
  return signed(percent(value, digits), direction(rounded));
}

export function outcomeWord(value: number): string {
  const dir = direction(value);
  if (dir === "up") return t("outcome.up");
  if (dir === "down") return t("outcome.down");
  return t("outcome.flat");
}

export function price(value: number): string {
  if (value >= 1000) return idr.format(Math.round(value));
  return new Intl.NumberFormat(locale, { maximumSignificantDigits: 6 }).format(value);
}

export function decimal(value: number, digits = 2): string {
  return new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

export function parseTs(value: string | number): number {
  if (typeof value === "number") return value;
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
}

export function clock(value: string | number, seconds = false): string {
  return (seconds ? hms : hm).format(new Date(parseTs(value)));
}

export function dayClock(value: string | number): string {
  return dayHm.format(new Date(parseTs(value)));
}

export function age(ms: number, ago = true): string {
  if (!Number.isFinite(ms)) return t("age.none");
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const span = s < 60 ? t("age.s", { n: s }) : m < 60 ? t("age.m", { n: m }) : h < 48 ? t("age.h", { n: h }) : t("age.d", { n: Math.floor(h / 24) });
  return ago ? t("age.ago", { span }) : span;
}

export function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return t("dur.s", { n: s });
  const m = Math.floor(s / 60);
  if (m < 60) return t("dur.m", { n: m });
  return t("dur.hm", { h: Math.floor(m / 60), m: m % 60 });
}
