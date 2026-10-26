"""Shadow swarm service: asks the voters about each entry the bot takes and records what a gate would have done."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sqlite3
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import uvicorn
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from tb_swarm.config import parse_config
from tb_swarm.models import ChoiceQuestion, DecisionRequest
from tb_swarm.runner import DecisionOutcome, SwarmRunner

from engine.decisions import DecisionStore
from engine.logredact import install as install_log_redaction
from engine.settings import ConfigError, Settings, load_settings
from engine.shadow_client import TOKEN_HEADER

logger = logging.getLogger("trading_bot.shadow")

VERDICTS = {
    "izinkan": "Take the entry at the full risk-based size.",
    "kecilkan": "Take the entry at half of the risk-based size.",
    "lewati": "Skip this entry.",
}
INSTRUCTIONS = (
    "A rule-based 1h swing strategy on a spot exchange wants to open a long position on the pair in state now."
    " Exits and the stop loss are fixed by the rules. Using only the candles, indicators and risk figures in state,"
    " decide whether this entry should go ahead."
)
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "ema_fast", "ema_slow", "rsi"]


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    bot: Annotated[str, Field(pattern=r"^[A-Z]$")]
    pair: Annotated[str, Field(pattern=r"^[A-Z0-9]+/[A-Z0-9]+$")]
    timeframe: str
    candle: str
    rate: Annotated[float, Field(gt=0)]
    entry_tag: str | None
    risk: dict[str, float]
    candles: Annotated[list[list[str | float | None]], Field(max_length=200)]


def decision_request(candidate: Candidate) -> DecisionRequest:
    return DecisionRequest(
        state={
            "pair": candidate.pair,
            "timeframe": candidate.timeframe,
            "entry_rate": candidate.rate,
            "entry_tag": candidate.entry_tag,
            "risk": candidate.risk,
            "candle_columns": CANDLE_COLUMNS,
            "candles": candidate.candles,
        },
        questions={"verdict": ChoiceQuestion(instructions=INSTRUCTIONS, criteria=dict(VERDICTS))},
    )


def verdict_of(outcome: DecisionOutcome) -> str:
    if not outcome.proceed or outcome.aggregate is None:
        return "lewati"
    return outcome.aggregate.questions["verdict"].winner


def voter_rows(outcome: DecisionOutcome, providers: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for record in outcome.voters:
        provider, model = providers[record.voter_id]
        rows.append(
            {
                **record.model_dump(mode="json"),
                "provider": provider,
                "configured_model": model,
                "model": record.model or model,
            }
        )
    return rows


class ShadowService:
    def __init__(self, settings: Settings, raw_config: dict[str, Any], store: DecisionStore, env: dict[str, str]):
        swarm_config = parse_config(raw_config)
        self.settings = settings
        self.store = store
        self.runner = SwarmRunner.from_config(swarm_config, env)
        self.providers = {voter.id: (voter.provider, voter.model) for voter in swarm_config.swarm.voters}
        self.tasks: set[asyncio.Task] = set()

    def submit(self, candidate: Candidate) -> None:
        request = decision_request(candidate)
        self.store.add_pending(
            decision_id=candidate.decision_id,
            bot=candidate.bot,
            pair=candidate.pair,
            timeframe=candidate.timeframe,
            candle=candidate.candle,
            rate=candidate.rate,
            mode=self.settings.swarm.mode,
            required=self.settings.swarm.min_voters_answered,
            iqr_limit=self.settings.swarm.max_spread,
            request=request.model_dump(mode="json"),
        )
        task = asyncio.create_task(self._decide(candidate.decision_id, request))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _decide(self, decision_id: str, request: DecisionRequest) -> None:
        try:
            outcome = await self.runner.decide(request, decision_id)
        except Exception:
            logger.exception("swarm failed for %s", decision_id)
            self.store.settle(
                decision_id,
                status="skip",
                reason="internal_error",
                answered=0,
                verdict="lewati",
                aggregate=None,
                voters=[],
            )
            return
        self.store.settle(
            decision_id,
            status=outcome.status,
            reason=outcome.reason,
            answered=outcome.answered,
            verdict=verdict_of(outcome),
            aggregate=asdict(outcome.aggregate) if outcome.aggregate else None,
            voters=voter_rows(outcome, self.providers),
        )
        logger.info(
            "decision %s %s: %s %s answered %d/%d",
            decision_id,
            request.state["pair"],
            outcome.status,
            outcome.reason or "",
            outcome.answered,
            outcome.required,
        )

    async def aclose(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.runner.aclose()


def create_app(service: ShadowService, token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        interrupted = service.store.interrupt_pending("shadow_restart")
        if interrupted:
            logger.warning("marked %d unfinished decisions as interrupted", interrupted)
        yield
        await service.aclose()

    app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)

    async def caller(request: Request) -> None:
        offered = request.headers.get(TOKEN_HEADER, "")
        if not secrets.compare_digest(offered.encode(), token.encode()):
            raise HTTPException(401, "unauthorized")

    @app.post("/candidates", status_code=202, dependencies=[Depends(caller)])
    async def candidates(candidate: Candidate) -> dict[str, str]:
        try:
            service.submit(candidate)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "decision already recorded") from exc
        return {"decision_id": candidate.decision_id}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": service.settings.swarm.mode,
            "voters": sum(1 for voter in service.settings.swarm.voters if voter.enabled),
            "pending": service.store.pending_count(),
        }

    return app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install_log_redaction()
    config_file = os.environ.get("TRADING_BOT_CONFIG", "config/config.yaml")
    userdir = Path(os.environ.get("TRADING_BOT_USERDIR", "user_data"))
    try:
        settings = load_settings(config_file)
    except ConfigError as exc:
        print(f"trading-bot shadow: refusing to start: {exc}", file=sys.stderr)
        return 2
    if not settings.swarm.enabled or settings.shadow is None:
        print("trading-bot shadow: refusing to start: swarm is disabled in this config", file=sys.stderr)
        return 2
    token = os.environ.get(settings.shadow.token_env, "")
    if len(token) < 32:
        message = f"{settings.shadow.token_env} needs at least 32 characters"
        print(f"trading-bot shadow: refusing to start: {message}", file=sys.stderr)
        return 2
    raw = yaml.safe_load(Path(config_file).read_text(encoding="utf-8"))
    store = DecisionStore(userdir / settings.shadow.database)
    service = ShadowService(settings, raw, store, dict(os.environ))
    uvicorn.run(create_app(service, token), host=settings.shadow.listen, port=settings.shadow.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
