from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from freqtrade.enums import RunMode
from freqtrade.persistence import Trade, init_db

from engine import search_plan
from engine.launch import freqtrade_config
from engine.risk import loss_ratio_at_stop
from engine.rules import RuleSpec
from engine.settings import load_settings
from engine.signals import resample, rule_frame
from engine.strategies.rule_strategy import RuleStrategy
from tests.conftest import EXAMPLE

START = datetime(2025, 1, 1, tzinfo=UTC)


def walk(hours: int, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, hours)))
    return pd.DataFrame(
        {
            "date": pd.date_range(START, periods=hours, freq="1h"),
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.003,
            "low": close * 0.997,
            "close": close,
            "volume": np.ones(hours),
        }
    )


class Provider:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.analyzed = pd.DataFrame()

    def current_whitelist(self):
        return ["BTC/IDR", "ETH/IDR"]

    def get_pair_dataframe(self, pair, timeframe):
        return resample(self.frame, timeframe)

    def get_analyzed_dataframe(self, pair, timeframe):
        return self.analyzed, None


def strategy(rule: RuleSpec | None = None) -> RuleStrategy:
    settings = load_settings(EXAMPLE)
    config = freqtrade_config(settings)
    if rule is not None:
        config["trading_bot"]["rule"] = rule.model_dump()
    config["runmode"] = RunMode.BACKTEST
    config["user_data_dir"] = "/tmp"
    instance = RuleStrategy(config)
    instance.dp = None
    return instance


def analyzed(instance: RuleStrategy, frame: pd.DataFrame) -> pd.DataFrame:
    instance.dp = Provider(frame)
    out = instance.populate_indicators(frame.copy(), {"pair": "BTC/IDR"})
    out = instance.populate_entry_trend(out, {"pair": "BTC/IDR"})
    return instance.populate_exit_trend(out, {"pair": "BTC/IDR"})


ROUND1_SELECTED = "J-rsi14-1h-tp3-sl10"


def test_example_config_runs_the_round_one_selection():
    [selected] = [candidate for candidate in search_plan.round1_candidates() if candidate.id == ROUND1_SELECTED]
    strategy = load_settings(EXAMPLE).strategy
    assert (strategy.name, strategy.rule) == ("RuleStrategy", selected.spec)


def test_default_rule_enters_where_the_shared_signal_enters():
    instance = strategy()
    frame = walk(2000)
    out = analyzed(instance, frame)
    expected = rule_frame(frame, instance.rule, {})["enter"]
    assert expected.sum() > 10
    assert (out["enter_long"] == 1).fillna(False).tolist() == expected.tolist()
    assert set(out.loc[out["enter_long"] == 1, "enter_tag"]) == {"rule_rsi_dip"}
    assert {"ema_fast", "ema_slow", "rsi"} <= set(out.columns)


def test_higher_timeframe_rule_reads_informative_candles_without_lookahead():
    rule = RuleSpec(entry="tsmom", timeframe="4h", lookback=6, exit="tsmom_flip", stoploss=-0.1)
    instance = strategy(rule)
    frame = walk(1500)
    out = analyzed(instance, frame)
    expected = rule_frame(frame, rule, {"4h": resample(frame, "4h")})
    assert (out["enter_long"] == 1).fillna(False).tolist() == expected["enter"].tolist()
    assert (out["exit_long"] == 1).fillna(False).tolist() == expected["exit_signal"].tolist()
    truncated = analyzed(strategy(rule), frame.iloc[:1000].reset_index(drop=True))
    assert truncated["enter_long"].fillna(0).tolist() == out["enter_long"].fillna(0).iloc[:1000].tolist()


def test_informative_pairs_cover_every_whitelisted_pair_and_rule_timeframe():
    rule = RuleSpec(
        entry="donchian", timeframe="4h", lookback=20, exit="none", trend_filter="above_sma200_1d", stoploss=-0.1
    )
    instance = strategy(rule)
    instance.dp = Provider(walk(10))
    assert sorted(instance.informative_pairs()) == [
        ("BTC/IDR", "1d"),
        ("BTC/IDR", "4h"),
        ("ETH/IDR", "1d"),
        ("ETH/IDR", "4h"),
    ]


