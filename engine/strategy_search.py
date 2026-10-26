"""Run the locked strategy search: walk-forward, controls, validation, and the single runs on untouched data."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from freqtrade.strategy import merge_informative_pair

from engine import search_metrics as metrics
from engine import search_plan as plan
from engine.search_plan import Candidate
from engine.signals import resample, rule_frame
from engine.simulate import Costs, Exits, Trade, exits_for, simulate
from engine.strategies.swing_ema_rsi import swing_entry, swing_exit, swing_indicators

REPO = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = REPO / "docs" / "strategy-research" / "ledger.jsonl"
SWING_EXITS = Exits(stoploss=-0.03, roi=((0, 0.05), (480, 0.025), (1440, 0.012)), roi_net_of_fee=True)
HOLDOUT_KINDS = ("holdout_started", "holdout")
PRESAMPLE_KINDS = ("presample_started", "presample")
COMPARE_ROWS = 48


@dataclass
class Signals:
    candles: pd.DataFrame
    enter: np.ndarray
    exit_signal: np.ndarray
    atr: np.ndarray
    exits: Exits


class HoldoutUsed(Exception):
    """Raised when an untouched period was already run for another configuration."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair_file(datadir: Path, pair: str) -> Path:
    return datadir / f"{pair.replace('/', '_')}-1h.feather"


def load_candles(datadir: Path, end: pd.Timestamp, pairs: tuple[str, ...] = plan.PAIRS) -> dict[str, pd.DataFrame]:
    out = {}
    for pair in pairs:
        frame = pd.read_feather(pair_file(datadir, pair))
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        out[pair] = frame[frame["date"] < end].sort_values("date").reset_index(drop=True)
    return out


def load_fear_greed(path: Path) -> pd.DataFrame:
    raw = json.loads(path.read_text(encoding="utf-8"))["data"]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime([int(row["timestamp"]) for row in raw], unit="s", utc=True),
            "fg": [float(row["value"]) for row in raw],
        }
    )
    return frame.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def regime_by_hour(btc: pd.DataFrame) -> pd.Series:
    """BTC/IDR daily regime known at each 1h close: bull, bear, or range."""
    daily = resample(btc, "1d")
    sma = daily["close"].rolling(200).mean()
    rising = sma > sma.shift(20)
    falling = sma < sma.shift(20)
    label = np.where(
        (daily["close"] > sma) & rising, "bull", np.where((daily["close"] < sma) & falling, "bear", "range")
    )
    label = np.where(sma.isna(), "unknown", label)
    merged = merge_informative_pair(btc[["date"]], pd.DataFrame({"date": daily["date"], "regime": label}), "1h", "1d")
    return pd.Series(merged["regime_1d"].fillna("unknown").to_numpy(), index=btc["date"])


def fold_of(time: pd.Timestamp) -> str | None:
    for name, start, end in plan.FOLDS:
        if pd.Timestamp(start, tz="UTC") <= time < pd.Timestamp(end, tz="UTC"):
            return name
    return None


def build_signals(
    candidate: Candidate,
    candles: dict[str, pd.DataFrame],
    fear_greed: pd.DataFrame,
    by_id: dict[str, Candidate],
    shuffle: int = 0,
    window: int | None = None,
) -> dict[str, Signals]:
    """Signals per pair; window keeps only the last candles of each timeframe, as a live start sees them."""
    if candidate.kind == "random":
        source = build_signals(by_id[candidate.exits_from], candles, fear_greed, by_id)
        return randomize(source, candidate.random_rate, shuffle)
    out = {}
    for pair, history in candles.items():
        frame = history if window is None else history.tail(window).reset_index(drop=True)
        if candidate.kind == "swing":
            analyzed = swing_indicators(frame.copy())
            enter = swing_entry(analyzed).fillna(False).to_numpy(dtype=bool)
            exit_signal = swing_exit(analyzed).fillna(False).to_numpy(dtype=bool)
            out[pair] = Signals(frame, enter, exit_signal, np.full(len(frame), np.nan), SWING_EXITS)
            continue
        spec = candidate.spec
        informative = {tf: resample(history, tf) for tf in spec.informative_timeframes}
        if window is not None:
            informative = {tf: candles_tf.tail(window).reset_index(drop=True) for tf, candles_tf in informative.items()}
        signals = rule_frame(frame, spec, informative)
        enter = signals["enter"].to_numpy(dtype=bool)
        if candidate.fear_greed_max is not None:
            fg = merge_informative_pair(frame[["date"]], fear_greed, "1h", "1d")["fg_1d"].to_numpy(dtype=float)
            enter = enter & (np.nan_to_num(fg, nan=101.0) <= candidate.fear_greed_max)
        out[pair] = Signals(
            frame,
            enter,
            signals["exit_signal"].to_numpy(dtype=bool),
            signals["atr"].to_numpy(dtype=float),
            exits_for(spec),
        )
    return out


