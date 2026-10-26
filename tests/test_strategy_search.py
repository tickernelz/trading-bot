from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from engine import search_metrics as metrics
from engine import search_plan as plan
from engine import strategy_search
from engine.rules import RuleSpec
from engine.signals import resample, rule_frame
from engine.simulate import Costs, Exits, exits_for, simulate

COSTS = Costs(buy=0.0020555, sell=0.0041555)
START = pd.Timestamp("2025-01-01", tz="UTC")


def candles(closes, highs=None, lows=None, opens=None) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    opens = np.asarray(opens if opens is not None else closes, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.date_range(START, periods=len(closes), freq="1h"),
            "open": opens,
            "high": np.asarray(highs if highs is not None else np.maximum(opens, closes), dtype=float),
            "low": np.asarray(lows if lows is not None else np.minimum(opens, closes), dtype=float),
            "close": closes,
            "volume": np.ones(len(closes)),
        }
    )


def flags(n: int, *indexes: int) -> np.ndarray:
    out = np.zeros(n, dtype=bool)
    out[list(indexes)] = True
    return out


def run(frame, enter, exit_signal=None, exits=Exits(stoploss=-0.1), atr=None):
    n = len(frame)
    exit_signal = flags(n) if exit_signal is None else exit_signal
    atr = np.full(n, np.nan) if atr is None else atr
    return simulate("BTC/IDR", frame, enter, exit_signal, atr, exits, COSTS)


def test_signal_at_close_fills_at_next_open_and_exit_signal_at_the_open_after():
    frame = candles([100, 100, 100, 110, 120], opens=[100, 100, 105, 110, 118])
    [trade] = run(frame, flags(5, 1), flags(5, 3))
    assert (trade.entry_price, trade.exit_price, trade.reason) == (105, 118, "exit_signal")
    assert trade.entry_time == frame["date"][2] and trade.exit_time == frame["date"][4]


def test_profit_ratio_charges_buy_and_sell_costs_separately():
    assert COSTS.profit_ratio(100, 100) == pytest.approx(100 * (1 - 0.0041555) / (100 * 1.0020555) - 1)
    assert COSTS.profit_ratio(100, 100.62) < 0 < COSTS.profit_ratio(100, 100.63)


def test_stop_gapping_through_fills_at_the_open_not_the_stop():
    frame = candles([100, 100, 100, 80], opens=[100, 100, 100, 85], lows=[100, 100, 99, 79])
    [trade] = run(frame, flags(4, 1))
    assert (trade.exit_price, trade.reason) == (85, "stoploss")


def test_stop_wins_when_stop_and_target_share_a_candle():
    frame = candles([100, 100, 100, 100], highs=[100, 100, 100, 104], lows=[100, 100, 100, 89])
    [trade] = run(frame, flags(4, 1), exits=Exits(stoploss=-0.1, roi=((0, 0.03),)))
    assert (trade.exit_price, trade.reason) == (90, "stoploss")


def test_gross_target_fills_at_target_price():
    frame = candles([100, 100, 100, 100], highs=[100, 100, 101, 104])
    [trade] = run(frame, flags(4, 1), exits=Exits(stoploss=-0.1, roi=((0, 0.03),)))
    assert (trade.exit_price, trade.reason) == (pytest.approx(103), "roi")


def test_net_of_fee_roi_target_matches_freqtrade_formula():
    frame = candles([100, 100, 100, 100], highs=[100, 100, 100, 110])
    [trade] = run(frame, flags(4, 1), exits=Exits(stoploss=-0.1, roi=((0, 0.05),), roi_net_of_fee=True))
    fee = (COSTS.buy + COSTS.sell) / 2
    assert trade.exit_price == pytest.approx(100 * (1 + fee) * 1.05 / (1 - fee))


def test_open_trade_closes_at_last_close():
    frame = candles([100, 100, 101, 102])
    [trade] = run(frame, flags(4, 1))
    assert (trade.exit_price, trade.reason) == (102, "end")


def test_no_reentry_on_the_candle_of_an_exit():
    frame = candles([100] * 6)
    trades = run(frame, flags(6, 1, 2, 3), flags(6, 2))
    assert [trade.entry_time for trade in trades] == [frame["date"][2], frame["date"][4]]


def spec(**fields) -> RuleSpec:
    base = {"entry": "donchian", "timeframe": "1h", "lookback": 3, "exit": "none", "stoploss": -0.5}
    return RuleSpec(**{**base, **fields})


