"""Pure transforms from Freqtrade payloads to the gateway contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.risk import ClosedTrade, RiskState, assess
from engine.settings import Settings
from gateway.redact import key_last4

CANDLE_COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ema_fast",
    "ema_slow",
    "rsi",
    "enter_long",
    "exit_long",
]
SECRET_FIELDS = ("api_key",)


def iso_ms(ms: int | float) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_text(value: str | None) -> str | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def candle_rows(frame: dict[str, Any]) -> list[list[Any]]:
    columns = frame.get("columns") or []
    index = {name: position for position, name in enumerate(columns)}
    rows = []
    for raw in frame.get("data") or []:
        stamp = raw[index["__date_ts"]] if "__date_ts" in index else None
        date = iso_ms(stamp).replace(".000Z", "Z") if stamp is not None else str(raw[index["date"]])
        rows.append([date, *(raw[index[name]] if name in index else None for name in CANDLE_COLUMNS[1:])])
    return rows


def candle_frame(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair": frame.get("pair"),
        "timeframe": frame.get("timeframe"),
        "strategy": frame.get("strategy"),
        "columns": CANDLE_COLUMNS,
        "length": frame.get("length"),
        "last_analyzed": iso_text(frame.get("last_analyzed")),
        "data": candle_rows(frame),
    }


def open_trade(trade: dict[str, Any], now_ms: int) -> dict[str, Any]:
    value = trade.get("open_trade_value") or 0
    profit = trade.get("profit_abs") or 0
    return {
        **trade,
        "profit_pct_now": round(profit / value * 100, 4) if value else None,
        "age_s": max(0, int((now_ms - (trade.get("open_timestamp") or now_ms)) / 1000)),
    }


def closed_trades(trades: list[dict[str, Any]]) -> list[ClosedTrade]:
    return [
        ClosedTrade(datetime.fromtimestamp(trade["close_timestamp"] / 1000, UTC), trade.get("close_profit_abs") or 0.0)
        for trade in trades
        if not trade.get("is_open") and trade.get("close_timestamp")
    ]


def risk_view(settings: Settings, state: RiskState, now: datetime) -> dict[str, Any]:
    return {
        "as_of": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "equity": round(state.equity, 2),
        "peak_equity": round(state.peak_equity, 2),
        "day_start": state.day_start.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "day_start_equity": round(state.day_start_equity, 2),
        "daily_pnl": round(state.daily_pnl, 2),
        "daily_loss_pct": round(state.daily_loss_pct, 4),
        "drawdown_pct": round(state.drawdown_pct, 4),
        "limits": {
            "max_daily_loss_pct": settings.risk.max_daily_loss_pct,
            "max_total_drawdown_pct": settings.risk.max_total_drawdown_pct,
            "risk_per_trade_pct": settings.risk.risk_per_trade_pct,
            "on_breach": settings.risk.on_breach,
            "timezone": settings.risk.daily_reset_timezone,
        },
        "breaches": list(state.breaches),
        "entries_allowed": state.entries_allowed,
    }


def compute_risk(settings: Settings, trades: list[dict[str, Any]], open_pnl: float, now: datetime) -> RiskState:
    return assess(settings.risk, settings.capital.initial_idr, closed_trades(trades), open_pnl, now)


def equity_points(
    initial: float, trades: list[dict[str, Any]], open_pnl: float, start: datetime, now: datetime
) -> list[list[Any]]:
    start_ms = start.timestamp() * 1000
    realized = initial
    at_start = initial
    points: list[list[Any]] = []
    for trade in sorted(
        (item for item in trades if not item.get("is_open") and item.get("close_timestamp")),
        key=lambda item: item["close_timestamp"],
    ):
        realized += trade.get("close_profit_abs") or 0.0
        if trade["close_timestamp"] < start_ms:
            at_start = realized
        elif trade["close_timestamp"] <= now.timestamp() * 1000:
            points.append([iso_ms(trade["close_timestamp"]), round(realized, 2)])
    return [
        [iso_ms(start_ms), round(at_start, 2)],
        *points,
        [iso_ms(now.timestamp() * 1000), round(realized + open_pnl, 2)],
    ]


def redacted_settings(settings: Settings) -> dict[str, Any]:
    data = settings.model_dump(mode="json")
    for provider, model in zip(data["providers"], settings.providers, strict=True):
        provider["api_key"] = None
        provider["api_key_configured"] = model.api_key is not None
        provider["api_key_last4"] = key_last4(model.api_key.get_secret_value()) if model.api_key is not None else None
    return data


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        out = {}
        for position, item in enumerate(value):
            label = item.get("id", position)
            out.update(flatten(item, f"{prefix}[{label}]"))
        return out
    return {prefix: value}


def config_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    keys = sorted(set(old) | set(new))
    return [{"key": key, "old": old.get(key), "new": new.get(key)} for key in keys if old.get(key) != new.get(key)]
