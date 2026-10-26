"""Analyst endpoints: the snapshot the analyst reads, a proxy to the analyst service, and the daily report timer."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict, Field
from tb_swarm.analyst import ChatTurn
from tb_swarm.snapshot import write_snapshot

from engine.settings import Analyst
from gateway.settings import BotRef
from gateway.upstream import ApiError

logger = logging.getLogger("trading_bot.gateway.analyst")

TOKEN_HEADER = "X-Analyst-Token"
SNAPSHOT_TTL_S = 30.0
DECISION_ROWS = 2_000
SERVICE_TIMEOUT_S = 120.0
RETRY_AFTER_FAILURE_S = 900.0
ASK_BUDGET = 6
ASK_WINDOW_S = 60.0
PROFIT_KEYS = (
    "profit_all_coin",
    "profit_all_percent",
    "profit_closed_coin",
    "profit_closed_percent",
    "trade_count",
    "closed_trade_count",
    "winning_trades",
    "losing_trades",
    "winrate",
    "best_pair",
    "worst_pair",
    "max_drawdown",
)
KIND_STATUS = {400: "invalid_request", 404: "not_found", 409: "invalid_request"}


class ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = None
    bot: str | None = None


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    history: Annotated[list[ChatTurn], Field(max_length=20)] = []
    bot: str | None = None


class AnalystLink:
    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway
        self.http = httpx.AsyncClient(timeout=SERVICE_TIMEOUT_S)
        self.locks: dict[str, asyncio.Lock] = {}
        self.refreshed: dict[str, float] = {}
        self.attempted: dict[tuple[str, str], float] = {}
        self.done: set[tuple[str, str]] = set()
        self.asked: list[float] = []

    def configured(self, bot: BotRef) -> Analyst | None:
        return self.gateway.engine_settings(bot).analyst

    def require(self, bot: BotRef) -> Analyst:
        analyst = self.configured(bot)
        if analyst is None:
            raise ApiError(404, "not_found", f"bot {bot.id} has no analyst section in its config")
        return analyst

    def today(self, bot: BotRef) -> str:
        zone = ZoneInfo(self.gateway.engine_settings(bot).risk.daily_reset_timezone)
        return datetime.now(zone).date().isoformat()

    async def refresh(self, bot: BotRef, analyst: Analyst) -> None:
        lock = self.locks.setdefault(bot.id, asyncio.Lock())
        async with lock:
            if time.monotonic() - self.refreshed.get(bot.id, -SNAPSHOT_TTL_S) < SNAPSHOT_TTL_S:
                return
            gateway = self.gateway
            settings = gateway.engine_settings(bot)
            closed, opened = await gateway.closed_and_open(bot)
            risk, profit = await asyncio.gather(gateway.risk(bot), gateway.ft(bot, "/profit"))
            store = gateway.store(bot)
            decisions = store.recent(DECISION_ROWS) if store is not None else []
            metrics = {
                "as_of": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "bot": {"id": bot.id, "label": bot.label, "strategy": bot.strategy},
                "risk": risk,
                "profit": {key: profit.get(key) for key in PROFIT_KEYS if key in profit},
                "costs_today": gateway.costs("day"),
            }
            try:
                await asyncio.to_thread(
                    write_snapshot,
                    Path(bot.userdir) / analyst.data_dir,
                    metrics=metrics,
                    trades=[*closed, *opened],
                    decisions=decisions,
                    timezone=settings.risk.daily_reset_timezone,
                )
            except ValueError as exc:
                raise ApiError(502, "upstream_error", f"analyst snapshot failed: {exc}") from exc
            self.refreshed[bot.id] = time.monotonic()

    async def call(self, bot: BotRef, analyst: Analyst, method: str, path: str, body: Any = None) -> Any:
        token = self.gateway.env.get(analyst.token_env, "")
        if not token:
            raise ApiError(503, "upstream_error", f"set {analyst.token_env} in the gateway environment")
        try:
            response = await self.http.request(method, analyst.url + path, json=body, headers={TOKEN_HEADER: token})
        except httpx.TimeoutException as exc:
            raise ApiError(504, "upstream_unavailable", "analyst service did not answer in time", 5000) from exc
        except httpx.HTTPError as exc:
            raise ApiError(503, "upstream_unavailable", "analyst service is not reachable", 5000) from exc
        if response.status_code == 200:
            return response.json()
        detail = (
            response.json().get("detail")
            if response.headers.get("content-type", "").startswith("application/json")
            else None
        )
        if isinstance(detail, dict):
            raise ApiError(
                response.status_code if response.status_code in (502, 504) else 502,
                "upstream_error",
                f"analyst provider failed: {detail.get('kind')}",
            )
        code = KIND_STATUS.get(response.status_code)
        if code is None:
            raise ApiError(502, "upstream_error", f"analyst service answered {response.status_code}")
        raise ApiError(response.status_code, code, str(detail or "request refused"))

    def take_ask_slot(self) -> None:
        now = time.monotonic()
        self.asked = [moment for moment in self.asked if now - moment < ASK_WINDOW_S]
        if len(self.asked) >= ASK_BUDGET:
            retry = int((ASK_WINDOW_S - (now - self.asked[0])) * 1000)
            raise ApiError(429, "rate_limited", "too many analyst questions", retry)
        self.asked.append(now)

    async def generate(self, bot: BotRef, day: str, actor: str, ip: str | None = None) -> dict[str, Any]:
        analyst = self.require(bot)
        await self.refresh(bot, analyst)
        try:
            report = await self.call(bot, analyst, "POST", "/reports", {"day": day})
        except ApiError as exc:
            self.gateway.ledger.audit(
                actor=actor,
                ip=ip,
                action="analyst.report",
                targets=[bot.id],
                result="error",
                detail={"day": day, "code": exc.code},
            )
            raise
        self.gateway.ledger.audit(
            actor=actor,
            ip=ip,
            action="analyst.report",
            targets=[bot.id],
            result="ok",
            detail={"day": day, "model": report["model"], "tokens": report["usage"], "latency_s": report["latency_s"]},
        )
        return report

    async def tick(self) -> None:
        for bot in self.gateway.settings.bots:
            analyst = self.configured(bot)
            if analyst is None:
                continue
            zone = ZoneInfo(self.gateway.engine_settings(bot).risk.daily_reset_timezone)
            now = datetime.now(zone)
            hour, minute = (int(part) for part in analyst.report_at.split(":"))
            if (now.hour, now.minute) < (hour, minute):
                continue
            day = (now - timedelta(days=1)).date().isoformat()
            key = (bot.id, day)
            if (
                key in self.done
                or time.monotonic() - self.attempted.get(key, -RETRY_AFTER_FAILURE_S) < RETRY_AFTER_FAILURE_S
            ):
                continue
            self.attempted[key] = time.monotonic()
            try:
                known = (await self.call(bot, analyst, "GET", "/reports"))["days"]
                if day not in known:
                    await self.generate(bot, day, "scheduler")
                self.done.add(key)
            except ApiError as exc:
                logger.warning("daily report %s for bot %s failed: %s", day, bot.id, exc.code)

    async def aclose(self) -> None:
        await self.http.aclose()


def install_analyst(app: FastAPI, gateway: Any, reader: Any, control: Any) -> None:
    link: AnalystLink = gateway.analyst

    @app.get("/gw/v1/analyst/reports", dependencies=[Depends(reader)])
    async def reports(bot: str | None = None) -> dict[str, Any]:
        ref = gateway.bot(bot)
        analyst = link.require(ref)
        listing = await link.call(ref, analyst, "GET", "/reports")
        return {"bot": ref.id, "report_at": analyst.report_at, "days": listing["days"]}

    @app.get("/gw/v1/analyst/reports/{day}", dependencies=[Depends(reader)])
    async def report(
        day: Annotated[str, PathParam(pattern=r"^\d{4}-\d{2}-\d{2}$")], bot: str | None = None
    ) -> dict[str, Any]:
        ref = gateway.bot(bot)
        return await link.call(ref, link.require(ref), "GET", f"/reports/{day}")

    @app.post("/gw/v1/analyst/reports", dependencies=[Depends(control)])
    async def generate(body: ReportBody, request: Request) -> dict[str, Any]:
        ref = gateway.bot(body.bot)
        ip = request.client.host if request.client else None
        return await link.generate(ref, body.day or link.today(ref), "owner", ip)

    @app.post("/gw/v1/analyst/ask", dependencies=[Depends(reader)])
    async def ask(body: AskBody, request: Request) -> dict[str, Any]:
        ref = gateway.bot(body.bot)
        analyst = link.require(ref)
        link.take_ask_slot()
        await link.refresh(ref, analyst)
        ip = request.client.host if request.client else None
        payload = {"question": body.question, "history": [turn.model_dump() for turn in body.history]}
        try:
            answer = await link.call(ref, analyst, "POST", "/ask", payload)
        except ApiError as exc:
            gateway.ledger.audit(
                actor="owner", ip=ip, action="analyst.ask", targets=[ref.id], result="error", detail={"code": exc.code}
            )
            raise
        gateway.ledger.audit(
            actor="owner",
            ip=ip,
            action="analyst.ask",
            targets=[ref.id],
            result="ok",
            detail={
                "tools": [use["name"] for use in answer["tools_used"]],
                "tokens": answer["usage"],
                "latency_s": answer["latency_s"],
            },
        )
        return answer
