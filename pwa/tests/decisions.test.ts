import { describe, expect, it } from "vitest";
import { actionLabel, auditPath, changeLines, isProblem, matches } from "../src/lib/audit";
import { decisionsPath, outcomeView } from "../src/lib/decisions";
import type { AuditRow, DecisionOutcome } from "../src/lib/types";

const price = (o: Partial<DecisionOutcome>): DecisionOutcome => ({
  state: "settled",
  basis: "price",
  horizon_h: 4,
  price_at: 100,
  price_after: 101,
  return_pct: 1,
  return_after_fees_pct: 0.6,
  trade_id: null,
  is_open: null,
  profit_abs: null,
  profit_pct: null,
  settles_at: "2026-10-25T21:00:00Z",
  ...o,
});

describe("outcome after a decision", () => {
  it("shows the after-fee return of a skipped entry as a hypothetical", () => {
    const v = outcomeView(price({}))!;
    expect(v.settled).toBe(true);
    expect(v.value).toBe(0.6);
    expect(v.note).toMatch(/bukan trade/);
  });

  it("marks pending and missing horizons as not enough data, without a number", () => {
    expect(outcomeView(price({ state: "pending", return_after_fees_pct: null }))).toMatchObject({ settled: false, value: null, headline: "Dilewati, belum cukup data" });
    expect(outcomeView(price({ state: "insufficient_data", return_after_fees_pct: null }))).toMatchObject({ settled: false, value: null });
  });

  it("uses the real trade when the bot entered, and never calls an open trade settled", () => {
    const trade = price({ basis: "trade", trade_id: 12, is_open: false, profit_pct: -0.4, profit_abs: -1333 });
    expect(outcomeView(trade)).toMatchObject({ settled: true, value: -0.4 });
    expect(outcomeView({ ...trade, is_open: true, state: "pending" })).toMatchObject({ settled: false, value: -0.4 });
    expect(outcomeView(undefined)).toBeNull();
  });

  it("builds paging and filter queries from the contract", () => {
    expect(decisionsPath("skip", "2026-10-25T17:02:05Z", "B", 30)).toBe("/gw/v1/decisions?limit=30&status=skip&before=2026-10-25T17%3A02%3A05Z&bot=B");
    expect(decisionsPath("semua", null, null)).toBe("/gw/v1/decisions?limit=30");
  });
});

describe("audit", () => {
  const row: AuditRow = {
    id: 9,
    ts: "2026-10-26T02:00:00Z",
    actor: "owner",
    ip: "127.0.0.1",
    action: "provider.update",
    targets: ["nutaraline"],
    idempotency_key: null,
    result: "ok",
    detail: { changes: [{ key: "providers[nutaraline].api_key", old: null, new: "<set>" }, { key: "risk.max_open_trades", old: 3, new: 2 }] },
  };

  it("shows key changes only as set or empty", () => {
    expect(changeLines(row)).toEqual([
      { key: "providers[nutaraline].api_key", old: "kosong", new: "terpasang" },
      { key: "risk.max_open_trades", old: "3", new: "2" },
    ]);
  });

  it("filters by action prefix and result, and pages by id", () => {
    expect(matches(row, "provider.", "")).toBe(true);
    expect(matches(row, "config.", "")).toBe(false);
    expect(matches(row, "", "denied")).toBe(false);
    expect(matches(row, "", "", "nutaraline")).toBe(true);
    expect(matches(row, "", "", "A")).toBe(false);
    expect(auditPath("control.", "forbidden", 120, 50, "B")).toBe("/gw/v1/audit?limit=50&action=control.&result=forbidden&target=B&before_id=120");
  });

  it("names ZHA-3774 actions and flags only results that need attention", () => {
    expect(actionLabel("control.stop_entry")).toBe("Hentikan entry baru");
    expect(actionLabel("trade.exit_all")).toBe("Exit paksa semua");
    expect(actionLabel("pair.unblacklist")).toBe("Hapus dari blacklist");
    for (const result of ["ok", "confirmation_required", "replayed"]) expect(isProblem({ ...row, result })).toBe(false);
    for (const result of ["failed", "rejected", "forbidden", "denied", "invalid"]) expect(isProblem({ ...row, result })).toBe(true);
  });
});
