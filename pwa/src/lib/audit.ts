import type { AuditRow } from "./types";

export const ACTION_GROUPS = [
  { id: "", label: "Semua" },
  { id: "control.", label: "Kontrol" },
  { id: "trade.", label: "Trade" },
  { id: "pair.", label: "Pair" },
  { id: "config.", label: "Konfigurasi" },
  { id: "provider.", label: "Provider" },
  { id: "session.", label: "Sesi" },
] as const;

export const RESULTS = [
  { id: "", label: "Semua hasil" },
  { id: "ok", label: "Berhasil" },
  { id: "failed", label: "Gagal di bot" },
  { id: "rejected", label: "Ditolak gateway" },
  { id: "forbidden", label: "Dilarang (bukan lokal)" },
  { id: "denied", label: "Login ditolak" },
  { id: "replayed", label: "Diputar ulang" },
  { id: "invalid", label: "Config tidak sah" },
] as const;

const ACTION_LABEL: Record<string, string> = {
  "session.create": "Masuk",
  "session.delete": "Keluar",
  "config.observed": "Konfigurasi terbaca pertama kali",
  "config.changed": "Konfigurasi berubah",
  "control.pause": "Jeda entry",
  "control.stop_entry": "Hentikan entry baru",
  "control.resume": "Lanjutkan entry",
  "control.stop": "Hentikan bot",
  "control.reload_config": "Muat ulang config",
  "trade.enter": "Entry paksa",
  "trade.exit": "Exit paksa",
  "trade.exit_all": "Exit paksa semua",
  "pair.lock": "Kunci pair",
  "pair.unlock": "Buka kunci pair",
  "pair.blacklist": "Tambah blacklist",
  "pair.unblacklist": "Hapus dari blacklist",
  "provider.test": "Uji koneksi provider",
  "provider.state": "Ubah status provider",
  "provider.create": "Tambah provider",
  "provider.update": "Ubah provider",
  "provider.import": "Impor provider",
};

const RESULT_LABEL: Record<string, string> = {
  ok: "berhasil",
  denied: "ditolak",
  failed: "gagal di bot",
  rejected: "ditolak gateway",
  forbidden: "dilarang",
  replayed: "diputar ulang",
  invalid: "tidak sah",
  confirmation_required: "minta konfirmasi",
};

const QUIET = new Set(["ok", "confirmation_required", "replayed"]);

export function auditPath(action: string, result: string, beforeId: number | null, limit = 50, target = ""): string {
  const q = new URLSearchParams({ limit: String(limit) });
  if (action) q.set("action", action);
  if (result) q.set("result", result);
  if (target) q.set("target", target);
  if (beforeId !== null) q.set("before_id", String(beforeId));
  return "/gw/v1/audit?" + q.toString();
}

export function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action;
}

export function resultLabel(result: string): string {
  return RESULT_LABEL[result] ?? result;
}

export function isProblem(row: AuditRow): boolean {
  return !QUIET.has(row.result);
}

export interface ChangeLine {
  key: string;
  old: string;
  new: string;
}

export function show(value: unknown): string {
  if (value === null || value === undefined) return "kosong";
  if (value === "<set>") return "terpasang";
  if (value === true) return "ya";
  if (value === false) return "tidak";
  if (Array.isArray(value)) return value.map(show).join(", ");
  if (typeof value === "number") return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 4 }).format(value);
  return String(value);
}

export function changeLines(row: AuditRow): ChangeLine[] {
  const changes = row.detail?.changes;
  if (!Array.isArray(changes)) return [];
  return changes.map((c: { key: string; old: unknown; new: unknown }) => ({ key: c.key, old: show(c.old), new: show(c.new) }));
}

export function matches(row: AuditRow, action: string, result: string, target = ""): boolean {
  return (!action || row.action.startsWith(action)) && (!result || row.result === result) && (!target || row.targets.includes(target));
}
