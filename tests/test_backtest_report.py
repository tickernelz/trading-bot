from __future__ import annotations

import pytest

from engine.backtest_report import bootstrap_mean_interval, closed_trade_drawdown, markdown, risk_denials, summarize

STATS = {
    "starting_balance": 1000.0,
    "backtest_start": "2025-01-01 00:00:00",
    "backtest_end": "2025-01-31 00:00:00",
    "max_drawdown_account": 0.25,
}


def _trade(day: int, ratio: float, profit: float, pair: str = "BTC/IDR", reason: str = "roi") -> dict:
    return {
        "pair": pair,
        "profit_ratio": ratio,
        "profit_abs": profit,
        "open_date": f"2025-01-{day:02d} 00:00:00+00:00",
        "close_date": f"2025-01-{day:02d} 06:00:00+00:00",
        "trade_duration": 360,
        "exit_reason": reason,
    }


TRADES = [
    _trade(1, 0.02, 100.0),
    _trade(2, -0.03, -300.0, reason="stop_loss"),
    _trade(3, 0.01, 50.0, pair="ETH/IDR"),
    _trade(4, -0.01, -100.0, pair="ETH/IDR", reason="exit_signal"),
    _trade(11, 0.03, 200.0),
]


def test_summary_reports_expectancy_spread_and_drawdown_from_trades():
    summary = summarize(TRADES, STATS, seed=1)
    assert summary["trades"] == 5
    assert summary["expectancy_pct"] == pytest.approx(0.4)
    assert summary["expectancy_idr"] == pytest.approx(-10.0)
    assert summary["win_rate_pct"] == pytest.approx(60.0)
    assert summary["quantiles_pct"]["p50"] == pytest.approx(1.0)
    assert summary["final_balance"] == pytest.approx(950.0)
    assert summary["total_return_pct"] == pytest.approx(-5.0)
    assert summary["drawdown"] == {"abs_idr": pytest.approx(350.0), "pct": pytest.approx(350 / 1100 * 100)}
    assert summary["per_pair"]["ETH/IDR"] == {"trades": 2, "expectancy_pct": pytest.approx(0.0)}
    assert summary["exit_reasons"] == {"roi": 3, "stop_loss": 1, "exit_signal": 1}
    assert summary["days_after_last_entry"] == 20.0
    assert summary["median_hold_hours"] == 6.0
    low, high = summary["expectancy_ci95_pct"]
    assert low < summary["expectancy_pct"] < high


def test_drawdown_follows_close_order_not_list_order():
    shuffled = [TRADES[4], TRADES[1], TRADES[0], TRADES[3], TRADES[2]]
    assert closed_trade_drawdown(shuffled, 1000.0) == closed_trade_drawdown(TRADES, 1000.0)


def test_bootstrap_interval_is_reproducible_and_needs_two_trades():
    values = [0.01, -0.02, 0.005, 0.03, -0.01]
    assert bootstrap_mean_interval(values, seed=7) == bootstrap_mean_interval(values, seed=7)
    assert bootstrap_mean_interval([0.01], seed=7) is None


def test_risk_denials_counted_per_breach():
    log = (
        "2025 - engine - WARNING - risk guard denied BTC/IDR: total_drawdown (daily loss 0.100%, drawdown 10.2%)\n"
        "2025 - engine - WARNING - risk guard denied ETH/IDR: daily_loss,total_drawdown (daily loss 1.1%, drawdown 11%)\n"
        "2025 - engine - WARNING - risk guard denied ETH/IDR: total_drawdown (daily loss 0.0%, drawdown 10.5%)\n"
    )
    assert risk_denials(log) == {"total_drawdown": 2, "daily_loss,total_drawdown": 1}


def test_markdown_renders_a_run_without_trades():
    empty = summarize([], STATS, seed=1)
    table = markdown(
        [{"id": "oos", "period": "out_of_sample", "fee": 0.0041, "risk_mode": "as_configured", "summary": empty}]
    )
    assert "| oos | out_of_sample | 0.41% | as_configured | 0 | - |" in table
