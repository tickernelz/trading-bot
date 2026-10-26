"""Live mode control as a gateway control action: owner-only, two-step, fail closed, never from outside the machine."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

from engine.modectl import MODE_FILE, ModeController, ModeRefused, read_exchange_key_configured, read_mode
from gateway.settings import BotRef
from gateway.upstream import ApiError

REFUSAL_STATUS = {"live_blocked": 422, "invalid_request": 400}


class ModeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["dry_run", "live"]
    confirm: Annotated[str, Field(min_length=1, max_length=128)] | None = None


class ModeDesk:
    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway
        self.controllers: dict[str, ModeController] = {}

    def controller(self, bot: BotRef) -> ModeController:
        if bot.id not in self.controllers:
            self.controllers[bot.id] = ModeController(
                Path(bot.userdir) / MODE_FILE,
                exchange_key_configured=lambda: read_exchange_key_configured(bot.userdir),
            )
        return self.controllers[bot.id]


def refused(refusal: ModeRefused) -> ApiError:
    extra = {"blockers": list(refusal.blockers)} if refusal.blockers else None
    return ApiError(REFUSAL_STATUS.get(refusal.code, 400), refusal.code, refusal.message, extra=extra)


def install_mode(app: FastAPI, gateway: Any, reader: Any) -> None:
    from gateway.app import Action

    desk: ModeDesk = gateway.modes

    @app.get("/gw/v1/mode", dependencies=[Depends(reader)])
    async def mode(bot: str | None = None) -> dict[str, Any]:
        ref = gateway.bot(bot)
        return {"bot": ref.id, **desk.controller(ref).status()}

    @app.post("/gw/v1/control/mode")
    async def change(request: Request, body: ModeBody, bot: str | None = None, token: str = Depends(reader)) -> Any:
        ref = gateway.bot(bot)
        controller = desk.controller(ref)
        to_live = body.mode == "live" and read_mode(Path(ref.userdir) / MODE_FILE)[0] != "live"

        async def precheck() -> None:
            if to_live:
                try:
                    controller.ensure_live_allowed()
                except ModeRefused as refusal:
                    raise refused(refusal) from None

        async def run() -> dict[str, Any]:
            try:
                return {"bot": ref.id, **controller.apply(body.mode, "owner")}
            except ModeRefused as refusal:
                raise refused(refusal) from None

        action = Action(
            name="mode.change",
            bot=ref,
            params={"mode": body.mode},
            targets=[body.mode],
            summary=f"Switch {ref.label} to live: orders will use real money",
            risky=to_live,
            precheck=precheck,
            run=run,
        )
        return await gateway.execute(request, token, action, body.confirm)
