import { spawn, type ChildProcess } from "node:child_process";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApi, type Api } from "../src/lib/api";
import { idempotencyKey, send } from "../src/lib/control";
import { diff, EDITABLE, patchBody, schemaErrors } from "../src/lib/settings";
import type { AuditRow, ChangeEntry, ControlResult, Decision, Equity, ImportCandidate, ImportResult, Overview, Provider, ProviderList, ProviderTest, ProfitTotal, Roles, SessionInfo, Settings, Trade, VoterList, VoterView, WriteResult } from "../src/lib/types";

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

describe("scope and control (ZHA-3774, 15.1)", () => {
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

describe("2a failures and keys (ZHA-3774)", () => {
  it("stores a Freqtrade failure per key and replays it, and audits a malformed key as rejected", async () => {
    await dev("fail", { path: "/gw/v1/control/reload-config", status: 502 });
    try {
      const key = idempotencyKey();
      const request = { method: "post" as const, path: "/gw/v1/control/reload-config?bot=B", body: {} };
      const first = await send(api, request, key);
      expect(first).toMatchObject({ kind: "failed", error: { status: 502, code: "upstream_error" } });
      await dev("fail", { path: "/gw/v1/control/reload-config", status: 0 });
      expect(await send(api, request, key)).toMatchObject({ kind: "failed", error: { status: 502 } });
      const rows = await api.get<AuditRow[]>("/gw/v1/audit?action=control.reload_config&limit=2");
      expect(rows.map((r) => r.result)).toEqual(["replayed", "failed"]);
    } finally {
      await dev("fail", { path: "/gw/v1/control/reload-config", status: 0 });
    }
    const bad = await send(api, { method: "post", path: "/gw/v1/control/resume?bot=B", body: {} }, "bad key!");
    expect(bad).toMatchObject({ kind: "failed", error: { status: 400, code: "invalid_request" } });
    const [row] = await api.get<AuditRow[]>("/gw/v1/audit?action=control.resume&limit=1");
    expect(row).toMatchObject({ result: "rejected", idempotency_key: null });
  });
});

describe("configuration (2b ZHA-3775, 15.1)", () => {
  async function patch(changes: Record<string, unknown>, confirm?: string, key = idempotencyKey(), bot = "A") {
    return { key, out: await send<WriteResult>(api, { method: "patch", path: "/gw/v1/settings?bot=" + bot, body: { changes } }, key, confirm) };
  }

  it("never returns a key value", async () => {
    const doc = await api.get<Settings>("/gw/v1/settings?bot=A");
    for (const p of doc.providers) expect(p.api_key).toBeNull();
  });

  it("lowers a limit at once with the nested body the client builds, and lists the change", async () => {
    const before = await api.get<Settings>("/gw/v1/settings?bot=A");
    const next = structuredClone(before);
    next.risk.max_daily_loss_pct = 0.9;
    const out = await patch(patchBody(diff(before, next)));
    expect(out.out).toMatchObject({ kind: "done", result: { bot: "A", changes: [{ key: "risk.max_daily_loss_pct", old: 1, new: 0.9 }], restart_required: true } });
    const [entry] = await api.get<ChangeEntry[]>("/gw/v1/settings/changes?bot=A&limit=1");
    expect(entry).toMatchObject({ action: "config.update", actor: "owner", key: "risk.max_daily_loss_pct", old: 1, new: 0.9, bot: "A" });
  });

  it("raises a limit or the capital only after the second step", async () => {
    const changes = { risk: { max_daily_loss_pct: 1.1 }, capital: { initial_idr: 2500000 } };
    const first = await patch(changes);
    expect(first.out.kind).toBe("confirm");
    if (first.out.kind !== "confirm") return;
    expect(first.out.confirmation.summary).toMatch(/capital\.initial_idr/);
    const second = await patch(changes, first.out.confirmation.id, first.key);
    expect(second.out).toMatchObject({ kind: "done", result: { changes: [{ key: "capital.initial_idr" }, { key: "risk.max_daily_loss_pct", old: 0.9, new: 1.1 }] } });
  });

  it("refuses frozen roots, voters through settings, schema errors, and any write from a read session", async () => {
    for (const changes of [{ mode: "live" }, { providers: [] }, { api: { force_entry: true } }, { swarm: { voters: [] } }]) {
      expect((await patch(changes)).out).toMatchObject({ kind: "failed", error: { status: 400, code: "invalid_request" } });
    }
    const schema = (await patch({ swarm: { min_voters_answered: 9 } })).out;
    expect(schema).toMatchObject({ kind: "failed", error: { code: "invalid_request" } });
    if (schema.kind === "failed") expect(schemaErrors(schema.error.message, EDITABLE).fields.map((f) => f.key)).toEqual(["swarm.min_voters_answered"]);
    await remotely(async (remote) => {
      const out = await send(remote, { method: "patch", path: "/gw/v1/settings?bot=A", body: { changes: { risk: { max_daily_loss_pct: 0.8 } } } }, idempotencyKey());
      expect(out).toMatchObject({ kind: "failed", error: { code: "forbidden_local_only" } });
    });
    const [denied] = await api.get<AuditRow[]>("/gw/v1/audit?action=admin.denied&limit=1");
    expect(denied).toMatchObject({ result: "forbidden", actor: "read_session" });
  });

  it("adds, edits and removes a voter through the voters routes, and refuses an unmet quorum", async () => {
    const fields = { adapter: "llm_structured", provider: "nutaraline", model: "deepseek-v4.1-flash-1017", variation: "temperature", timeout_s: 20, weight: 1, enabled: true };
    const added = await send<WriteResult & { voters: VoterView[] }>(api, { method: "put", path: "/gw/v1/voters/v8?bot=B", body: fields }, idempotencyKey());
    expect(added.kind).toBe("done");
    if (added.kind === "done") expect(added.result.voters.map((v) => v.id)).toContain("v8");
    expect((await api.get<VoterList>("/gw/v1/voters?bot=B")).swarm.enabled_voters).toBe(8);
    expect((await api.get<VoterList>("/gw/v1/voters?bot=A")).voters.map((v) => v.id)).not.toContain("v8");
    expect(await send(api, { method: "del", path: "/gw/v1/voters/v8?bot=B", body: {} }, idempotencyKey())).toMatchObject({ kind: "done" });
    for (const id of ["v7", "v6"]) await send(api, { method: "put", path: "/gw/v1/voters/" + id + "?bot=B", body: { ...fields, enabled: false } }, idempotencyKey());
    const tooFew = await send(api, { method: "put", path: "/gw/v1/voters/v5?bot=B", body: { ...fields, enabled: false } }, idempotencyKey());
    expect(tooFew).toMatchObject({ kind: "failed", error: { status: 400 } });
  });

  it("sets the analyst through roles", async () => {
    const out = await send<WriteResult>(api, { method: "put", path: "/gw/v1/roles?bot=A", body: { analyst: { provider: "omniroute", model: "contoh-model-lokal" } } }, idempotencyKey());
    expect(out).toMatchObject({ kind: "done", result: { changes: [{ key: "llm.analyst_model", new: "omniroute:contoh-model-lokal" }] } });
    expect((await api.get<Roles>("/gw/v1/roles?bot=A")).analyst).toEqual({ provider: "omniroute", model: "contoh-model-lokal" });
  });
});

describe("providers and keys (2b ZHA-3775, 15.1, 15.2)", () => {
  it("lets a read session list and test, and nothing else", async () => {
    await remotely(async (remote) => {
      const list = await remote.get<ProviderList>("/gw/v1/providers?bot=A");
      expect(list.bot).toBe("A");
      expect(list.providers.map((p) => p.id)).toContain("nutaraline");
      const tested = await send<ProviderTest>(remote, { method: "post", path: "/gw/v1/providers/nutaraline/test?bot=A", body: { model: "deepseek-v4.1-flash-1017" } }, idempotencyKey());
      expect(tested).toMatchObject({ kind: "done", result: { ok: true, status: 200 } });
      const again = await send(remote, { method: "post", path: "/gw/v1/providers/nutaraline/test?bot=A", body: {} }, idempotencyKey());
      expect(again).toMatchObject({ kind: "failed", error: { status: 429, code: "rate_limited" } });
      for (const request of [
        { method: "put" as const, path: "/gw/v1/providers/nutaraline?bot=A", body: { type: "openai-completions", base_url: "https://x.invalid/v1", models: ["m"] } },
        { method: "put" as const, path: "/gw/v1/providers/nutaraline/key?bot=A", body: { api_key: "sk-contoh-12345678" } },
        { method: "post" as const, path: "/gw/v1/providers/nutaraline/state?bot=A", body: { enabled: false } },
      ]) {
        expect(await send(remote, request, idempotencyKey())).toMatchObject({ kind: "failed", error: { code: "forbidden_local_only" } });
      }
      await expect(remote.get("/gw/v1/providers/import?bot=A")).rejects.toMatchObject({ code: "forbidden_local_only" });
    });
  });

  it("stores a key only through the key route, shows its last four characters, and masks it in audit and changes", async () => {
    const inBody = await send(api, { method: "put", path: "/gw/v1/providers/omniroute?bot=A", body: { type: "openai-completions", base_url: "https://omni.invalid/v1", models: ["contoh-model-lokal"], api_key: "sk-contoh-WXYZ" } }, idempotencyKey());
    expect(inBody).toMatchObject({ kind: "failed", error: { status: 400 } });
    const out = await send<WriteResult & { provider: Provider }>(api, { method: "put", path: "/gw/v1/providers/omniroute/key?bot=A", body: { api_key: "sk-contoh-PENANDA-WXYZ" } }, idempotencyKey());
    expect(out).toMatchObject({ kind: "done", result: { provider: { key: { source: "config", configured: true, last4: "WXYZ" } } } });
    const everything = JSON.stringify([await api.get("/gw/v1/audit?limit=200"), await api.get("/gw/v1/settings/changes?limit=200"), await api.get("/gw/v1/settings?bot=A"), await api.get("/gw/v1/providers?bot=A")]);
    expect(everything).not.toContain("PENANDA");
    expect(everything).toContain("****WXYZ");
    const env = await send<WriteResult & { provider: Provider }>(api, { method: "put", path: "/gw/v1/providers/omniroute/key?bot=A", body: { api_key_env: "OMNIROUTE_API_KEY" } }, idempotencyKey());
    expect(env).toMatchObject({ kind: "done", result: { provider: { key: { source: "env", env_name: "OMNIROUTE_API_KEY", last4: null } } } });
  });

  it("refuses removing a provider still in use", async () => {
    expect(await send(api, { method: "del", path: "/gw/v1/providers/nutaraline?bot=A", body: {} }, idempotencyKey())).toMatchObject({ kind: "failed", error: { status: 400 } });
  });

  it("previews models.yml without key values and imports a key only when ticked and allowed", async () => {
    const preview = await api.get<{ providers: ImportCandidate[] }>("/gw/v1/providers/import?bot=B");
    expect(JSON.stringify(preview)).not.toMatch(/sk-/);
    expect(preview.providers.find((c) => c.name === "Odd Name")?.blocker).toBeTruthy();
    const command = await send(api, { method: "post", path: "/gw/v1/providers/import?bot=B", body: { providers: [{ name: "shellkey", with_key: true, models: null, replace: false }] } }, idempotencyKey());
    expect(command).toMatchObject({ kind: "failed", error: { status: 400 } });
    const out = await send<{ results: ImportResult[] }>(api, { method: "post", path: "/gw/v1/providers/import?bot=B", body: { providers: [{ name: "modelrouter", with_key: true, models: null, replace: false }, { name: "nutaraline", with_key: false, models: null, replace: false }] } }, idempotencyKey());
    expect(out).toMatchObject({ kind: "done", result: { results: [{ name: "modelrouter", result: "created", with_key: true }, { name: "nutaraline", result: "skipped" }] } });
  });
});

describe("history, decisions, A vs B, audit (15.3)", () => {
  it("pages decisions by timestamp and attaches an outcome", async () => {
    const first = await api.get<Decision[]>("/gw/v1/decisions?limit=10");
    const next = await api.get<Decision[]>("/gw/v1/decisions?limit=10&before=" + encodeURIComponent(first.at(-1)!.candle));
    expect(first).toHaveLength(10);
    expect(Date.parse(next[0].candle) < Date.parse(first.at(-1)!.candle)).toBe(true);
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
