"""Entry and exit signals of the rule strategies on 1h candles, higher timeframes merged without lookahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import merge_informative_pair

from engine.rules import RuleSpec

BASE = "1h"
ADX_PERIOD = 14
ATR_PERIOD = 14
VOLUME_PERIOD = 20
BB_DEVIATIONS = 2.0
FREQ = {"4h": "4h", "1d": "24h"}


def resample(candles: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate 1h candles into UTC-aligned candles of timeframe, as Indodax serves them."""
    frame = candles.set_index("date")
    grouped = frame.resample(FREQ[timeframe], label="left", closed="left", origin="epoch")
    out = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
        }
    ).dropna(subset=["open", "close"])
    return out.reset_index()


def _indicators(candles: pd.DataFrame, spec: RuleSpec, timeframe: str) -> pd.DataFrame:
    shift = 1 if timeframe == BASE else 0
    out = pd.DataFrame({"date": candles["date"], "close": candles["close"]})
    if timeframe == spec.timeframe:
        out["dc_high"] = candles["high"].rolling(spec.lookback).max().shift(shift)
        out["ret"] = candles["close"] / candles["close"].shift(spec.lookback) - 1
        out["adx"] = ta.ADX(candles, timeperiod=ADX_PERIOD)
        out["atr"] = ta.ATR(candles, timeperiod=ATR_PERIOD)
        out["rsi"] = ta.RSI(candles, timeperiod=spec.lookback)
        out["vol_ratio"] = candles["volume"] / candles["volume"].rolling(VOLUME_PERIOD).mean()
        bands = ta.BBANDS(candles, timeperiod=spec.lookback, nbdevup=BB_DEVIATIONS, nbdevdn=BB_DEVIATIONS)
        out["bb_lower"] = bands["lowerband"]
        out["bb_mid"] = bands["middleband"]
        if spec.fast is not None and spec.slow is not None:
            out["ema_fast"] = ta.EMA(candles, timeperiod=spec.fast)
            out["ema_slow"] = ta.EMA(candles, timeperiod=spec.slow)
        if spec.exit_lookback is not None:
            highs = candles["high"].rolling(spec.exit_lookback).max()
            lows = candles["low"].rolling(spec.exit_lookback).min()
            out["dc_mid"] = ((highs + lows) / 2).shift(shift)
            out["sma_exit"] = ta.SMA(candles, timeperiod=spec.exit_lookback)
    if timeframe == "1d" and spec.trend_sma is not None:
        out["sma_trend"] = ta.SMA(candles, timeperiod=spec.trend_sma)
    return out


def _on_base(base: pd.DataFrame, indicators: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == BASE:
        return indicators.drop(columns=["date"]).reset_index(drop=True)
    merged = merge_informative_pair(base[["date"]], indicators, BASE, timeframe, ffill=True)
    columns = [column for column in indicators.columns if column != "date"]
    return merged[[f"{column}_{timeframe}" for column in columns]].set_axis(columns, axis=1).reset_index(drop=True)


def _edge(condition: pd.Series) -> pd.Series:
    condition = condition.fillna(False).astype(bool)
    return condition & ~condition.shift(1, fill_value=False)


def rule_frame(candles: pd.DataFrame, spec: RuleSpec, informative: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return enter, exit_signal and atr per 1h candle.

    informative maps a timeframe to its completed candles; a btc trend filter reads the 1d BTC/IDR frame there.
    """
    base = candles.reset_index(drop=True)
    sources = {BASE: base, **informative}
    main = _on_base(base, _indicators(sources[spec.timeframe], spec, spec.timeframe), spec.timeframe)
    close = base["close"]
    if spec.entry == "donchian":
        condition = close > main["dc_high"]
    elif spec.entry == "tsmom":
        condition = main["ret"] > 0
    elif spec.entry == "ema_trend":
        condition = main["ema_fast"] > main["ema_slow"]
    elif spec.entry == "breakout_volume":
        condition = (close > main["dc_high"]) & (main["vol_ratio"] > spec.threshold)
    elif spec.entry == "rsi_dip":
        condition = main["rsi"] < spec.threshold
    else:
        condition = main["close"] < main["bb_lower"]
    if spec.adx_min is not None:
        condition &= main["adx"] > spec.adx_min
    if spec.adx_max is not None:
        condition &= main["adx"] < spec.adx_max
    if spec.trend_sma is not None:
        if spec.trend_on_btc:
            daily = _on_base(base, _indicators(sources["btc"], spec, "1d"), "1d")
        else:
            daily = main if spec.timeframe == "1d" else _on_base(base, _indicators(sources["1d"], spec, "1d"), "1d")
        condition &= daily["close"] > daily["sma_trend"]
    condition &= base["volume"] > 0
    if spec.exit == "donchian_mid":
        exit_signal = close < main["dc_mid"]
    elif spec.exit == "tsmom_flip":
        exit_signal = main["ret"] < 0
    elif spec.exit == "ema_cross":
        exit_signal = main["ema_fast"] < main["ema_slow"]
    elif spec.exit == "sma_reclaim":
        exit_signal = main["close"] > main["sma_exit"]
    elif spec.exit == "bb_mid":
        exit_signal = main["close"] > main["bb_mid"]
    else:
        exit_signal = pd.Series(False, index=base.index)
    return pd.DataFrame(
        {
            "enter": _edge(condition).to_numpy(),
            "exit_signal": exit_signal.fillna(False).astype(bool).to_numpy(),
            "atr": main["atr"].to_numpy(dtype=float),
        },
        index=candles.index,
    )


def trade_exit_reason(
    spec: RuleSpec, entry_price: float, closes: np.ndarray, atr: float, held_hours: float
) -> str | None:
    """Exit decided at a candle close from the closes since entry; filled at the next open."""
    last = float(closes[-1])
    if spec.max_hold_hours is not None and held_hours >= spec.max_hold_hours:
        return "time"
    if spec.trail_atr is not None and np.isfinite(atr) and last < float(np.max(closes)) - spec.trail_atr * atr:
        return "trail"
    if spec.lock_at is not None and np.max(closes) >= entry_price * (1 + spec.lock_at):
        if last < entry_price * (1 + spec.lock_at / 2):
            return "lock"
    return None
