"""Parameters of the rule strategies shared by the research simulator and the Freqtrade strategy."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Timeframe = Literal["1h", "4h", "1d"]
Ratio = Annotated[float, Field(gt=0, lt=1)]


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
    trend_filter: Literal["none", "above_sma200_1d"] = "none"
    exit: Literal["none", "donchian_mid", "tsmom_flip", "ema_cross", "sma_reclaim", "bb_mid"]
    exit_lookback: Annotated[int, Field(ge=2, le=400)] | None = None
    stoploss: Annotated[float, Field(gt=-1, lt=0)]
    take_profit: Ratio | None = None
    lock_at: Ratio | None = None
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
        return self

    def freqtrade_roi(self, fee: float) -> dict[str, float]:
        """Freqtrade ROI table whose fee-inclusive threshold fills at the gross take-profit price."""
        if self.take_profit is None:
            return {}
        return {"0": round((1 + self.take_profit) * (1 - fee) / (1 + fee) - 1, 10)}

    @property
    def informative_timeframes(self) -> tuple[str, ...]:
        """Timeframes above 1h whose completed candles the rule reads."""
        needed = {self.timeframe, "1d"} if self.trend_filter != "none" else {self.timeframe}
        return tuple(sorted(tf for tf in needed if tf != "1h"))
