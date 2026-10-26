"""Per-trade metrics of the strategy search: net win rate, expectancy with bootstrap CI, stability and tiers."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine import search_plan as plan
from engine.risk import loss_ratio_at_stop

DAYS_PER_MONTH = 30.4375


@dataclass(frozen=True)
class Row:
    pair: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    profit: float
    reason: str
    regime: str
    fold: str | None


def wilson_lower(wins: int, n: int, z: float = 1.959963984540054) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def bootstrap_ci(
    values: np.ndarray, seed: int = plan.SEED, samples: int = plan.BOOTSTRAP_SAMPLES
) -> tuple[float, float]:
    if len(values) == 0:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    chunk = max(1, min(samples, 2_000_000 // len(values)))
    means = np.concatenate(
        [
            rng.choice(values, size=(min(chunk, samples - done), len(values)), replace=True).mean(axis=1)
            for done in range(0, samples, chunk)
        ]
    )
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def rolling_min_win_rate(wins: np.ndarray, window: int = plan.ROLLING_WINDOW) -> float | None:
    if len(wins) < window:
        return None
    sums = np.convolve(wins.astype(float), np.ones(window), mode="valid")
    return float(sums.min() / window)


def max_drawdown(rows: list[Row], stoploss: float, fee: float) -> float:
    """Realised-equity drawdown with the risk layer's sizing: risk_per_trade of equity lost at the stop."""
    per_stake = loss_ratio_at_stop(stoploss, fee)
    events = sorted(
        [(row.entry_time, 0, i) for i, row in enumerate(rows)] + [(row.exit_time, 1, i) for i, row in enumerate(rows)]
    )
    equity = peak = 1.0
    drawdown = 0.0
    stakes: dict[int, float] = {}
    for _, kind, i in events:
        if kind == 0:
            if len(stakes) >= plan.MAX_OPEN_TRADES:
                stakes[i] = 0.0
                continue
            free = equity - sum(stakes.values())
            stakes[i] = max(0.0, min(equity * plan.RISK_PER_TRADE / per_stake, free))
        elif i in stakes:
            equity += stakes.pop(i) * rows[i].profit
            peak = max(peak, equity)
            drawdown = max(drawdown, 1 - equity / peak)
    return drawdown


def summarize(rows: list[Row], start: pd.Timestamp, end: pd.Timestamp, stoploss: float, fee: float) -> dict:
    rows = sorted(rows, key=lambda row: row.entry_time)
    profits = np.array([row.profit for row in rows], dtype=float)
    n = len(rows)
    wins = profits > 0
    months = (end - start).total_seconds() / 86400 / DAYS_PER_MONTH
    out: dict = {"trades": n, "trades_per_month": round(n / months, 3) if months > 0 else None}
    if n == 0:
        return out
    gains = profits[wins].sum()
    losses = -profits[~wins].sum()
    entries = [start, *(row.entry_time for row in rows), end]
    gaps = [(b - a).total_seconds() / 86400 for a, b in zip(entries, entries[1:])]
    lo, hi = bootstrap_ci(profits)
    out.update(
        {
            "win_rate": float(wins.mean()),
            "wilson_lower": wilson_lower(int(wins.sum()), n),
            "mean": float(profits.mean()),
            "ci95": [lo, hi],
            "median": float(np.median(profits)),
            "profit_factor": float(gains / losses) if losses > 0 else None,
            "payoff_ratio": float(profits[wins].mean() / -profits[~wins].mean())
            if wins.any() and (~wins).any()
            else None,
            "largest_loss": float(profits.min()),
            "worst5_mean": float(np.sort(profits)[:5].mean()),
            "max_drawdown": max_drawdown(rows, stoploss, fee),
            "rolling30_min_win_rate": rolling_min_win_rate(wins),
            "longest_days_without_entry": round(max(gaps), 1),
            "days_without_entry_at_end": round(gaps[-1], 1),
            "exit_reasons": {
                reason: int(sum(row.reason == reason for row in rows))
                for reason in sorted({row.reason for row in rows})
            },
        }
    )
    return out


def groups(rows: list[Row], key: str) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for row in rows:
        value = getattr(row, key)
        if value is not None:
            out.setdefault(value, []).append(row)
    return out


def win_rate_of(rows: list[Row]) -> float | None:
    return sum(row.profit > 0 for row in rows) / len(rows) if rows else None


def target_checks(target_rows: list[Row], fold_rows: list[Row], stability_sets: list[list[Row]]) -> dict:
    """Locked target: (a) on target_rows, (b) per fold, (c) and (d) on every stability set."""
    n = len(target_rows)
    wins = sum(row.profit > 0 for row in target_rows)
    per_pair = {pair: len(rows) for pair, rows in groups(target_rows, "pair").items()}
    pairs_ok = sum(count >= plan.TARGET_MIN_TRADES_PER_PAIR for count in per_pair.values()) >= plan.TARGET_MIN_PAIRS
    a = (
        (
            n >= plan.TARGET_MIN_TRADES
            and pairs_ok
            and wins / n >= plan.TARGET_WIN_RATE
            and wilson_lower(wins, n) >= plan.TARGET_WILSON_LOWER
        )
        if n
        else False
    )
    by_fold = groups(fold_rows, "fold")
    fold_rates = [win_rate_of(by_fold.get(fold)) for fold, _, _ in plan.FOLDS]
    measured = [rate for rate in fold_rates if rate is not None]
    fold_std = float(np.std(measured, ddof=1)) if len(measured) > 1 else None
    b = (
        all(rate is not None and rate >= plan.TARGET_FOLD_WIN_RATE for rate in fold_rates)
        and fold_std is not None
        and fold_std <= plan.TARGET_FOLD_STD
    )
    c_values, d_ok = [], True
    regime_rates: list[dict] = []
    for rows in stability_sets:
        ordered = sorted(rows, key=lambda row: row.entry_time)
        c_values.append(rolling_min_win_rate(np.array([row.profit > 0 for row in ordered])))
        rates = {}
        for regime, members in groups(ordered, "regime").items():
            rates[regime] = {"trades": len(members), "win_rate": win_rate_of(members)}
            if len(members) >= plan.REGIME_MIN_TRADES and win_rate_of(members) < plan.TARGET_REGIME_WIN_RATE:
                d_ok = False
        regime_rates.append(rates)
    c = all(value is not None and value >= plan.TARGET_ROLLING_MIN for value in c_values)
    return {
        "a_win_rate": a,
        "b_folds": b,
        "c_rolling": c,
        "d_regimes": d_ok,
        "met": a and b and c and d_ok,
        "trades": n,
        "win_rate": wins / n if n else None,
        "wilson_lower": wilson_lower(wins, n),
        "trades_per_pair": per_pair,
        "fold_win_rates": dict(zip([fold for fold, _, _ in plan.FOLDS], fold_rates)),
        "fold_std": fold_std,
        "rolling30_min": c_values,
        "regimes": regime_rates,
    }


def tier(target_met: bool, mean: float, ci_low: float, null_beaten: bool | None = None) -> str:
    """T1 also requires the null p95 to be beaten when a null was run; a T1 that fails it is reported as T2."""
    if not target_met:
        return "T4"
    if mean <= 0:
        return "T3"
    if ci_low > 0 and null_beaten is not False:
        return "T1"
    return "T2"