def test_lock_exits_after_giving_back_half_of_the_lock_level():
    frame = candles([100, 100, 100, 104, 101.5, 101.5])
    [trade] = run(frame, flags(6, 1), exits=exits_for(spec(lock_at=0.04)))
    assert (trade.reason, trade.exit_time) == ("lock", frame["date"][5])


def test_time_stop_counts_hours_from_the_entry_open():
    frame = candles([100] * 8)
    [trade] = run(frame, flags(8, 1), exits=exits_for(spec(max_hold_hours=3)))
    assert (trade.reason, trade.exit_time - trade.entry_time) == ("time", pd.Timedelta(hours=3))


def test_trailing_stop_uses_highest_close_minus_atr_multiple():
    frame = candles([100, 100, 110, 108, 104, 104])
    atr = np.full(6, 2.0)
    [trade] = run(frame, flags(6, 0), exits=exits_for(spec(trail_atr=2.5)), atr=atr)
    assert (trade.reason, trade.exit_time) == ("trail", frame["date"][5])


def test_atr_target_and_stop_use_the_atr_of_the_signal_candle():
    rule = spec(take_profit_atr=1.5, stop_atr=2.0, stoploss=-0.2)
    atr = np.array([2.0, 50.0, 50.0, 50.0])
    target = candles([100, 100, 100, 100], highs=[100, 100, 102.9, 104])
    [won] = run(target, flags(4, 0), exits=exits_for(rule), atr=atr)
    assert (won.exit_price, won.reason, won.exit_time) == (pytest.approx(103), "roi", target["date"][3])
    stop = candles([100, 100, 100, 100], lows=[100, 96.5, 100, 95])
    [lost] = run(stop, flags(4, 0), exits=exits_for(rule), atr=atr)
    assert (lost.exit_price, lost.reason, lost.exit_time) == (96, "stoploss", stop["date"][3])


def test_atr_stop_never_loosens_the_hard_stoploss():
    rule = spec(stop_atr=3.0, stoploss=-0.05)
    assert rule.stop_price(100.0, 10.0) == pytest.approx(95.0)
    assert rule.stop_price(100.0, 1.0) == pytest.approx(97.0)
    assert rule.stop_price(100.0, float("nan")) == pytest.approx(95.0)
    assert rule.atr_target(100.0, float("nan")) is None


@pytest.mark.parametrize(
    "fields",
    [{"take_profit": 0.03, "take_profit_atr": 1.0}, {"take_profit_atr": 1.0, "lock_at": 0.02}],
)
def test_conflicting_exit_fields_are_rejected(fields):
    with pytest.raises(ValueError):
        spec(**fields)


def test_trend_filter_compares_the_daily_close_with_the_configured_sma():
    frame = daily_walk(260, seed=4)
    daily = {"1d": resample(frame, "1d")}
    entries = {
        trend: rule_frame(frame, spec(entry="tsmom", lookback=5, exit="none", trend_filter=trend), daily)["enter"]
        for trend in ("none", "above_sma50_1d", "above_sma200_1d")
    }
    assert entries["above_sma50_1d"].sum() < entries["none"].sum()
    assert not entries["above_sma200_1d"].iloc[: 200 * 24].any()
    assert not entries["above_sma50_1d"].iloc[: 50 * 24].any()
    assert entries["above_sma50_1d"].iloc[50 * 24 : 200 * 24].any()


def daily_walk(days: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, days * 24)))
    frame = candles(closes)
    frame["high"] = frame["close"] * 1.002
    frame["low"] = frame["close"] * 0.998
    return frame


