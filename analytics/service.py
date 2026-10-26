"""Per-bot data sources and the scoreboard job that retires drifting voters."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analytics.errors import AnalyticsError
from analytics.scoreboard import apply_disables, plan_disables, scoreboard
from analytics.source import load_decisions
from engine.settings import ConfigError, Settings, load_settings

logger = logging.getLogger("trading_bot.analytics")

Audit = Callable[..., None]


@dataclass(frozen=True)
class BotSource:
    bot_id: str
    config_path: Path
    decisions_db: Path | None
    trades_db: Path | None

    def settings(self) -> Settings:
        try:
            return load_settings(self.config_path)
        except ConfigError as exc:
            raise AnalyticsError(500, "invalid_config", str(exc)) from exc


def evaluate(source: BotSource, limit: int, mode: str = "read") -> dict[str, Any]:
    """Score the voters of one bot; mode auto turns off the planned ones, manual the recommended ones."""
    if source.decisions_db is None:
        raise AnalyticsError(404, "not_found", f"bot {source.bot_id} records no swarm decisions")
    settings = source.settings()
    loaded = load_decisions(source.decisions_db, source.trades_db, limit)
    board = scoreboard(loaded.decisions, settings.analytics.scoreboard)
    board["invalid_decisions"] = loaded.invalid
    plan = plan_disables(board, settings)
    board["plan"] = plan
    chosen = {"read": [], "auto": plan["disable"], "manual": plan["recommended"]}[mode]
    board["applied"] = apply_disables(source.config_path, chosen)
    return board


async def auto_disable_loop(sources: list[BotSource], audit: Audit, limit: int = 2000) -> None:
    """Every interval_s per bot, retire drifting voters when the config allows auto_disable."""
    next_run: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    while True:
        for source in sources:
            try:
                config = source.settings().analytics.scoreboard
            except AnalyticsError as exc:
                logger.warning("scoreboard skipped for %s: %s", source.bot_id, exc.message)
                continue
            if not (config.enabled and config.auto_disable) or loop.time() < next_run.get(source.bot_id, 0.0):
                continue
            next_run[source.bot_id] = loop.time() + config.interval_s
            try:
                board = await asyncio.to_thread(evaluate, source, limit, "auto")
            except (AnalyticsError, ConfigError, OSError, ValueError) as exc:
                logger.warning("scoreboard failed for %s: %s", source.bot_id, exc)
                audit(
                    "analytics.scoreboard.auto_disable",
                    "failed",
                    request=None,
                    targets=[source.bot_id],
                    detail={"error": type(exc).__name__},
                )
                continue
            if board["applied"]:
                audit(
                    "analytics.scoreboard.auto_disable",
                    "ok",
                    request=None,
                    targets=[source.bot_id],
                    detail={"voters": board["applied"]},
                )
        await asyncio.sleep(30)
