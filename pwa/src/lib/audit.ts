import { t, type Key } from "./i18n";
import type { AuditRow } from "./types";

export const ACTION_GROUPS = [
  { id: "", label: t("audit.g_all") },
  { id: "control.", label: t("audit.g_control") },
  { id: "trade.", label: t("audit.g_trade") },
  { id: "pair.", label: t("audit.g_pair") },
  { id: "config.", label: t("audit.g_config") },
  { id: "provider.", label: t("audit.g_provider") },
  { id: "admin.", label: t("audit.g_admin") },
  { id: "session.", label: t("audit.g_session") },
] as const;

export const RESULTS = [
  { id: "", label: t("audit.r_all") },
  { id: "ok", label: t("audit.r_ok") },
  { id: "failed", label: t("audit.r_failed") },
  { id: "rejected", label: t("audit.r_rejected") },
  { id: "forbidden", label: t("audit.r_forbidden") },
  { id: "denied", label: t("audit.r_denied") },
  { id: "replayed", label: t("audit.r_replayed") },
  { id: "invalid", label: t("audit.r_invalid") },
] as const;

const ACTION_LABEL: Record<string, Key> = {
  "session.create": "audit.a_session_create",
  "session.delete": "audit.a_session_delete",
  "config.observed": "audit.a_config_observed",
  "config.changed": "audit.a_config_changed",
  "config.update": "audit.a_config_update",
  "config.provider.upsert": "audit.a_provider_upsert",
  "config.provider.delete": "audit.a_provider_delete",
  "config.provider.key": "audit.a_provider_key",
  "config.provider.import": "audit.a_provider_import",
  "config.voter.upsert": "audit.a_voter_upsert",
  "config.voter.delete": "audit.a_voter_delete",
  "config.roles": "audit.a_roles",
  "provider.test": "audit.a_provider_test",
  "admin.denied": "audit.a_admin_denied",
  "control.pause": "audit.a_pause",
  "control.stop_entry": "audit.a_stop_entry",
  "control.resume": "audit.a_resume",
  "control.stop": "audit.a_stop",
  "control.reload_config": "audit.a_reload",
  "trade.enter": "audit.a_enter",
  "trade.exit": "audit.a_exit",
  "trade.exit_all": "audit.a_exit_all",
  "pair.lock": "audit.a_lock",
  "pair.unlock": "audit.a_unlock",
  "pair.blacklist": "audit.a_blacklist",
  "pair.unblacklist": "audit.a_unblacklist",
};

const RESULT_LABEL: Record<string, Key> = {
  ok: "audit.res_ok",
  denied: "audit.res_denied",
  failed: "audit.res_failed",
  rejected: "audit.res_rejected",
  forbidden: "audit.res_forbidden",
  replayed: "audit.res_replayed",
  invalid: "audit.res_invalid",
  confirmation_required: "audit.res_confirm",
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
  const key = ACTION_LABEL[action];
  return key ? t(key) : action;
}

export function resultLabel(result: string): string {
  const key = RESULT_LABEL[result];
  return key ? t(key) : result;
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
  if (value === null || value === undefined) return t("audit.v_empty");
  if (value === "<set>") return t("audit.v_set");
  if (value === true) return t("audit.v_true");
  if (value === false) return t("audit.v_false");
  if (Array.isArray(value)) return value.map(show).join(", ");
  if (typeof value === "number") return new Intl.NumberFormat(t("audit.locale"), { maximumFractionDigits: 4 }).format(value);
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
