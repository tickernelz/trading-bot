"""Stress scenario: every open position's price falls by a fixed percentage from now."""

from __future__ import annotations

from typing import Any

from analytics.trades import OpenPosition, RiskInputs
from engine.settings import RiskSettings


def shocked_rate(position: OpenPosition, drop_pct: float) -> float:
    return position.rate * (1 - drop_pct / 100)


def exit_pnl(position: OpenPosition, drop_pct: float, stop_fills: bool) -> float:
    shocked = shocked_rate(position, drop_pct)
    if stop_fills and position.stop_abs is not None and shocked < position.stop_abs:
        return position.pnl_at(position.stop_abs)
    return position.pnl_at(shocked)


def state_view(risk: RiskSettings, inputs: RiskInputs, open_pnl: float) -> dict[str, Any]:
    state = inputs.assess(risk, open_pnl)
    return {
        "open_pnl": open_pnl,
        "equity": state.equity,
        "equity_change_idr": state.equity - inputs.assess(risk).equity,
        "daily_loss_pct": state.daily_loss_pct,
        "drawdown_pct": state.drawdown_pct,
        "breaches": list(state.breaches),
        "entries_allowed": state.entries_allowed,
    }


def stress(risk: RiskSettings, inputs: RiskInputs, drop_pct: float) -> dict[str, Any]:
    """Evaluate the book after a uniform fall, with the stop filling at its price and with the stop missed."""
    rows = []
    for position in inputs.positions:
        rows.append(
            {
                "trade_id": position.trade_id,
                "pair": position.pair,
                "rate_now": position.rate,
                "rate_after": shocked_rate(position, drop_pct),
                "stop_abs": position.stop_abs,
                "pnl_now": position.pnl,
                "pnl_stop_fills": exit_pnl(position, drop_pct, True),
                "pnl_stop_missed": exit_pnl(position, drop_pct, False),
            }
        )
    return {
        "as_of": inputs.now.isoformat(),
        "drop_pct": drop_pct,
        "positions": rows,
        "now": state_view(risk, inputs, inputs.open_pnl),
        "stop_fills": state_view(risk, inputs, sum(row["pnl_stop_fills"] for row in rows)),
        "stop_missed": state_view(risk, inputs, sum(row["pnl_stop_missed"] for row in rows)),
        "assumptions": [
            "semua posisi terbuka turun sebesar drop_pct dari harga sekarang secara bersamaan",
            "stop_fills: stop terisi di harga stop bila harga jatuh melewatinya",
            "stop_missed: stop tidak terisi (celah harga), posisi dinilai di harga jatuh",
            "tidak ada entry baru dan tidak ada exit lain; biaya tutup memakai fee_close trade",
        ],
    }