@pytest.mark.parametrize(
    "rule",
    [
        spec(timeframe="1d", lookback=5, exit="donchian_mid", exit_lookback=5),
        spec(entry="rsi_dip", timeframe="4h", lookback=2, threshold=20, exit="sma_reclaim", exit_lookback=5),
        spec(entry="ema_trend", timeframe="4h", lookback=14, fast=5, slow=10, exit="ema_cross", trail_atr=2.0),
        spec(entry="tsmom", timeframe="1d", lookback=5, exit="tsmom_flip", trend_filter="above_sma200_1d"),
        spec(timeframe="1d", lookback=5, exit="donchian_mid", exit_lookback=5, trend_filter="above_sma50_1d"),
        spec(timeframe="1d", lookback=5, exit="donchian_mid", exit_lookback=5, trend_filter="btc_above_sma100_1d"),
    ],
)
def test_signals_never_change_when_later_candles_are_added(rule):
    frame = daily_walk(260)
    btc = daily_walk(260, seed=9)

    def informative(part: pd.DataFrame, btc_part: pd.DataFrame) -> dict:
        out = {tf: resample(part, tf) for tf in rule.informative_timeframes}
        return out | ({"btc": resample(btc_part, "1d")} if rule.trend_on_btc else {})

    full = rule_frame(frame, rule, informative(frame, btc))
    for cut in (24 * 230 + 5, 24 * 240 + 23, 24 * 250 + 11):
        part = frame.iloc[:cut].reset_index(drop=True)
        cut_frame = rule_frame(part, rule, informative(part, btc.iloc[:cut].reset_index(drop=True)))
        pd.testing.assert_frame_equal(cut_frame.tail(48), full.iloc[:cut].tail(48))


def test_btc_regime_gate_reads_btc_not_the_traded_pair():
    pair = daily_walk(260, seed=4)
    rising, falling = pair.copy(), pair.copy()
    rising["close"] = rising["open"] = np.linspace(100, 300, len(pair))
    falling["close"] = falling["open"] = np.linspace(300, 100, len(pair))
    for frame in (rising, falling):
        frame["high"], frame["low"] = frame["close"] * 1.002, frame["close"] * 0.998
    rule = spec(entry="tsmom", lookback=5, exit="none", trend_filter="btc_above_sma100_1d")
    gated = {"1d": resample(pair, "1d")}
    up = rule_frame(pair, rule, gated | {"btc": resample(rising, "1d")})["enter"]
    down = rule_frame(pair, rule, gated | {"btc": resample(falling, "1d")})["enter"]
    assert up.iloc[24 * 110 :].sum() > 0 and down.iloc[24 * 110 :].sum() == 0


def test_daily_feature_is_known_only_from_the_last_hour_of_its_day():
    frame = candles(np.linspace(200, 100, 24 * 30))
    frame.loc[frame.index[24 * 20 + 23], ["close", "high"]] = 1_000.0
    rule = spec(entry="tsmom", timeframe="1d", lookback=2, exit="tsmom_flip")
    enter = rule_frame(frame, rule, {"1d": resample(frame, "1d")})["enter"]
    assert enter.iloc[24 * 20 + 23] and not enter.iloc[24 * 20 + 22]


def gross_mean(trades) -> float:
    return float(np.mean([trade.profit(Costs(0, 0)) for trade in trades]))


def test_shifting_the_signal_into_the_future_is_detected_as_an_edge():
    frame = daily_walk(120, seed=7)
    rule = spec(entry="donchian", timeframe="1h", lookback=24, exit="none", max_hold_hours=12)
    signals = rule_frame(frame, rule, {})
    honest = simulate(
        "BTC/IDR",
        frame,
        signals["enter"].to_numpy(),
        signals["exit_signal"].to_numpy(),
        signals["atr"].to_numpy(),
        exits_for(rule),
        Costs(0, 0),
    )
    cheat_enter = np.concatenate([signals["enter"].to_numpy()[24:], np.zeros(24, dtype=bool)])
    cheat = simulate(
        "BTC/IDR",
        frame,
        cheat_enter,
        signals["exit_signal"].to_numpy(),
        signals["atr"].to_numpy(),
        exits_for(rule),
        Costs(0, 0),
    )
    assert gross_mean(cheat) > gross_mean(honest) + 0.002


def test_peeking_at_the_fill_candle_is_detected_for_a_dip_buyer():
    frame = daily_walk(120, seed=11)
    frame["open"] = frame["close"].shift(1).fillna(frame["close"].iloc[0])
    rule = spec(
        entry="rsi_dip", timeframe="1h", lookback=14, threshold=35, exit="none", take_profit=0.01, stoploss=-0.05
    )
    signals = rule_frame(frame, rule, {})
    item = strategy_search.Signals(
        frame,
        signals["enter"].to_numpy(),
        signals["exit_signal"].to_numpy(),
        signals["atr"].to_numpy(),
        exits_for(rule),
    )
    honest = strategy_search.trades_of({"BTC/IDR": item}, Costs(0, 0))
    cheat = strategy_search.trades_of(strategy_search.peeked({"BTC/IDR": item}), Costs(0, 0))
    assert gross_mean(cheat) > gross_mean(honest) + 0.002


