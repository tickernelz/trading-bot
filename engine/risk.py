"""Deterministic loss limits and risk-based position sizing."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.settings import RiskSettings

DAILY_LOSS = "daily_loss"
TOTAL_DRAWDOWN = "total_drawdown"


@dataclass(frozen=True)
class ClosedTrade:
    close_time: datetime
    profit_abs: float


@dataclass(frozen=True)
class RiskState:
    equity: float
    peak_equity: float
    day_start: datetime
    day_start_equity: float
    daily_pnl: float
    daily_loss_pct: float
    drawdown_pct: float
    breaches: tuple[str, ...]

    @property
    def entries_allowed(self) -> bool:
        return not self.breaches


def day_start(now: datetime, timezone: str) -> datetime:
    """Return midnight of the trading day containing now, in the reset timezone."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(ZoneInfo(timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def assess(
    settings: RiskSettings,
    initial_capital: float,
    closed: Iterable[ClosedTrade],
    open_pnl: float,
    now: datetime,
) -> RiskState:
    """Evaluate the daily-loss and peak-drawdown limits at now."""
    if not math.isfinite(open_pnl):
        raise ValueError("open_pnl must be finite")
    start = day_start(now, settings.daily_reset_timezone)
    realized = initial_capital
    peak = initial_capital
    day_start_equity = initial_capital
    daily_realized = 0.0
    for trade in sorted(closed, key=lambda item: item.close_time):
        if trade.close_time.tzinfo is None:
            raise ValueError("close_time must be timezone-aware")
        if trade.close_time > now:
            continue
        if not math.isfinite(trade.profit_abs):
            raise ValueError("profit_abs must be finite")
        realized += trade.profit_abs
        peak = max(peak, realized)
        if trade.close_time < start:
            day_start_equity = realized
        else:
            daily_realized += trade.profit_abs
    equity = realized + open_pnl
    daily_pnl = daily_realized + open_pnl
    daily_loss_pct = max(0.0, -daily_pnl) / day_start_equity * 100 if day_start_equity > 0 else 100.0
    drawdown_pct = max(0.0, peak - equity) / peak * 100
    breaches = []
    if daily_loss_pct >= settings.max_daily_loss_pct:
        breaches.append(DAILY_LOSS)
    if drawdown_pct >= settings.max_total_drawdown_pct:
        breaches.append(TOTAL_DRAWDOWN)
    return RiskState(
        equity=equity,
        peak_equity=peak,
        day_start=start,
        day_start_equity=day_start_equity,
        daily_pnl=daily_pnl,
        daily_loss_pct=daily_loss_pct,
        drawdown_pct=drawdown_pct,
        breaches=tuple(breaches),
    )


def loss_ratio_at_stop(stoploss: float, fee: float) -> float:
    """Return the fraction of a long stake lost when the stoploss fills, entry and exit fees included."""
    if not -1 < stoploss < 0:
        raise ValueError("stoploss must be a negative ratio above -1")
    if not 0 <= fee < 1:
        raise ValueError("fee must be a ratio in [0, 1)")
    return (1 + fee) - (1 + stoploss) * (1 - fee)


def stake_for_risk(
    settings: RiskSettings,
    equity: float,
    stoploss: float,
    fee: float,
    min_stake: float | None,
    max_stake: float,
) -> float:
    """Size a stake so that a stoploss fill, fees included, loses risk_per_trade_pct of equity; 0 means skip."""
    per_stake = loss_ratio_at_stop(stoploss, fee)
    if not math.isfinite(equity) or equity <= 0:
        return 0.0
    stake = min(equity * settings.risk_per_trade_pct / 100 / per_stake, max_stake)
    if min_stake is not None and stake < min_stake:
        return 0.0
    return max(stake, 0.0)
