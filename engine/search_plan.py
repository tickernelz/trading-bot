"""Round 1 strategy search plan, frozen before the first backtest: candidates, periods, costs, seeds and targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from engine.rules import RuleSpec
from engine.simulate import Costs

ROUND = 1
SEED = 3872
BOOTSTRAP_SAMPLES = 10_000
NULL_SHUFFLES = 1_000
PAIRS = ("BTC/IDR", "ETH/IDR", "SOL/IDR")
REGIME_PAIR = "BTC/IDR"

WALK_FORWARD_START = pd.Timestamp("2022-07-01", tz="UTC")
HOLDOUT_START = pd.Timestamp("2026-04-26", tz="UTC")
DATA_END = pd.Timestamp("2026-10-26", tz="UTC")
FOLDS = (
    ("F1", "2022-07-01", "2023-01-01"),
    ("F2", "2023-01-01", "2023-07-01"),
    ("F3", "2023-07-01", "2024-01-01"),
    ("F4", "2024-01-01", "2024-07-01"),
    ("F5", "2024-07-01", "2025-01-01"),
    ("F6", "2025-01-01", "2025-07-01"),
    ("F7", "2025-07-01", "2026-01-01"),
    ("F8", "2026-01-01", "2026-04-26"),
)
STAGE2_IN_SAMPLE = ("2023-10-26", "2025-10-26")

PRIMARY_COST = "taker"
COSTS = {
    "taker": Costs(buy=0.0020555, sell=0.0041555),
    "stress_041": Costs(buy=0.0041, sell=0.0041),
    "no_tax": Costs(buy=0.0020555, sell=0.0020555),
    "slip_005": Costs(buy=0.0025555, sell=0.0046555),
    "slip_010": Costs(buy=0.0030555, sell=0.0051555),
}

RISK_PER_TRADE = 0.005
MAX_OPEN_TRADES = 3

TARGET_WIN_RATE = 0.60
TARGET_WILSON_LOWER = 0.50
TARGET_MIN_TRADES = 100
TARGET_MIN_PAIRS = 2
TARGET_MIN_TRADES_PER_PAIR = 10
TARGET_FOLD_WIN_RATE = 0.50
TARGET_FOLD_STD = 0.08
ROLLING_WINDOW = 30
TARGET_ROLLING_MIN = 0.40
REGIME_MIN_TRADES = 20
TARGET_REGIME_WIN_RATE = 0.50
LOOKAHEAD_CUTS = 40
LIVE_WINDOW_CANDLES = 649


@dataclass(frozen=True)
class Candidate:
    id: str
    family: str
    kind: Literal["rule", "swing", "random", "buy_hold"]
    spec: RuleSpec | None = None
    fear_greed_max: float | None = None
    random_rate: float | None = None
    exits_from: str | None = None
    deployable: bool = True


def _rule(cid: str, family: str, deployable: bool = True, fear_greed_max: float | None = None, **fields) -> Candidate:
    return Candidate(cid, family, "rule", RuleSpec(**fields), fear_greed_max=fear_greed_max, deployable=deployable)


def _pct(value: float) -> str:
    return f"{value * 100:g}"


def candidates() -> list[Candidate]:
    """The locked round 1 matrix."""
    out: list[Candidate] = []
    for n in (10, 20, 30, 60, 90):
        for sl in (0.10, 0.20):
            out.append(
                _rule(f"A-don1d-{n}-sl{_pct(sl)}", "A donchian 1d", entry="donchian", timeframe="1d", lookback=n,
                      exit="donchian_mid", exit_lookback=n, stoploss=-sl)
            )
    for n in (20, 55):
        for adx in (20, 25):
            for exit_ in ("mid", "atr3"):
                trail = {"exit": "none", "trail_atr": 3.0} if exit_ == "atr3" else {"exit": "donchian_mid", "exit_lookback": n}
                out.append(
                    _rule(f"B-don1d-{n}-adx{adx}-{exit_}", "B donchian 1d regime", entry="donchian", timeframe="1d",
                          lookback=n, adx_min=adx, trend_filter="above_sma200_1d", stoploss=-0.15, **trail)
                )
    for n in (20, 55):
        for exit_ in ("mid", "atr3"):
            trail = {"exit": "none", "trail_atr": 3.0} if exit_ == "atr3" else {"exit": "donchian_mid", "exit_lookback": n}
            out.append(
                _rule(f"B-don4h-{n}-{exit_}", "B donchian 4h regime", entry="donchian", timeframe="4h", lookback=n,
                      trend_filter="above_sma200_1d", stoploss=-0.10, **trail)
            )
    for n in (20, 30, 60, 90):
        for sl in (0.15, 0.25):
            out.append(
                _rule(f"C-tsmom-{n}-sl{_pct(sl)}", "C time-series momentum 1d", entry="tsmom", timeframe="1d",
                      lookback=n, exit="tsmom_flip", stoploss=-sl)
            )
    for fast, slow in ((20, 50), (50, 200)):
        for adx in (20, 25):
            for exit_ in ("cross", "atr3"):
                trail = {"exit": "none", "trail_atr": 3.0} if exit_ == "atr3" else {"exit": "ema_cross"}
                out.append(
                    _rule(f"D-ema4h-{fast}-{slow}-adx{adx}-{exit_}", "D EMA trend 4h", entry="ema_trend",
                          timeframe="4h", lookback=14, fast=fast, slow=slow, adx_min=adx,
                          trend_filter="above_sma200_1d", stoploss=-0.10, **trail)
                )
    for fast, slow in ((20, 50), (50, 200)):
        out.append(
            _rule(f"D-ema1d-{fast}-{slow}", "D EMA trend 1d", entry="ema_trend", timeframe="1d", lookback=14,
                  fast=fast, slow=slow, adx_min=20, trend_filter="above_sma200_1d", exit="ema_cross", stoploss=-0.15)
        )
    for tf, sl in (("4h", 0.10), ("1d", 0.15)):
        for k in (1.5, 2.0):
            out.append(
                _rule(f"E-volbreak-{tf}-x{k:g}", "E breakout with volume", entry="breakout_volume", timeframe=tf,
                      lookback=20, threshold=k, trend_filter="above_sma200_1d", exit="none", trail_atr=3.0,
                      stoploss=-sl)
            )
    bases = (
        ("don1d20", {"entry": "donchian", "timeframe": "1d", "lookback": 20, "exit": "donchian_mid", "exit_lookback": 20}),
        ("ema4h", {"entry": "ema_trend", "timeframe": "4h", "lookback": 14, "fast": 20, "slow": 50, "exit": "ema_cross"}),
    )
    for name, base in bases:
        for tp, lock in ((0.03, 0.015), (0.05, 0.015), (0.05, 0.03), (0.08, 0.015), (0.08, 0.03)):
            out.append(
                _rule(f"F-{name}-tp{_pct(tp)}-lock{_pct(lock)}", "F trend entry with asymmetric exit",
                      trend_filter="above_sma200_1d", take_profit=tp, lock_at=lock, stoploss=-0.08, **base)
            )
    for thr in (5, 10, 15):
        for sl in (0.10, 0.25):
            out.append(
                _rule(f"G-rsi2-1d-{thr}-sl{_pct(sl)}", "G RSI2 mean reversion 1d", entry="rsi_dip", timeframe="1d",
                      lookback=2, threshold=thr, trend_filter="above_sma200_1d", exit="sma_reclaim", exit_lookback=5,
                      max_hold_hours=240, stoploss=-sl)
            )
    for thr in (5, 10):
        for sl in (0.06, 0.12):
            out.append(
                _rule(f"G-rsi2-4h-{thr}-sl{_pct(sl)}", "G RSI2 mean reversion 4h", entry="rsi_dip", timeframe="4h",
                      lookback=2, threshold=thr, trend_filter="above_sma200_1d", exit="sma_reclaim", exit_lookback=5,
                      max_hold_hours=72, stoploss=-sl)
            )
    for tf in ("1h", "4h"):
        for sl in (0.05, 0.10):
            for trend in ("none", "above_sma200_1d"):
                tag = "trend" if trend != "none" else "any"
                out.append(
                    _rule(f"H-bb-{tf}-sl{_pct(sl)}-{tag}", "H Bollinger range reversion", entry="bollinger_range",
                          timeframe=tf, lookback=20, adx_max=20, trend_filter=trend, exit="bb_mid",
                          max_hold_hours=72, stoploss=-sl)
                )
    dips = (
        ("rsi14-1h", {"timeframe": "1h", "lookback": 14, "threshold": 30}),
        ("rsi2-4h", {"timeframe": "4h", "lookback": 2, "threshold": 10}),
    )
    for name, dip in dips:
        for tp in (0.02, 0.03, 0.04):
            for sl in (0.06, 0.10):
                out.append(
                    _rule(f"N-{name}-tp{_pct(tp)}-sl{_pct(sl)}", "N trend dip with fixed target", entry="rsi_dip",
                          trend_filter="above_sma200_1d", exit="none", take_profit=tp, max_hold_hours=168,
                          stoploss=-sl, **dip)
                )
    out += [
        _rule("I-fg75-don1d-20", "I Fear and Greed filter", deployable=False, fear_greed_max=75, entry="donchian",
              timeframe="1d", lookback=20, exit="donchian_mid", exit_lookback=20, stoploss=-0.15),
        _rule("I-fg50-rsi2-1d-10", "I Fear and Greed filter", deployable=False, fear_greed_max=50, entry="rsi_dip",
              timeframe="1d", lookback=2, threshold=10, trend_filter="above_sma200_1d", exit="sma_reclaim",
              exit_lookback=5, max_hold_hours=240, stoploss=-0.10),
        _rule("I-fg75-tsmom-30", "I Fear and Greed filter", deployable=False, fear_greed_max=75, entry="tsmom",
              timeframe="1d", lookback=30, exit="tsmom_flip", stoploss=-0.15),
        _rule("I-fg50-rsi14-1h-tp3", "I Fear and Greed filter", deployable=False, fear_greed_max=50, entry="rsi_dip",
              timeframe="1h", lookback=14, threshold=30, trend_filter="above_sma200_1d", exit="none",
              take_profit=0.03, max_hold_hours=168, stoploss=-0.10),
        _rule("J-rsi14-1h-tp1.5-sl15", "J high win rate control", entry="rsi_dip", timeframe="1h", lookback=14,
              threshold=30, exit="none", take_profit=0.015, stoploss=-0.15),
        _rule("J-rsi14-1h-tp3-sl10", "J high win rate control", entry="rsi_dip", timeframe="1h", lookback=14,
              threshold=30, exit="none", take_profit=0.03, stoploss=-0.10),
        Candidate("J-random-tp1.5-sl15", "J high win rate control", "random", random_rate=0.004,
                  exits_from="J-rsi14-1h-tp1.5-sl15", deployable=False),
        Candidate("K-SwingEmaRsi", "K benchmark", "swing"),
        Candidate("K-buy-and-hold", "K benchmark", "buy_hold", deployable=False),
    ]
    return out
