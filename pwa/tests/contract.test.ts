import { spawn, type ChildProcess } from "node:child_process";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApi, type Api } from "../src/lib/api";
import { idempotencyKey, send } from "../src/lib/control";
import { diff, strip } from "../src/lib/settings";
import type { AuditRow, ControlResult, Decision, Equity, Overview, Provider, ProfitTotal, SessionInfo, SettingsDoc, SettingsSaved, Trade } from "../src/lib/types";

const PORT = 18000 + Math.floor(Math.random() * 2000);
const BASE = "http://127.0.0.1:" + PORT;
const root = fileURLToPath(new URL("..", import.meta.url));
let gateway: ChildProcess;
let token: string | null = null;
let api: Api;

async function login(): Promise<SessionInfo> {
  return api.post<SessionInfo>("/gw/v1/session", { password: "contoh" });
}

async function remotely<T>(fn: (remote: Api) => Promise<T>): Promise<T> {
  await dev("remote", { remote: true });
  const session = await login();
  const remote = createApi(BASE, () => session.token, () => undefined);
  try {
    expect(session.scope).toBe("read");
    return await fn(remote);
  } finally {
    await dev("remote", { remote: false });
  }
}

async function dev(path: string, body: unknown) {
  await fetch(BASE + "/gw/v1/dev/" + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}

beforeAll(async () => {
  gateway = spawn(root + "node_modules/.bin/tsx", ["mock-gateway/server.ts"], {
    cwd: root,
    env: { ...process.env, MOCK_GATEWAY_PORT: String(PORT), MOCK_SCRIPT_MS: "3600000" },
    stdio: ["ignore", "pipe", "inherit"],
  });
  await new Promise<void>((resolve, reject) => {
    gateway.stdout!.on("data", (chunk: Buffer) => {
      if (chunk.toString().includes("mock gateway")) resolve();
    });
    gateway.on("exit", (code) => reject(new Error("mock gateway exited " + code)));
  });
  api = createApi(BASE, () => token, () => (token = null));
  token = (await login()).token;
}, 30000);

afterAll(() => {
  gateway?.kill("SIGTERM");
});

describe("scope and control (2, 3, 6, 13 of ZHA-3774; 14.1, 14.2)", () => {
  it("gives control only to a loopback login and refuses control from a read session with an audit row", async () => {
    expect((await login()).scope).toBe("control");
    await remotely(async (remote) => {
      const out = await send(remote, { method: "post", path: "/gw/v1/control/stop-entry?bot=B", body: {} }, idempotencyKey());
      expect(out).toMatchObject({ kind: "failed", error: { status: 403, code: "forbidden_local_only" } });
    });
    const [row] = await api.get<AuditRow[]>("/gw/v1/audit?result=forbidden&limit=1");
    expect(row).toMatchObject({ action: "control.stop_entry", actor: "read_session", targets: ["B"] });
    expect((await api.get<Overview>("/gw/v1/overview?bot=B")).state).toBe("running");
  });

  it("requires an Idempotency-Key and replays a finished request without running it twice", async () => {
    const missing = await fetch(BASE + "/gw/v1/control/stop-entry?bot=B", { method: "POST", headers: { authorization: "Bearer " + token, "content-type": "application/json" }, body: "{}" });
    expect(missing.status).toBe(400);
    const key = idempotencyKey();
    const request = { method: "post" as const, path: "/gw/v1/control/stop-entry?bot=B", body: {} };
    const first = await send<ControlResult>(api, request, key);
    expect(first).toMatchObject({ kind: "done", result: { status: expect.stringMatching(/^paused/) } });
    expect((await api.get<Overview>("/gw/v1/overview?bot=B")).state).toBe("paused");
    expect((await api.get<Overview>("/gw/v1/overview?bot=A")).state).toBe("running");
    expect(await send<ControlResult>(api, request, key)).toEqual(first);
    const [row] = await api.get<AuditRow[]>("/gw/v1/audit?action=control.stop_entry&limit=1");
    expect(row.result).toBe("replayed");
    const other = await send(api, { method: "post", path: "/gw/v1/control/resume?bot=B", body: {} }, key);
    expect(other).toMatchObject({ kind: "failed", error: { status: 409, code: "invalid_request" } });
  });

  it("needs a confirmation to exit a trade, runs it once, and refuses the token for another trade", async () => {
    const [trade, other] = await api.get<Trade[]>("/gw/v1/trades/open");
    const request = { method: "post" as const, path: "/gw/v1/trades/" + trade.trade_id + "/exit", body: {} };
    const key = idempotencyKey();
    const step1 = await send<ControlResult>(api, request, key);
    expect(step1.kind).toBe("confirm");
    if (step1.kind !== "confirm") return;
    expect(step1.confirmation.action).toBe("trade.exit");
    expect(await api.get<Trade[]>("/gw/v1/trades/open")).toContainEqual(expect.objectContaining({ trade_id: trade.trade_id }));
    const wrong = await send<ControlResult>(api, { ...request, path: "/gw/v1/trades/" + other.trade_id + "/exit" }, idempotencyKey(), step1.confirmation.id);
    expect(wrong).toEqual({ kind: "restart", reason: "invalid" });
    const again = await send<ControlResult>(api, request, key);
    if (again.kind !== "confirm") throw new Error("expected a fresh confirmation");
    const step2 = await send<ControlResult>(api, request, key, again.confirmation.id);
    expect(step2).toMatchObject({ kind: "done", result: { result: "Created exit order for trade " + trade.trade_id + "." } });
    expect((await api.get<Trade[]>("/gw/v1/trades/open")).some((t) => t.trade_id === trade.trade_id)).toBe(false);
  });

  it("exits every open trade through trades/exit-all and confirms DELETE with a body", async () => {
    const key = idempotencyKey();
    const all = { method: "post" as const, path: "/gw/v1/trades/exit-all", body: {} };
    const step1 = await send(api, all, key);
    if (step1.kind !== "confirm") throw new Error("expected confirmation");
    expect(step1.confirmation.targets).toEqual(["A", "all"]);
    expect(await send(api, all, key, step1.confirmation.id)).toMatchObject({ kind: "done" });
    expect(await api.get<Trade[]>("/gw/v1/trades/open")).toEqual([]);
    await send(api, { method: "post", path: "/gw/v1/blacklist", body: { pairs: ["SOL/IDR"] } }, idempotencyKey());
    const del = { method: "del" as const, path: "/gw/v1/blacklist?pairs=SOL%2FIDR", body: {} };
    const k2 = idempotencyKey();
    const d1 = await send(api, del, k2);
    if (d1.kind !== "confirm") throw new Error("expected confirmation");
    expect(await send(api, del, k2, d1.confirmation.id)).toMatchObject({ kind: "done", result: { blacklist: [] } });
    await send(api, { method: "post", path: "/gw/v1/blacklist", body: { pairs: ["SOL/IDR"] } }, idempotencyKey());
    expect(await send(api, del, idempotencyKey(), d1.confirmation.id)).toEqual({ kind: "restart", reason: "invalid" });
  });
});

describe("settings (5.15, 14.3)", () => {
  async function patch(changes: { key: string; value: unknown }[], confirm?: string, key = idempotencyKey()) {
    const doc = await api.get<SettingsDoc>("/gw/v1/settings?bot=A");
    return { doc, out: await send<SettingsSaved>(api, { method: "patch", path: "/gw/v1/settings?bot=A", body: { revision: doc.revision, changes, note: "uji kontrak" } }, key, confirm), key };
  }

  it("never returns a key value and carries the file revision", async () => {
    const doc = await api.get<SettingsDoc>("/gw/v1/settings?bot=A");
    expect(doc.revision).toMatch(/^[0-9a-f]{64}$/);
    for (const p of doc.providers) expect(p.api_key).toBeNull();
  });

  it("lowers a limit at once from loopback and refuses any change from a read session", async () => {
    const lower = await patch([{ key: "risk.max_daily_loss_pct", value: 0.9 }]);
    expect(lower.out).toMatchObject({ kind: "done", result: { applied: [{ key: "risk.max_daily_loss_pct", old: 1, new: 0.9 }] } });
    await remotely(async (remote) => {
      const doc = await remote.get<SettingsDoc>("/gw/v1/settings?bot=A");
      const out = await send(remote, { method: "patch", path: "/gw/v1/settings?bot=A", body: { revision: doc.revision, changes: [{ key: "risk.max_daily_loss_pct", value: 0.8 }], note: "x" } }, idempotencyKey());
      expect(out).toMatchObject({ kind: "failed", error: { code: "forbidden_local_only" } });
    });
  });

  it("raises a limit locally only after the second step, and records the note in audit", async () => {
    const first = await patch([{ key: "risk.max_daily_loss_pct", value: 1.1 }]);
    expect(first.out.kind).toBe("confirm");
    if (first.out.kind !== "confirm") return;
    const second = await send<SettingsSaved>(api, { method: "patch", path: "/gw/v1/settings?bot=A", body: { revision: first.doc.revision, changes: [{ key: "risk.max_daily_loss_pct", value: 1.1 }], note: "uji kontrak" } }, first.key, first.out.confirmation.id);
    expect(second.kind).toBe("done");
    const [row] = await api.get<AuditRow[]>("/gw/v1/audit?action=config.changed&result=ok&limit=1");
    expect(row.detail).toMatchObject({ note: "uji kontrak", changes: [{ key: "risk.max_daily_loss_pct", old: 0.9, new: 1.1 }] });
  });

  it("rejects a stale revision and returns schema errors per key", async () => {
    const stale = await send(api, { method: "patch", path: "/gw/v1/settings?bot=A", body: { revision: "0".repeat(64), changes: [], note: "x" } }, idempotencyKey());
    expect(stale).toMatchObject({ kind: "failed", error: { code: "stale_revision" } });
    const invalid = await patch([{ key: "swarm.min_voters_answered", value: 9 }]);
    expect(invalid.out).toMatchObject({ kind: "failed", error: { code: "invalid_request", detail: { fields: [{ key: "swarm.min_voters_answered" }] } } });
  });

  it("applies voter changes keyed by id", async () => {
    const doc = await api.get<SettingsDoc>("/gw/v1/settings?bot=B");
    const next = structuredClone(strip(doc));
    next.swarm.voters[6].enabled = false;
    const changes = diff(strip(doc), next);
    expect(changes.map((c) => c.key)).toEqual(["swarm.voters[v7].enabled"]);
    const out = await send<SettingsSaved>(api, { method: "patch", path: "/gw/v1/settings?bot=B", body: { revision: doc.revision, changes: changes.map((c) => ({ key: c.key, value: c.new })), note: "matikan v7" } }, idempotencyKey());
    expect(out.kind).toBe("done");
    expect((await api.get<SettingsDoc>("/gw/v1/settings?bot=B")).swarm.voters.find((v) => v.id === "v7")?.enabled).toBe(false);
  });
});

describe("providers (14.4)", () => {
  it("lets a read session see status and test, and keeps key management on loopback", async () => {
    await remotely(async (remote) => {
      const list = await remote.get<Provider[]>("/gw/v1/providers");
      expect(list.map((p) => p.id)).toContain("nutaraline");
      for (const p of list) expect(p.api_key_last4).toBeNull();
      const tested = await send(remote, { method: "post", path: "/gw/v1/providers/nutaraline/test", body: {} }, idempotencyKey());
      expect(tested).toMatchObject({ kind: "done", result: { ok: true } });
      const put = await send(remote, { method: "put", path: "/gw/v1/providers/nutaraline", body: { id: "nutaraline", type: "openai-completions", base_url: "from_import", models: ["m"], api_key: "sk-contoh-1234" } }, idempotencyKey());
      expect(put).toMatchObject({ kind: "failed", error: { code: "forbidden_local_only" } });
      await expect(remote.get("/gw/v1/providers/import")).rejects.toMatchObject({ code: "forbidden_local_only" });
    });
  });

  it("stores a key from loopback, shows only its last four characters, and audits it as set", async () => {
    const out = await send<Provider>(api, { method: "put", path: "/gw/v1/providers/omniroute", body: { id: "omniroute", type: "openai-completions", base_url: "from_import", models: ["contoh-model-lokal"], api_key_env: null, api_key: "sk-contoh-WXYZ" } }, idempotencyKey());
    expect(out).toMatchObject({ kind: "done", result: { api_key_configured: true, api_key_last4: "WXYZ" } });
    const rows = await api.get<AuditRow[]>("/gw/v1/audit?action=provider.update&limit=1");
    expect(JSON.stringify(rows)).not.toContain("sk-contoh");
    expect(rows[0].detail).toMatchObject({ changes: [{ new: "<set>" }] });
  });
});

describe("history, decisions, A vs B, audit (14.5 to 14.8)", () => {
  it("pages decisions by timestamp and attaches an outcome", async () => {
    const first = await api.get<Decision[]>("/gw/v1/decisions?limit=10");
    const next = await api.get<Decision[]>("/gw/v1/decisions?limit=10&before=" + encodeURIComponent(first.at(-1)!.ts));
    expect(first).toHaveLength(10);
    expect(next[0].ts < first.at(-1)!.ts).toBe(true);
    for (const d of [...first, ...next]) expect(["pending", "insufficient_data", "settled"]).toContain(d.outcome?.state);
    const skipped = await api.get<Decision[]>("/gw/v1/decisions?limit=50&status=skip");
    expect(skipped.every((d) => d.status === "skip")).toBe(true);
  });

  it("returns closed trades by offset and total profit per bot", async () => {
    const page = await api.get<Trade[]>("/gw/v1/trades?limit=2&offset=1&state=closed");
    expect(page).toHaveLength(2);
    expect(page.every((t) => !t.is_open)).toBe(true);
    const a = await api.get<ProfitTotal>("/gw/v1/profit?window=total&bot=A");
    const b = await api.get<ProfitTotal>("/gw/v1/profit?window=total&bot=B");
    expect(a.closed_trade_count).toBeGreaterThan(0);
    expect(typeof b.max_drawdown).toBe("number");
  });

  it("draws both bots since the start of the dry-run", async () => {
    const e = await api.get<Equity>("/gw/v1/equity?window=total&bots=A,B");
    expect(e.series.map((s) => s.bot)).toEqual(["A", "B"]);
    expect(e.series[0].points.length).toBeGreaterThan(24 * 7);
  });

  it("filters audit by action prefix and pages by id", async () => {
    const control = await api.get<AuditRow[]>("/gw/v1/audit?action=control.&limit=50");
    expect(control.length).toBeGreaterThan(0);
    expect(control.every((r) => r.action.startsWith("control."))).toBe(true);
    const all = await api.get<AuditRow[]>("/gw/v1/audit?limit=3");
    const older = await api.get<AuditRow[]>("/gw/v1/audit?limit=3&before_id=" + all.at(-1)!.id);
    expect(older.every((r) => r.id < all.at(-1)!.id)).toBe(true);
  });
});
