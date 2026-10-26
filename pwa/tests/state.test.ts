import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createApi } from "../src/lib/api";
import { describe as feedText } from "../src/lib/feedText";
import { carriesData, FEED_TOPICS, greetingMessages, isStale, loadSnapshot, safetyOf, STALE_AFTER_MS, type Freshness } from "../src/lib/state";
import type { Health, Risk } from "../src/lib/types";

const health = (state: string) => ({ freqtrade: { state } }) as Health;
const risk = (entries_allowed: boolean) => ({ entries_allowed }) as Risk;

const fresh: Freshness = { linkOpen: true, lastDataAt: 1000, now: 2000, upstream: null, core: null };

describe("data freshness", () => {
  it("advances only on events that come from the Freqtrade feed", () => {
    for (const type of FEED_TOPICS.filter((t) => t !== "gw.decision" && t !== "gw.audit")) expect(carriesData(type)).toBe(true);
    for (const type of ["gw.decision", "gw.audit", "gw.hello", "gw.resync", "gw.error", "pong"]) expect(carriesData(type)).toBe(false);
  });

  it("marks the last known state stale when the gateway reports the bot unreachable", () => {
    expect(isStale(fresh)).toBe(false);
    expect(isStale({ ...fresh, upstream: { code: "upstream_unavailable", message: "", at: 2000 } })).toBe(true);
  });

  it("marks the last known state stale when the core refresh fails", () => {
    expect(isStale({ ...fresh, core: { code: "http_502", message: "", at: 2000 } })).toBe(true);
  });

  it("marks stale on a closed link or old data, never before the first data", () => {
    expect(isStale({ ...fresh, linkOpen: false })).toBe(true);
    expect(isStale({ ...fresh, now: 1000 + STALE_AFTER_MS + 1 })).toBe(true);
    expect(isStale({ ...fresh, lastDataAt: null, linkOpen: false })).toBe(false);
  });
});

describe("reconnect greeting", () => {
  type Message = { type: string; topics?: string[]; last_seq?: number };
  const buffered = [
    { type: "entry", seq: 24 },
    { type: "exit_fill", seq: 25 },
    { type: "gw.risk_denied", seq: 26 },
  ];
  const ALWAYS = new Set(["gw.hello", "gw.resync", "gw.error", "pong"]);

  function replayed(messages: object[]): number[] {
    let topics = new Set<string>();
    const sent: number[] = [];
    for (const raw of messages) {
      const m = raw as Message;
      if (m.type === "subscribe") topics = new Set(m.topics ?? []);
      if (m.type === "resume") {
        for (const e of buffered) if (e.seq > m.last_seq! && (ALWAYS.has(e.type) || topics.has(e.type))) sent.push(e.seq);
      }
    }
    return sent;
  }

  it("replays the gap under a replacing subscription", () => {
    expect(replayed(greetingMessages(23, ["BTC/IDR"]))).toEqual([24, 25, 26]);
  });

  it("subscribes before resuming and skips resume on the first connection", () => {
    expect(greetingMessages(23, []).map((m) => (m as Message).type)).toEqual(["subscribe", "resume"]);
    expect(greetingMessages(null, ["ETH/IDR"])).toEqual([
      { type: "subscribe", topics: [...FEED_TOPICS], candles: [{ pair: "ETH/IDR", timeframe: "1h", limit: 300 }] },
    ]);
  });
});

describe("safety state", () => {
  it("puts a stopped bot ahead of the risk gate", () => {
    expect(safetyOf(health("stopped"), risk(false))).toBe("berhenti");
    expect(safetyOf(health("running"), risk(false))).toBe("ditahan");
    expect(safetyOf(health("running"), risk(true))).toBe("aman");
    expect(safetyOf(null, risk(true))).toBeNull();
  });
});

describe("snapshot loading", () => {
  const ok = (path: string): unknown => {
    if (path.startsWith("/gw/v1/health")) return health("running");
    if (path.startsWith("/gw/v1/overview")) return { mode: "dry_run", as_of: "2026-10-25T17:08:00Z" };
    if (path.startsWith("/gw/v1/risk")) return risk(true);
    if (path.startsWith("/gw/v1/trades")) return [{ trade_id: 1, is_open: false }];
    if (path.startsWith("/gw/v1/logs")) return { logs: [["2026-10-25 17:36:56", 0, "freqtrade.worker", "INFO", "Bot heartbeat"]] };
    return [];
  };
  const getter = (failing: string) =>
    (<T>(path: string): Promise<T> =>
      path.startsWith(failing) ? Promise.reject(new ApiError(404, "not_found", "missing")) : Promise.resolve(ok(path) as T));

  it("keeps the safety core when an optional panel endpoint fails", async () => {
    const snap = await loadSnapshot(getter("/gw/v1/decisions"), () => 5);
    expect(safetyOf(snap.core!.health, snap.core!.risk)).toBe("aman");
    expect(snap.coreFault).toBeNull();
    expect(snap.panelFaults).toEqual({ decisions: { code: "not_found", message: "missing", at: 5 } });
    expect(snap.panels.closed).toEqual([{ trade_id: 1, is_open: false }]);
    expect(snap.panels.logs?.[0]).toEqual({ ts: "2026-10-25 17:36:56", logger: "freqtrade.worker", level: "INFO", message: "Bot heartbeat" });
  });

  it("reports a core fault without inventing a safety state", async () => {
    const snap = await loadSnapshot(getter("/gw/v1/risk"), () => 7);
    expect(snap.core).toBeNull();
    expect(snap.coreFault).toEqual({ code: "not_found", message: "missing", at: 7 });
    expect(snap.panelFaults).toEqual({});
  });
});

describe("dry-run label", () => {
  it("is added only when the mode is known to be dry-run", () => {
    const event = { type: "entry_fill", seq: 1, ts: "", data: { pair: "BTC/IDR", open_rate: 1, stake_amount: 1 } };
    expect(feedText(event, true)?.text).toMatch(/\(dry-run\)$/);
    expect(feedText(event, false)?.text).not.toMatch(/dry-run/);
  });
});

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("turns a non-JSON proxy error page into an ApiError", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>502 Bad Gateway</html>", { status: 502 }));
    const api = createApi("http://gw", () => "t", () => undefined);
    await expect(api.get("/gw/v1/health")).rejects.toMatchObject({ status: 502, code: "http_502" });
  });

  it("rejects a non-JSON success body instead of throwing SyntaxError", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>login</html>", { status: 200 }));
    const api = createApi("http://gw", () => "t", () => undefined);
    await expect(api.get("/gw/v1/health")).rejects.toBeInstanceOf(ApiError);
  });
});
