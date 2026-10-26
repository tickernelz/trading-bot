from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine.risk import (
    DAILY_LOSS,
    TOTAL_DRAWDOWN,
    ClosedTrade,
    assess,
    day_start,
    loss_ratio_at_stop,
    stake_for_risk,
)
from engine.settings import load_settings
from tests.conftest import EXAMPLE

CAPITAL = 2_000_000.0
FEE = 0.002
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


@pytest.fixture
def risk():
    return load_settings(EXAMPLE).risk


def test_day_starts_at_jakarta_midnight(risk):
    assert day_start(NOW, risk.daily_reset_timezone) == datetime(2026, 10, 24, 17, 0, tzinfo=UTC)


def test_no_trades_allows_entries(risk):
    state = assess(risk, CAPITAL, [], 0.0, NOW)
    assert state.entries_allowed
    assert state.equity == CAPITAL


def test_daily_loss_just_below_limit_allows_entries(risk):
    state = assess(risk, CAPITAL, [ClosedTrade(NOW - timedelta(hours=1), -19_999.0)], 0.0, NOW)
    assert state.entries_allowed
    assert state.daily_loss_pct == pytest.approx(0.99995)


def test_daily_loss_at_limit_stops_entries(risk):
    state = assess(risk, CAPITAL, [ClosedTrade(NOW - timedelta(hours=1), -20_000.0)], 0.0, NOW)
    assert state.breaches == (DAILY_LOSS,)
    assert not state.entries_allowed


def test_unrealized_loss_counts_toward_daily_limit(risk):
    state = assess(risk, CAPITAL, [ClosedTrade(NOW - timedelta(hours=1), -10_000.0)], -10_000.0, NOW)
    assert state.breaches == (DAILY_LOSS,)


def test_yesterdays_loss_does_not_count_today(risk):
    yesterday = datetime(2026, 10, 24, 16, 59, tzinfo=UTC)
    state = assess(risk, CAPITAL, [ClosedTrade(yesterday, -30_000.0)], 0.0, NOW)
    assert state.entries_allowed
    assert state.day_start_equity == CAPITAL - 30_000.0


def test_daily_limit_uses_equity_at_day_start(risk):
    yesterday = NOW - timedelta(days=1)
    closed = [ClosedTrade(yesterday, 1_000_000.0), ClosedTrade(NOW - timedelta(hours=1), -25_000.0)]
    state = assess(risk, CAPITAL, closed, 0.0, NOW)
    assert state.entries_allowed
    assert state.daily_loss_pct == pytest.approx(25_000 / 3_000_000 * 100)


def test_total_drawdown_from_peak_stops_entries(risk):
    closed = [ClosedTrade(NOW - timedelta(days=d), -50_000.0) for d in range(1, 5)]
    state = assess(risk, CAPITAL, closed, 0.0, NOW)
    assert state.breaches == (TOTAL_DRAWDOWN,)
    assert state.drawdown_pct == pytest.approx(10.0)


def test_drawdown_is_measured_from_realized_peak(risk):
    closed = [ClosedTrade(NOW - timedelta(days=5), 500_000.0)]
    closed += [ClosedTrade(NOW - timedelta(days=d), -62_500.0) for d in range(1, 5)]
    state = assess(risk, CAPITAL, closed, 0.0, NOW)
    assert state.peak_equity == 2_500_000.0
    assert state.equity == 2_250_000.0
    assert state.breaches == (TOTAL_DRAWDOWN,)


def test_both_limits_can_breach_together(risk):
    closed = [ClosedTrade(NOW - timedelta(hours=1), -200_000.0)]
    assert assess(risk, CAPITAL, closed, 0.0, NOW).breaches == (DAILY_LOSS, TOTAL_DRAWDOWN)


def test_future_trades_are_ignored(risk):
    state = assess(risk, CAPITAL, [ClosedTrade(NOW + timedelta(hours=1), -500_000.0)], 0.0, NOW)
    assert state.entries_allowed


def test_naive_times_are_rejected(risk):
    with pytest.raises(ValueError):
        assess(risk, CAPITAL, [], 0.0, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        assess(risk, CAPITAL, [ClosedTrade(datetime(2026, 10, 25), -1.0)], 0.0, NOW)


def test_loss_at_stop_includes_both_fees():
    assert loss_ratio_at_stop(-0.03, FEE) == pytest.approx(0.002 + 0.03 + 0.97 * 0.002)
    assert loss_ratio_at_stop(-0.03, 0.0) == pytest.approx(0.03)


def test_stake_loses_configured_fraction_at_stoploss_after_fees(risk):
    stake = stake_for_risk(risk, CAPITAL, -0.03, FEE, 10_000.0, 1_000_000.0)
    assert stake * loss_ratio_at_stop(-0.03, FEE) == pytest.approx(CAPITAL * 0.005)
    assert stake < CAPITAL * 0.005 / 0.03


def test_stake_scales_with_equity(risk):
    small = stake_for_risk(risk, CAPITAL, -0.03, FEE, None, 10_000_000.0)
    large = stake_for_risk(risk, 3_000_000.0, -0.03, FEE, None, 10_000_000.0)
    assert large == pytest.approx(small * 1.5)


def test_stake_is_capped_by_max_stake(risk):
    assert stake_for_risk(risk, CAPITAL, -0.03, FEE, None, 100_000.0) == 100_000.0


def test_stake_below_exchange_minimum_skips_trade(risk):
    assert stake_for_risk(risk, CAPITAL, -0.03, FEE, 400_000.0, 1_000_000.0) == 0.0


def test_stake_rejects_invalid_stoploss_and_fee(risk):
    with pytest.raises(ValueError):
        stake_for_risk(risk, CAPITAL, 0.0, FEE, None, 1_000_000.0)
    with pytest.raises(ValueError):
        stake_for_risk(risk, CAPITAL, -0.03, 0.2 * 100, None, 1_000_000.0)


def test_non_finite_equity_skips_trade(risk):
    assert stake_for_risk(risk, float("nan"), -0.03, FEE, None, 1_000_000.0) == 0.0


def test_non_finite_open_pnl_is_rejected(risk):
    with pytest.raises(ValueError):
        assess(risk, CAPITAL, [], float("nan"), NOW)


def test_non_finite_closed_profit_is_rejected(risk):
    with pytest.raises(ValueError):
        assess(risk, CAPITAL, [ClosedTrade(NOW - timedelta(hours=1), float("nan"))], 0.0, NOW)
