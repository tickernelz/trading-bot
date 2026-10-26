"""Configurable rule strategy from config strategy.rule, gated by the deterministic risk layer."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from freqtrade.persistence import Trade
from pandas import DataFrame

from engine.rules import RuleSpec
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
        held = dataframe[dataframe["date"] >= pd.Timestamp(trade.open_date_utc).floor("1h")]
        if held.empty:
            return None
        closes = held["close"].to_numpy(dtype=float)
        hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        reason = trade_exit_reason(self.rule, trade.open_rate, closes, float(held["rule_atr"].iloc[-1]), hours)
        return None if reason is None else f"rule_{reason}"
