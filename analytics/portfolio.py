"""Per-pair view of the open book for a configuration with several pairs."""

from __future__ import annotations

from typing import Any

from analytics.trades import OpenPosition
from engine.risk import RiskState, loss_ratio_at_stop
from engine.settings import Settings


def stop_risk(position: OpenPosition) -> float | None:
    if position.stop_pct is None or not -100 < position.stop_pct < 0:
        return None
    return position.stake * loss_ratio_at_stop(position.stop_pct / 100, position.fee_open)


def portfolio(settings: Settings, state: RiskState, positions: tuple[OpenPosition, ...]) -> dict[str, Any]:
    """Group open positions by pair against equity, slots and the configured concentration limit."""
    limit = settings.analytics.portfolio.max_pair_share_pct
    equity = state.equity
    rows: dict[str, dict[str, Any]] = {
        pair: {"pair": pair, "open_trades": 0, "stake_idr": 0.0, "pnl_idr": 0.0, "risk_at_stop_idr": 0.0}
        for pair in settings.exchange.pairs
    }
    unmanaged = []
    for position in positions:
        row = rows.get(position.pair)
        if row is None:
            unmanaged.append(position.pair)
            row = rows.setdefault(
                position.pair,
                {"pair": position.pair, "open_trades": 0, "stake_idr": 0.0, "pnl_idr": 0.0, "risk_at_stop_idr": 0.0},
            )
        row["open_trades"] += 1
        row["stake_idr"] += position.stake
        row["pnl_idr"] += position.pnl
        row["risk_at_stop_idr"] += stop_risk(position) or 0.0
    exposure = sum(row["stake_idr"] for row in rows.values())
    for row in rows.values():
        row["share_of_equity_pct"] = row["stake_idr"] / equity * 100 if equity > 0 else 0.0
        row["over_limit"] = row["share_of_equity_pct"] > limit
    return {
        "equity": equity,
        "pairs_configured": len(settings.exchange.pairs),
        "slots_used": len(positions),
        "slots_max": settings.risk.max_open_trades,
        "exposure_idr": exposure,
        "exposure_pct": exposure / equity * 100 if equity > 0 else 0.0,
        "cash_idr": equity - exposure,
        "max_pair_share_pct": limit,
        "pairs": sorted(rows.values(), key=lambda row: (-row["stake_idr"], row["pair"])),
        "pairs_not_in_config": sorted(set(unmanaged)),
    }
