"""What the risk limits mean in rupiah and what a changed limit would have done to the current book."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from analytics.errors import AnalyticsError
from analytics.trades import OpenPosition, RiskInputs
from engine.risk import RiskState
from engine.settings import RiskSettings

TUNABLE = ("max_daily_loss_pct", "max_total_drawdown_pct", "risk_per_trade_pct", "max_open_trades")


@dataclass(frozen=True)
class LimitsIdr:
    max_daily_loss_idr: float
    daily_floor_idr: float
    max_total_drawdown_idr: float
    drawdown_floor_idr: float
    risk_per_trade_idr: float
    max_open_trades: int
    max_open_risk_idr: float
    trades_to_daily_limit: float


def limits_idr(risk: RiskSettings, state: RiskState) -> LimitsIdr:
    """Express the percentage limits in rupiah against the equity the engine uses for each of them."""
    daily = state.day_start_equity * risk.max_daily_loss_pct / 100
    drawdown = state.peak_equity * risk.max_total_drawdown_pct / 100
    per_trade = state.equity * risk.risk_per_trade_pct / 100
    return LimitsIdr(
        max_daily_loss_idr=daily,
        daily_floor_idr=state.day_start_equity - daily,
        max_total_drawdown_idr=drawdown,
        drawdown_floor_idr=state.peak_equity - drawdown,
        risk_per_trade_idr=per_trade,
        max_open_trades=risk.max_open_trades,
        max_open_risk_idr=per_trade * risk.max_open_trades,
        trades_to_daily_limit=daily / per_trade if per_trade > 0 else 0.0,
    )


def pnl_if_stopped(position: OpenPosition) -> float | None:
    if position.stop_abs is None:
        return None
    return position.pnl_at(position.stop_abs)


def open_risk_at_stop(positions: tuple[OpenPosition, ...]) -> tuple[float, int]:
    """Return the rupiah lost from now if every open stop fills, and how many positions have no stop."""
    lost = 0.0
    missing = 0
    for position in positions:
        stopped = pnl_if_stopped(position)
        if stopped is None:
            missing += 1
            continue
        lost += max(0.0, position.pnl - stopped)
    return lost, missing


def scenario(risk: RiskSettings, inputs: RiskInputs) -> dict[str, Any]:
    state = inputs.assess(risk)
    lost, missing = open_risk_at_stop(inputs.positions)
    stopped = inputs.assess(risk, inputs.open_pnl - lost)
    return {
        "risk": risk.model_dump(),
        "limits_idr": asdict(limits_idr(risk, state)),
        "now": {
            "daily_loss_pct": state.daily_loss_pct,
            "drawdown_pct": state.drawdown_pct,
            "breaches": list(state.breaches),
            "entries_allowed": state.entries_allowed,
        },
        "all_stops_hit": {
            "additional_loss_idr": lost,
            "positions_without_stop": missing,
            "daily_loss_pct": stopped.daily_loss_pct,
            "drawdown_pct": stopped.drawdown_pct,
            "breaches": list(stopped.breaches),
        },
    }


def propose(current: RiskSettings, overrides: dict[str, float | int]) -> RiskSettings:
    unknown = sorted(set(overrides) - set(TUNABLE))
    if unknown:
        raise AnalyticsError(
            422, "invalid_request", f"cannot preview {', '.join(unknown)}; allowed: {', '.join(TUNABLE)}"
        )
    try:
        return RiskSettings.model_validate({**current.model_dump(), **overrides})
    except ValueError as exc:
        raise AnalyticsError(422, "invalid_request", str(exc)) from exc


def whatif_limits(current: RiskSettings, overrides: dict[str, float | int], inputs: RiskInputs) -> dict[str, Any]:
    """Compare the configured limits with a proposal on the same trades, without changing anything."""
    proposed = propose(current, overrides)
    before = scenario(current, inputs)
    after = scenario(proposed, inputs)
    delta = {
        key: after["limits_idr"][key] - before["limits_idr"][key]
        for key in before["limits_idr"]
        if isinstance(before["limits_idr"][key], (int, float))
    }
    return {
        "as_of": inputs.now.isoformat(),
        "equity": inputs.assess(current).equity,
        "open_positions": len(inputs.positions),
        "current": before,
        "proposed": after,
        "delta_idr": delta,
        "changed": sorted(overrides),
    }
