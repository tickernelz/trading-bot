import { describe, expect, it } from "vitest";
import { anyNeedsConfirmation, diff, direction, flatten, needsConfirmation, validate } from "../src/lib/settings";
import type { Settings } from "../src/lib/types";

function base(): Settings {
  const voter = (id: string) => ({ id, adapter: "llm_structured" as const, provider: "nutaraline", model: "deepseek-v4.1-flash-1017", variation: "option_order" as const, timeout_s: 30, weight: 1, enabled: true });
  return {
    mode: "dry_run",
    capital: { initial_idr: 2000000, compounding: true },
    risk: { max_daily_loss_pct: 1, max_total_drawdown_pct: 10, risk_per_trade_pct: 0.5, max_open_trades: 3, leverage: "none", on_breach: "stop_new_entries", daily_reset_timezone: "Asia/Jakarta" },
    exchange: { name: "indodax", pairs: ["BTC/IDR", "ETH/IDR"], timeframe: "1h", fee_pct: 0.2 },
    providers: [{ id: "nutaraline", type: "openai-completions", base_url: "from_import", api_key_env: "NUTARALINE_API_KEY", api_key: null, api_key_configured: true, models: ["deepseek-v4.1-flash-1017"] }],
    swarm: { enabled: true, mode: "shadow", shuffle_options: true, min_voters_answered: 2, max_spread: null, voters: [voter("v1"), voter("v2"), voter("v3")] },
    llm: { backend: "deepagents", analyst_model: "nutaraline:deepseek-v4.1-flash-1017" },
    compute: { max_cost_idr_per_day: false, on_exceed: "skip_new_entries", log_cost: true },
    data: { news_rss: ["coindesk"], fear_greed: true, social: false },
    notify: { web_push: true },
    api: { listen: "127.0.0.1", port: 8080, username_env: "FT_API_USERNAME", password_env: "FT_API_PASSWORD", jwt_secret_env: "FT_API_JWT_SECRET", ws_token_env: "FT_API_WS_TOKEN", force_entry: false },
  };
}

describe("settings keys", () => {
  it("flattens like the gateway audit: ids for object lists, plain lists as values", () => {
    const flat = flatten(base());
    expect(flat["risk.max_daily_loss_pct"]).toBe(1);
    expect(flat["swarm.voters[v2].enabled"]).toBe(true);
    expect(flat["providers[nutaraline].api_key"]).toBeNull();
    expect(flat["exchange.pairs"]).toEqual(["BTC/IDR", "ETH/IDR"]);
    expect(flat["compute.max_cost_idr_per_day"]).toBe(false);
  });

  it("reports only changed keys, including voters added and removed", () => {
    const next = base();
    next.risk.max_daily_loss_pct = 0.8;
    next.swarm.voters = next.swarm.voters.filter((v) => v.id !== "v3");
    next.swarm.voters.push({ ...next.swarm.voters[0], id: "v4" });
    const changes = diff(base(), next);
    expect(changes.find((c) => c.key === "risk.max_daily_loss_pct")).toEqual({ key: "risk.max_daily_loss_pct", old: 1, new: 0.8 });
    expect(changes.find((c) => c.key === "swarm.voters[v3].enabled")).toEqual({ key: "swarm.voters[v3].enabled", old: true, new: null });
    expect(changes.find((c) => c.key === "swarm.voters[v4].id")).toEqual({ key: "swarm.voters[v4].id", old: null, new: "v4" });
    expect(changes.some((c) => c.key.startsWith("swarm.voters[v1]"))).toBe(false);
  });
});

describe("risk direction", () => {
  it("treats a larger limit or more open trades as raising risk", () => {
    expect(direction({ key: "risk.max_daily_loss_pct", old: 1, new: 1.5 })).toBe("naik");
    expect(direction({ key: "risk.max_open_trades", old: 3, new: 2 })).toBe("turun");
    expect(direction({ key: "api.force_entry", old: false, new: true })).toBe("naik");
    expect(direction({ key: "swarm.mode", old: "shadow", new: "veto" })).toBe("netral");
  });

  it("asks for the second step exactly where risky_changes of ZHA-3774 does", () => {
    const lower = [{ key: "risk.max_daily_loss_pct", old: 1, new: 0.8 }];
    expect(anyNeedsConfirmation(lower)).toBe(false);
    expect(anyNeedsConfirmation([...lower, { key: "risk.max_open_trades", old: 3, new: 4 }])).toBe(true);
    expect(needsConfirmation({ key: "mode", old: "live", new: "dry_run" })).toBe(true);
    expect(needsConfirmation({ key: "api.force_entry", old: true, new: false })).toBe(false);
    expect(needsConfirmation({ key: "swarm.mode", old: "shadow", new: "veto" })).toBe(false);
  });
});

describe("validation mirrors engine/settings.py", () => {
  it("accepts the example configuration", () => {
    expect(validate(base())).toEqual([]);
  });

  it("enforces percent bounds and limit ordering", () => {
    const s = base();
    s.risk.risk_per_trade_pct = 2;
    expect(validate(s).map((e) => e.key)).toEqual(["risk.risk_per_trade_pct"]);
    s.risk.risk_per_trade_pct = 0.5;
    s.risk.max_daily_loss_pct = 12;
    expect(validate(s).map((e) => e.key)).toEqual(["risk.max_daily_loss_pct"]);
    s.risk.max_daily_loss_pct = 0;
    expect(validate(s).map((e) => e.key)).toEqual(["risk.max_daily_loss_pct"]);
    s.risk.max_daily_loss_pct = 1;
    s.risk.max_open_trades = 2.5;
    expect(validate(s).map((e) => e.key)).toEqual(["risk.max_open_trades"]);
  });

  it("rejects a quorum larger than the enabled voters only while swarm is on", () => {
    const s = base();
    s.swarm.voters[0].enabled = false;
    s.swarm.voters[1].enabled = false;
    expect(validate(s).map((e) => e.key)).toEqual(["swarm.min_voters_answered"]);
    s.swarm.enabled = false;
    expect(validate(s)).toEqual([]);
  });

  it("resolves voter and analyst references against the provider list", () => {
    const s = base();
    s.swarm.voters[1].model = "other";
    s.llm.analyst_model = "ghost:model";
    expect(validate(s).map((e) => e.key)).toEqual(["swarm.voters[v2].model", "llm.analyst_model"]);
  });

  it("requires unique IDR pairs and a positive cost cap when set", () => {
    const s = base();
    s.exchange.pairs = ["BTC/USDT"];
    s.compute.max_cost_idr_per_day = 0;
    expect(validate(s).map((e) => e.key)).toEqual(["exchange.pairs", "compute.max_cost_idr_per_day"]);
    s.exchange.pairs = ["BTC/IDR", "BTC/IDR"];
    expect(validate(s).find((e) => e.key === "exchange.pairs")?.message).toMatch(/ganda/);
  });
});
