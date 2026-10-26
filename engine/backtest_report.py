"""Summarise exported Freqtrade backtest results into per-trade expectancy, spread, and drawdown."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from freqtrade.data.btanalysis import load_backtest_stats

STRATEGY = "SwingEmaRsi"
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
RESAMPLES = 10_000
DENIAL = re.compile(r"risk guard denied \S+: (\S+) ")


def load_run(directory: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the trades and statistics of the latest backtest exported into directory."""
    stats = load_backtest_stats(directory)["strategy"][STRATEGY]
    return stats["trades"], stats


def bootstrap_mean_interval(values: list[float], seed: int, level: float = 0.95) -> tuple[float, float] | None:
    """Percentile bootstrap interval of the mean; None below two observations."""
    if len(values) < 2:
        return None
    sample = np.asarray(values, dtype=float)
    picks = np.random.default_rng(seed).integers(0, len(sample), size=(RESAMPLES, len(sample)))
    means = sample[picks].mean(axis=1)
    tail = (1 - level) / 2
    return float(np.quantile(means, tail)), float(np.quantile(means, 1 - tail))


def closed_trade_drawdown(trades: list[dict[str, Any]], starting_balance: float) -> dict[str, float]:
    """Largest peak-to-trough fall of the balance after each closed trade, in IDR and percent of the peak."""
    balance = peak = starting_balance
    worst_abs = worst_pct = 0.0
    for trade in sorted(trades, key=lambda item: item["close_date"]):
        balance += trade["profit_abs"]
        peak = max(peak, balance)
        worst_abs = max(worst_abs, peak - balance)
        worst_pct = max(worst_pct, (peak - balance) / peak * 100)
    return {"abs_idr": worst_abs, "pct": worst_pct}


def risk_denials(log_text: str) -> dict[str, int]:
    """Count entries the risk guard denied, per breach list, from a Freqtrade log."""
    return dict(Counter(match.group(1) for match in DENIAL.finditer(log_text)))


def _scaled(bounds: tuple[float, float] | None) -> list[float] | None:
    return None if bounds is None else [bounds[0] * 100, bounds[1] * 100]


def _date(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def summarize(trades: list[dict[str, Any]], stats: dict[str, Any], seed: int, log_text: str = "") -> dict[str, Any]:
    """Compute the per-run figures the stage 2 report shows; profit ratios are after the run's fee."""
    ratios = [float(trade["profit_ratio"]) for trade in trades]
    start = float(stats["starting_balance"])
    final = start + sum(float(trade["profit_abs"]) for trade in trades)
    end = _date(stats["backtest_end"])
    entries = [_date(trade["open_date"]) for trade in trades]
    summary: dict[str, Any] = {
        "backtest_start": stats["backtest_start"],
        "backtest_end": stats["backtest_end"],
        "trades": len(trades),
        "wins": sum(1 for ratio in ratios if ratio > 0),
        "starting_balance": start,
        "final_balance": final,
        "total_return_pct": (final / start - 1) * 100,
        "drawdown": closed_trade_drawdown(trades, start),
        "freqtrade_max_drawdown_account_pct": float(stats.get("max_drawdown_account", 0.0)) * 100,
        "risk_denials": risk_denials(log_text),
        "rejected_signals": stats.get("rejected_signals"),
        "timedout_entry_orders": stats.get("timedout_entry_orders"),
        "last_entry": max(entries).isoformat() if entries else None,
        "days_after_last_entry": round((end - max(entries)).total_seconds() / 86400, 1) if entries else None,
        "exit_reasons": dict(Counter(trade["exit_reason"] for trade in trades)),
        "per_pair": {},
    }
    if not trades:
        return summary
    sample = np.asarray(ratios)
    summary.update(
        {
            "win_rate_pct": summary["wins"] / len(trades) * 100,
            "expectancy_pct": float(sample.mean()) * 100,
            "expectancy_idr": float(np.mean([trade["profit_abs"] for trade in trades])),
            "expectancy_ci95_pct": _scaled(bootstrap_mean_interval(ratios, seed)),
            "std_pct": float(sample.std(ddof=1)) * 100 if len(trades) > 1 else None,
            "quantiles_pct": {f"p{round(q * 100):02d}": float(np.quantile(sample, q)) * 100 for q in QUANTILES},
            "min_pct": float(sample.min()) * 100,
            "max_pct": float(sample.max()) * 100,
            "median_hold_hours": float(np.median([trade["trade_duration"] for trade in trades])) / 60,
        }
    )
    for pair in sorted({trade["pair"] for trade in trades}):
        chosen = [float(trade["profit_ratio"]) for trade in trades if trade["pair"] == pair]
        summary["per_pair"][pair] = {"trades": len(chosen), "expectancy_pct": float(np.mean(chosen)) * 100}
    return summary


def _pct(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:+.{digits}f}%"


def _plain(value: float | None, suffix: str = "", digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def _interval(bounds: list[float] | None) -> str:
    return "-" if not bounds else f"{bounds[0]:+.3f}% .. {bounds[1]:+.3f}%"


def markdown(runs: list[dict[str, Any]]) -> str:
    """Render the summary tables that the stage 2 document quotes."""
    lines = [
        "| Run | Period | Fee per side | Risk mode | Trades | Expectancy per trade | 95% CI | Median | Win rate "
        "| Max drawdown | Total return | Days after last entry |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        s = run["summary"]
        lines.append(
            f"| {run['id']} | {run['period']} | {run['fee'] * 100:.2f}% | {run['risk_mode']} | {s['trades']} "
            f"| {_pct(s.get('expectancy_pct'))} | {_interval(s.get('expectancy_ci95_pct'))} "
            f"| {_pct(s.get('quantiles_pct', {}).get('p50'))} | {_plain(s.get('win_rate_pct'), '%')} "
            f"| {_plain(s['drawdown']['pct'], '%', 2)} | {_pct(s['total_return_pct'], 2)} "
            f"| {_plain(s['days_after_last_entry'])} |"
        )
    lines += [
        "",
        "| Run | p05 | p25 | p75 | p95 | Std dev | Min | Max | Median holding time (h) | Risk gate rejections |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        s = run["summary"]
        q = s.get("quantiles_pct", {})
        denials = ", ".join(f"{key} {count}" for key, count in sorted(s["risk_denials"].items())) or "0"
        lines.append(
            f"| {run['id']} | {_pct(q.get('p05'))} | {_pct(q.get('p25'))} | {_pct(q.get('p75'))} | {_pct(q.get('p95'))} "
            f"| {_plain(s.get('std_pct'), '%', 3)} | {_pct(s.get('min_pct'))} | {_pct(s.get('max_pct'))} "
            f"| {_plain(s.get('median_hold_hours'))} | {denials} |"
        )
    lines += ["", "| Run | Pair | Trade | Ekspektasi per trade |", "| --- | --- | --- | --- |"]
    for run in runs:
        for pair, figures in run["summary"]["per_pair"].items():
            lines.append(f"| {run['id']} | {pair} | {figures['trades']} | {_pct(figures['expectancy_pct'])} |")
    lines += ["", "| Run | Alasan exit |", "| --- | --- |"]
    for run in runs:
        reasons = ", ".join(f"{key} {count}" for key, count in sorted(run["summary"]["exit_reasons"].items()))
        lines.append(f"| {run['id']} | {reasons or '-'} |")
    return "\n".join(lines) + "\n"
