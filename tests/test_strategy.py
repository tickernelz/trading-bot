from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from freqtrade.persistence import Trade, init_db
from pandas import DataFrame

from engine.launch import freqtrade_config
from engine.settings import load_settings
from engine.strategies.swing_ema_rsi import SwingEmaRsi
from tests.conftest import EXAMPLE

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
FEE = 0.002


class CandleStub:
    def __init__(self, closes: dict[str, float]):
        self.closes = closes
        self.messages: list[dict] = []

    def send_msg(self, message: str, *, always_send: bool = False) -> None:
        self.messages.append(json.loads(message))

    def get_analyzed_dataframe(self, pair, timeframe):
        if pair not in self.closes:
            return DataFrame(), None
        return DataFrame({"close": [self.closes[pair]]}), None


def _make_strategy(compounding: bool = True) -> SwingEmaRsi:
    config = freqtrade_config(load_settings(EXAMPLE))
    config["trading_bot"]["compounding"] = compounding
    instance = SwingEmaRsi(config)
    instance.dp = CandleStub({})
    instance.bot_start()
    return instance


@pytest.fixture
def fixed_strategy():
    init_db("sqlite://")
    yield _make_strategy(compounding=False)
    Trade.session.remove()


@pytest.fixture
def strategy():
    init_db("sqlite://")
    config = freqtrade_config(load_settings(EXAMPLE))
    instance = SwingEmaRsi(config)
    instance.dp = CandleStub({})
    instance.bot_start()
    yield instance
    Trade.session.remove()


def _trade(pair: str, open_rate: float, stake: float, **fields) -> Trade:
    trade = Trade(
        pair=pair,
        stake_amount=stake,
        amount=stake / open_rate,
        open_rate=open_rate,
        fee_open=FEE,
        fee_close=FEE,
        open_date=NOW - timedelta(days=2),
        exchange="indodax",
        strategy="SwingEmaRsi",
        timeframe=60,
        **fields,
    )
    trade.recalc_open_trade_value()
    Trade.session.add(trade)
    Trade.commit()
    return trade


def _closed(close_date: datetime, profit_abs: float) -> Trade:
    return _trade(
        "BTC/IDR",
        1_000_000_000.0,
        300_000.0,
        is_open=False,
        close_rate=1_000_000_000.0,
        close_date=close_date.replace(tzinfo=None),
        close_profit_abs=profit_abs,
    )


def _confirm(strategy, pair="ETH/IDR"):
    return strategy.confirm_trade_entry(pair, "limit", 1.0, 60_000_000.0, "GTC", NOW, "ema_cross_up", "long")


def _stake(strategy, min_stake=10_000.0, max_stake=1_000_000.0):
    return strategy.custom_stake_amount(
        "ETH/IDR", NOW, 60_000_000.0, 600_000.0, min_stake, max_stake, 1.0, "ema_cross_up", "long"
    )


def test_entry_allowed_without_losses(strategy):
    assert _confirm(strategy)
    assert strategy.dp.messages == []


def test_entry_allowed_below_daily_limit(strategy):
    _closed(NOW - timedelta(hours=1), -19_000.0)
    assert _confirm(strategy)


def test_entry_denied_after_daily_loss_limit(strategy):
    _closed(NOW - timedelta(hours=2), -12_000.0)
    _closed(NOW - timedelta(hours=1), -8_000.0)
    assert not _confirm(strategy)
    [message] = strategy.dp.messages
    assert message["event"] == "risk_guard_denied"
    assert message["breaches"] == ["daily_loss"]
    assert message["daily_loss_pct"] == 1.0


def test_entry_denied_when_open_loss_breaches_daily_limit(strategy):
    strategy.dp = CandleStub({"SOL/IDR": 2_850_000.0})
    _trade("SOL/IDR", 3_000_000.0, 400_000.0, is_open=True)
    assert strategy.risk_state(NOW).daily_pnl < -20_000
    assert not _confirm(strategy)


def test_entry_denied_after_total_drawdown(strategy):
    for days in range(1, 5):
        _closed(NOW - timedelta(days=days), -50_000.0)
    assert not _confirm(strategy)


def test_entry_allowed_again_on_next_day(strategy):
    _closed(NOW - timedelta(days=1), -25_000.0)
    assert _confirm(strategy)


def test_entry_denied_when_open_trade_cannot_be_priced(strategy):
    _trade("SOL/IDR", 3_000_000.0, 400_000.0, is_open=True)
    assert not _confirm(strategy)
    assert _stake(strategy) == 0.0


def test_stoploss_fill_loses_risk_per_trade_of_equity_after_fees(strategy):
    stake = _stake(strategy)
    open_rate = 60_000_000.0
    trade = _trade("ETH/IDR", open_rate, stake, is_open=True)
    loss = trade.calculate_profit(open_rate * (1 + strategy.stoploss)).profit_abs
    assert loss == pytest.approx(-2_000_000.0 * 0.005, rel=1e-6)


def test_stake_compounds_with_realized_profit(strategy):
    base = _stake(strategy)
    _closed(NOW - timedelta(days=3), 1_000_000.0)
    assert _stake(strategy) == pytest.approx(base * 1.5)


def test_stake_without_compounding_ignores_profit(fixed_strategy):
    base = _stake(fixed_strategy)
    _closed(NOW - timedelta(days=3), 1_000_000.0)
    assert _stake(fixed_strategy) == pytest.approx(base)


def test_stake_without_compounding_still_shrinks_after_loss(fixed_strategy):
    base = _stake(fixed_strategy)
    _closed(NOW - timedelta(days=3), -100_000.0)
    assert _stake(fixed_strategy) == pytest.approx(base * 0.95)


def test_entry_denied_when_open_trade_price_is_nan(strategy):
    strategy.dp = CandleStub({"SOL/IDR": float("nan")})
    _trade("SOL/IDR", 3_000_000.0, 400_000.0, is_open=True)
    assert not _confirm(strategy)
    assert _stake(strategy) == 0.0


def test_stake_skips_when_below_exchange_minimum(strategy):
    assert _stake(strategy, min_stake=500_000.0) == 0.0
