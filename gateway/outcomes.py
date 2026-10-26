"""What a swarm decision would have done and how the price and the shadowed trade went afterwards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

ACTIONS = {
    "izinkan": "masuk dengan ukuran penuh",
    "kecilkan": "masuk dengan setengah ukuran",
    "lewati": "tidak masuk",
}
PENDING = "belum_cukup_data"
MISSING = "data_tidak_tersedia"

Candle = tuple[float, float, float]


def moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sign_result(value: float) -> str:
    if value > 0:
        return "untung"
    if value < 0:
        return "rugi"
    return "impas"


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


def trade_result(trade: dict[str, Any] | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    is_open = bool(trade.get("is_open"))
    profit_abs = trade.get("profit_abs") if is_open else trade.get("close_profit_abs")
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
        "profit_abs": profit_abs,
        "profit_pct": round(ratio * 100, 4) if ratio is not None else None,
        "result": "masih_terbuka" if is_open else sign_result(profit_abs or 0.0),
    }


def forward(
    rate: float,
    requested_at: str,
    by_open: dict[int, Candle],
    now: datetime,
    horizons: list[int],
    cost_pct: float,
    timeframe_s: int,
) -> dict[str, Any]:
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
            point["result"] = MISSING
        elif closes_at > now or (window[-1] is None and latest < last_open):
            point["result"] = PENDING
        elif any(candle is None for candle in window):
            point["result"] = MISSING
        else:
            close = window[-1][2]
            gross = (close / rate - 1) * 100
            net = round(gross - cost_pct, 4)
            point.update(
                close=close,
                return_pct=round(gross, 4),
                net_pct=net,
                max_up_pct=round((max(candle[0] for candle in window) / rate - 1) * 100, 4),
                max_down_pct=round((min(candle[1] for candle in window) / rate - 1) * 100, 4),
                result=sign_result(net),
            )
        points.append(point)
    return {"reference_rate": rate, "round_trip_cost_pct": cost_pct, "horizons": points}


def effect(verdict: str, trade: dict[str, Any] | None, ahead: dict[str, Any]) -> dict[str, Any]:
    """What following the verdict would have changed, judged by the closed trade first, else the longest horizon."""
    if verdict == "izinkan":
        return {"effect": "sama_dengan_aturan", "basis": None}
    basis, result = None, PENDING
    if trade is not None and not trade["is_open"]:
        basis, result = "trade", trade["result"]
    elif trade is None and ahead["horizons"]:
        longest = ahead["horizons"][-1]
        basis, result = f"forward_{longest['candles']}", longest["result"]
    if result not in ("untung", "rugi", "impas"):
        return {"effect": result if result == MISSING else PENDING, "basis": basis}
    names = {
        "lewati": {"rugi": "menghindari_rugi", "untung": "melewatkan_untung", "impas": "impas"},
        "kecilkan": {"rugi": "mengurangi_rugi", "untung": "mengurangi_untung", "impas": "impas"},
    }
    return {"effect": names[verdict][result], "basis": basis}


def explain(
    decision: dict[str, Any],
    trade: dict[str, Any] | None,
    by_open: dict[int, Candle],
    now: datetime,
    horizons: list[int],
    cost_pct: float,
    timeframe_s: int,
) -> dict[str, Any]:
    shadowed = trade_result(trade)
    ahead = forward(decision["rate"], decision["requested_at"], by_open, now, horizons, cost_pct, timeframe_s)
    return {
        **decision,
        "quorum": quorum(decision),
        "would_take": would_take(decision),
        "outcome": {"trade": shadowed, "forward": ahead, **effect(decision["verdict"], shadowed, ahead)},
    }
