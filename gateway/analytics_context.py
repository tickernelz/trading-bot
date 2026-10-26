"""Binds the analytics package to the gateway: bot sources, full trade books, audit rows and the control guard."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Request

from analytics.freqtrade import AnalysisClient
from analytics.service import BotSource, auto_disable_loop
from engine.launch import DRY_RUN_DB
from gateway.control import is_local, loggable_key

if TYPE_CHECKING:
    from gateway.app import Gateway

logger = logging.getLogger("trading_bot.gateway.analytics")

RESTART_DELAY_S = 30


class AnalyticsContext:
    def __init__(self, gateway: Gateway, analysis: AnalysisClient | None) -> None:
        self.gateway = gateway
        self.client = analysis

    def scored_sources(self) -> list[BotSource]:
        sources = (self.source(bot.id) for bot in self.gateway.settings.bots)
        return [source for source in sources if source.decisions_db is not None]

    def source(self, bot: str | None) -> BotSource:
        ref = self.gateway.bot(bot)
        return BotSource(
            bot_id=ref.id,
            config_path=Path(ref.config),
            decisions_db=Path(ref.decisions) if ref.decisions else None,
            trades_db=Path(ref.userdir) / DRY_RUN_DB,
        )

    async def trades(self, bot: str) -> list[dict[str, Any]]:
        closed, opened = await self.gateway.closed_and_open(self.gateway.bot(bot))
        return [*closed, *opened]

    def analysis(self) -> AnalysisClient | None:
        return self.client

    def can_control(self, request: Request) -> bool:
        token = self.gateway.token_of(request)
        return is_local(request) and token is not None and self.gateway.ledger.session_scope(token) == "control"

    def actor_of(self, request: Request | None, result: str) -> str:
        if request is None:
            return "gateway"
        if result != "forbidden":
            return "owner"
        token = self.gateway.token_of(request)
        return f"{self.gateway.ledger.session_scope(token) if token else None}_session"

    def audit(
        self, action: str, result: str, *, request: Request | None, targets: list[str], detail: dict[str, Any]
    ) -> None:
        raw_key = request.headers.get("idempotency-key") if request is not None else None
        row = self.gateway.ledger.audit(
            actor=self.actor_of(request, result),
            action=action,
            targets=targets,
            result=result,
            ip=request.client.host if request is not None and request.client else None,
            idempotency_key=loggable_key(raw_key),
            detail=detail,
        )
        known = {bot.id for bot in self.gateway.settings.bots}
        bot = targets[0] if len(targets) == 1 and targets[0] in known else None
        self.gateway.hub.emit("gw.audit", row, bot=bot)

    async def run_auto_disable(self) -> None:
        while True:
            try:
                await auto_disable_loop(self.scored_sources(), self.audit)
            except Exception as exc:
                logger.warning("auto-disable loop stopped, restarting: %r", exc)
                await asyncio.sleep(RESTART_DELAY_S)

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