def randomize(source: dict[str, Signals], rate: float | dict[str, float], shuffle: int) -> dict[str, Signals]:
    out = {}
    for index, (pair, signals) in enumerate(source.items()):
        rng = np.random.default_rng([plan.SEED, index, shuffle])
        pair_rate = rate[pair] if isinstance(rate, dict) else rate
        enter = rng.random(len(signals.enter)) < pair_rate
        out[pair] = Signals(signals.candles, enter, signals.exit_signal, signals.atr, signals.exits)
    return out


def trades_of(signals: dict[str, Signals], costs: Costs) -> list[Trade]:
    out = []
    for pair, item in signals.items():
        out += simulate(pair, item.candles, item.enter, item.exit_signal, item.atr, item.exits, costs)
    return out


def rows_of(trades: list[Trade], costs: Costs, regimes: pd.Series, start: pd.Timestamp, end: pd.Timestamp):
    return [
        metrics.Row(
            pair=trade.pair,
            signal_time=trade.signal_time,
            entry_time=trade.entry_time,
            exit_time=trade.exit_time,
            profit=trade.profit(costs),
            reason=trade.reason,
            regime=str(regimes.get(trade.signal_time, "unknown")),
            fold=fold_of(trade.entry_time),
        )
        for trade in trades
        if start <= trade.entry_time < end
    ]


def stoploss_of(signals: dict[str, Signals]) -> float:
    return next(iter(signals.values())).exits.stoploss


def mean_fee(costs: Costs) -> float:
    return (costs.buy + costs.sell) / 2


def report(rows, start, end, stoploss, costs: Costs) -> dict:
    fee = mean_fee(costs)
    return {
        "all": metrics.summarize(rows, start, end, stoploss, fee),
        "folds": {
            name: metrics.summarize(
                group, pd.Timestamp(fold_start, tz="UTC"), pd.Timestamp(fold_end, tz="UTC"), stoploss, fee
            )
            for name, fold_start, fold_end in plan.FOLDS
            for group in [[row for row in rows if row.fold == name]]
            if start <= pd.Timestamp(fold_start, tz="UTC") < end
        },
        "pairs": {
            pair: metrics.summarize(group, start, end, stoploss, fee)
            for pair, group in metrics.groups(rows, "pair").items()
        },
        "regimes": {
            regime: metrics.summarize(group, start, end, stoploss, fee)
            for regime, group in metrics.groups(rows, "regime").items()
        },
    }


def buy_and_hold(candles: dict[str, pd.DataFrame], costs: Costs, windows: list[tuple[str, pd.Timestamp, pd.Timestamp]]):
    out = {}
    for name, start, end in windows:
        out[name] = {}
        for pair, frame in candles.items():
            window = frame[(frame["date"] >= start) & (frame["date"] < end)]
            if len(window):
                out[name][pair] = costs.profit_ratio(float(window["open"].iloc[0]), float(window["close"].iloc[-1]))
    return out


def null_distribution(selected: dict[str, Signals], costs, regimes, start, end):
    """Random entries at the selected rate with the selected exits, one series per shuffle."""
    shuffles = plan.NULL_SHUFFLES
    rates = {}
    for pair, item in selected.items():
        in_period = (item.candles["date"] >= start) & (item.candles["date"] < end)
        bars = int(in_period.sum())
        rates[pair] = float(item.enter[in_period.to_numpy()].sum()) / bars if bars else 0.0
    means, win_rates, counts = [], [], []
    for shuffle in range(shuffles):
        rows = rows_of(trades_of(randomize(selected, rates, shuffle + 1), costs), costs, regimes, start, end)
        profits = np.array([row.profit for row in rows])
        means.append(float(profits.mean()) if len(profits) else np.nan)
        win_rates.append(float((profits > 0).mean()) if len(profits) else np.nan)
        counts.append(len(rows))
    means_a, wr_a = np.array(means), np.array(win_rates)
    return {
        "shuffles": shuffles,
        "entry_rate_per_bar": rates,
        "mean_p95": float(np.nanpercentile(means_a, 95)),
        "mean_p50": float(np.nanpercentile(means_a, 50)),
        "win_rate_p95": float(np.nanpercentile(wr_a, 95)),
        "win_rate_p50": float(np.nanpercentile(wr_a, 50)),
        "trades_median": float(np.median(counts)),
    }