def test_wilson_lower_bound_matches_reference_values():
    assert metrics.wilson_lower(60, 100) == pytest.approx(0.5020, abs=1e-4)
    assert metrics.wilson_lower(0, 0) == 0.0


def test_bootstrap_ci_is_reproducible_with_the_locked_seed():
    values = np.linspace(-0.02, 0.03, 57)
    assert metrics.bootstrap_ci(values) == metrics.bootstrap_ci(values)
    low, high = metrics.bootstrap_ci(values)
    assert low < values.mean() < high


@pytest.mark.parametrize(
    ("met", "mean", "ci_low", "beaten", "expected"),
    [
        (False, 0.01, 0.005, True, "T4"),
        (True, -0.001, -0.01, True, "T3"),
        (True, 0.01, -0.001, True, "T2"),
        (True, 0.01, 0.002, False, "T2"),
        (True, 0.01, 0.002, True, "T1"),
    ],
)
def test_tiers_follow_the_locked_definitions(met, mean, ci_low, beaten, expected):
    assert metrics.tier(met, mean, ci_low, beaten) == expected


def row(profit: float, hour: int, pair: str = "BTC/IDR", regime: str = "bull", fold: str | None = "F1"):
    time = START + pd.Timedelta(hours=hour)
    return metrics.Row(pair, time, time, time, profit, "roi", regime, fold)


def test_target_fails_when_one_fold_drops_below_half_even_if_pooled_rate_is_high():
    rows = [row(0.01, i, pair=("BTC/IDR", "ETH/IDR")[i % 2], fold=f"F{1 + i % 8}") for i in range(160)]
    rows += [row(-0.01, 500 + i, fold="F8") for i in range(25)]
    checks = metrics.target_checks(rows, rows, [rows])
    assert checks["a_win_rate"] and not checks["b_folds"] and not checks["met"]


def test_target_needs_two_pairs_with_trades():
    rows = [row(0.01, i, fold=f"F{1 + i % 8}") for i in range(200)]
    assert not metrics.target_checks(rows, rows, [rows])["a_win_rate"]


def test_drawdown_sizes_each_trade_by_the_stop_distance():
    rows = [row(-0.10, 0), row(-0.10, 1)]
    loss = 0.005 / (1.0031 - 0.9 * 0.9969) * 0.10
    expected = 1 - (1 - loss) ** 2
    assert metrics.max_drawdown(rows, -0.10, 0.0031) == pytest.approx(expected)


def test_an_entry_refused_for_lack_of_slots_frees_no_slot_it_never_held():
    def held(profit: float, entry: int, exit_: int) -> metrics.Row:
        start = pd.Timestamp("2025-01-01", tz="UTC")
        hours = pd.Timedelta(hours=1)
        return metrics.Row("BTC/IDR", start, start + entry * hours, start + exit_ * hours, profit, "roi", "bull", "F1")

    open_three = [held(0.0, 0, 10), held(0.0, 1, 11), held(0.0, 2, 3)]
    refused, fifth = held(0.0, 2, 20), held(-0.10, 4, 5)
    loss = 0.005 / (1.0031 - 0.9 * 0.9969) * 0.10
    assert metrics.max_drawdown([*open_three, refused, fifth], -0.10, 0.0031) == pytest.approx(loss)


def day_row(profit: float, entry: int, exit_: int, pair: str = "BTC/IDR") -> metrics.Row:
    start = pd.Timestamp("2025-01-01 01:00", tz="UTC")
    hours = pd.Timedelta(hours=1)
    return metrics.Row(
        pair, start + (entry - 1) * hours, start + entry * hours, start + exit_ * hours, profit, "x", "bull", "F1"
    )


LIMITS = metrics.Limits(0.01, 0.10, "Asia/Jakarta")


def test_daily_loss_limit_refuses_entries_until_the_next_jakarta_day():
    stops = [day_row(-0.11, 1, 2), day_row(-0.11, 3, 4), day_row(0.02, 6, 7), day_row(0.02, 18, 19)]
    research = metrics.portfolio(stops, -0.10, 0.0031)
    jakarta = metrics.portfolio(stops, -0.10, 0.0031, LIMITS)
    utc = metrics.portfolio(stops, -0.10, 0.0031, metrics.Limits(0.01, 0.10, "UTC"))
    assert research["taken"] == [0, 1, 2, 3] and research["refused_limits"] == 0
    assert jakarta["taken"] == [0, 1, 3] and jakarta["refused_limits"] == 1
    assert utc["taken"] == [0, 1] and utc["refused_limits"] == 2


