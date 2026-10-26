from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from freqtrade.enums import RunMode
from freqtrade.persistence import Trade, init_db
from pandas import DataFrame

from engine.decisions import SHADOW_KEY
from engine.heartbeat import read_heartbeat
from engine.launch import freqtrade_config
from engine.settings import load_settings
from engine.strategies.swing_ema_rsi import SwingEmaRsi
from tests.conftest import EXAMPLE

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
FEE = load_settings(EXAMPLE).exchange.fee_pct / 100


class CandleStub:
    def __init__(self, closes: dict[str, float]):
        self.closes = closes
        self.messages: list[dict] = []

    def send_msg(self, message: str, *, always_send: bool = False) -> None:
        self.messages.append(json.loads(message))

    def get_analyzed_dataframe(self, pair, timeframe):
        if pair not in self.closes:
            return DataFrame(), None
        close = self.closes[pair]
        dates = [NOW - timedelta(hours=hours) for hours in (2, 1)]
        return DataFrame(
            {
                "date": dates,
                "open": [close, close],
                "high": [close, close],
                "low": [close, close],
                "close": [close, close],
                "volume": [1.0, 1.0],
                "ema_fast": [close, close],
                "ema_slow": [close, float("nan")],
                "rsi": [50.0, 55.0],
            }
        ), None


class ShadowRecorder:
    def __init__(self, fail: bool = False):
        self.candidates: list[dict] = []
        self.fail = fail
        self.sent = 0
        self.failed = 0

    def submit(self, candidate: dict) -> None:
        if self.fail:
            raise RuntimeError("shadow down")
        self.candidates.append(candidate)


def _unstarted(userdir, compounding: bool = True, runmode: RunMode = RunMode.DRY_RUN) -> SwingEmaRsi:
    config = freqtrade_config(load_settings(EXAMPLE), shadow=True)
    config["trading_bot"]["compounding"] = compounding
    config["user_data_dir"] = userdir
    config["runmode"] = runmode
    instance = SwingEmaRsi(config)
    instance.dp = CandleStub({})
    instance.bot_start()
    instance.shadow = None
    return instance


def _make_strategy(userdir, compounding: bool = True) -> SwingEmaRsi:
    instance = _unstarted(userdir, compounding)
    instance.bot_loop_start(NOW)
    assert instance.startup_checked
    instance.dp.messages.clear()
    return instance


@pytest.fixture
def db():
    init_db("sqlite://")
    yield
    Trade.session.remove()


@pytest.fixture
def fixed_strategy(db, tmp_path):
    return _make_strategy(tmp_path, compounding=False)


@pytest.fixture
def strategy(db, tmp_path):
    return _make_strategy(tmp_path)


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


def test_entries_denied_before_first_loop(db, tmp_path):
    instance = _unstarted(tmp_path)
    assert instance.risk_state(NOW).entries_allowed
    assert not _confirm(instance)
    instance.bot_loop_start(NOW)
    assert _confirm(instance)


def test_entries_wait_for_startup_check_of_open_positions(db, tmp_path):
    instance = _unstarted(tmp_path)
    _trade("SOL/IDR", 3_000_000.0, 400_000.0, is_open=True)
    assert not _confirm(instance)
    instance.bot_loop_start(NOW)
    assert not instance.startup_checked
    assert not _confirm(instance)
    instance.dp.closes["SOL/IDR"] = 2_990_000.0
    instance.bot_loop_start(NOW)
    assert instance.startup_checked
    [report] = instance.dp.messages
    assert report["event"] == "startup_check"
    assert report["open_trades"] == ["SOL/IDR"]
    assert report["entries_allowed"] is True
    assert _confirm(instance)


def test_startup_check_reports_breached_limit_and_keeps_entries_denied(db, tmp_path):
    _closed(NOW - timedelta(hours=1), -25_000.0)
    instance = _unstarted(tmp_path)
    instance.bot_loop_start(NOW)
    [report] = instance.dp.messages
    assert report["entries_allowed"] is False
    assert report["breaches"] == ["daily_loss"]
    assert not _confirm(instance)


def test_heartbeat_counts_restarts(db, tmp_path):
    _make_strategy(tmp_path)
    second = _make_strategy(tmp_path)
    beat = read_heartbeat(tmp_path)
    assert second.starts == 2
    assert beat["starts"] == 2
    assert beat["bot"] == "A"
    assert beat["startup_checked"] is True
    assert beat["open_trades"] == 0


def test_shadow_receives_allowed_entry_and_links_filled_trade(strategy):
    strategy.dp = CandleStub({"ETH/IDR": 60_000_000.0})
    strategy.shadow = ShadowRecorder()
    assert _confirm(strategy)
    [candidate] = strategy.shadow.candidates
    assert candidate["pair"] == "ETH/IDR"
    assert candidate["rate"] == 60_000_000.0
    assert len(candidate["candles"]) == 2
    assert candidate["candles"][-1][7] is None
    assert candidate["candle"] == (NOW - timedelta(hours=1)).isoformat()
    json.dumps(candidate, allow_nan=False)
    trade = _trade("ETH/IDR", 60_000_000.0, 300_000.0, is_open=True)
    strategy.order_filled("ETH/IDR", trade, SimpleNamespace(ft_order_side="sell"), NOW)
    assert trade.get_custom_data(SHADOW_KEY) is None
    strategy.order_filled("ETH/IDR", trade, SimpleNamespace(ft_order_side="buy"), NOW)
    assert trade.get_custom_data(SHADOW_KEY) == candidate["decision_id"]
    assert strategy.shadow_pending == {}


def test_denied_entry_is_not_sent_to_shadow(strategy):
    strategy.shadow = ShadowRecorder()
    _closed(NOW - timedelta(hours=1), -25_000.0)
    assert not _confirm(strategy)
    assert strategy.shadow.candidates == []


def test_shadow_failure_never_blocks_entry(strategy):
    strategy.dp = CandleStub({"ETH/IDR": 60_000_000.0})
    strategy.shadow = ShadowRecorder(fail=True)
    assert _confirm(strategy)
    assert strategy.shadow_pending == {}


@pytest.mark.parametrize("runmode", [RunMode.BACKTEST, RunMode.WEBSERVER, RunMode.HYPEROPT])
def test_non_trading_runmodes_leave_live_files_and_shadow_alone(db, tmp_path, monkeypatch, runmode):
    monkeypatch.setenv("SHADOW_TOKEN", "s" * 32)
    (tmp_path / "heartbeat.json").write_text('{"ts": "2026-10-25T00:00:00+00:00", "pid": 1}', encoding="utf-8")
    (tmp_path / "starts.jsonl").write_text('{"pid": 1}\n', encoding="utf-8")
    config = freqtrade_config(load_settings(EXAMPLE), shadow=True)
    config["user_data_dir"] = tmp_path
    config["runmode"] = runmode
    instance = SwingEmaRsi(config)
    instance.dp = CandleStub({"ETH/IDR": 60_000_000.0})
    instance.bot_start()
    assert instance.shadow is None
    for _ in range(3):
        instance.bot_loop_start(NOW)
    assert _confirm(instance)
    assert instance.dp.messages == []
    assert (tmp_path / "starts.jsonl").read_text(encoding="utf-8") == '{"pid": 1}\n'
    assert read_heartbeat(tmp_path) == {"ts": "2026-10-25T00:00:00+00:00", "pid": 1}
