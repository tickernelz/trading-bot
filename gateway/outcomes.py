"""What a swarm decision would have done and how the price and the shadowed trade went afterwards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

ACTIONS = {
    "izinkan": "masuk dengan ukuran penuh",
    "kecilkan": "masuk dengan setengah ukuran",
    "lewati": "tidak masuk",
}
EFFECTS = {
    "lewati": {-1: "avoided_loss", 1: "missed_gain", 0: "flat"},
    "kecilkan": {-1: "reduced_loss", 1: "reduced_gain", 0: "flat"},
}
PENDING = "pending"
MISSING = "insufficient_data"
SETTLED = "settled"

Candle = tuple[float, float, float]


def moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sign(value: float) -> int:
    return (value > 0) - (value < 0)


def by_open_time(frame: dict[str, Any]) -> dict[int, Candle]:
    """High, low and close of each candle in a Freqtrade /pair_candles frame, keyed by open time in seconds."""
    columns = frame.get("columns") or []
    if not columns:
        return {}
    index = {name: position for position, name in enumerate(columns)}
    high, low, close = index["high"], index["low"], index["close"]
    rows = frame.get("data") or []
    if "__date_ts" in index:
        stamp = index["__date_ts"]
        return {raw[stamp] // 1000: (raw[high], raw[low], raw[close]) for raw in rows}
    date = index["date"]
    return {int(moment(str(raw[date])).timestamp()): (raw[high], raw[low], raw[close]) for raw in rows}


def quorum(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": decision["required"],
        "answered": decision["answered"],
        "met": decision["answered"] >= decision["required"],
    }


def would_take(decision: dict[str, Any]) -> dict[str, Any]:
    verdict = decision["verdict"]
    return {"verdict": verdict, "action": ACTIONS.get(verdict), "applied": decision["mode"] == "veto"}


def trade_view(trade: dict[str, Any] | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    is_open = bool(trade.get("is_open"))
    ratio = trade.get("profit_ratio") if is_open else trade.get("close_profit")
    return {
        "trade_id": trade.get("trade_id"),
        "is_open": is_open,
        "enter_tag": trade.get("enter_tag"),
        "exit_reason": trade.get("exit_reason"),
        "open_rate": trade.get("open_rate"),
        "close_rate": trade.get("close_rate"),
        "open_date": trade.get("open_date"),
        "close_date": trade.get("close_date"),
        "profit_abs": trade.get("profit_abs") if is_open else trade.get("close_profit_abs"),
        "profit_pct": round(ratio * 100, 4) if ratio is not None else None,
    }


def forward(
    rate: float,
    requested_at: str,
    by_open: dict[int, Candle],
    now: datetime,
    horizons: list[int],
    cost_pct: float,
    timeframe_s: int,
) -> list[dict[str, Any]]:
    """Return per horizon from the entry rate to the close of the h-th candle, counting the candle the entry fell in."""
    start = int(moment(requested_at).timestamp() // timeframe_s) * timeframe_s
    first = min(by_open) if by_open else None
    latest = max(by_open) if by_open else None
    points = []
    for horizon in horizons:
        last_open = start + (horizon - 1) * timeframe_s
        closes_at = datetime.fromtimestamp(last_open + timeframe_s, UTC)
        point: dict[str, Any] = {"candles": horizon, "until": iso(closes_at)}
        window = [by_open.get(start + step * timeframe_s) for step in range(horizon)]
        if first is None or first > start:
            point["state"] = MISSING
        elif closes_at > now or (window[-1] is None and latest < last_open):
            point["state"] = PENDING
        elif any(candle is None for candle in window):
            point["state"] = MISSING
        else:
            close = window[-1][2]
            gross = (close / rate - 1) * 100
            point.update(
                state=SETTLED,
                close=close,
                return_pct=round(gross, 4),
                net_pct=round(gross - cost_pct, 4),
                max_up_pct=round((max(candle[0] for candle in window) / rate - 1) * 100, 4),
                max_down_pct=round((min(candle[1] for candle in window) / rate - 1) * 100, 4),
            )
        points.append(point)
    return points


def effect(verdict: str, state: str, value: float | None) -> str:
    """What following the verdict would have changed, from the settled trade profit or the price return after costs."""
    if verdict == "izinkan":
        return "same_as_rules"
    if state != SETTLED or value is None:
        return state
    return EFFECTS[verdict][sign(value)]


def summary(
    decision: dict[str, Any], shadowed: dict[str, Any] | None, ahead: list[dict[str, Any]], cost_pct: float
) -> dict[str, Any]:
    point = ahead[-1]
    priced = point["state"] == SETTLED
    common = {
        "horizon_h": point["candles"],
        "round_trip_cost_pct": cost_pct,
        "price_at": decision["rate"],
        "price_after": point.get("close"),
        "return_pct": point.get("return_pct"),
        "return_after_fees_pct": point.get("net_pct"),
    }
    if shadowed is not None:
        state = PENDING if shadowed["is_open"] else SETTLED
        return {
            "state": state,
            "basis": "trade",
            **common,
            "trade_id": shadowed["trade_id"],
            "is_open": shadowed["is_open"],
            "profit_abs": shadowed["profit_abs"],
            "profit_pct": shadowed["profit_pct"],
            "settles_at": None,
            "effect": effect(decision["verdict"], state, shadowed["profit_pct"]),
        }
    return {
        "state": point["state"],
        "basis": "price",
        **common,
        "trade_id": None,
        "is_open": None,
        "profit_abs": None,
        "profit_pct": None,
        "settles_at": point["until"] if point["state"] == PENDING else None,
        "effect": effect(decision["verdict"], point["state"], point.get("net_pct") if priced else None),
    }


def explain(
    decision: dict[str, Any],
    trade: dict[str, Any] | None,
    by_open: dict[int, Candle],
    now: datetime,
    horizons: list[int],
    cost_pct: float,
    timeframe_s: int,
) -> dict[str, Any]:
    shadowed = trade_view(trade)
    ahead = forward(decision["rate"], decision["requested_at"], by_open, now, horizons, cost_pct, timeframe_s)
    return {
        **decision,
        "quorum": quorum(decision),
        "would_take": would_take(decision),
        "outcome": {**summary(decision, shadowed, ahead, cost_pct), "trade": shadowed, "forward": ahead},
    }
