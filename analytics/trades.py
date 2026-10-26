"""Freqtrade trade objects as the gateway forwards them, parsed into the figures the risk module needs."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from analytics.errors import AnalyticsError
from engine.risk import ClosedTrade, RiskState, assess
from engine.settings import RiskSettings, Settings


def parse_time(value: str) -> datetime:
    """Parse a Freqtrade timestamp, which is UTC with or without an offset."""
    text = value.strip().replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def number(trade: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = trade.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    return None


def required_number(trade: dict[str, Any], *keys: str) -> float:
    value = number(trade, *keys)
    if value is None:
        raise AnalyticsError(502, "upstream_error", f"trade {trade.get('trade_id')} lacks {'/'.join(keys)}")
    return value


def is_closed(trade: dict[str, Any]) -> bool:
    return trade.get("is_open") is False and bool(trade.get("close_date"))


def closed_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [trade for trade in trades if is_closed(trade)]


def open_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [trade for trade in trades if trade.get("is_open") is True]


def profit_abs(trade: dict[str, Any]) -> float:
    return required_number(trade, "close_profit_abs", "profit_abs")


@dataclass(frozen=True)
class OpenPosition:
    trade_id: int
    pair: str
    amount: float
    stake: float
    cost: float
    rate: float
    stop_abs: float | None
    stop_pct: float | None
    fee_open: float
    fee_close: float
    pnl: float

    def value_at(self, rate: float) -> float:
        return self.amount * rate * (1 - self.fee_close)

    def pnl_at(self, rate: float) -> float:
        return self.value_at(rate) - self.cost


def position_of(trade: dict[str, Any]) -> OpenPosition:
    """Read the figures of one open trade from its Freqtrade object."""
    amount = required_number(trade, "amount")
    cost = required_number(trade, "open_trade_value")
    stake = number(trade, "stake_amount") or cost
    rate = required_number(trade, "current_rate", "open_rate")
    fee_open = number(trade, "fee_open") or 0.0
    fee_close = number(trade, "fee_close")
    stop_pct = number(trade, "stop_loss_pct")
    pnl = number(trade, "profit_abs")
    position = OpenPosition(
        trade_id=int(trade.get("trade_id", 0)),
        pair=str(trade.get("pair", "")),
        amount=amount,
        stake=stake,
        cost=cost,
        rate=rate,
        stop_abs=number(trade, "stop_loss_abs"),
        stop_pct=stop_pct,
        fee_open=fee_open,
        fee_close=fee_open if fee_close is None else fee_close,
        pnl=0.0,
    )
    return replace(position, pnl=position.pnl_at(rate) if pnl is None else pnl)


@dataclass(frozen=True)
class RiskInputs:
    initial_capital: float
    closed: tuple[ClosedTrade, ...]
    positions: tuple[OpenPosition, ...]
    now: datetime

    @property
    def open_pnl(self) -> float:
        return sum(position.pnl for position in self.positions)

    def assess(self, risk: RiskSettings, open_pnl: float | None = None) -> RiskState:
        pnl = self.open_pnl if open_pnl is None else open_pnl
        return assess(risk, self.initial_capital, self.closed, pnl, self.now)


def risk_inputs(settings: Settings, trades: list[dict[str, Any]], now: datetime) -> RiskInputs:
    """Collect what the engine risk module needs from forwarded trades."""
    closed = tuple(
        ClosedTrade(close_time=parse_time(str(trade["close_date"])), profit_abs=profit_abs(trade))
        for trade in closed_trades(trades)
    )
    positions = tuple(position_of(trade) for trade in open_trades(trades))
    return RiskInputs(settings.capital.initial_idr, closed, positions, now)
