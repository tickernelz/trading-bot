"""Strategy search plan, frozen per round before its first backtest: candidates, periods, costs, seeds and targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from engine.rules import RuleSpec
from engine.simulate import Costs

ROUND = 5
SEED = 3872
BOOTSTRAP_SAMPLES = 10_000
NULL_SHUFFLES = 1_000
ROUND1_PAIRS = ("BTC/IDR", "ETH/IDR", "SOL/IDR")
PAIRS = (*ROUND1_PAIRS, "XRP/IDR", "DOGE/IDR")
REGIME_PAIR = "BTC/IDR"
SEARCH_BUDGET = 1_500

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
CROSS_SPREAD_BPS = {
    "BNB/IDR": 0.0,
    "NEAR/IDR": 0.1,
    "HBAR/IDR": 7.1,
    "ADA/IDR": 29.7,
    "LTC/IDR": 29.2,
    "TRX/IDR": 38.4,
}
CROSS_PAIRS = tuple(CROSS_SPREAD_BPS)
CROSS_HALF_SPREAD = {pair: bps / 2 / 10_000 for pair, bps in CROSS_SPREAD_BPS.items()}
PRESAMPLE_PAIRS = ("BTC/IDR", "ETH/IDR", "XRP/IDR", "DOGE/IDR")
PRESAMPLE_START = pd.Timestamp("2018-09-01", tz="UTC")
PRESAMPLE_END = pd.Timestamp("2021-01-01", tz="UTC")

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
CAPITAL_IDR = 2_000_000
RESEARCH_RISK_PER_TRADE = 0.02
ALLOCATION = 0.99
PROFIT_KEY = "monthly_profit_idr_equal_weight"
MAX_DAILY_LOSS = 0.01
MAX_TOTAL_DRAWDOWN = 0.10
DAILY_RESET_TIMEZONE = "Asia/Jakarta"

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


def round1_candidates() -> list[Candidate]:
    """The locked round 1 matrix."""
    out: list[Candidate] = []
    for n in (10, 20, 30, 60, 90):
        for sl in (0.10, 0.20):
            out.append(
                _rule(
                    f"A-don1d-{n}-sl{_pct(sl)}",
                    "A donchian 1d",
                    entry="donchian",
                    timeframe="1d",
                    lookback=n,
                    exit="donchian_mid",
                    exit_lookback=n,
                    stoploss=-sl,
                )
            )
    for n in (20, 55):
        for adx in (20, 25):
            for exit_ in ("mid", "atr3"):
                trail = (
                    {"exit": "none", "trail_atr": 3.0}
                    if exit_ == "atr3"
                    else {"exit": "donchian_mid", "exit_lookback": n}
                )
                out.append(
                    _rule(
                        f"B-don1d-{n}-adx{adx}-{exit_}",
                        "B donchian 1d regime",
                        entry="donchian",
                        timeframe="1d",
                        lookback=n,
                        adx_min=adx,
                        trend_filter="above_sma200_1d",
                        stoploss=-0.15,
                        **trail,
                    )
                )
    for n in (20, 55):
        for exit_ in ("mid", "atr3"):
            trail = (
                {"exit": "none", "trail_atr": 3.0} if exit_ == "atr3" else {"exit": "donchian_mid", "exit_lookback": n}
            )
            out.append(
                _rule(
                    f"B-don4h-{n}-{exit_}",
                    "B donchian 4h regime",
                    entry="donchian",
                    timeframe="4h",
                    lookback=n,
                    trend_filter="above_sma200_1d",
                    stoploss=-0.10,
                    **trail,
                )
            )
    for n in (20, 30, 60, 90):
        for sl in (0.15, 0.25):
            out.append(
                _rule(
                    f"C-tsmom-{n}-sl{_pct(sl)}",
                    "C time-series momentum 1d",
                    entry="tsmom",
                    timeframe="1d",
                    lookback=n,
                    exit="tsmom_flip",
                    stoploss=-sl,
                )
            )
    for fast, slow in ((20, 50), (50, 200)):
        for adx in (20, 25):
            for exit_ in ("cross", "atr3"):
                trail = {"exit": "none", "trail_atr": 3.0} if exit_ == "atr3" else {"exit": "ema_cross"}
                out.append(
                    _rule(
                        f"D-ema4h-{fast}-{slow}-adx{adx}-{exit_}",
                        "D EMA trend 4h",
                        entry="ema_trend",
                        timeframe="4h",
                        lookback=14,
                        fast=fast,
                        slow=slow,
                        adx_min=adx,
                        trend_filter="above_sma200_1d",
                        stoploss=-0.10,
                        **trail,
                    )
                )
    for fast, slow in ((20, 50), (50, 200)):
        out.append(
            _rule(
                f"D-ema1d-{fast}-{slow}",
                "D EMA trend 1d",
                entry="ema_trend",
                timeframe="1d",
                lookback=14,
                fast=fast,
                slow=slow,
                adx_min=20,
                trend_filter="above_sma200_1d",
                exit="ema_cross",
                stoploss=-0.15,
            )
        )
    for tf, sl in (("4h", 0.10), ("1d", 0.15)):
        for k in (1.5, 2.0):
            out.append(
                _rule(
                    f"E-volbreak-{tf}-x{k:g}",
                    "E breakout with volume",
                    entry="breakout_volume",
                    timeframe=tf,
                    lookback=20,
                    threshold=k,
                    trend_filter="above_sma200_1d",
                    exit="none",
                    trail_atr=3.0,
                    stoploss=-sl,
                )
            )
    bases = (
        (
            "don1d20",
            {"entry": "donchian", "timeframe": "1d", "lookback": 20, "exit": "donchian_mid", "exit_lookback": 20},
        ),
        (
            "ema4h",
            {"entry": "ema_trend", "timeframe": "4h", "lookback": 14, "fast": 20, "slow": 50, "exit": "ema_cross"},
        ),
    )
    for name, base in bases:
        for tp, lock in ((0.03, 0.015), (0.05, 0.015), (0.05, 0.03), (0.08, 0.015), (0.08, 0.03)):
            out.append(
                _rule(
                    f"F-{name}-tp{_pct(tp)}-lock{_pct(lock)}",
                    "F trend entry with asymmetric exit",
                    trend_filter="above_sma200_1d",
                    take_profit=tp,
                    lock_at=lock,
                    stoploss=-0.08,
                    **base,
                )
            )
    for thr in (5, 10, 15):
        for sl in (0.10, 0.25):
            out.append(
                _rule(
                    f"G-rsi2-1d-{thr}-sl{_pct(sl)}",
                    "G RSI2 mean reversion 1d",
                    entry="rsi_dip",
                    timeframe="1d",
                    lookback=2,
                    threshold=thr,
                    trend_filter="above_sma200_1d",
                    exit="sma_reclaim",
                    exit_lookback=5,
                    max_hold_hours=240,
                    stoploss=-sl,
                )
            )
    for thr in (5, 10):
        for sl in (0.06, 0.12):
            out.append(
                _rule(
                    f"G-rsi2-4h-{thr}-sl{_pct(sl)}",
                    "G RSI2 mean reversion 4h",
                    entry="rsi_dip",
                    timeframe="4h",
                    lookback=2,
                    threshold=thr,
                    trend_filter="above_sma200_1d",
                    exit="sma_reclaim",
                    exit_lookback=5,
                    max_hold_hours=72,
                    stoploss=-sl,
                )
            )
    for tf in ("1h", "4h"):
        for sl in (0.05, 0.10):
            for trend in ("none", "above_sma200_1d"):
                tag = "trend" if trend != "none" else "any"
                out.append(
                    _rule(
                        f"H-bb-{tf}-sl{_pct(sl)}-{tag}",
                        "H Bollinger range reversion",
                        entry="bollinger_range",
                        timeframe=tf,
                        lookback=20,
                        adx_max=20,
                        trend_filter=trend,
                        exit="bb_mid",
                        max_hold_hours=72,
                        stoploss=-sl,
                    )
                )
    dips = (
        ("rsi14-1h", {"timeframe": "1h", "lookback": 14, "threshold": 30}),
        ("rsi2-4h", {"timeframe": "4h", "lookback": 2, "threshold": 10}),
    )
    for name, dip in dips:
        for tp in (0.02, 0.03, 0.04):
            for sl in (0.06, 0.10):
                out.append(
                    _rule(
                        f"N-{name}-tp{_pct(tp)}-sl{_pct(sl)}",
                        "N trend dip with fixed target",
                        entry="rsi_dip",
                        trend_filter="above_sma200_1d",
                        exit="none",
                        take_profit=tp,
                        max_hold_hours=168,
                        stoploss=-sl,
                        **dip,
                    )
                )
    out += [
        _rule(
            "I-fg75-don1d-20",
            "I Fear and Greed filter",
            deployable=False,
            fear_greed_max=75,
            entry="donchian",
            timeframe="1d",
            lookback=20,
            exit="donchian_mid",
            exit_lookback=20,
            stoploss=-0.15,
        ),
        _rule(
            "I-fg50-rsi2-1d-10",
            "I Fear and Greed filter",
            deployable=False,
            fear_greed_max=50,
            entry="rsi_dip",
            timeframe="1d",
            lookback=2,
            threshold=10,
            trend_filter="above_sma200_1d",
            exit="sma_reclaim",
            exit_lookback=5,
            max_hold_hours=240,
            stoploss=-0.10,
        ),
        _rule(
            "I-fg75-tsmom-30",
            "I Fear and Greed filter",
            deployable=False,
            fear_greed_max=75,
            entry="tsmom",
            timeframe="1d",
            lookback=30,
            exit="tsmom_flip",
            stoploss=-0.15,
        ),
        _rule(
            "I-fg50-rsi14-1h-tp3",
            "I Fear and Greed filter",
            deployable=False,
            fear_greed_max=50,
            entry="rsi_dip",
            timeframe="1h",
            lookback=14,
            threshold=30,
            trend_filter="above_sma200_1d",
            exit="none",
            take_profit=0.03,
            max_hold_hours=168,
            stoploss=-0.10,
        ),
        _rule(
            "J-rsi14-1h-tp1.5-sl15",
            "J high win rate control",
            entry="rsi_dip",
            timeframe="1h",
            lookback=14,
            threshold=30,
            exit="none",
            take_profit=0.015,
            stoploss=-0.15,
        ),
        _rule(
            "J-rsi14-1h-tp3-sl10",
            "J high win rate control",
            entry="rsi_dip",
            timeframe="1h",
            lookback=14,
            threshold=30,
            exit="none",
            take_profit=0.03,
            stoploss=-0.10,
        ),
        Candidate(
            "J-random-tp1.5-sl15",
            "J high win rate control",
            "random",
            random_rate=0.004,
            exits_from="J-rsi14-1h-tp1.5-sl15",
            deployable=False,
        ),
        Candidate("K-SwingEmaRsi", "K benchmark", "swing"),
        Candidate("K-buy-and-hold", "K benchmark", "buy_hold", deployable=False),
    ]
    return out


def round2_candidates() -> list[Candidate]:
    """The locked round 2 matrix, run on PAIRS."""
    out: list[Candidate] = []
    don1d20 = {"entry": "donchian", "timeframe": "1d", "lookback": 20, "exit": "donchian_mid", "exit_lookback": 20}
    out += [
        _rule(
            f"Q-F-don1d20-tp{_pct(tp)}-lock3",
            "Q round 1 near miss on five pairs",
            trend_filter="above_sma200_1d",
            take_profit=tp,
            lock_at=0.03,
            stoploss=-0.08,
            **don1d20,
        )
        for tp in (0.05, 0.08)
    ]
    out.append(
        _rule(
            "Q-G-rsi2-1d-10-sl25",
            "Q round 1 near miss on five pairs",
            entry="rsi_dip",
            timeframe="1d",
            lookback=2,
            threshold=10,
            trend_filter="above_sma200_1d",
            exit="sma_reclaim",
            exit_lookback=5,
            max_hold_hours=240,
            stoploss=-0.25,
        )
    )
    out.append(
        _rule(
            "Q-J-rsi14-1h-tp3-sl10",
            "Q round 1 near miss on five pairs",
            entry="rsi_dip",
            timeframe="1h",
            lookback=14,
            threshold=30,
            exit="none",
            take_profit=0.03,
            stoploss=-0.10,
        )
    )
    filters = {"sma50": "above_sma50_1d", "sma100": "above_sma100_1d", "nofilter": "none"}
    for n in (10, 20):
        for tag, trend in filters.items():
            for tp in (0.05, 0.08):
                out.append(
                    _rule(
                        f"S-don1d{n}-{tag}-tp{_pct(tp)}-lock3",
                        "S faster trend filter",
                        entry="donchian",
                        timeframe="1d",
                        lookback=n,
                        exit="donchian_mid",
                        exit_lookback=n,
                        trend_filter=trend,
                        take_profit=tp,
                        lock_at=0.03,
                        stoploss=-0.08,
                    )
                )
    for tag in ("sma200", "sma100"):
        for tp in (1.0, 1.5, 2.0):
            for st in (2.0, 3.0):
                out.append(
                    _rule(
                        f"V-don1d20-{tag}-tp{tp:g}atr-st{st:g}atr",
                        "V volatility exits on 1d trend entry",
                        trend_filter=f"above_{tag}_1d",
                        take_profit_atr=tp,
                        stop_atr=st,
                        stoploss=-0.15,
                        **don1d20,
                    )
                )
    for tp in (1.5, 2.5, 3.5):
        for st in (2.0, 3.0):
            out.append(
                _rule(
                    f"V-don4h20-sma200-tp{tp:g}atr-st{st:g}atr",
                    "V volatility exits on 4h trend entry",
                    entry="donchian",
                    timeframe="4h",
                    lookback=20,
                    exit="donchian_mid",
                    exit_lookback=20,
                    trend_filter="above_sma200_1d",
                    take_profit_atr=tp,
                    stop_atr=st,
                    stoploss=-0.10,
                )
            )
    for tag in ("sma50", "sma100"):
        for tp in (1.0, 1.5):
            for st in (1.5, 2.5):
                out.append(
                    _rule(
                        f"W-rsi2-4h-{tag}-tp{tp:g}atr-st{st:g}atr",
                        "W trend pullback with volatility exits",
                        entry="rsi_dip",
                        timeframe="4h",
                        lookback=2,
                        threshold=10,
                        trend_filter=f"above_{tag}_1d",
                        exit="none",
                        take_profit_atr=tp,
                        stop_atr=st,
                        max_hold_hours=72,
                        stoploss=-0.12,
                    )
                )
    for tp in (2.0, 3.0):
        for st in (3.0, 5.0):
            out.append(
                _rule(
                    f"W-rsi14-1h-sma100-tp{tp:g}atr-st{st:g}atr",
                    "W trend pullback with volatility exits",
                    entry="rsi_dip",
                    timeframe="1h",
                    lookback=14,
                    threshold=30,
                    trend_filter="above_sma100_1d",
                    exit="none",
                    take_profit_atr=tp,
                    stop_atr=st,
                    max_hold_hours=168,
                    stoploss=-0.10,
                )
            )
    out += [
        Candidate(
            "R-random-V-don1d20-exits",
            "R random entry control",
            "random",
            random_rate=0.001,
            exits_from="V-don1d20-sma200-tp1.5atr-st2atr",
            deployable=False,
        ),
        Candidate("K-SwingEmaRsi", "K benchmark", "swing"),
        Candidate("K-buy-and-hold", "K benchmark", "buy_hold", deployable=False),
    ]
    return out


def round3_candidates() -> list[Candidate]:
    """The locked round 3 matrix, run on PAIRS: trend entries that let winners run, ranked by monthly profit."""
    out: list[Candidate] = []
    for n in (30, 60, 90):
        out.append(
            _rule(
                f"P-don1d-{n}-mid-sl20",
                "P round 1 positive trend rules on five pairs",
                entry="donchian",
                timeframe="1d",
                lookback=n,
                exit="donchian_mid",
                exit_lookback=n,
                stoploss=-0.20,
            )
        )
    for n in (30, 55, 90):
        for tag, trend in (("sma100", "above_sma100_1d"), ("nofilter", "none")):
            for trail in (3.0, 4.0):
                out.append(
                    _rule(
                        f"L-don1d-{n}-{tag}-trail{trail:g}atr",
                        "L Donchian 1d with ATR trailing exit",
                        entry="donchian",
                        timeframe="1d",
                        lookback=n,
                        trend_filter=trend,
                        exit="none",
                        trail_atr=trail,
                        stoploss=-0.20,
                    )
                )
    for n in (30, 60, 90):
        for tag, trend in (("sma100", "above_sma100_1d"), ("nofilter", "none")):
            out.append(
                _rule(
                    f"M-tsmom-{n}-{tag}",
                    "M time-series momentum 1d with trend filter",
                    entry="tsmom",
                    timeframe="1d",
                    lookback=n,
                    trend_filter=trend,
                    exit="tsmom_flip",
                    stoploss=-0.20,
                )
            )
    for fast, slow in ((20, 100), (50, 200)):
        out.append(
            _rule(
                f"E-ema1d-{fast}-{slow}-trail3atr",
                "E EMA trend 1d with ATR trailing exit",
                entry="ema_trend",
                timeframe="1d",
                lookback=14,
                fast=fast,
                slow=slow,
                exit="ema_cross",
                trail_atr=3.0,
                stoploss=-0.20,
            )
        )
    out += [
        Candidate(
            "R3-random-L-exits",
            "R random entry control",
            "random",
            random_rate=0.0008,
            exits_from="L-don1d-55-nofilter-trail4atr",
            deployable=False,
        ),
        Candidate("K-SwingEmaRsi", "K benchmark", "swing"),
        Candidate("K-buy-and-hold", "K benchmark", "buy_hold", deployable=False),
    ]
    return out


def round4_candidates() -> list[Candidate]:
    """The locked round 4 matrix, run on PAIRS: trend entries behind the BTC/IDR regime gate (ZHA-3913)."""
    out: list[Candidate] = []
    for n, exit_lookback, trend, stop in (
        (55, 20, "btc_above_sma100_1d", -0.20),
        (55, 55, "btc_above_sma100_1d", -0.20),
        (20, 20, "btc_above_sma100_1d", -0.20),
        (55, 20, "btc_above_sma200_1d", -0.20),
        (90, 20, "btc_above_sma100_1d", -0.20),
    ):
        out.append(
            _rule(
                f"F3-don1d{n}-exit{exit_lookback}-{trend.replace('_1d', '')}-sl20",
                "F3 variants: Donchian with the BTC regime gate",
                entry="donchian",
                timeframe="1d",
                lookback=n,
                exit="donchian_mid",
                exit_lookback=exit_lookback,
                trend_filter=trend,
                stoploss=stop,
            )
        )
    out.append(
        _rule(
            "F3-tsmom-55-btcabove-sma100-sl20",
            "F3 variants: time-series momentum with the BTC regime gate",
            entry="tsmom",
            timeframe="1d",
            lookback=55,
            exit="tsmom_flip",
            trend_filter="btc_above_sma100_1d",
            stoploss=-0.20,
        )
    )
    return out


def candidates() -> list[Candidate]:
    """The locked round 5 matrix, run on PAIRS: ZHA-3913 F1 and F3, each pair one equal share of the account."""
    out: list[Candidate] = []
    for n in (50, 100, 200):
        out.append(
            _rule(
                f"F1-regime-btc-sma{n}",
                "F1 hold every pair while BTC/IDR closes above its SMA",
                entry="regime",
                timeframe="1d",
                lookback=2,
                trend_filter=f"btc_above_sma{n}_1d",
                exit="regime_off",
                stoploss=-0.95,
            )
        )
    for n, m in ((20, 10), (55, 20), (100, 50)):
        for tag, trend in (("btc100", "btc_above_sma100_1d"), ("nofilter", "none")):
            out.append(
                _rule(
                    f"F3L-don1d{n}-low{m}-{tag}-st2atr",
                    "F3 Donchian high entry, Donchian low exit, 2 ATR stop",
                    entry="donchian",
                    timeframe="1d",
                    lookback=n,
                    exit="donchian_low",
                    exit_lookback=m,
                    trend_filter=trend,
                    stop_atr=2.0,
                    stoploss=-0.50,
                )
            )
    out += [
        Candidate(
            "R5-random-F1-exits",
            "R random entry control",
            "random",
            random_rate=0.0005,
            exits_from="F1-regime-btc-sma100",
            deployable=False,
        ),
        Candidate("K-SwingEmaRsi", "K benchmark", "swing"),
        Candidate("K-buy-and-hold", "K benchmark", "buy_hold", deployable=False),
    ]
    return out


def all_candidates() -> dict[str, Candidate]:
    """Every configuration of every round by id; a later round wins for the shared benchmarks."""
    rounds = (round1_candidates(), round2_candidates(), round3_candidates(), round4_candidates(), candidates())
    return {c.id: c for matrix in rounds for c in matrix}


def cumulative_trials() -> int:
    """Configurations tried over every round so far, the count the multiple-testing correction uses."""
    rounds = (round1_candidates(), round2_candidates(), round3_candidates(), round4_candidates(), candidates())
    return sum(len(matrix) for matrix in rounds)
