"""1h EMA-crossover swing strategy gated by the deterministic risk layer."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from pandas import DataFrame

from engine.risk import ClosedTrade, RiskState, assess, stake_for_risk
from engine.settings import RiskSettings

logger = logging.getLogger(__name__)


class RiskDataUnavailable(Exception):
    """Raised when an open trade cannot be priced for the risk assessment."""


class SwingEmaRsi(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 100
    use_exit_signal = True
    exit_profit_only = False
    stoploss = -0.03
    trailing_stop = False
    minimal_roi = {"0": 0.05, "480": 0.025, "1440": 0.012}
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def bot_start(self, **kwargs) -> None:
        section = self.config["trading_bot"]
        self.risk_settings = RiskSettings.model_validate(section["risk"])
        self.initial_capital = float(section["initial_capital"])

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        crossed_up = (dataframe["ema_fast"] > dataframe["ema_slow"]) & (
            dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1)
        )
        dataframe.loc[
            crossed_up & dataframe["rsi"].between(45, 70) & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "ema_cross_up")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        crossed_down = (dataframe["ema_fast"] < dataframe["ema_slow"]) & (
            dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1)
        )
        dataframe.loc[crossed_down | (dataframe["rsi"] > 78), ["exit_long", "exit_tag"]] = (1, "ema_cross_down_or_rsi")
        return dataframe

    def risk_state(self, current_time: datetime, pair: str | None = None, rate: float | None = None) -> RiskState:
        closed = [
            ClosedTrade(trade.close_date_utc, trade.close_profit_abs or 0.0)
            for trade in Trade.get_trades_proxy(is_open=False)
        ]
        open_pnl = sum(
            trade.calculate_profit(rate if trade.pair == pair and rate else self._last_close(trade.pair)).profit_abs
            for trade in Trade.get_trades_proxy(is_open=True)
        )
        return assess(self.risk_settings, self.initial_capital, closed, open_pnl, current_time)

    def _last_close(self, pair: str) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            raise RiskDataUnavailable(f"no candles for open trade {pair}")
        return float(dataframe["close"].iloc[-1])

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        try:
            state = self.risk_state(current_time, pair, current_rate)
            return stake_for_risk(self.risk_settings, state.equity, self.stoploss, min_stake, max_stake)
        except Exception:
            logger.exception("risk guard could not size %s; skipping entry", pair)
            return 0.0

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        try:
            state = self.risk_state(current_time, pair, rate)
        except Exception:
            logger.exception("risk guard could not assess %s; denying entry", pair)
            return False
        if state.entries_allowed:
            return True
        self.dp.send_msg(
            json.dumps(
                {
                    "event": "risk_guard_denied",
                    "pair": pair,
                    "breaches": list(state.breaches),
                    "daily_loss_pct": round(state.daily_loss_pct, 4),
                    "drawdown_pct": round(state.drawdown_pct, 4),
                    "equity": round(state.equity, 2),
                }
            )
        )
        logger.warning(
            "risk guard denied %s: %s (daily loss %.3f%%, drawdown %.3f%%)",
            pair,
            ",".join(state.breaches),
            state.daily_loss_pct,
            state.drawdown_pct,
        )
        return False
