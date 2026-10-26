"""Owner-only configuration endpoints: settings, providers and keys, voters and roles."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from engine.settings import ConfigError, Settings
from gateway.configstore import (
    breached_limits,
    check_patch,
    diff,
    inline_keys,
    merge,
    raising_keys,
    read_raw,
    snapshot,
    unsafe_for_inline_key,
    validate,
    validate_or_none,
    write_raw,
)
from gateway.control import digest, idempotency_key, is_local, loggable_key, sanitize
from gateway.ledger import iso
from gateway.providers import (
    PROVIDER_ID,
    TEST_COOLDOWN_S,
    ProviderTester,
    apply_import,
    check_provider_id,
    clear_key,
    delete_provider,
    import_blocker,
    import_candidate,
    provider_view,
    read_models_yml,
    set_key,
    upsert_provider,
)
from gateway.redact import registry
from gateway.upstream import ApiError

logger = logging.getLogger("trading_bot.gateway.admin")

MAX_TEST_CONCURRENCY = 2
HISTORY_SCAN = 500
LOCAL_ONLY_MESSAGE = "this action works only from 127.0.0.1 on the bot machine"


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsPatch(Body):
    changes: dict[str, Any]
    confirm: str | None = None


class ProviderBody(Body):
    type: Literal["openai-completions", "openai-responses", "anthropic-messages"]
    base_url: str = Field(pattern=r"^https?://\S+$")
    models: list[str] = Field(min_length=1)


class KeyBody(Body):
    api_key: SecretStr | None = None
    api_key_env: str | None = None


class ImportItem(Body):
    name: str
    with_key: bool = False
    models: list[str] | None = None
    replace: bool = False


class ImportBody(Body):
    providers: list[ImportItem] = Field(min_length=1)


class ProbeBody(Body):
    model: str | None = None


class VoterBody(Body):
    adapter: Literal["llm_structured", "systemone", "openrouter_decisions", "openai_decisions"]
    provider: str
    model: str
    variation: Literal["option_order", "temperature", "prompt_variant"]
    timeout_s: float
    weight: float
    enabled: bool


class RoleRef(Body):
    provider: str
    model: str


class RolesBody(Body):
    analyst: RoleRef | None = None
    voters: dict[str, RoleRef] = Field(default_factory=dict)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def confirmation_response(confirmation: dict[str, Any], message: str) -> JSONResponse:
    body = {"code": "confirmation_required", "message": message, "confirmation": confirmation}
    return JSONResponse({"error": body}, status_code=409)


def apply_patch(raw: dict[str, Any], changes: dict[str, Any]) -> None:
    merged = merge(raw, changes)
    raw.clear()
    raw.update(merged)


def check_voter_id(voter_id: str) -> None:
    if not PROVIDER_ID.match(voter_id):
        raise ApiError(400, "invalid_request", f"invalid voter id {voter_id!r}")


class Admin:
    def __init__(
        self,
        gateway: Any,
        tester: ProviderTester | None = None,
        models_yml: str | Path | None = None,
    ) -> None:
        self.gateway = gateway
        self.tester = tester or ProviderTester()
        self.models_yml = Path(models_yml or gateway.settings.models_yml).expanduser()
        self.locks: dict[str, asyncio.Lock] = {}
        self.test_slots = asyncio.Semaphore(MAX_TEST_CONCURRENCY)
        self.test_started: dict[tuple[str, str], float] = {}
        self.tests: dict[tuple[str, str], dict[str, Any]] = {}
        self.hydrated = False
        for ref in gateway.settings.bots:
            try:
                self.remember(gateway.engine_settings(ref))
            except (ConfigError, ApiError, OSError):
                logger.warning("bot %s configuration could not be read at start", ref.id)

    def lock(self, bot_id: str) -> asyncio.Lock:
        return self.locks.setdefault(bot_id, asyncio.Lock())

    def remember(self, settings: Settings) -> None:
        for provider in settings.providers:
            if provider.api_key is not None:
                registry.add(provider.api_key.get_secret_value())
            if provider.api_key_env:
                registry.add(self.gateway.env.get(provider.api_key_env))

    def audit(
        self,
        request: Request,
        ref: Any,
        action: str,
        result: str,
        detail: dict[str, Any] | None,
        *,
        targets: list[str] | None = None,
        actor: str = "owner",
    ) -> dict[str, Any]:
        row = self.gateway.ledger.audit(
            actor=actor,
            ip=client_ip(request),
            action=action,
            targets=targets if targets is not None else [ref.id],
            result=result,
            idempotency_key=loggable_key(request.headers.get("idempotency-key")),
            detail=detail,
        )
        self.gateway.hub.emit("gw.audit", row, bot=ref.id if ref is not None else None)
        return row

    async def write(
        self,
        request: Request,
        token: str,
        ref: Any,
        action: str,
        edit: Callable[[dict[str, Any]], None],
        *,
        extra: Any,
        confirm: str | None = None,
        render: Callable[[Settings], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | JSONResponse:
        raw_key = request.headers.get("idempotency-key")
        try:
            key = idempotency_key(raw_key)
        except ApiError as exc:
            self.audit(request, ref, action, "rejected", {"error": exc.code})
            raise
        request_hash = digest({"action": action, "bot": ref.id, "params": extra})
        stored = self.gateway.ledger.stored_result(key)
        if stored is not None:
            if stored[0] != request_hash:
                self.audit(request, ref, action, "rejected", {"error": "idempotency_key_reused"})
                raise ApiError(409, "invalid_request", "Idempotency-Key was already used for another request")
            self.audit(request, ref, action, "replayed", {"status": stored[1]})
            return JSONResponse(stored[2], status_code=stored[1])
        inflight = self.gateway.inflight
        if key in inflight:
            raise ApiError(409, "invalid_request", "a request with this Idempotency-Key is still running")
        inflight.add(key)
        try:
            async with self.lock(ref.id):
                return await self.apply(request, token, ref, action, edit, extra, confirm, render, key, request_hash)
        finally:
            inflight.discard(key)

    async def apply(
        self,
        request: Request,
        token: str,
        ref: Any,
        action: str,
        edit: Callable[[dict[str, Any]], None],
        extra: Any,
        confirm: str | None,
        render: Callable[[Settings], dict[str, Any]] | None,
        key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        params = sanitize(extra)

        def log(result: str, detail: dict[str, Any]) -> dict[str, Any]:
            return self.audit(request, ref, action, result, {"params": params, **detail})

        raw_old = read_raw(ref.config)
        old = validate_or_none(raw_old)
        raw_new = copy.deepcopy(raw_old)
        try:
            edit(raw_new)
            new = validate(raw_new)
        except ApiError as exc:
            if exc.status == 400:
                self.audit(request, ref, action, "rejected", {"error": exc.code, "message": exc.message})
            raise
        changes = diff(raw_old, raw_new)
        if not changes:
            return {"bot": ref.id, "changes": [], "restart_required": False, **(render(new) if render else {})}
        changed = {item["key"] for item in changes}
        risk_check = "not_needed"
        if any(name in changed for name in ("risk.max_daily_loss_pct", "risk.max_total_drawdown_pct")):
            try:
                hits = breached_limits(new, old, await self.gateway.risk(ref))
                risk_check = "checked"
            except (ApiError, ConfigError):
                hits, risk_check = [], "skipped_upstream_unavailable"
            if hits:
                log("rejected", {"error": "risk_limit_breached", "hits": hits})
                raise ApiError(409, "risk_limit_breached", "; ".join(hits))
        risky = raising_keys(raw_old, raw_new)
        if risky:
            binding = digest({"request": request_hash, "session": digest(token)})
            if confirm is None:
                steps = {item["key"]: item for item in changes}
                summary = "Raise " + "; ".join(f"{name} {steps[name]['old']} -> {steps[name]['new']}" for name in risky)
                pending = self.gateway.confirmations.issue(action, [ref.id], summary, binding)
                log("confirmation_required", {"keys": risky})
                raise ApiError(
                    409,
                    "confirmation_required",
                    "raising risk limits needs a second step",
                    extra={"confirmation": pending.public()},
                )
            try:
                self.gateway.confirmations.redeem(confirm, binding)
            except ApiError as exc:
                log("rejected", {"error": exc.code, "keys": risky})
                raise
        added = set(inline_keys(raw_new)) - set(inline_keys(raw_old))
        if added and await asyncio.to_thread(unsafe_for_inline_key, ref.config):
            log("rejected", {"error": "config_not_ignored"})
            raise ApiError(
                400,
                "invalid_request",
                "the config file is inside a git work tree and is not ignored; use api_key_env instead",
            )
        digest_hex = write_raw(ref.config, raw_new)
        self.gateway.ledger.store_config_hash(ref.id, digest_hex, snapshot(raw_new))
        self.gateway.bot_settings.pop(ref.id, None)
        self.remember(new)
        row = log(
            "ok", {"changes": changes, "confirmed": bool(risky), "risk_check": risk_check, "restart_required": True}
        )
        response = {
            "bot": ref.id,
            "changes": changes,
            "restart_required": True,
            "audit_id": row["id"],
            **(render(new) if render else {}),
        }
        self.gateway.ledger.store_result(key, request_hash, 200, response)
        return response

    def last_test(self, bot_id: str, provider_id: str) -> dict[str, Any] | None:
        if not self.hydrated:
            for row in self.gateway.ledger.audit_rows(HISTORY_SCAN, action="provider.test"):
                if len(row["targets"]) == 2 and row["detail"]:
                    self.tests.setdefault(
                        (row["targets"][0], row["targets"][1]), {**row["detail"], "tested_at": row["ts"]}
                    )
            self.hydrated = True
        return self.tests.get((bot_id, provider_id))

    def router(self, reader: Callable[..., Any]) -> APIRouter:
        gateway = self.gateway
        api = APIRouter(prefix="/gw/v1")

        async def owner(request: Request, token: str = Depends(reader)) -> str:
            scope = gateway.ledger.session_scope(token)
            reason = "not_local" if not is_local(request) else ("scope" if scope != "control" else None)
            if reason is not None:
                self.audit(
                    request,
                    None,
                    "admin.denied",
                    "forbidden",
                    {"method": request.method, "path": request.url.path, "reason": reason},
                    targets=[],
                    actor=f"{scope}_session",
                )
                message = LOCAL_ONLY_MESSAGE if reason == "not_local" else "sign in from 127.0.0.1 to get control scope"
                raise ApiError(403, "forbidden_local_only", message)
            return token

        def settings_of(ref: Any) -> Settings:
            settings = gateway.engine_settings(ref)
            self.remember(settings)
            return settings

        def provider_views(ref: Any, settings: Settings) -> list[dict[str, Any]]:
            return [
                provider_view(provider, settings, gateway.env, self.last_test(ref.id, provider.id))
                for provider in settings.providers
            ]

        def one_provider(provider_id: str) -> Callable[[Settings], dict[str, Any]]:
            def render(settings: Settings) -> dict[str, Any]:
                provider = next((item for item in settings.providers if item.id == provider_id), None)
                return {"provider": provider_view(provider, settings, gateway.env, None)} if provider else {}

            return render

        def voter_list(settings: Settings, ref: Any) -> list[dict[str, Any]]:
            return [
                {**voter.model_dump(), "last_test": self.last_test(ref.id, voter.provider)}
                for voter in settings.swarm.voters
            ]

        @api.get("/settings/changes", dependencies=[Depends(reader)])
        async def changes(bot: str | None = None, limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
            wanted = gateway.bot(bot).id if bot else None
            out: list[dict[str, Any]] = []
            for row in gateway.ledger.audit_rows(limit * 4, action="config."):
                if wanted and wanted not in row["targets"]:
                    continue
                for item in (row["detail"] or {}).get("changes") or []:
                    out.append(
                        {
                            "audit_id": row["id"],
                            "ts": row["ts"],
                            "actor": row["actor"],
                            "ip": row["ip"],
                            "action": row["action"],
                            "bot": row["targets"][0] if row["targets"] else None,
                            **item,
                        }
                    )
            return out[:limit]

        @api.patch("/settings")
        async def patch_settings(
            body: SettingsPatch, request: Request, bot: str | None = None, token: str = Depends(owner)
        ):
            ref = gateway.bot(bot)
            check_patch(body.changes)
            return await self.write(
                request,
                token,
                ref,
                "config.update",
                lambda raw: apply_patch(raw, body.changes),
                extra={"changes": body.changes},
                confirm=body.confirm,
            )

        @api.get("/providers", dependencies=[Depends(reader)])
        async def providers(bot: str | None = None) -> dict[str, Any]:
            ref = gateway.bot(bot)
            return {"bot": ref.id, "providers": provider_views(ref, settings_of(ref))}

        @api.get("/providers/import", dependencies=[Depends(owner)])
        async def import_preview(bot: str | None = None) -> dict[str, Any]:
            ref = gateway.bot(bot)
            existing = {item.id for item in settings_of(ref).providers}
            out = []
            for name, entry in read_models_yml(self.models_yml).items():
                candidate = import_candidate(name, entry)
                out.append({**candidate, "exists": candidate["id"] in existing, "blocker": import_blocker(candidate)})
            return {"bot": ref.id, "providers": out}

        @api.post("/providers/import")
        async def import_apply(body: ImportBody, request: Request, bot: str | None = None, token: str = Depends(owner)):
            ref = gateway.bot(bot)
            results: list[dict[str, Any]] = []

            def edit(raw: dict[str, Any]) -> None:
                results.extend(
                    apply_import(raw, read_models_yml(self.models_yml), [item.model_dump() for item in body.providers])
                )

            return await self.write(
                request,
                token,
                ref,
                "config.provider.import",
                edit,
                extra=body.model_dump(),
                render=lambda settings: {"results": results},
            )

        @api.put("/providers/{provider_id}")
        async def put_provider(
            provider_id: str, body: ProviderBody, request: Request, bot: str | None = None, token: str = Depends(owner)
        ):
            ref = gateway.bot(bot)
            check_provider_id(provider_id)
            return await self.write(
                request,
                token,
                ref,
                "config.provider.upsert",
                lambda raw: upsert_provider(raw, provider_id, body.type, body.base_url, body.models),
                extra=body.model_dump(),
                render=one_provider(provider_id),
            )

        @api.delete("/providers/{provider_id}")
        async def remove_provider(
            provider_id: str, request: Request, bot: str | None = None, token: str = Depends(owner)
        ):
            ref = gateway.bot(bot)
            return await self.write(
                request,
                token,
                ref,
                "config.provider.delete",
                lambda raw: delete_provider(raw, provider_id),
                extra={"provider": provider_id},
            )

        @api.put("/providers/{provider_id}/key")
        async def put_key(
            provider_id: str, body: KeyBody, request: Request, bot: str | None = None, token: str = Depends(owner)
        ):
            ref = gateway.bot(bot)
            secret = body.api_key.get_secret_value() if body.api_key is not None else None
            registry.add(secret)
            return await self.write(
                request,
                token,
                ref,
                "config.provider.key",
                lambda raw: set_key(raw, provider_id, secret, body.api_key_env),
                extra={"provider": provider_id, "api_key": secret, "api_key_env": body.api_key_env},
                render=one_provider(provider_id),
            )

        @api.delete("/providers/{provider_id}/key")
        async def remove_key(provider_id: str, request: Request, bot: str | None = None, token: str = Depends(owner)):
            ref = gateway.bot(bot)
            return await self.write(
                request,
                token,
                ref,
                "config.provider.key",
                lambda raw: clear_key(raw, provider_id),
                extra={"provider": provider_id, "clear": True},
                render=one_provider(provider_id),
            )

        @api.post("/providers/{provider_id}/test")
        async def test_provider(
            provider_id: str,
            request: Request,
            body: ProbeBody | None = None,
            bot: str | None = None,
            token: str = Depends(reader),
        ) -> dict[str, Any]:
            ref = gateway.bot(bot)
            settings = settings_of(ref)
            provider = next((item for item in settings.providers if item.id == provider_id), None)
            if provider is None:
                raise ApiError(404, "not_found", f"unknown provider {provider_id}")
            model = body.model if body and body.model else provider.models[0]
            if model not in provider.models:
                raise ApiError(400, "invalid_request", f"model {model!r} is not listed by provider {provider_id}")
            slot = (ref.id, provider_id)
            now = time.monotonic()
            waited = now - self.test_started.get(slot, -TEST_COOLDOWN_S)
            if waited < TEST_COOLDOWN_S:
                raise ApiError(
                    429, "rate_limited", "this provider was tested a moment ago", int((TEST_COOLDOWN_S - waited) * 1000)
                )
            self.test_started[slot] = now
            key = (
                provider.api_key.get_secret_value() if provider.api_key else gateway.env.get(provider.api_key_env or "")
            )
            registry.add(key)
            async with self.test_slots:
                result = await self.tester.run(provider, model, key)
            result["tested_at"] = iso(datetime.now(UTC))
            self.tests[slot] = result
            scope = gateway.ledger.session_scope(token)
            self.audit(
                request,
                ref,
                "provider.test",
                "ok" if result["ok"] else "failed",
                {name: value for name, value in result.items() if name != "tested_at"},
                targets=[ref.id, provider_id],
                actor="owner" if scope == "control" else "remote",
            )
            return {"bot": ref.id, "provider": provider_id, **result}

        @api.get("/voters", dependencies=[Depends(reader)])
        async def voters(bot: str | None = None) -> dict[str, Any]:
            ref = gateway.bot(bot)
            settings = settings_of(ref)
            return {
                "bot": ref.id,
                "swarm": {
                    "enabled": settings.swarm.enabled,
                    "mode": settings.swarm.mode,
                    "min_voters_answered": settings.swarm.min_voters_answered,
                    "enabled_voters": sum(1 for voter in settings.swarm.voters if voter.enabled),
                },
                "voters": voter_list(settings, ref),
            }

        @api.put("/voters/{voter_id}")
        async def put_voter(
            voter_id: str, body: VoterBody, request: Request, bot: str | None = None, token: str = Depends(owner)
        ):
            ref = gateway.bot(bot)
            check_voter_id(voter_id)

            def edit(raw: dict[str, Any]) -> None:
                items = raw.setdefault("swarm", {}).setdefault("voters", [])
                entry = {"id": voter_id, **body.model_dump()}
                for position, item in enumerate(items):
                    if item.get("id") == voter_id:
                        items[position] = entry
                        return
                items.append(entry)

            return await self.write(
                request,
                token,
                ref,
                "config.voter.upsert",
                edit,
                extra={"voter": voter_id, **body.model_dump()},
                render=lambda settings: {"voters": voter_list(settings, ref)},
            )

        @api.delete("/voters/{voter_id}")
        async def remove_voter(voter_id: str, request: Request, bot: str | None = None, token: str = Depends(owner)):
            ref = gateway.bot(bot)

            def edit(raw: dict[str, Any]) -> None:
                items = (raw.get("swarm") or {}).get("voters") or []
                if not any(item.get("id") == voter_id for item in items):
                    raise ApiError(404, "not_found", f"unknown voter {voter_id}")
                raw["swarm"]["voters"] = [item for item in items if item.get("id") != voter_id]

            return await self.write(
                request,
                token,
                ref,
                "config.voter.delete",
                edit,
                extra={"voter": voter_id},
                render=lambda settings: {"voters": voter_list(settings, ref)},
            )

        @api.get("/roles", dependencies=[Depends(reader)])
        async def roles(bot: str | None = None) -> dict[str, Any]:
            ref = gateway.bot(bot)
            settings = settings_of(ref)
            provider_id, model = settings.llm.analyst_model.split(":", 1)
            return {
                "bot": ref.id,
                "analyst": {"provider": provider_id, "model": model},
                "voters": [
                    {"id": voter.id, "provider": voter.provider, "model": voter.model, "enabled": voter.enabled}
                    for voter in settings.swarm.voters
                ],
            }

        @api.put("/roles")
        async def put_roles(body: RolesBody, request: Request, bot: str | None = None, token: str = Depends(owner)):
            ref = gateway.bot(bot)

            def edit(raw: dict[str, Any]) -> None:
                if body.analyst is not None:
                    raw.setdefault("llm", {})["analyst_model"] = f"{body.analyst.provider}:{body.analyst.model}"
                items = (raw.get("swarm") or {}).get("voters") or []
                for voter_id, role in body.voters.items():
                    entry = next((item for item in items if item.get("id") == voter_id), None)
                    if entry is None:
                        raise ApiError(404, "not_found", f"unknown voter {voter_id}")
                    entry.update(provider=role.provider, model=role.model)

            return await self.write(
                request,
                token,
                ref,
                "config.roles",
                edit,
                extra=body.model_dump(),
                render=lambda settings: {"voters": voter_list(settings, ref)},
            )

        return api
