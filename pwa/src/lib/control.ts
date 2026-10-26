import { ApiError, type Api, type Headers } from "./api";
import type { Confirmation } from "./types";

export type Method = "post" | "put" | "patch" | "del";

export interface Request {
  method: Method;
  path: string;
  body: Record<string, unknown>;
}

export type Outcome<T> =
  | { kind: "done"; result: T }
  | { kind: "confirm"; confirmation: Confirmation }
  | { kind: "restart"; reason: "expired" | "invalid" }
  | { kind: "failed"; error: ApiError };

export function idempotencyKey(random: (bytes: Uint8Array) => Uint8Array = (b) => crypto.getRandomValues(b)): string {
  const b = random(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" + hex.slice(16, 20) + "-" + hex.slice(20);
}

function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError(0, "client", error instanceof Error ? error.message : String(error));
}

export async function send<T>(api: Api, request: Request, key: string, confirm?: string): Promise<Outcome<T>> {
  const body = confirm ? { ...request.body, confirm } : request.body;
  const headers = { "idempotency-key": key };
  try {
    const call: <R>(path: string, body: unknown, headers?: Headers) => Promise<R> = { post: api.post, put: api.put, patch: api.patch, del: api.del }[request.method];
    const result = await call<T>(request.path, body, headers);
    return { kind: "done", result };
  } catch (error) {
    const e = asApiError(error);
    if (e.code === "confirmation_required" && e.detail.confirmation) {
      return { kind: "confirm", confirmation: e.detail.confirmation as Confirmation };
    }
    if (e.code === "confirmation_expired") return { kind: "restart", reason: "expired" };
    if (e.code === "confirmation_invalid") return { kind: "restart", reason: "invalid" };
    return { kind: "failed", error: e };
  }
}

export function restartText(reason: "expired" | "invalid"): string {
  return reason === "expired" ? "Konfirmasi kedaluwarsa (60 detik). Tidak ada yang dijalankan; mulai lagi dari langkah 1." : "Konfirmasi tidak berlaku (sudah dipakai atau untuk aksi lain). Tidak ada yang dijalankan; mulai lagi dari langkah 1.";
}

export function resultText(result: unknown): string {
  if (result && typeof result === "object") {
    const r = result as Record<string, unknown>;
    if (typeof r.status === "string") return r.status;
    if (typeof r.result === "string") return r.result;
  }
  return "perintah diterima";
}

export function secondsLeft(confirmation: Confirmation, now: number): number {
  return Math.max(0, Math.ceil((Date.parse(confirmation.expires_at) - now) / 1000));
}

const MESSAGES: Record<string, string> = {
  forbidden_local_only: "Hanya bisa dari PC bot (localhost), bukan lewat tunnel atau jaringan.",
  unauthorized: "Sesi berakhir. Masuk lagi.",
  upstream_unavailable: "Bot tidak menjawab. Coba lagi setelah bot tersambung.",
  upstream_error: "Bot menolak perintah ini.",
  risk_limit_breached: "Ditolak lapisan risiko: batas rugi sudah terlewati.",
  invalid_request: "Permintaan tidak sah.",
  stale_revision: "Konfigurasi berubah sejak dibuka. Muat ulang lalu tinjau lagi.",
  rate_limited: "Terlalu banyak permintaan. Tunggu sebentar.",
  network: "Gateway tidak terjangkau. Periksa koneksi.",
  not_found: "Endpoint ini belum ada di gateway.",
};

const READ_MESSAGES: Record<string, string> = {
  upstream_error: "Gateway gagal membaca dari bot.",
  upstream_unavailable: "Bot tidak menjawab gateway.",
  network: "Gateway tidak terjangkau.",
  not_found: "Endpoint ini belum ada di gateway.",
  forbidden_local_only: "Hanya bisa dibaca dari PC bot (localhost).",
};

export function explainRead(error: { code: string }): string {
  return (READ_MESSAGES[error.code] ?? "Gagal dimuat.") + " Data dimuat lagi saat layar dibuka atau Coba lagi ditekan.";
}

export function explain(error: { code: string; message: string }): string {
  const base = MESSAGES[error.code] ?? "Gagal.";
  return error.message && !MESSAGES[error.code] ? base + " " + error.message : base;
}