def test_open_losses_count_toward_the_limits_at_the_signal_candle():
    rows = [day_row(-0.10, 1, 20), day_row(-0.10, 2, 20), day_row(0.02, 5, 6)]
    deep = metrics.portfolio(rows, -0.10, 0.0031, LIMITS, lambda row, time: -0.11)
    flat = metrics.portfolio(rows, -0.10, 0.0031, LIMITS, lambda row, time: 0.0)
    assert deep["taken"] == [0, 1] and flat["taken"] == [0, 1, 2]


def test_worst_month_is_the_largest_realised_monthly_loss_of_the_account():
    rows = [day_row(-0.10, 1, 2), day_row(0.05, 24 * 40, 24 * 40 + 1)]
    loss = 0.005 / (1.0031 - 0.9 * 0.9969) * 0.10
    assert metrics.portfolio(rows, -0.10, 0.0031)["worst_month"] == pytest.approx(-loss)


def test_monthly_profit_compounds_the_final_equity_over_the_months():
    assert metrics.monthly_profit_idr(1.0, 12) == 0
    assert metrics.monthly_profit_idr(1.01**12, 12) == pytest.approx(plan.CAPITAL_IDR * 0.01)
    assert metrics.monthly_profit_idr(0.0, 12) == -plan.CAPITAL_IDR
    rows = [day_row(0.10, 1, 2), day_row(0.10, 3, 4)]
    low, high = metrics.portfolio(rows, -0.10, 0.0031), metrics.portfolio(rows, -0.10, 0.0031, risk=0.02)
    assert 1 < low["final_equity"] < high["final_equity"]


def test_cross_asset_ranking_puts_tier_before_monthly_profit_before_drawdown():
    def entry(cid, tier, monthly, drawdown):
        summary = {"monthly_profit_idr": monthly, "max_drawdown": drawdown}
        return {"id": cid, "tier": tier, "costs": {plan.PRIMARY_COST: {"all": summary}}}

    entries = [
        entry("a", "T3", 0.9, 0.01),
        entry("b", "T2", 0.6, 0.2),
        entry("c", "T2", 0.7, 0.3),
        entry("d", "T2", 0.7, 0.1),
    ]
    assert [item["id"] for item in sorted(entries, key=strategy_search.cross_rank_key)] == ["d", "c", "b", "a"]


def test_rounds_stay_within_the_search_budget_and_ids_are_unique():
    rounds = [plan.round1_candidates(), plan.round2_candidates(), plan.round3_candidates(), plan.candidates()]
    ids = [[candidate.id for candidate in matrix] for matrix in rounds]
    benchmarks = {"K-SwingEmaRsi", "K-buy-and-hold"}
    assert all(len(matrix) == len(set(matrix)) for matrix in ids)
    assert all(not (set(a) & set(b)) - benchmarks for i, a in enumerate(ids) for b in ids[i + 1 :])
    assert plan.cumulative_trials() == sum(map(len, ids)) <= plan.SEARCH_BUDGET
    assert set(plan.all_candidates()) == set().union(*ids)


def test_adjusted_lower_bound_widens_with_the_number_of_trials():
    values = np.random.default_rng(1).normal(0.01, 0.05, 200)
    one, many = metrics.adjusted_lower(values, 1), metrics.adjusted_lower(values, 150)
    assert one == pytest.approx(values.mean() - 1.959964 * values.std(ddof=1) / np.sqrt(200), rel=1e-5)
    assert many < one


def search_dirs(tmp_path, pairs):
    datadir = tmp_path / "data"
    datadir.mkdir(exist_ok=True)
    for pair in pairs:
        strategy_search.pair_file(datadir, pair).write_bytes(pair.encode())
    fear_greed = tmp_path / "fg.json"
    fear_greed.write_text("{}", encoding="utf-8")
    return datadir, fear_greed


def ledger_kinds(path):
    return [line["kind"] for line in strategy_search.ledger_lines(path)]


