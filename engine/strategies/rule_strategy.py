"""Configurable rule strategy from config strategy.rule, gated by the deterministic risk layer."""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute
from pandas import DataFrame

from engine.rules import RuleSpec, fee_inclusive_roi
from engine.signals import rule_frame, trade_exit_reason
from engine.strategies.gated import RiskGated
from engine.strategies.swing_ema_rsi import swing_indicators

STARTUP_CANDLES = 400


class RuleStrategy(RiskGated):
    startup_candle_count = STARTUP_CANDLES
    stoploss = -0.10
    minimal_roi: dict = {}

    def __init__(self, config: dict) -> None:
        self.rule = RuleSpec.model_validate(config["trading_bot"]["rule"])
        self.stoploss = self.rule.stoploss
        self.fee = float(config["fee"])
        self.minimal_roi = self.rule.freqtrade_roi(self.fee)
        self.use_custom_roi = self.rule.take_profit_atr is not None
        self.use_custom_stoploss = self.rule.stop_atr is not None
        super().__init__(config)

    def informative_pairs(self) -> list[tuple[str, str]]:
        return [(pair, tf) for pair in self.dp.current_whitelist() for tf in self.rule.informative_timeframes]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = swing_indicators(dataframe)
        informative = {
            tf: self.dp.get_pair_dataframe(metadata["pair"], tf).loc[
                :, ["date", "open", "high", "low", "close", "volume"]
            ]
            for tf in self.rule.informative_timeframes
        }
        signals = rule_frame(dataframe, self.rule, informative)
        dataframe["rule_enter"] = signals["enter"].to_numpy()
        dataframe["rule_exit"] = signals["exit_signal"].to_numpy()
        dataframe["rule_atr"] = signals["atr"].to_numpy()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["rule_enter"], ["enter_long", "enter_tag"]] = (1, f"rule_{self.rule.entry}")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["rule_exit"], ["exit_long", "exit_tag"]] = (1, f"rule_{self.rule.exit}")
        return dataframe

    def custom_exit(
        self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs
    ) -> str | None:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None
        opened = pd.Timestamp(trade.open_date_utc).floor("1h")
        held = dataframe[dataframe["date"] >= opened]
        if held.empty:
            return None
        closes = held["close"].to_numpy(dtype=float)
        hours = (pd.Timestamp(current_time) - opened).total_seconds() / 3600
        reason = trade_exit_reason(self.rule, trade.open_rate, closes, float(held["rule_atr"].iloc[-1]), hours)
        return None if reason is None else f"rule_{reason}"

    def signal_atr(self, pair: str, trade: Trade) -> float:
        """ATR of the rule timeframe at the candle whose close produced the entry signal."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        signal = pd.Timestamp(trade.open_date_utc).floor("1h") - pd.Timedelta(hours=1)
        values = dataframe.loc[dataframe["date"] == signal, "rule_atr"] if not dataframe.empty else []
        return float(values.iloc[0]) if len(values) else math.nan

    def custom_roi(
        self, pair: str, trade: Trade, current_time: datetime, trade_duration: int, entry_tag, side: str, **kwargs
    ) -> float | None:
        target = self.rule.atr_target(trade.open_rate, self.signal_atr(pair, trade))
        return None if target is None else fee_inclusive_roi(target / trade.open_rate, self.fee)

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        stop = self.rule.stop_price(trade.open_rate, self.signal_atr(pair, trade))
        return stoploss_from_absolute(stop, current_rate)
