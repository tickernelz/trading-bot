"""1h EMA-crossover swing strategy gated by the deterministic risk layer."""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from datetime import datetime
from pathlib import Path

import talib.abstract as ta
from freqtrade.persistence import Order, Trade
from freqtrade.strategy import IStrategy
from pandas import DataFrame

from engine.decisions import SHADOW_KEY
from engine.heartbeat import record_start, write_heartbeat
from engine.logredact import install as install_log_redaction
from engine.risk import ClosedTrade, RiskState, assess, stake_for_risk
from engine.settings import RiskSettings
from engine.shadow_client import ShadowClient

logger = logging.getLogger(__name__)

SHADOW_CANDLES = 48
SHADOW_COLUMNS = ("open", "high", "low", "close", "volume", "ema_fast", "ema_slow", "rsi")


def _number(value: object) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


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

    def __init__(self, config: dict) -> None:
        install_log_redaction()
        super().__init__(config)

    def bot_start(self, **kwargs) -> None:
        section = self.config["trading_bot"]
        self.risk_settings = RiskSettings.model_validate(section["risk"])
        self.initial_capital = float(section["initial_capital"])
        self.compounding = bool(section["compounding"])
        self.fee = float(self.config["fee"])
        self.bot_id = section["bot_id"]
        self.userdir = Path(self.config["user_data_dir"])
        self.shadow = (
            ShadowClient(section["shadow_url"], os.environ.get(section["shadow_token_env"], ""))
            if section.get("shadow_url")
            else None
        )
        self.shadow_pending: dict[str, str] = {}
        self.startup_checked = False
        self._startup_waiting = False
        self.starts = record_start(self.userdir, os.getpid())

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if not self.startup_checked:
            self.startup_check(current_time)
        write_heartbeat(
            self.userdir,
            {
                "bot": self.bot_id,
                "pid": os.getpid(),
                "starts": self.starts,
                "startup_checked": self.startup_checked,
                "open_trades": len(Trade.get_trades_proxy(is_open=True)),
                "shadow": None if self.shadow is None else {"sent": self.shadow.sent, "failed": self.shadow.failed},
            },
        )

    def startup_check(self, current_time: datetime) -> None:
        """Assess open positions and loss limits once after each start; entries stay denied until it passes."""
        open_pairs = [trade.pair for trade in Trade.get_trades_proxy(is_open=True)]
        try:
            state = self.risk_state(current_time)
        except RiskDataUnavailable as exc:
            if not self._startup_waiting:
                logger.info("startup check waiting for prices: %s", exc)
                self._startup_waiting = True
            return
        self.startup_checked = True
        report = {
            "event": "startup_check",
            "start": self.starts,
            "open_trades": open_pairs,
            "entries_allowed": state.entries_allowed,
            "breaches": list(state.breaches),
            "daily_loss_pct": round(state.daily_loss_pct, 4),
            "drawdown_pct": round(state.drawdown_pct, 4),
            "equity": round(state.equity, 2),
        }
        self.dp.send_msg(json.dumps(report), always_send=True)
        logger.info(
            "startup check %d: %d open trades %s, entries allowed %s, daily loss %.3f%%, drawdown %.3f%%",
            self.starts,
            len(open_pairs),
            open_pairs,
            state.entries_allowed,
            state.daily_loss_pct,
            state.drawdown_pct,
        )

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

    def sizing_equity(self, state: RiskState) -> float:
        return state.equity if self.compounding else min(state.equity, self.initial_capital)

    def _last_close(self, pair: str) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            raise RiskDataUnavailable(f"no candles for open trade {pair}")
        close = float(dataframe["close"].iloc[-1])
        if not math.isfinite(close) or close <= 0:
            raise RiskDataUnavailable(f"no usable close for open trade {pair}")
        return close

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
            return stake_for_risk(
                self.risk_settings, self.sizing_equity(state), self.stoploss, self.fee, min_stake, max_stake
            )
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
        if not self.startup_checked:
            logger.warning("startup check has not passed yet; denying entry for %s", pair)
            return False
        try:
            state = self.risk_state(current_time, pair, rate)
        except Exception:
            logger.exception("risk guard could not assess %s; denying entry", pair)
            return False
        if state.entries_allowed:
            self.submit_shadow(pair, rate, entry_tag, current_time, state)
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

    def submit_shadow(
        self, pair: str, rate: float, entry_tag: str | None, current_time: datetime, state: RiskState
    ) -> None:
        if self.shadow is None:
            return
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            tail = dataframe.tail(SHADOW_CANDLES)
            candles = [
                [row["date"].isoformat(), *(_number(row[column]) for column in SHADOW_COLUMNS)]
                for _, row in tail.iterrows()
            ]
            candle = candles[-1][0] if candles else current_time.isoformat()
            decision_id = uuid.uuid4().hex
            self.shadow.submit(
                {
                    "decision_id": decision_id,
                    "bot": self.bot_id,
                    "pair": pair,
                    "timeframe": self.timeframe,
                    "candle": candle,
                    "rate": rate,
                    "entry_tag": entry_tag,
                    "risk": {
                        "equity": round(state.equity, 2),
                        "daily_loss_pct": round(state.daily_loss_pct, 4),
                        "drawdown_pct": round(state.drawdown_pct, 4),
                        "max_daily_loss_pct": self.risk_settings.max_daily_loss_pct,
                        "max_total_drawdown_pct": self.risk_settings.max_total_drawdown_pct,
                    },
                    "candles": candles,
                }
            )
            self.shadow_pending[pair] = decision_id
        except Exception:
            logger.exception("shadow candidate for %s not built; entry unaffected", pair)

    def order_filled(self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs) -> None:
        if order.ft_order_side != trade.entry_side:
            return
        decision_id = self.shadow_pending.pop(pair, None)
        if decision_id:
            trade.set_custom_data(SHADOW_KEY, decision_id)
