export const MINUS = "\u2212";

const idr = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
const pct2 = new Intl.NumberFormat("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct1 = new Intl.NumberFormat("id-ID", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const hm = new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const hms = new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const dayHm = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

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
  if (dir === "up") return "untung";
  if (dir === "down") return "rugi";
  return "impas";
}

export function price(value: number): string {
  if (value >= 1000) return idr.format(Math.round(value));
  return new Intl.NumberFormat("id-ID", { maximumSignificantDigits: 6 }).format(value);
}

export function decimal(value: number, digits = 2): string {
  return new Intl.NumberFormat("id-ID", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
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

export function age(ms: number): string {
  if (!Number.isFinite(ms)) return "belum ada data";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return s + " dtk lalu";
  const m = Math.floor(s / 60);
  if (m < 60) return m + " mnt lalu";
  const h = Math.floor(m / 60);
  if (h < 48) return h + " jam lalu";
  return Math.floor(h / 24) + " hari lalu";
}

export function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return s + " dtk";
  const m = Math.floor(s / 60);
  if (m < 60) return m + " mnt";
  const h = Math.floor(m / 60);
  return h + " jam " + (m % 60) + " mnt";
}