def test_a_run_writes_its_started_line_before_reading_any_data(tmp_path, monkeypatch):
    datadir, fear_greed = search_dirs(tmp_path, plan.PAIRS)
    ledger = tmp_path / "ledger.jsonl"

    def killed(args, entry):
        assert ledger_kinds(ledger) == ["walk_forward_started"]
        raise KeyboardInterrupt

    monkeypatch.setitem(strategy_search.COMMANDS, "walk-forward", ("walk_forward", killed))
    argv = ["walk-forward", "--datadir", str(datadir), "--fear-greed", str(fear_greed), "--out", str(tmp_path / "o")]
    with pytest.raises(KeyboardInterrupt):
        strategy_search.main([*argv, "--ledger", str(ledger)])
    [line] = strategy_search.ledger_lines(ledger)
    assert line["status"] == "started" and set(line["data_sha256"]) == {*plan.PAIRS, "fear_greed"}


def test_controls_run_for_a_btc_gated_rule(tmp_path, monkeypatch):
    btc, eth = daily_walk(330, seed=2), daily_walk(330, seed=5)
    rule = spec(timeframe="1d", lookback=5, exit="donchian_mid", exit_lookback=5, trend_filter="btc_above_sma100_1d")
    gated = plan.Candidate("btc-gated", "test", "rule", rule)
    monkeypatch.setattr(plan, "candidates", lambda: [gated])
    monkeypatch.setattr(plan, "WALK_FORWARD_START", btc["date"].iloc[24 * 220])
    monkeypatch.setattr(plan, "HOLDOUT_START", btc["date"].iloc[-1] + pd.Timedelta(hours=1))
    monkeypatch.setattr(plan, "LOOKAHEAD_CUTS", 2)
    monkeypatch.setattr(strategy_search, "load_candles", lambda *a, **k: {"BTC/IDR": btc, "ETH/IDR": eth})
    monkeypatch.setattr(strategy_search, "load_fear_greed", lambda path: pd.DataFrame(columns=["date", "fg"]))
    [result] = strategy_search.controls(type("Args", (), {"datadir": tmp_path, "fear_greed": tmp_path})(), {})[
        "results"
    ]
    assert result["truncation_cuts"] == 4
    assert result["truncation_failures"] == 0 and result["live_window_entry_mismatches"] == 0


def test_a_second_run_with_the_same_output_name_is_refused_before_the_ledger(tmp_path):
    datadir, fear_greed = search_dirs(tmp_path, plan.PAIRS)
    out, ledger = tmp_path / "o", tmp_path / "ledger.jsonl"
    out.mkdir()
    (out / "walk-forward.json").write_text("{}", encoding="utf-8")
    argv = ["walk-forward", "--datadir", str(datadir), "--fear-greed", str(fear_greed), "--out", str(out)]
    with pytest.raises(SystemExit):
        strategy_search.main([*argv, "--ledger", str(ledger)])
    with pytest.raises(SystemExit):
        strategy_search.main([*argv, "--ledger", str(ledger), "--label", "walk-forward"])
    assert not ledger.exists()


@pytest.mark.parametrize("command,kind", [("holdout", "holdout_started"), ("presample", "presample")])
def test_second_run_on_an_untouched_period_is_refused_before_any_data_is_read(tmp_path, monkeypatch, command, kind):
    datadir, fear_greed = search_dirs(tmp_path, {*plan.PAIRS, *plan.ROUND1_PAIRS, *plan.PRESAMPLE_PAIRS})
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"kind": kind, "run_id": "r1", "candidate": "A"}) + "\n", encoding="utf-8")

    def reads_data(args, entry):
        raise AssertionError("data was read")

    monkeypatch.setitem(strategy_search.COMMANDS, command, (strategy_search.COMMANDS[command][0], reads_data))
    base = [command, "--datadir", str(datadir), "--wf-datadir", str(datadir), "--fear-greed", str(fear_greed)]
    base += ["--out", str(tmp_path / "o"), "--ledger", str(ledger), "--candidate"]
    assert strategy_search.main([*base, "B"]) == 3
    assert strategy_search.main([*base, "B", "--replay"]) == 3
    assert ledger_kinds(ledger) == [kind, command, f"{command}_replay"]


def test_replay_without_a_recorded_run_is_refused(tmp_path):
    args = type("Args", (), {"ledger": tmp_path / "ledger.jsonl", "replay": True, "candidate": "A"})()
    with pytest.raises(strategy_search.HoldoutUsed):
        strategy_search.single_run_guard(args, strategy_search.PRESAMPLE_KINDS, "presample")
