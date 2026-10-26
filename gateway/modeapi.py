"""Live mode control: owner-only, two steps, fail closed, never from outside the machine."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from engine.modectl import MODE_FILE, Confirmation, ModeController, ModeRefused, read_exchange_key_configured
from gateway.settings import BotRef
from gateway.upstream import ApiError

LOOPBACK = frozenset({"127.0.0.1", "::1"})
FORWARDED = ("x-forwarded-for", "forwarded", "x-real-ip", "cf-connecting-ip", "true-client-ip")
IDEMPOTENCY_TTL_S = 600.0
IDEMPOTENCY_MAX = 256
REFUSAL_STATUS = {"live_blocked": 422, "confirmation_expired": 409, "confirmation_invalid": 409, "invalid_request": 400}
REFUSAL_CODE = {"confirmation_invalid": "invalid_request"}


class ModeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["dry_run", "live"]
    confirm: Annotated[str, Field(pattern=r"^cf_[0-9a-f]{16}$")] | None = None
    bot: str | None = None


def is_local(request: Request) -> bool:
    host = request.client.host if request.client else None
    return host in LOOPBACK and not any(name in request.headers for name in FORWARDED)


class ModeDesk:
    def __init__(self, gateway) -> None:
        self.gateway = gateway
        self.controllers: dict[str, ModeController] = {}
        self.replays: dict[tuple[str, str], tuple[float, str, int, dict[str, Any]]] = {}

    def controller(self, bot: BotRef) -> ModeController:
        if bot.id not in self.controllers:
            self.controllers[bot.id] = ModeController(
                Path(bot.userdir) / MODE_FILE,
                exchange_key_configured=lambda: read_exchange_key_configured(bot.userdir),
            )
        return self.controllers[bot.id]

    def remember(self, bot: BotRef, key: str, request: str, status: int, body: dict[str, Any]) -> None:
        now = time.monotonic()
        live = {item: value for item, value in self.replays.items() if now - value[0] < IDEMPOTENCY_TTL_S}
        if len(live) >= IDEMPOTENCY_MAX:
            live.pop(next(iter(live)))
        live[(bot.id, key)] = (now, request, status, body)
        self.replays = live

    def replay(self, bot: BotRef, key: str, request: str) -> tuple[int, dict[str, Any]] | None:
        found = self.replays.get((bot.id, key))
        if found is None or time.monotonic() - found[0] >= IDEMPOTENCY_TTL_S:
            return None
        if found[1] != request:
            raise ApiError(422, "invalid_request", "this Idempotency-Key was already used for a different request")
        return found[2], found[3]


def confirmation_body(confirmation: Confirmation) -> dict[str, Any]:
    return {
        "error": {
            "code": "confirmation_required",
            "message": "switching to live needs confirmation",
            "confirmation": {
                "id": confirmation.id,
                "action": confirmation.action,
                "targets": list(confirmation.targets),
                "summary": confirmation.summary,
                "expires_at": confirmation.expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            },
        }
    }


def refusal_body(refusal: ModeRefused) -> dict[str, Any]:
    error: dict[str, Any] = {"code": REFUSAL_CODE.get(refusal.code, refusal.code), "message": refusal.message}
    if refusal.blockers:
        error["blockers"] = list(refusal.blockers)
    return {"error": error}


def install_mode(app: FastAPI, gateway: Any, reader: Any) -> None:
    desk: ModeDesk = gateway.modes

    @app.get("/gw/v1/mode", dependencies=[Depends(reader)])
    async def mode(bot: str | None = None) -> dict[str, Any]:
        ref = gateway.bot(bot)
        return {"bot": ref.id, **desk.controller(ref).status()}

    @app.post("/gw/v1/control/mode", dependencies=[Depends(reader)])
    async def change(
        body: ModeBody, request: Request, idempotency_key: Annotated[str | None, Header()] = None
    ) -> JSONResponse:
        ref = gateway.bot(body.bot)
        ip = request.client.host if request.client else None
        if not is_local(request):
            gateway.ledger.audit(
                actor="owner",
                ip=ip,
                action="mode.change",
                targets=[ref.id],
                result="denied",
                detail={"mode": body.mode},
            )
            raise ApiError(403, "forbidden_local_only", "the mode can only be changed from the bot's own machine")
        if body.confirm is not None and body.mode != "live":
            raise ApiError(400, "invalid_request", "a confirmation only applies to the switch to live")
        if not idempotency_key or len(idempotency_key) > 128:
            raise ApiError(400, "invalid_request", "send an Idempotency-Key header of at most 128 characters")
        fingerprint = json.dumps([body.mode, body.confirm])
        replayed = desk.replay(ref, idempotency_key, fingerprint)
        if replayed is not None:
            return JSONResponse(replayed[1], status_code=replayed[0])
        controller = desk.controller(ref)
        status, payload, result = 200, {}, "ok"
        detail: dict[str, Any] = {"mode": body.mode}
        try:
            if body.confirm is not None:
                payload = {"bot": ref.id, **controller.confirm(body.confirm, "owner")}
            else:
                outcome = controller.request(body.mode, "owner")
                if isinstance(outcome, Confirmation):
                    status, payload, result = 409, confirmation_body(outcome), "confirmation_required"
                else:
                    payload = {"bot": ref.id, **outcome}
        except ModeRefused as refusal:
            status, payload, result = REFUSAL_STATUS.get(refusal.code, 400), refusal_body(refusal), "refused"
            detail["code"] = refusal.code
            detail["blockers"] = [item["code"] for item in refusal.blockers]
        gateway.ledger.audit(
            actor="owner",
            ip=ip,
            action="mode.change",
            targets=[ref.id],
            result=result,
            idempotency_key=idempotency_key,
            detail=detail,
        )
        if result != "confirmation_required":
            desk.remember(ref, idempotency_key, fingerprint, status, payload)
        return JSONResponse(payload, status_code=status)