def tier_on(rows: list[metrics.Row], checks: dict, null: dict | None = None) -> dict:
    summary = metrics.summarize(rows, plan.WALK_FORWARD_START, plan.HOLDOUT_START, -0.1, 0.003)
    mean = summary.get("mean", 0.0)
    ci_low = summary.get("ci95", [0.0, 0.0])[0]
    adjusted = metrics.adjusted_lower(np.array([row.profit for row in rows], dtype=float), plan.cumulative_trials())
    beaten = None if null is None else bool(mean > null["mean_p95"])
    return {
        "tier": metrics.tier(checks["met"], mean, min(ci_low, adjusted), beaten),
        "mean": mean,
        "ci_low": ci_low,
        "ci_low_adjusted": adjusted,
        "trials": plan.cumulative_trials(),
        "null_beaten": beaten,
    }


def rank_key(entry: dict) -> tuple:
    primary = entry["costs"][plan.PRIMARY_COST]["all"]
    return (entry["wf_tier"]["tier"], -primary.get("mean", -1.0), primary.get("max_drawdown", 1.0))


def eligible(entry: dict) -> bool:
    checks = entry["wf_checks"]
    per_pair = checks["trades_per_pair"]
    pairs = sum(count >= plan.TARGET_MIN_TRADES_PER_PAIR for count in per_pair.values())
    return entry["deployable"] and checks["trades"] >= plan.TARGET_MIN_TRADES and pairs >= plan.TARGET_MIN_PAIRS


