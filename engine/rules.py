"""Parameters of the rule strategies shared by the research simulator and the Freqtrade strategy."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Timeframe = Literal["1h", "4h", "1d"]
Ratio = Annotated[float, Field(gt=0, lt=1)]


def fee_inclusive_roi(gross_ratio: float, fee: float) -> float:
    """Freqtrade ROI threshold reached exactly when the price is gross_ratio times the entry price."""
    return gross_ratio * (1 - fee) / (1 + fee) - 1


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry: Literal["donchian", "tsmom", "ema_trend", "breakout_volume", "rsi_dip", "bollinger_range"]
    timeframe: Timeframe
    lookback: Annotated[int, Field(ge=2, le=400)]
    fast: Annotated[int, Field(ge=2, le=400)] | None = None
    slow: Annotated[int, Field(ge=3, le=400)] | None = None
    threshold: Annotated[float, Field(gt=0, le=100)] | None = None
    adx_min: Annotated[float, Field(gt=0, lt=100)] | None = None
    adx_max: Annotated[float, Field(gt=0, lt=100)] | None = None
    trend_filter: Literal["none", "above_sma50_1d", "above_sma100_1d", "above_sma200_1d"] = "none"
    exit: Literal["none", "donchian_mid", "tsmom_flip", "ema_cross", "sma_reclaim", "bb_mid"]
    exit_lookback: Annotated[int, Field(ge=2, le=400)] | None = None
    stoploss: Annotated[float, Field(gt=-1, lt=0)]
    take_profit: Ratio | None = None
    lock_at: Ratio | None = None
    take_profit_atr: Annotated[float, Field(gt=0, le=20)] | None = None
    stop_atr: Annotated[float, Field(gt=0, le=20)] | None = None
    trail_atr: Annotated[float, Field(gt=0, le=20)] | None = None
    max_hold_hours: Annotated[int, Field(ge=1, le=24 * 365)] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RuleSpec:
        if self.entry == "ema_trend" and (self.fast is None or self.slow is None or self.fast >= self.slow):
            raise ValueError("ema_trend needs fast < slow")
        if self.exit == "ema_cross" and (self.fast is None or self.slow is None):
            raise ValueError("exit ema_cross needs fast and slow")
        if self.entry in ("breakout_volume", "rsi_dip") and self.threshold is None:
            raise ValueError(f"entry {self.entry} needs threshold")
        if self.exit in ("donchian_mid", "sma_reclaim") and self.exit_lookback is None:
            raise ValueError(f"exit {self.exit} needs exit_lookback")
        if self.lock_at is not None and self.take_profit is not None and self.lock_at >= self.take_profit:
            raise ValueError("lock_at must be below take_profit")
        if self.adx_min is not None and self.adx_max is not None and self.adx_min >= self.adx_max:
            raise ValueError("adx_min must be below adx_max")
        if self.take_profit is not None and self.take_profit_atr is not None:
            raise ValueError("take_profit and take_profit_atr exclude each other")
        if self.lock_at is not None and self.take_profit_atr is not None:
            raise ValueError("lock_at needs a fixed take_profit")
        return self

    @property
    def trend_sma(self) -> int | None:
        """Length of the 1d SMA the trend filter compares the daily close with."""
        return {"none": None, "above_sma50_1d": 50, "above_sma100_1d": 100, "above_sma200_1d": 200}[self.trend_filter]

    def atr_target(self, entry_price: float, atr: float) -> float | None:
        """Gross take-profit price from the ATR known at the signal candle."""
        if self.take_profit_atr is None or not math.isfinite(atr):
            return None
        return entry_price + self.take_profit_atr * atr

    def stop_price(self, entry_price: float, atr: float) -> float:
        """Stop price: the ATR stop when it is set and tighter than the hard stoploss, else the hard stoploss."""
        hard = entry_price * (1 + self.stoploss)
        if self.stop_atr is None or not math.isfinite(atr):
            return hard
        return max(hard, entry_price - self.stop_atr * atr)

    def freqtrade_roi(self, fee: float) -> dict[str, float]:
        """Freqtrade ROI table whose fee-inclusive threshold fills at the gross take-profit price."""
        if self.take_profit is None:
            return {}
        return {"0": round(fee_inclusive_roi(1 + self.take_profit, fee), 10)}

    @property
    def informative_timeframes(self) -> tuple[str, ...]:
        """Timeframes above 1h whose completed candles the rule reads."""
        needed = {self.timeframe, "1d"} if self.trend_filter != "none" else {self.timeframe}
        return tuple(sorted(tf for tf in needed if tf != "1h"))
