import { describe, expect, it, vi } from "vitest";
import { ApiError, type Api } from "../src/lib/api";
import { explain, idempotencyKey, resultText, secondsLeft, send } from "../src/lib/control";

const confirmation = { id: "cf_1", action: "control.stop", targets: ["A"], summary: "Stop A", expires_at: "2026-10-26T03:01:00Z" };

function stubApi(responses: (() => unknown)[]) {
  const calls: { path: string; body: unknown; headers: Record<string, string> | undefined }[] = [];
  const handler = async (path: string, body: unknown, headers?: Record<string, string>) => {
    calls.push({ path, body, headers });
    return responses.shift()!();
  };
  const api = { get: vi.fn(), post: handler, put: handler, patch: handler, del: handler } as unknown as Api;
  return { api, calls };
}

describe("two-step control", () => {
  it("returns the gateway confirmation, then repeats the same request with the same key and the confirm id", async () => {
    const { api, calls } = stubApi([
      () => {
        throw new ApiError(409, "confirmation_required", "needs confirmation", undefined, { confirmation });
      },
      () => ({ status: "stopping trader ..." }),
    ]);
    const request = { method: "post" as const, path: "/gw/v1/control/stop?bot=A", body: {} };
    const first = await send(api, request, "k-1");
    expect(first).toEqual({ kind: "confirm", confirmation });
    const second = await send(api, request, "k-1", "cf_1");
    expect(second).toEqual({ kind: "done", result: { status: "stopping trader ..." } });
    if (second.kind === "done") expect(resultText(second.result)).toBe("stopping trader ...");
    expect(calls.map((c) => c.headers?.["idempotency-key"])).toEqual(["k-1", "k-1"]);
    expect(calls[0].body).toEqual({});
    expect(calls[1].body).toEqual({ confirm: "cf_1" });
  });

  it("runs actions that lower risk in one step", async () => {
    const { api, calls } = stubApi([() => ({ status: "paused, no more entries will occur from now. Run /start to enable entries." })]);
    const out = await send(api, { method: "post", path: "/gw/v1/control/pause", body: {} }, "k-2");
    expect(out.kind).toBe("done");
    expect(calls).toHaveLength(1);
  });

  it("sends an expired or invalid confirmation back to step one and reports other errors", async () => {
    const { api } = stubApi([
      () => {
        throw new ApiError(409, "confirmation_expired", "expired");
      },
      () => {
        throw new ApiError(409, "confirmation_invalid", "used");
      },
      () => {
        throw new ApiError(403, "forbidden_local_only", "loopback only");
      },
    ]);
    const request = { method: "patch" as const, path: "/gw/v1/settings", body: { note: "x" } };
    expect(await send(api, request, "k-3", "cf_old")).toEqual({ kind: "restart", reason: "expired" });
    expect(await send(api, request, "k-3", "cf_used")).toEqual({ kind: "restart", reason: "invalid" });
    const failed = await send(api, request, "k-4");
    expect(failed.kind).toBe("failed");
    if (failed.kind === "failed") expect(explain(failed.error)).toMatch(/localhost/);
  });

  it("counts the confirmation window down to zero", () => {
    const end = Date.parse(confirmation.expires_at);
    expect(secondsLeft(confirmation, end - 59500)).toBe(60);
    expect(secondsLeft(confirmation, end + 1000)).toBe(0);
  });

  it("makes RFC 4122 version 4 keys without a secure context", () => {
    const key = idempotencyKey((b) => b.fill(0xff));
    expect(key).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
    expect(idempotencyKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});