def walk_forward(args, ledger_entry: dict) -> dict:
    candles = load_candles(args.datadir, plan.HOLDOUT_START)
    fear_greed = load_fear_greed(args.fear_greed)
    regimes = regime_by_hour(candles[plan.REGIME_PAIR])
    by_id = {candidate.id: candidate for candidate in plan.candidates()}
    start, end = plan.WALK_FORWARD_START, plan.HOLDOUT_START
    results, trade_dump, kept_signals, kept_rows = [], {}, {}, {}
    for candidate in by_id.values():
        if candidate.kind == "buy_hold":
            continue
        signals = build_signals(candidate, candles, fear_greed, by_id)
        kept_signals[candidate.id] = signals
        stoploss = stoploss_of(signals)
        entry = {
            "id": candidate.id,
            "family": candidate.family,
            "kind": candidate.kind,
            "deployable": candidate.deployable,
            "spec": candidate.spec.model_dump() if candidate.spec else None,
            "fear_greed_max": candidate.fear_greed_max,
            "costs": {},
        }
        base_trades = trades_of(signals, plan.COSTS[plan.PRIMARY_COST])
        for name, costs in plan.COSTS.items():
            trades = trades_of(signals, costs) if candidate.kind == "swing" else base_trades
            rows = rows_of(trades, costs, regimes, start, end)
            entry["costs"][name] = report(rows, start, end, stoploss, costs)
            if name == plan.PRIMARY_COST:
                primary_rows = rows
        checks = metrics.target_checks(primary_rows, primary_rows, [primary_rows])
        entry["wf_checks"] = checks
        entry["wf_tier"] = tier_on(primary_rows, checks)
        kept_rows[candidate.id] = primary_rows
        entry["open_at_end"] = sum(row.reason == "end" for row in primary_rows)
        trade_dump[candidate.id] = [
            [
                row.pair,
                row.signal_time.isoformat(),
                row.entry_time.isoformat(),
                row.exit_time.isoformat(),
                round(row.profit, 8),
                row.reason,
                row.regime,
                row.fold,
            ]
            for row in primary_rows
        ]
        results.append(entry)
        print(f"{candidate.id}: {checks['trades']} trades, tier {entry['wf_tier']['tier']}", file=sys.stderr)
    pool = [entry for entry in results if eligible(entry)]
    ranked = sorted(pool, key=rank_key)
    selected = ranked[0] if ranked else None
    windows = [(name, pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for name, a, b in plan.FOLDS]
    out = {
        "round": plan.ROUND,
        "period": [start.isoformat(), end.isoformat()],
        "pairs": list(plan.PAIRS),
        "candidates": len(by_id),
        "cumulative_trials": plan.cumulative_trials(),
        "results": results,
        "buy_and_hold": {
            name: buy_and_hold(candles, costs, windows + [("walk_forward", start, end)])
            for name, costs in plan.COSTS.items()
        },
        "eligible": [entry["id"] for entry in ranked],
        "selected": selected["id"] if selected else None,
        "selection_process": selection_process(results),
    }
    if selected:
        out["selected_null"] = null_distribution(
            kept_signals[selected["id"]], plan.COSTS[plan.PRIMARY_COST], regimes, start, end
        )
        selected["wf_tier"] = tier_on(kept_rows[selected["id"]], selected["wf_checks"], out["selected_null"])
    with gzip.open(args.out / "walk_forward_trades.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(trade_dump, handle)
    ledger_entry["selected"] = out["selected"]
    return out


def selection_process(results: list[dict]) -> list[dict]:
    """Walk the selection forward: pick by in-sample mean before each fold, score the pick on that fold."""
    out = []
    deployable = [entry for entry in results if entry["deployable"]]
    for index, (name, _, _) in enumerate(plan.FOLDS[1:], start=1):
        earlier = [fold for fold, _, _ in plan.FOLDS[:index]]
        best, best_mean = None, None
        for entry in deployable:
            folds = entry["costs"][plan.PRIMARY_COST]["folds"]
            count = sum(folds.get(fold, {}).get("trades", 0) for fold in earlier)
            if count < 30:
                continue
            mean = sum(folds[fold].get("mean", 0.0) * folds[fold]["trades"] for fold in earlier) / count
            if best_mean is None or mean > best_mean:
                best, best_mean = entry, mean
        if best is not None:
            fold = best["costs"][plan.PRIMARY_COST]["folds"].get(name, {})
            out.append(
                {
                    "fold": name,
                    "picked": best["id"],
                    "in_sample_mean": best_mean,
                    "fold_trades": fold.get("trades"),
                    "fold_mean": fold.get("mean"),
                    "fold_win_rate": fold.get("win_rate"),
                }
            )
    return out


def shifted(signals: dict[str, Signals], rows: int) -> dict[str, Signals]:
    out = {}
    for pair, item in signals.items():
        enter = np.concatenate([item.enter[rows:], np.zeros(rows, dtype=bool)])
        exit_signal = np.concatenate([item.exit_signal[rows:], np.zeros(rows, dtype=bool)])
        out[pair] = Signals(item.candles, enter, exit_signal, item.atr, item.exits)
    return out


def peeked(signals: dict[str, Signals]) -> dict[str, Signals]:
    """Entries kept only when the candle they fill on closes above its open: knowledge of the future."""
    out = {}
    for pair, item in signals.items():
        opens = item.candles["open"].to_numpy(dtype=float)
        closes = item.candles["close"].to_numpy(dtype=float)
        green_next = np.concatenate([closes[1:] > opens[1:], [False]])
        out[pair] = Signals(item.candles, item.enter & green_next, item.exit_signal, item.atr, item.exits)
    return out


def frame_equal(a: Signals, b: Signals, dates: pd.Series) -> bool:
    left = pd.DataFrame({"date": a.candles["date"], "e": a.enter, "x": a.exit_signal, "atr": a.atr})
    right = pd.DataFrame({"date": b.candles["date"], "e": b.enter, "x": b.exit_signal, "atr": b.atr})
    left = left[left["date"].isin(dates)].reset_index(drop=True)
    right = right[right["date"].isin(dates)].reset_index(drop=True)
    return len(left) == len(right) and left.equals(right) if len(left) else True


def controls(args, ledger_entry: dict) -> dict:
    candles = load_candles(args.datadir, plan.HOLDOUT_START)
    fear_greed = load_fear_greed(args.fear_greed)
    regimes = regime_by_hour(candles[plan.REGIME_PAIR])
    by_id = {candidate.id: candidate for candidate in plan.candidates()}
    start, end = plan.WALK_FORWARD_START, plan.HOLDOUT_START
    costs = plan.COSTS[plan.PRIMARY_COST]
    rng = np.random.default_rng(plan.SEED)
    span = int((end - start).total_seconds() // 3600)
    cuts = sorted(start + pd.Timedelta(hours=int(h)) for h in rng.integers(24 * 30, span - 1, plan.LOOKAHEAD_CUTS))
    out = []
    for candidate in by_id.values():
        if candidate.kind in ("buy_hold", "random"):
            continue
        honest = build_signals(candidate, candles, fear_greed, by_id)
        tf_rows = {"1h": 1, "4h": 4, "1d": 24}[candidate.spec.timeframe if candidate.spec else "1h"]
        entry = {"id": candidate.id}
        for label, signals in (
            ("honest", honest),
            ("shift_1h", shifted(honest, 1)),
            ("shift_tf", shifted(honest, tf_rows)),
            ("peek_next_close", peeked(honest)),
        ):
            rows = rows_of(trades_of(signals, costs), costs, regimes, start, end)
            summary = metrics.summarize(rows, start, end, stoploss_of(signals), mean_fee(costs))
            entry[label] = {key: summary.get(key) for key in ("trades", "win_rate", "mean", "ci95")}
        truncation_failures, live_mismatch, compared = 0, 0, 0
        for cut in cuts:
            cut_candles = {pair: frame[frame["date"] <= cut].reset_index(drop=True) for pair, frame in candles.items()}
            cut_signals = build_signals(candidate, cut_candles, fear_greed, by_id)
            for pair, item in cut_signals.items():
                dates = item.candles["date"].tail(COMPARE_ROWS)
                if not frame_equal(item, honest[pair], dates):
                    truncation_failures += 1
                live = build_signals(
                    candidate, {pair: cut_candles[pair]}, fear_greed, by_id, window=plan.LIVE_WINDOW_CANDLES
                )[pair]
                compared += 1
                if not frame_equal(_entries_only(live), _entries_only(item), dates):
                    live_mismatch += 1
        entry["truncation_cuts"] = compared
        entry["truncation_failures"] = truncation_failures
        entry["live_window_entry_mismatches"] = live_mismatch
        out.append(entry)
        print(f"{candidate.id}: truncation failures {truncation_failures}/{compared}", file=sys.stderr)
    return {"cuts": [cut.isoformat() for cut in cuts], "results": out}


def _entries_only(item: Signals) -> Signals:
    blank = np.zeros(len(item.enter), dtype=bool)
    return Signals(item.candles, item.enter, blank, np.full(len(item.enter), np.nan), item.exits)


def validate(args, ledger_entry: dict) -> dict:
    first, last = (pd.Timestamp(day, tz="UTC") for day in plan.STAGE2_IN_SAMPLE)
    candles = load_candles(args.datadir, last, plan.ROUND1_PAIRS)
    regimes = regime_by_hour(candles[plan.REGIME_PAIR])
    by_id = {candidate.id: candidate for candidate in plan.candidates()}
    signals = build_signals(by_id["K-SwingEmaRsi"], candles, pd.DataFrame(columns=["date", "fg"]), by_id)
    costs = plan.COSTS["stress_041"]
    rows = rows_of(trades_of(signals, costs), costs, regimes, first, last)
    return {
        "period": [first.isoformat(), last.isoformat()],
        "stage2_freqtrade": {"trades": 447, "mean": -0.00818, "win_rate": 0.383},
        "simulator": metrics.summarize(rows, first, last, -0.03, 0.0041),
    }


def ledger_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_ledger(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def single_run_guard(args, kinds: tuple[str, ...], name: str) -> None:
    """Refuse a second run on an untouched period; a replay must name the recorded configuration."""
    used = [line for line in ledger_lines(args.ledger) if line["kind"] in kinds]
    if used and not args.replay:
        raise HoldoutUsed(f"{name} already used by run {used[0]['run_id']} for {used[0].get('candidate')}")
    if args.replay and (not used or used[0].get("candidate") != args.candidate):
        raise HoldoutUsed(f"a replay must name the configuration of the recorded {name} run")


def holdout(args, ledger_entry: dict) -> dict:
    candles = load_candles(args.datadir, plan.DATA_END, plan.ROUND1_PAIRS)
    wf_candles = {
        pair: frame[frame["date"] < plan.HOLDOUT_START].reset_index(drop=True) for pair, frame in candles.items()
    }
    fear_greed = load_fear_greed(args.fear_greed)
    regimes = regime_by_hour(candles[plan.REGIME_PAIR])
    by_id = {candidate.id: candidate for candidate in plan.round1_candidates()}
    candidate = by_id[args.candidate]
    start, end = plan.HOLDOUT_START, plan.DATA_END
    signals = build_signals(candidate, candles, fear_greed, by_id)
    wf_signals = build_signals(candidate, wf_candles, fear_greed, by_id)
    primary = plan.COSTS[plan.PRIMARY_COST]
    stoploss = stoploss_of(signals)
    out = {"candidate": candidate.id, "period": [start.isoformat(), end.isoformat()], "costs": {}}
    for name, costs in plan.COSTS.items():
        rows = rows_of(trades_of(signals, costs), costs, regimes, start, end)
        out["costs"][name] = report(rows, start, end, stoploss, costs)
    rows = rows_of(trades_of(signals, primary), primary, regimes, start, end)
    wf_rows = rows_of(trades_of(wf_signals, primary), primary, regimes, plan.WALK_FORWARD_START, plan.HOLDOUT_START)
    null = null_distribution(signals, primary, regimes, start, end)
    checks = metrics.target_checks(rows, wf_rows, [wf_rows, rows])
    summary = out["costs"][plan.PRIMARY_COST]["all"]
    mean = summary.get("mean", 0.0)
    ci_low = summary.get("ci95", [0.0, 0.0])[0]
    beaten = bool(mean > null["mean_p95"])
    out.update(
        {
            "null": null,
            "null_beaten": beaten,
            "checks": checks,
            "tier": metrics.tier(checks["met"], mean, ci_low, beaten),
            "trades": [
                [
                    row.pair,
                    row.entry_time.isoformat(),
                    row.exit_time.isoformat(),
                    round(row.profit, 8),
                    row.reason,
                    row.regime,
                ]
                for row in rows
            ],
            "comparators": comparators(candles, fear_greed, regimes, by_id, start, end),
        }
    )
    ledger_entry["candidate"] = candidate.id
    ledger_entry["tier"] = out["tier"]
    return out


def presample(args, ledger_entry: dict) -> dict:
    """One configuration on the untouched period before the round 1 data, judged with its walk-forward folds."""
    candles = load_candles(args.datadir, plan.PRESAMPLE_END, plan.PRESAMPLE_PAIRS)
    wf_candles = load_candles(args.wf_datadir, plan.HOLDOUT_START)
    fear_greed = load_fear_greed(args.fear_greed)
    regimes = regime_by_hour(candles[plan.REGIME_PAIR])
    wf_regimes = regime_by_hour(wf_candles[plan.REGIME_PAIR])
    by_id = {candidate.id: candidate for candidate in plan.candidates()}
    candidate = by_id[args.candidate]
    start, end = plan.PRESAMPLE_START, plan.PRESAMPLE_END
    signals = build_signals(candidate, candles, fear_greed, by_id)
    wf_signals = build_signals(candidate, wf_candles, fear_greed, by_id)
    primary = plan.COSTS[plan.PRIMARY_COST]
    stoploss = stoploss_of(signals)
    out = {"candidate": candidate.id, "period": [start.isoformat(), end.isoformat()], "costs": {}}
    for name, costs in plan.COSTS.items():
        rows = rows_of(trades_of(signals, costs), costs, regimes, start, end)
        out["costs"][name] = report(rows, start, end, stoploss, costs)
    rows = rows_of(trades_of(signals, primary), primary, regimes, start, end)
    wf_rows = rows_of(trades_of(wf_signals, primary), primary, wf_regimes, plan.WALK_FORWARD_START, plan.HOLDOUT_START)
    null = null_distribution(signals, primary, regimes, start, end)
    checks = metrics.target_checks(rows, wf_rows, [wf_rows, rows])
    summary = out["costs"][plan.PRIMARY_COST]["all"]
    mean = summary.get("mean", 0.0)
    ci_low = summary.get("ci95", [0.0, 0.0])[0]
    beaten = bool(mean > null["mean_p95"])
    out.update(
        {
            "null": null,
            "null_beaten": beaten,
            "checks": checks,
            "tier": metrics.tier(checks["met"], mean, ci_low, beaten),
            "trades": [
                [
                    row.pair,
                    row.entry_time.isoformat(),
                    row.exit_time.isoformat(),
                    round(row.profit, 8),
                    row.reason,
                    row.regime,
                ]
                for row in rows
            ],
            "comparators": comparators(candles, fear_greed, regimes, by_id, start, end),
        }
    )
    ledger_entry["tier"] = out["tier"]
    return out


def comparators(candles, fear_greed, regimes, by_id, start, end) -> dict:
    costs = plan.COSTS[plan.PRIMARY_COST]
    swing = build_signals(by_id["K-SwingEmaRsi"], candles, fear_greed, by_id)
    rows = rows_of(trades_of(swing, costs), costs, regimes, start, end)
    return {
        "K-SwingEmaRsi": metrics.summarize(rows, start, end, -0.03, mean_fee(costs)),
        "K-buy-and-hold": buy_and_hold(candles, costs, [("holdout", start, end)])["holdout"],
    }


COMMANDS = {
    "walk-forward": ("walk_forward", walk_forward),
    "controls": ("controls", controls),
    "validate": ("validation", validate),
    "holdout": ("holdout", holdout),
    "presample": ("presample", presample),
}
GUARDS = {"holdout": (HOLDOUT_KINDS, "holdout"), "presample": (PRESAMPLE_KINDS, "presample")}
PERIODS = {
    "walk_forward": (plan.WALK_FORWARD_START, plan.HOLDOUT_START),
    "controls": (plan.WALK_FORWARD_START, plan.HOLDOUT_START),
    "validation": tuple(pd.Timestamp(day, tz="UTC") for day in plan.STAGE2_IN_SAMPLE),
    "holdout": (plan.HOLDOUT_START, plan.DATA_END),
    "presample": (plan.PRESAMPLE_START, plan.PRESAMPLE_END),
}


def data_hashes(args) -> dict[str, str]:
    out = {pair: sha256(pair_file(args.datadir, pair)) for pair in pairs_of(args.command)}
    if args.wf_datadir:
        out |= {f"walk_forward {pair}": sha256(pair_file(args.wf_datadir, pair)) for pair in plan.PAIRS}
    return out | {"fear_greed": sha256(args.fear_greed)}


def pairs_of(command: str) -> tuple[str, ...]:
    return {"holdout": plan.ROUND1_PAIRS, "validate": plan.ROUND1_PAIRS, "presample": plan.PRESAMPLE_PAIRS}.get(
        command, plan.PAIRS
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.strategy_search", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--datadir", required=True, type=Path)
    parser.add_argument("--fear-greed", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--wf-datadir", type=Path, help="walk-forward candles, for presample")
    parser.add_argument("--candidate")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args(argv)
    if args.command in GUARDS and not args.candidate:
        parser.error(f"{args.command} needs --candidate")
    if args.command == "presample" and not args.wf_datadir:
        parser.error("presample needs --wf-datadir")
    if args.replay and args.command not in GUARDS:
        parser.error("--replay applies to holdout and presample")
    kind, run = COMMANDS[args.command]
    period = PERIODS[kind]
    if args.replay:
        kind = f"{kind}_replay"
    args.out.mkdir(parents=True, exist_ok=True)
    entry = {
        "run_id": uuid.uuid4().hex,
        "round": plan.ROUND,
        "kind": kind,
        "git_sha": os.environ.get("TRADING_BOT_GIT_SHA", "unknown"),
        "git_dirty": os.environ.get("TRADING_BOT_GIT_DIRTY", "unknown"),
        "started_at": datetime.now(UTC).isoformat(),
        "candidate": args.candidate,
        "period": [period[0].isoformat(), period[1].isoformat()],
    }
    try:
        entry["data_sha256"] = data_hashes(args)
        if args.command in GUARDS:
            single_run_guard(args, *GUARDS[args.command])
        append_ledger(args.ledger, {**entry, "kind": f"{kind}_started", "status": "started"})
        result = run(args, entry)
        (args.out / f"{args.command}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        entry["status"] = "ok"
        return_code = 0
    except HoldoutUsed as exc:
        print(f"strategy_search: refused: {exc}", file=sys.stderr)
        entry["status"] = f"refused: {exc}"
        return_code = 3
    except Exception as exc:
        traceback.print_exc()
        entry["status"] = f"failed: {type(exc).__name__}: {exc}"
        return_code = 1
    entry["finished_at"] = datetime.now(UTC).isoformat()
    append_ledger(args.ledger, entry)
    return return_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
