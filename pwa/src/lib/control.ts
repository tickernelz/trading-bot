import { ApiError, type Api, type Headers } from "./api";
import { t, type Key } from "./i18n";
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

const MESSAGES: Record<string, Key> = {
  forbidden_local_only: "err.forbidden_local_only",
  unauthorized: "err.unauthorized",
  upstream_unavailable: "err.upstream_unavailable",
  upstream_error: "err.upstream_error",
  risk_limit_breached: "err.risk_limit_breached",
  invalid_request: "err.invalid_request",
  rate_limited: "err.rate_limited",
  network: "err.network",
  not_found: "err.not_found",
  config_unwritable: "err.config_unwritable",
};

const READ_MESSAGES: Record<string, Key> = {
  upstream_error: "err.read_upstream_error",
  upstream_unavailable: "err.read_upstream_unavailable",
  network: "err.read_network",
  not_found: "err.not_found",
  forbidden_local_only: "err.read_forbidden",
};

export function explainRead(error: { code: string }): string {
  const key = READ_MESSAGES[error.code];
  return (key ? t(key) : t("err.read_generic")) + " " + t("err.read_retry");
}

export function explain(error: { code: string; message: string }): string {
  const key = MESSAGES[error.code];
  if (key) return t(key) + (error.code === "risk_limit_breached" && error.message ? " " + error.message : "");
  return t("err.generic") + (error.message ? " " + error.message : "");
}

export function restartText(reason: "expired" | "invalid"): string {
  return reason === "expired" ? t("err.confirm_expired") : t("err.confirm_invalid");
}

export function resultText(result: unknown): string {
  if (result && typeof result === "object") {
    const r = result as Record<string, unknown>;
    if (typeof r.status === "string") return r.status;
    if (typeof r.result === "string") return r.result;
  }
  return t("common.accepted");
}

export function secondsLeft(confirmation: Confirmation, now: number): number {
  return Math.max(0, Math.ceil((Date.parse(confirmation.expires_at) - now) / 1000));
}
