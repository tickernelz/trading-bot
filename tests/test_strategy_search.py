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
    ],
)
def test_signals_never_change_when_later_candles_are_added(rule):
    frame = daily_walk(260)
    full = rule_frame(frame, rule, {tf: resample(frame, tf) for tf in rule.informative_timeframes})
    for cut in (24 * 230 + 5, 24 * 240 + 23, 24 * 250 + 11):
        part = frame.iloc[:cut].reset_index(drop=True)
        cut_frame = rule_frame(part, rule, {tf: resample(part, tf) for tf in rule.informative_timeframes})
        pd.testing.assert_frame_equal(cut_frame.tail(48), full.iloc[:cut].tail(48))


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


def test_plan_stays_within_the_round_budget_and_ids_are_unique():
    ids = [candidate.id for candidate in plan.candidates()]
    assert len(ids) == len(set(ids)) <= 300


def holdout_args(tmp_path, candidate: str, replay: bool = False):
    return type("Args", (), {"ledger": tmp_path / "ledger.jsonl", "replay": replay, "candidate": candidate})()


def test_second_holdout_run_is_refused_before_any_data_is_read(tmp_path):
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps({"kind": "holdout_started", "run_id": "r1", "candidate": "A"}) + "\n", encoding="utf-8"
    )
    with pytest.raises(strategy_search.HoldoutUsed):
        strategy_search.holdout(holdout_args(tmp_path, "B"), {})
    with pytest.raises(strategy_search.HoldoutUsed):
        strategy_search.holdout(holdout_args(tmp_path, "B", replay=True), {})


def test_replay_without_a_recorded_holdout_is_refused(tmp_path):
    with pytest.raises(strategy_search.HoldoutUsed):
        strategy_search.holdout(holdout_args(tmp_path, "A", replay=True), {})
