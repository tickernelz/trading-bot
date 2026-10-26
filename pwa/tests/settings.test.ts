import { describe, expect, it } from "vitest";
import { anyNeedsConfirmation, diff, direction, flatten, needsConfirmation, patchBody, schemaErrors, EDITABLE, validate, validateVoter } from "../src/lib/settings";
import type { Settings } from "../src/lib/types";

function base(): Settings {
  const voter = (id: string) => ({ id, adapter: "llm_structured" as const, provider: "nutaraline", model: "deepseek-v4.1-flash-1017", variation: "option_order" as const, timeout_s: 30, weight: 1, enabled: true });
  return {
    mode: "dry_run",
    capital: { initial_idr: 2000000, compounding: true },
    risk: { max_daily_loss_pct: 1, max_total_drawdown_pct: 10, risk_per_trade_pct: 0.5, max_open_trades: 3, leverage: "none", on_breach: "stop_new_entries", daily_reset_timezone: "Asia/Jakarta" },
    exchange: { name: "indodax", pairs: ["BTC/IDR", "ETH/IDR"], timeframe: "1h", fee_pct: 0.2 },
    providers: [{ id: "nutaraline", type: "openai-completions", base_url: "from_import", api_key_env: "NUTARALINE_API_KEY", api_key: null, models: ["deepseek-v4.1-flash-1017"] }],
    swarm: { enabled: true, mode: "shadow", shuffle_options: true, min_voters_answered: 2, max_spread: null, voters: [voter("v1"), voter("v2"), voter("v3")] },
    llm: { backend: "deepagents", analyst_model: "nutaraline:deepseek-v4.1-flash-1017" },
    compute: { max_cost_idr_per_day: false, on_exceed: "skip_new_entries", log_cost: true },
    data: { news_rss: ["coindesk"], fear_greed: true, social: false },
    notify: { web_push: true },
    api: { force_entry: false },
  };
}

describe("settings keys", () => {
  it("flattens like the gateway audit: ids for object lists, plain lists as values", () => {
    const flat = flatten(base());
    expect(flat["risk.max_daily_loss_pct"]).toBe(1);
    expect(flat["swarm.voters[v2].enabled"]).toBe(true);
    expect(flat["exchange.pairs"]).toEqual(["BTC/IDR", "ETH/IDR"]);
    expect(flat["compute.max_cost_idr_per_day"]).toBe(false);
  });

  it("diffs only keys the settings route may change, never voters, providers, mode or api", () => {
    const next = base();
    next.risk.max_daily_loss_pct = 0.8;
    next.exchange.pairs = ["BTC/IDR"];
    next.swarm.voters[0].enabled = false;
    next.providers = [];
    next.mode = "live";
    next.api = { force_entry: true };
    expect(diff(base(), next)).toEqual([
      { key: "risk.max_daily_loss_pct", old: 1, new: 0.8 },
      { key: "exchange.pairs", old: ["BTC/IDR", "ETH/IDR"], new: ["BTC/IDR"] },
    ]);
    for (const key of EDITABLE) expect(key.split(".")[0]).not.toMatch(/^(mode|bot_id|api|shadow|providers)$/);
  });

  it("builds the nested changes body 2b merges, replacing lists whole", () => {
    expect(
      patchBody([
        { key: "risk.max_daily_loss_pct", old: 1, new: 0.8 },
        { key: "risk.max_open_trades", old: 3, new: 2 },
        { key: "exchange.pairs", old: ["BTC/IDR"], new: ["BTC/IDR", "ETH/IDR"] },
        { key: "compute.max_cost_idr_per_day", old: false, new: 50000 },
      ]),
    ).toEqual({ risk: { max_daily_loss_pct: 0.8, max_open_trades: 2 }, exchange: { pairs: ["BTC/IDR", "ETH/IDR"] }, compute: { max_cost_idr_per_day: 50000 } });
  });
});

