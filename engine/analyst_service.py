"""Analyst service: runs the read-only analyst on the gateway's snapshot and is the only holder of the model key."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import uvicorn
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from tb_swarm.analyst import (
    DAY_PATTERN,
    MAX_HISTORY_TURNS,
    MAX_QUESTION_CHARS,
    AnalystRunner,
    ChatTurn,
    ReportStore,
    build_runner,
    check_day,
)
from tb_swarm.errors import ConfigError, ProviderError

from engine.exitcodes import REFUSED
from engine.logredact import install as install_log_redaction
from engine.settings import Analyst, Settings, load_settings
from engine.settings import ConfigError as SettingsError

logger = logging.getLogger("trading_bot.analyst")

TOKEN_HEADER = "X-Analyst-Token"
REPORT_TIMEOUT_S = 90.0
ASK_TIMEOUT_S = 90.0
PROVIDER_STATUS = {"auth": 502, "rate_limit": 502, "http": 502, "network": 502, "timeout": 504}


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Annotated[str, Field(pattern=DAY_PATTERN.pattern)]


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION_CHARS)]
    history: Annotated[list[ChatTurn], Field(max_length=MAX_HISTORY_TURNS)] = []


class AnalystService:
    def __init__(self, runner: AnalystRunner, store: ReportStore, model_id: str) -> None:
        self.runner = runner
        self.store = store
        self.model_id = model_id
        self.generating: set[str] = set()


def provider_failure(exc: ProviderError) -> HTTPException:
    status = PROVIDER_STATUS.get(exc.kind, 502)
    return HTTPException(status, {"kind": exc.kind, "message": str(exc)})


def create_app(service: AnalystService, token: str) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    async def caller(request: Request) -> None:
        offered = request.headers.get(TOKEN_HEADER, "")
        if not secrets.compare_digest(offered.encode(), token.encode()):
            raise HTTPException(401, "unauthorized")

    @app.post("/reports", dependencies=[Depends(caller)])
    async def generate(body: ReportRequest) -> dict[str, Any]:
        try:
            check_day(body.day)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if body.day in service.generating:
            raise HTTPException(409, "a report for this day is already being generated")
        service.generating.add(body.day)
        try:
            report = await service.runner.daily_report(body.day, timeout_s=REPORT_TIMEOUT_S)
        except ProviderError as exc:
            logger.warning("report %s failed: %s", body.day, exc.kind)
            raise provider_failure(exc) from exc
        finally:
            service.generating.discard(body.day)
        service.store.save(report)
        return report.model_dump(mode="json")

    @app.get("/reports", dependencies=[Depends(caller)])
    async def days() -> dict[str, list[str]]:
        return {"days": service.store.days()}

    @app.get("/reports/{day}", dependencies=[Depends(caller)])
    async def report(day: str) -> dict[str, Any]:
        try:
            found = service.store.load(day)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if found is None:
            raise HTTPException(404, "no report for this day")
        return found.model_dump(mode="json")

    @app.post("/ask", dependencies=[Depends(caller)])
    async def ask(body: AskRequest) -> dict[str, Any]:
        try:
            answer = await service.runner.ask(body.question, body.history, timeout_s=ASK_TIMEOUT_S)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ProviderError as exc:
            logger.warning("ask failed: %s", exc.kind)
            raise provider_failure(exc) from exc
        return answer.model_dump(mode="json")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "model": service.model_id, "generating": sorted(service.generating)}

    return app


def build_service(
    settings: Settings, analyst: Analyst, raw: Mapping[str, Any], userdir: Path, env: Mapping[str, str]
) -> AnalystService:
    runner = build_runner(
        raw, env, userdir / analyst.data_dir, language=analyst.language, timeout_s=max(REPORT_TIMEOUT_S, ASK_TIMEOUT_S)
    )
    return AnalystService(runner, ReportStore(userdir / analyst.reports_dir), settings.llm.analyst_model)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install_log_redaction()
    config_file = os.environ.get("TRADING_BOT_CONFIG", "config/config.yaml")
    userdir = Path(os.environ.get("TRADING_BOT_USERDIR", "user_data"))
    try:
        settings = load_settings(config_file)
        analyst = settings.analyst
        if analyst is None:
            raise ConfigError("this config has no analyst section")
        token = os.environ.get(analyst.token_env, "")
        if len(token) < 32:
            raise ConfigError(f"{analyst.token_env} needs at least 32 characters")
        raw = yaml.safe_load(Path(config_file).read_text(encoding="utf-8"))
        service = build_service(settings, analyst, raw, userdir, dict(os.environ))
    except (SettingsError, ConfigError) as exc:
        print(f"trading-bot analyst: refusing to start: {exc}", file=sys.stderr)
        return REFUSED
    uvicorn.run(create_app(service, token), host=analyst.listen, port=analyst.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
