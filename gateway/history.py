"""Closed-trade history grouped into days, weeks and months of the risk timezone."""

from __future__ import annotations

from bisect import bisect_left
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def period_start(day: date, unit: str) -> date:
    if unit == "weekly":
        return day - timedelta(days=day.weekday())
    if unit == "monthly":
        return day.replace(day=1)
    return day


def step_back(start: date, unit: str) -> date:
    if unit == "weekly":
        return start - timedelta(days=7)
    if unit == "monthly":
        return (start - timedelta(days=1)).replace(day=1)
    return start - timedelta(days=1)


def outcome(trade: dict[str, Any]) -> str:
    ratio = trade.get("close_profit") or 0.0
    if ratio > 0:
        return "wins"
    if ratio < 0:
        return "losses"
    return "draws"


def periods(
    trades: list[dict[str, Any]], unit: str, count: int, timezone: str, initial: float, now: datetime
) -> list[dict[str, Any]]:
    """Newest period first, like Freqtrade /daily; starting balance is initial capital plus earlier realised profit."""
    zone = ZoneInfo(timezone)
    closed = sorted(
        (trade for trade in trades if not trade.get("is_open") and trade.get("close_timestamp")),
        key=lambda trade: trade["close_timestamp"],
    )
    starts = [period_start(now.astimezone(zone).date(), unit)]
    for _ in range(count - 1):
        starts.append(step_back(starts[-1], unit))
    stamps = [trade["close_timestamp"] for trade in closed]
    cumulative = [0.0]
    for trade in closed:
        cumulative.append(cumulative[-1] + (trade.get("close_profit_abs") or 0.0))
    edges = [datetime(start.year, start.month, start.day, tzinfo=zone) for start in starts]
    rows = []
    for position, start in enumerate(starts):
        begin = edges[position]
        first = bisect_left(stamps, begin.timestamp() * 1000)
        last = bisect_left(stamps, edges[position - 1].timestamp() * 1000) if position else len(stamps)
        inside = closed[first:last]
        profit = cumulative[last] - cumulative[first]
        balance = initial + cumulative[first]
        tally = {"wins": 0, "losses": 0, "draws": 0}
        for trade in inside:
            tally[outcome(trade)] += 1
        rows.append(
            {
                "date": start.isoformat(),
                "start": begin.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "abs_profit": round(profit, 8),
                "starting_balance": round(balance, 8),
                "rel_profit": round(profit / balance, 8) if balance > 0 else 0.0,
                "trade_count": len(inside),
                **tally,
            }
        )
    return rows