describe("two-step rule mirrors raising_keys of 2b", () => {
  it("asks for confirmation when a risk limit or the capital rises, never when they fall", () => {
    expect(direction({ key: "risk.max_daily_loss_pct", old: 1, new: 1.5 })).toBe("up");
    expect(direction({ key: "risk.max_open_trades", old: 3, new: 2 })).toBe("down");
    expect(needsConfirmation({ key: "capital.initial_idr", old: 2000000, new: 3000000 })).toBe(true);
    expect(needsConfirmation({ key: "capital.initial_idr", old: 2000000, new: 1500000 })).toBe(false);
    expect(needsConfirmation({ key: "swarm.mode", old: "shadow", new: "veto" })).toBe(false);
    expect(anyNeedsConfirmation([{ key: "risk.max_daily_loss_pct", old: 1, new: 0.8 }, { key: "risk.max_open_trades", old: 3, new: 4 }])).toBe(true);
    expect(anyNeedsConfirmation([{ key: "risk.max_daily_loss_pct", old: 1, new: 0.8 }])).toBe(false);
  });
});

describe("schema errors from the gateway", () => {
  it("maps loc: message parts onto known fields and keeps the rest for the banner", () => {
    const out = schemaErrors("risk.max_daily_loss_pct: Input should be less than or equal to 100; risk: Value error, risk_per_trade_pct must not exceed max_daily_loss_pct", EDITABLE);
    expect(out.fields).toEqual([{ key: "risk.max_daily_loss_pct", message: "Input should be less than or equal to 100" }]);
    expect(out.rest).toEqual(["risk: Value error, risk_per_trade_pct must not exceed max_daily_loss_pct"]);
  });
});

describe("validation mirrors engine/settings.py", () => {
  it("accepts the example configuration", () => {
    expect(validate(base(), 3)).toEqual([]);
  });

  it("enforces percent bounds and limit ordering", () => {
    const s = base();
    s.risk.risk_per_trade_pct = 2;
    expect(validate(s, 3).map((e) => e.key)).toEqual(["risk.risk_per_trade_pct"]);
    s.risk.risk_per_trade_pct = 0.5;
    s.risk.max_daily_loss_pct = 12;
    expect(validate(s, 3).map((e) => e.key)).toEqual(["risk.max_daily_loss_pct"]);
    s.risk.max_daily_loss_pct = 0;
    expect(validate(s, 3).map((e) => e.key)).toEqual(["risk.max_daily_loss_pct"]);
    s.risk.max_daily_loss_pct = 1;
    s.risk.max_open_trades = 2.5;
    expect(validate(s, 3).map((e) => e.key)).toEqual(["risk.max_open_trades"]);
  });

  it("rejects a quorum larger than the enabled voters only while swarm is on", () => {
    const s = base();
    expect(validate(s, 1).map((e) => e.key)).toEqual(["swarm.min_voters_answered"]);
    s.swarm.enabled = false;
    expect(validate(s, 1)).toEqual([]);
  });

  it("requires unique IDR pairs and a positive cost cap when set", () => {
    const s = base();
    s.exchange.pairs = ["BTC/USDT"];
    s.compute.max_cost_idr_per_day = 0;
    expect(validate(s, 3).map((e) => e.key)).toEqual(["exchange.pairs", "compute.max_cost_idr_per_day"]);
  });

  it("checks a voter against the provider list, its id, timeout and weight", () => {
    const s = base();
    const v = { adapter: "llm_structured" as const, provider: "nutaraline", model: "deepseek-v4.1-flash-1017", variation: "option_order" as const, timeout_s: 30, weight: 1, enabled: true };
    expect(validateVoter("v4", v, s.providers, ["v1", "v2", "v3"])).toEqual([]);
    expect(validateVoter("v1", v, s.providers, ["v1", "v2", "v3"]).map((e) => e.key)).toEqual(["id"]);
    expect(validateVoter("V4", { ...v, model: "other", timeout_s: 0, weight: 0 }, s.providers, []).map((e) => e.key)).toEqual(["id", "model", "timeout_s", "weight"]);
    expect(validateVoter("v4", { ...v, provider: "ghost" }, s.providers, []).map((e) => e.key)).toEqual(["provider"]);
  });
});