def open_trade(open_date: datetime, open_rate: float = 100.0):
    return SimpleNamespace(open_date_utc=open_date, open_rate=open_rate)


def exit_for(rule: RuleSpec, closes: list[float], now_hours: int):
    instance = strategy(rule)
    frame = walk(len(closes))
    frame["close"] = closes
    frame["rule_atr"] = 1.0
    instance.dp = Provider(frame)
    instance.dp.analyzed = frame
    trade = open_trade(START + timedelta(minutes=3))
    return instance.custom_exit("BTC/IDR", trade, START + timedelta(hours=now_hours), closes[-1], 0.0)


def test_time_stop_fires_once_the_holding_period_is_reached():
    rule = RuleSpec(
        entry="rsi_dip", timeframe="1h", lookback=14, threshold=30, exit="none", stoploss=-0.1, max_hold_hours=5
    )
    assert exit_for(rule, [100.0] * 5, 4) is None
    assert exit_for(rule, [100.0] * 5, 5) == "rule_time"


def test_lock_exit_counts_the_entry_candle_of_a_trade_filled_after_its_open():
    rule = RuleSpec(
        entry="rsi_dip", timeframe="1h", lookback=14, threshold=30, exit="none", stoploss=-0.1, lock_at=0.04
    )
    assert exit_for(rule, [104.5, 103.0], 2) is None
    assert exit_for(rule, [104.5, 101.5], 2) == "rule_lock"


def atr_callbacks(rule: RuleSpec, signal_atr: float):
    instance = strategy(rule)
    frame = walk(6)
    frame["rule_atr"] = [9.0, signal_atr, 7.0, 7.0, 7.0, 7.0]
    instance.dp = Provider(frame)
    instance.dp.analyzed = frame
    return instance, open_trade(START + timedelta(hours=2, minutes=3))


def test_atr_target_reaches_freqtrade_roi_exactly_at_the_gross_target_price():
    rule = RuleSpec(
        entry="donchian", timeframe="1h", lookback=5, exit="none", stoploss=-0.2, take_profit_atr=1.5, stop_atr=2.0
    )
    instance, trade = atr_callbacks(rule, 2.0)
    assert instance.use_custom_roi and instance.use_custom_stoploss
    roi = instance.custom_roi("BTC/IDR", trade, START + timedelta(hours=4), 120, None, "long")
    fee = instance.fee
    assert 103.0 * (1 - fee) / (100.0 * (1 + fee)) - 1 == pytest.approx(roi)
    stop = instance.custom_stoploss("BTC/IDR", trade, START + timedelta(hours=4), 110.0, 0.1, False)
    assert 110.0 * (1 - stop) == pytest.approx(96.0)


def test_fixed_exit_rules_leave_the_custom_callbacks_off():
    rule = RuleSpec(entry="rsi_dip", timeframe="1h", lookback=14, threshold=30, exit="none", stoploss=-0.1)
    instance = strategy(rule)
    assert not instance.use_custom_roi and not instance.use_custom_stoploss


def test_stake_risks_the_configured_share_of_equity_at_the_rule_stop():
    init_db("sqlite://")
    try:
        rule = RuleSpec(entry="rsi_dip", timeframe="1h", lookback=14, threshold=30, exit="none", stoploss=-0.25)
        instance = strategy(rule)
        instance.dp = Provider(walk(10))
        instance.bot_start()
        stake = instance.custom_stake_amount("BTC/IDR", START, 100.0, 1.0, 10_000.0, 10_000_000.0, 1.0, None, "long")
        settings = load_settings(EXAMPLE)
        fee = settings.exchange.fee_pct / 100
        assert instance.stoploss == -0.25
        assert stake == pytest.approx(settings.capital.initial_idr * 0.005 / loss_ratio_at_stop(-0.25, fee))
    finally:
        Trade.session.remove()
