"""Bar-by-bar long-only simulator: signal at a 1h close, fill at the next open, stop and target inside the bar."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.rules import RuleSpec
from engine.signals import trade_exit_reason

HOUR = pd.Timedelta(hours=1)


@dataclass(frozen=True)
class Costs:
    buy: float
    sell: float

    def profit_ratio(self, entry: float, exit_: float) -> float:
        """Freqtrade profit_ratio: exit value after the sell cost over entry value after the buy cost."""
        return exit_ * (1 - self.sell) / (entry * (1 + self.buy)) - 1


@dataclass(frozen=True)
class Exits:
    stoploss: float
    roi: tuple[tuple[int, float], ...] = ()
    roi_net_of_fee: bool = False
    rule: RuleSpec | None = None


@dataclass(frozen=True)
class Trade:
    pair: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    reason: str

    def profit(self, costs: Costs) -> float:
        return costs.profit_ratio(self.entry_price, self.exit_price)


def exits_for(spec: RuleSpec) -> Exits:
    roi = ((0, spec.take_profit),) if spec.take_profit is not None else ()
    return Exits(stoploss=spec.stoploss, roi=roi, rule=spec)


def _roi_price(exits: Exits, entry: float, minutes: float, costs: Costs) -> float | None:
    ratio = None
    for start, value in exits.roi:
        if minutes >= start:
            ratio = value
    if ratio is None:
        return None
    if not exits.roi_net_of_fee:
        return entry * (1 + ratio)
    fee = (costs.buy + costs.sell) / 2
    return entry * (1 + fee) * (1 + ratio) / (1 - fee)


def simulate(
    pair: str,
    candles: pd.DataFrame,
    enter: np.ndarray,
    exit_signal: np.ndarray,
    atr: np.ndarray,
    exits: Exits,
    costs: Costs,
) -> list[Trade]:
    """Simulate one position at a time on one pair; a trade still open at the last candle closes at its close."""
    dates = candles["date"].to_numpy()
    opens = candles["open"].to_numpy(dtype=float)
    highs = candles["high"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    closes = candles["close"].to_numpy(dtype=float)
    trades: list[Trade] = []
    entry_index = -1
    entry_price = 0.0
    pending: str | None = None
    for i in range(1, len(closes)):
        exit_price = None
        reason = None
        if entry_index >= 0 and pending is not None:
            exit_price, reason = opens[i], pending
        exited_now = exit_price is not None
        if exited_now:
            trades.append(_trade(pair, dates, entry_index, i, entry_price, exit_price, reason))
            entry_index, pending = -1, None
        if entry_index < 0 and not exited_now and enter[i - 1]:
            entry_index, entry_price = i, opens[i]
        if entry_index < 0 or exited_now:
            continue
        first = i == entry_index
        stop_price = entry_price * (1 + exits.stoploss)
        target = _roi_price(exits, entry_price, (i - entry_index) * 60, costs)
        if lows[i] <= stop_price:
            exit_price, reason = (stop_price if first else min(opens[i], stop_price)), "stoploss"
        elif target is not None and highs[i] >= target:
            exit_price, reason = (target if first else max(opens[i], target)), "roi"
        if exit_price is not None:
            trades.append(_trade(pair, dates, entry_index, i, entry_price, exit_price, reason))
            entry_index = -1
            continue
        if exit_signal[i]:
            pending = "exit_signal"
        elif exits.rule is not None:
            pending = trade_exit_reason(
                exits.rule, entry_price, closes[entry_index : i + 1], atr[i], float(i + 1 - entry_index)
            )
    if entry_index >= 0:
        last = len(closes) - 1
        trades.append(_trade(pair, dates, entry_index, last, entry_price, closes[last], "end"))
    return trades


def _trade(pair: str, dates: np.ndarray, entry: int, exit_: int, entry_price: float, exit_price: float, reason: str):
    return Trade(
        pair=pair,
        signal_time=pd.Timestamp(dates[entry - 1]),
        entry_time=pd.Timestamp(dates[entry]),
        exit_time=pd.Timestamp(dates[exit_]),
        entry_price=float(entry_price),
        exit_price=float(exit_price),
        reason=reason,
    )
