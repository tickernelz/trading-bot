"""FastAPI routes for the analytics endpoints, installed into the gateway app."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from analytics.errors import AnalyticsError
from analytics.export import tax_summary, trades_csv
from analytics.freqtrade import TIMERANGE, AnalysisClient, backtest_view, signals_view
from analytics.limits import TUNABLE, whatif_limits
from analytics.portfolio import portfolio
from analytics.replay import whatif_replay
from analytics.service import BotSource, evaluate
from analytics.source import load_decisions
from analytics.stress import stress
from analytics.trades import risk_inputs
from engine.launch import STRATEGY
from engine.settings import Settings

PREFIX = "/gw/v1/analytics"
MAX_SIGNAL_DAYS = 60
TRADE_LIMIT = 1000


class Context(Protocol):
    def source(self, bot: str | None) -> BotSource: ...

    async def trades(self, bot: str, limit: int) -> list[dict[str, Any]]: ...

    def analysis(self) -> AnalysisClient | None: ...

    def audit(self, action: str, detail: dict[str, Any]) -> None: ...


class ReplayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot: str | None = None
    min_voters_answered: Annotated[int, Field(ge=1)] | None = None
    max_spread: Annotated[float, Field(gt=0)] | None = None
    exclude_voters: list[str] = []
    limit: Annotated[int, Field(ge=1, le=5000)] = 500


class BacktestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot: str | None = None
    timerange: str
    max_open_trades: Annotated[int, Field(ge=1, le=20)] | None = None
    dry_run_wallet: Annotated[float, Field(gt=0)] | None = None


def error_envelope(_: Request, exc: AnalyticsError) -> JSONResponse:
    body: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.retry_after_ms is not None:
        body["retry_after_ms"] = exc.retry_after_ms
    return JSONResponse({"error": body}, status_code=exc.status)


def analysis_of(ctx: Context) -> AnalysisClient:
    client = ctx.analysis()
    if client is None:
        raise AnalyticsError(404, "not_found", "no Freqtrade webserver instance is configured for analysis")
    return client


def timerange_of(start: date, end: date) -> str:
    if end < start:
        raise AnalyticsError(422, "invalid_request", "to is before from")
    if (end - start).days > MAX_SIGNAL_DAYS:
        raise AnalyticsError(422, "invalid_request", f"range is longer than {MAX_SIGNAL_DAYS} days")
    return f"{start:%Y%m%d}-{end:%Y%m%d}"


def check_timerange(value: str) -> str:
    if not TIMERANGE.match(value):
        raise AnalyticsError(422, "invalid_request", "timerange must look like 20260901-20261001")
    return value


def make_router(ctx: Context, reader: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix=PREFIX, dependencies=[Depends(reader)])

    async def book(bot: str | None) -> tuple[BotSource, Settings, list[dict[str, Any]]]:
        source = ctx.source(bot)
        settings = await asyncio.to_thread(source.settings)
        return source, settings, await ctx.trades(source.bot_id, TRADE_LIMIT)

    @router.get("/limits/whatif")
    async def limits_whatif(
        bot: str | None = None,
        max_daily_loss_pct: Annotated[float | None, Query(gt=0, le=100)] = None,
        max_total_drawdown_pct: Annotated[float | None, Query(gt=0, le=100)] = None,
        risk_per_trade_pct: Annotated[float | None, Query(gt=0, le=100)] = None,
        max_open_trades: Annotated[int | None, Query(ge=1, le=20)] = None,
    ) -> dict[str, Any]:
        _, settings, trades = await book(bot)
        given = {
            "max_daily_loss_pct": max_daily_loss_pct,
            "max_total_drawdown_pct": max_total_drawdown_pct,
            "risk_per_trade_pct": risk_per_trade_pct,
            "max_open_trades": max_open_trades,
        }
        overrides = {key: value for key, value in given.items() if value is not None and key in TUNABLE}
        inputs = risk_inputs(settings, trades, datetime.now(UTC))
        return whatif_limits(settings.risk, overrides, inputs)

    @router.post("/replay")
    async def replay(body: ReplayBody) -> dict[str, Any]:
        source = ctx.source(body.bot)
        if source.decisions_db is None:
            raise AnalyticsError(404, "not_found", f"bot {source.bot_id} records no swarm decisions")
        settings = await asyncio.to_thread(source.settings)
        swarm = settings.swarm
        required = body.min_voters_answered if body.min_voters_answered is not None else swarm.min_voters_answered
        spread = body.max_spread if "max_spread" in body.model_fields_set else swarm.max_spread
        loaded = await asyncio.to_thread(load_decisions, source.decisions_db, source.trades_db, body.limit)
        weights = {voter.id: voter.weight for voter in swarm.voters}
        result = whatif_replay(loaded.decisions, weights, required, spread, frozenset(body.exclude_voters))
        result["invalid_decisions"] = loaded.invalid
        return result

    @router.get("/signals")
    async def signals(
        pair: str,
        start: Annotated[date, Query(alias="from")],
        end: Annotated[date, Query(alias="to")],
        bot: str | None = None,
    ) -> dict[str, Any]:
        source = ctx.source(bot)
        settings = await asyncio.to_thread(source.settings)
        if pair not in settings.exchange.pairs:
            raise AnalyticsError(404, "not_found", f"{pair} is not in the configured pairs")
        history = await analysis_of(ctx).pair_history(
            pair, settings.exchange.timeframe, timerange_of(start, end), STRATEGY
        )
        return signals_view(history)

    @router.get("/scoreboard")
    async def board(bot: str | None = None, limit: Annotated[int, Query(ge=1, le=5000)] = 2000) -> dict[str, Any]:
        return await asyncio.to_thread(evaluate, ctx.source(bot), limit, False)

    @router.post("/scoreboard/apply")
    async def board_apply(bot: str | None = None, limit: Annotated[int, Query(ge=1, le=5000)] = 2000) -> dict[str, Any]:
        source = ctx.source(bot)
        result = await asyncio.to_thread(evaluate, source, limit, True)
        if result["applied"]:
            ctx.audit("scoreboard.apply", {"bot": source.bot_id, "voters": result["applied"]})
        return result

    @router.get("/stress")
    async def stress_view(
        bot: str | None = None, drop_pct: Annotated[float | None, Query(gt=0, le=100)] = None
    ) -> dict[str, Any]:
        _, settings, trades = await book(bot)
        drop = drop_pct if drop_pct is not None else settings.analytics.stress.drop_pct
        return stress(settings.risk, risk_inputs(settings, trades, datetime.now(UTC)), drop)

    @router.get("/portfolio")
    async def portfolio_view(bot: str | None = None) -> dict[str, Any]:
        _, settings, trades = await book(bot)
        inputs = risk_inputs(settings, trades, datetime.now(UTC))
        return portfolio(settings, inputs.assess(settings.risk), inputs.positions)

    @router.get("/export/trades.csv")
    async def export_trades(bot: str | None = None) -> Response:
        source, _, trades = await book(bot)
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        return Response(
            trades_csv(trades),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="trades-{source.bot_id}-{stamp}.csv"'},
        )

    @router.get("/export/tax")
    async def export_tax(
        bot: str | None = None, year: Annotated[int | None, Query(ge=2025, le=2100)] = None
    ) -> dict[str, Any]:
        _, settings, trades = await book(bot)
        return tax_summary(trades, settings.analytics.tax.pph22_final_pct, year)

    @router.post("/backtest", status_code=202)
    async def backtest_start(body: BacktestBody) -> dict[str, Any]:
        source = ctx.source(body.bot)
        settings = await asyncio.to_thread(source.settings)
        request = {
            "strategy": STRATEGY,
            "timeframe": settings.exchange.timeframe,
            "timerange": check_timerange(body.timerange),
            "max_open_trades": body.max_open_trades or settings.risk.max_open_trades,
            "stake_amount": "unlimited",
            "enable_protections": False,
            "dry_run_wallet": body.dry_run_wallet or settings.capital.initial_idr,
            "backtest_cache": "none",
        }
        ctx.audit("backtest.start", {"bot": source.bot_id, "request": request})
        return backtest_view(await analysis_of(ctx).backtest_start(request), STRATEGY)

    @router.get("/backtest")
    async def backtest_status() -> dict[str, Any]:
        return backtest_view(await analysis_of(ctx).backtest_status(), STRATEGY)

    @router.delete("/backtest")
    async def backtest_stop() -> dict[str, Any]:
        client = analysis_of(ctx)
        status = await client.backtest_status()
        if status.get("running"):
            await client.backtest_abort()
        return backtest_view(await client.backtest_reset(), STRATEGY)

    @router.get("/backtest/history")
    async def backtest_history() -> list[dict[str, Any]]:
        return await analysis_of(ctx).backtest_history()

    @router.get("/backtest/history/result")
    async def backtest_history_result(filename: Annotated[str, Query(pattern=r"^[A-Za-z0-9._-]+$")]) -> dict[str, Any]:
        return backtest_view(await analysis_of(ctx).backtest_history_result(filename, STRATEGY), STRATEGY)

    return router


def install(app: FastAPI, ctx: Context, reader: Callable[..., Any]) -> None:
    app.add_exception_handler(AnalyticsError, error_envelope)
    app.include_router(make_router(ctx, reader))
