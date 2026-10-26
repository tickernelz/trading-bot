"""1h EMA-crossover swing strategy gated by the deterministic risk layer."""

from __future__ import annotations

import talib.abstract as ta
from pandas import DataFrame, Series

from engine.strategies.gated import RiskGated


def swing_indicators(dataframe: DataFrame) -> DataFrame:
    dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=20)
    dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=50)
    dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
    return dataframe


def swing_entry(dataframe: DataFrame) -> Series:
    crossed_up = (dataframe["ema_fast"] > dataframe["ema_slow"]) & (
        dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1)
    )
    return crossed_up & dataframe["rsi"].between(45, 70) & (dataframe["volume"] > 0)


def swing_exit(dataframe: DataFrame) -> Series:
    crossed_down = (dataframe["ema_fast"] < dataframe["ema_slow"]) & (
        dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1)
    )
    return crossed_down | (dataframe["rsi"] > 78)


class SwingEmaRsi(RiskGated):
    startup_candle_count = 100
    stoploss = -0.03
    minimal_roi = {"0": 0.05, "480": 0.025, "1440": 0.012}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return swing_indicators(dataframe)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[swing_entry(dataframe), ["enter_long", "enter_tag"]] = (1, "ema_cross_up")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[swing_exit(dataframe), ["exit_long", "exit_tag"]] = (1, "ema_cross_down_or_rsi")
        return dataframe
