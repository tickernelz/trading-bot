"""Gateway between the PWA and the Freqtrade bots: auth, read API, live feed, health, cost and audit."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psutil
import yaml
from fastapi import Depends, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from engine.decisions import DecisionStore
from engine.heartbeat import read_heartbeat
from engine.launch import TRADABLE_BALANCE_RATIO
from engine.logredact import redact
from engine.risk import day_start
from engine.settings import ConfigError, Settings, load_settings
from gateway import VERSION
from gateway.analyst import AnalystLink, install_analyst
from gateway.events import FILL_SIDES, translate
from gateway.feed import Client, Hub, now_iso
from gateway.ledger import Ledger, LoginThrottle
from gateway.modeapi import ModeDesk, install_mode
from gateway.settings import BotRef, GatewaySettings
from gateway.upstream import ApiError, Upstream
from gateway.views import (
    candle_frame,
    candle_rows,
    compute_risk,
    config_changes,
    equity_points,
    flatten,
    iso_text,
    open_trade,
    redacted_settings,
    risk_view,
)

logger = logging.getLogger("trading_bot.gateway")

CACHE_TTL_S = 2.0
TRADE_PAGE = 500
CANDLE_SECONDS = 3600
HEARTBEAT_EVENT_S = 60
SECRET_KEYS = ("api_key",)


class Login(BaseModel):
    password: str


def balance_summary(balance: dict[str, Any]) -> dict[str, Any]:
    return {
        "stake_currency": balance.get("stake"),
        "total": balance.get("total"),
        "bot_owned": balance.get("total_bot"),
        "note": balance.get("note"),
    }


def error_response(status: int, code: str, message: str, retry_after_ms: int | None = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if retry_after_ms is not None:
        body["retry_after_ms"] = retry_after_ms
    return JSONResponse({"error": body}, status_code=status)


class Gateway:
    def __init__(self, settings: GatewaySettings, env: dict[str, str]) -> None:
        password = env.get(settings.password_env, "")
        if len(password) < 12:
            raise ConfigError(f"{settings.password_env} must hold at least 12 characters")
        missing = [name for name in (settings.ft_username_env, settings.ft_password_env) if not env.get(name)]
        if missing:
            raise ConfigError(f"set environment variables: {', '.join(missing)}")
        self.settings = settings
        self.env = env
        self.password = password
        self.started = time.monotonic()
        self.ledger = Ledger(Path(settings.state_dir) / "gateway.sqlite")
        self.throttle = LoginThrottle()
        self.hub = Hub()
        self.upstreams = {
            bot.id: Upstream(bot, env[settings.ft_username_env], env[settings.ft_password_env]) for bot in settings.bots
        }
        self.stores: dict[str, DecisionStore] = {}
        self.decision_seq: dict[str, int] = {}
        self.cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self.bot_settings: dict[str, tuple[float, Settings]] = {}
        self.heartbeats: dict[str, dict[str, Any]] = {}
        self.shadow_health: dict[str, dict[str, Any]] = {}
        self.exchange: dict[str, Any] = {"name": None, "reachable": None, "latency_ms": None, "checked_at": None}
        self.last_risk: dict[str, Any] = {}
        self.last_candle: dict[str, str] = {}
        self.process = psutil.Process()
        self.process.cpu_percent(None)
        self.cpu_recent: float | None = None
        self.http = httpx.AsyncClient(timeout=5.0)
        self.tasks: list[asyncio.Task] = []
        self.analyst = AnalystLink(self)
        self.modes = ModeDesk(self)

    def primary(self) -> BotRef:
        return self.settings.bots[0]

    def bot(self, bot_id: str | None) -> BotRef:
        bot = self.settings.bot(bot_id)
        if bot is None:
            raise ApiError(404, "not_found", f"unknown bot {bot_id}")
        return bot

    def engine_settings(self, bot: BotRef) -> Settings:
        mtime = os.stat(bot.config).st_mtime
        cached = self.bot_settings.get(bot.id)
        if cached and cached[0] == mtime:
            return cached[1]
        settings = load_settings(bot.config)
        self.bot_settings[bot.id] = (mtime, settings)
        return settings

    def store(self, bot: BotRef) -> DecisionStore | None:
        if bot.decisions is None:
            return None
        if bot.id not in self.stores:
            if not Path(bot.decisions).exists():
                return None
            self.stores[bot.id] = DecisionStore(bot.decisions, readonly=True)
        return self.stores[bot.id]

    async def ft(self, bot: BotRef, path: str, ttl: float = CACHE_TTL_S, **params: Any) -> Any:
        key = (bot.id, path + json.dumps(params, sort_keys=True))
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        value = await self.upstreams[bot.id].get(path, **params)
        now = time.monotonic()
        self.cache = {item: entry for item, entry in self.cache.items() if entry[0] > now}
        self.cache[key] = (now + ttl, value)
        return value

    async def closed_trades(self, bot: BotRef) -> list[dict[str, Any]]:
        """Every closed trade, paged from Freqtrade; fails closed when the pages do not add up to the total."""
        rows: dict[int, dict[str, Any]] = {}
        total = 0
        while True:
            page = await self.ft(bot, "/trades", limit=TRADE_PAGE, offset=len(rows), order_by_id=True)
            total = page.get("total_trades", 0)
            batch = page.get("trades", [])
            for trade in batch:
                rows[trade["trade_id"]] = trade
            if len(rows) >= total or len(batch) < TRADE_PAGE:
                break
        if len(rows) != total:
            raise ApiError(502, "upstream_error", f"Freqtrade returned {len(rows)} of {total} closed trades", 2000)
        return list(rows.values())

    async def closed_and_open(self, bot: BotRef) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        closed, status = await asyncio.gather(self.closed_trades(bot), self.ft(bot, "/status"))
        return closed, status

    async def risk(self, bot: BotRef) -> dict[str, Any]:
        settings = self.engine_settings(bot)
        trades, opened = await self.closed_and_open(bot)
        now = datetime.now(UTC)
        open_pnl = sum(trade.get("profit_abs") or 0.0 for trade in opened)
        return risk_view(settings, compute_risk(settings, trades, open_pnl, now), now)

    async def overview(self, bot: BotRef) -> dict[str, Any]:
        settings = self.engine_settings(bot)
        config, balance, profit, count, whitelist, blacklist, locks, risk = await asyncio.gather(
            self.ft(bot, "/show_config"),
            self.ft(bot, "/balance"),
            self.ft(bot, "/profit"),
            self.ft(bot, "/count"),
            self.ft(bot, "/whitelist"),
            self.ft(bot, "/blacklist"),
            self.ft(bot, "/locks"),
            self.risk(bot),
        )
        return {
            "bot": bot.id,
            "mode": "dry_run" if config.get("dry_run") else "live",
            "as_of": now_iso(),
            "capital": {
                "initial_idr": settings.capital.initial_idr,
                "compounding": settings.capital.compounding,
                "tradable_ratio": TRADABLE_BALANCE_RATIO,
            },
            "balance": balance_summary(balance),
            "profit": {
                "abs": profit.get("profit_all_coin"),
                "pct": profit.get("profit_all_percent"),
                "trades_closed": profit.get("closed_trade_count"),
                "winrate": profit.get("winrate"),
            },
            "open_trades": {"count": count.get("current"), "max": count.get("max")},
            "risk": {
                "daily_loss_pct": risk["daily_loss_pct"],
                "daily_limit_pct": settings.risk.max_daily_loss_pct,
                "drawdown_pct": risk["drawdown_pct"],
                "drawdown_limit_pct": settings.risk.max_total_drawdown_pct,
                "entries_allowed": risk["entries_allowed"],
                "breaches": risk["breaches"],
            },
            "pairs": {
                "whitelist": whitelist.get("whitelist", []),
                "blacklist": blacklist.get("blacklist", []),
                "locks": locks.get("lock_count", 0),
            },
        }

    def load(self) -> dict[str, Any]:
        with self.process.oneshot():
            times = self.process.cpu_times()
            rss = self.process.memory_info().rss
        uptime = time.monotonic() - self.started
        return {
            "gateway_cpu_pct_10s": self.cpu_recent,
            "gateway_cpu_pct_avg": round((times.user + times.system) / uptime * 100, 3) if uptime > 0 else None,
            "gateway_rss_mb": round(rss / 2**20, 1),
            "loadavg": [round(value, 2) for value in os.getloadavg()],
            "cpu_count": os.cpu_count(),
            "clients": len(self.hub.clients),
        }

    def bot_health(self, bot: BotRef) -> dict[str, Any]:
        beat = read_heartbeat(bot.userdir)
        age = None
        if beat:
            age = round((datetime.now(UTC) - datetime.fromisoformat(beat["ts"])).total_seconds(), 1)
        upstream = self.upstreams[bot.id]
        return {
            "id": bot.id,
            "label": bot.label,
            "strategy": bot.strategy,
            "heartbeat_at": iso_text(beat["ts"]) if beat else None,
            "heartbeat_age_s": age,
            "heartbeat_lost": age is None or age > self.settings.heartbeat_lost_s,
            "starts": beat.get("starts") if beat else None,
            "startup_checked": beat.get("startup_checked") if beat else None,
            "open_trades": beat.get("open_trades") if beat else None,
            "feed_connected": upstream.connected,
            "feed_last_event_at": upstream.last_event_at,
            "feed_reconnects": upstream.reconnects,
            "shadow": self.shadow_health.get(bot.id),
        }

    async def health(self) -> dict[str, Any]:
        bot = self.primary()
        version, health, config = await asyncio.gather(
            self.ft(bot, "/version"), self.ft(bot, "/health"), self.ft(bot, "/show_config")
        )
        providers = []
        for ref in self.settings.bots:
            store = self.store(ref)
            if store is not None:
                providers += [{"bot": ref.id, **entry} for entry in store.provider_health()]
        return {
            "gateway": {
                "status": "ok" if self.upstreams[bot.id].connected else "degraded",
                "version": VERSION,
                "uptime_s": int(time.monotonic() - self.started),
                "sample_data": False,
            },
            "freqtrade": {
                "version": version.get("version"),
                "state": config.get("state"),
                "last_process": iso_text(health.get("last_process")),
                "bot_start": iso_text(health.get("bot_start")),
                "dry_run": config.get("dry_run"),
            },
            "exchange": {**self.exchange, "name": config.get("exchange")},
            "feed": {
                "connected": self.upstreams[bot.id].connected,
                "last_event_at": self.hub.last_event_at,
                "sequence": self.hub.seq,
            },
            "bots": [self.bot_health(ref) for ref in self.settings.bots],
            "providers": providers,
            "load": self.load(),
        }

    async def equity(self, window: str, bot_ids: list[str]) -> dict[str, Any]:
        now = datetime.now(UTC)
        series = []
        unavailable = []
        start_equity = None
        for bot_id in bot_ids:
            bot = self.bot(bot_id)
            settings = self.engine_settings(bot)
            start = day_start(now, settings.risk.daily_reset_timezone) if window == "day" else now - timedelta(days=7)
            try:
                trades, opened = await self.closed_and_open(bot)
            except ApiError:
                unavailable.append(bot.id)
                continue
            open_pnl = sum(trade.get("profit_abs") or 0.0 for trade in opened)
            points = equity_points(settings.capital.initial_idr, trades, open_pnl, start, now)
            start_equity = points[0][1] if start_equity is None else start_equity
            series.append({"bot": bot.id, "label": bot.label, "strategy": bot.strategy, "points": points})
        return {"window": window, "start_equity": start_equity, "series": series, "unavailable": unavailable}

    def costs(self, window: str) -> dict[str, Any]:
        bot = self.primary()
        settings = self.engine_settings(bot)
        now = datetime.now(UTC)
        since = None
        if window == "day":
            since = day_start(now, settings.risk.daily_reset_timezone).astimezone(UTC)
        elif window == "7d":
            since = now - timedelta(days=7)
        since_text = since.isoformat(timespec="milliseconds").replace("+00:00", "Z") if since else None
        per_bot = []
        for ref in self.settings.bots:
            store = self.store(ref)
            if store is not None:
                per_bot.append({"bot": ref.id, **store.usage(since_text)})
        totals = {
            key: sum(item[key] for item in per_bot)
            for key in ("decisions", "voter_calls", "input_tokens", "output_tokens", "reasoning_tokens")
        }
        costs = [item["cost"] for item in per_bot if item["cost"] is not None]
        return {
            "window": window,
            "since": since_text,
            "as_of": now_iso(),
            "cap": {
                "max_cost_idr_per_day": settings.compute.max_cost_idr_per_day,
                "on_exceed": settings.compute.on_exceed,
                "enforced": False,
            },
            **totals,
            "cost": sum(costs) if costs else None,
            "cost_unit": "as reported by each provider; providers that report nothing leave cost null",
            "bots": per_bot,
            "analyst": self.ledger.analyst_usage(since_text),
        }

    async def on_message(self, bot_id: str, message: dict[str, Any], received_ms: int) -> None:
        kind = message.get("type")
        if kind == "new_candle":
            if bot_id == self.primary().id:
                data = message.get("data") or []
                if data and data[0] in self.hub.candle_pairs():
                    self.spawn(self.push_candles(data[0]))
            return
        translated = translate(message)
        if translated is None:
            return
        event_type, data = translated
        self.hub.emit(event_type, data, bot=bot_id)
        if kind in FILL_SIDES and isinstance(data, dict) and data.get("trade_id") is not None:
            self.spawn(self.record_fill(bot_id, int(data["trade_id"]), FILL_SIDES[kind], received_ms))

    async def on_state(self, bot_id: str, connected: bool) -> None:
        if not connected:
            self.hub.emit(
                "gw.error",
                {"code": "upstream_unavailable", "message": "Freqtrade websocket closed", "retry_ms": 2000},
                bot=bot_id,
            )

    async def record_fill(self, bot_id: str, trade_id: int, side: str, received_ms: int) -> None:
        bot = self.bot(bot_id)
        trade = await self.upstreams[bot_id].get(f"/trade/{trade_id}")
        filled = [
            order["order_filled_timestamp"]
            for order in trade.get("orders", [])
            if order.get("ft_order_side") == side and order.get("order_filled_timestamp")
        ]
        if filled:
            latency = self.ledger.add_fill(bot_id, trade_id, side, max(filled), received_ms)
            logger.info("bot %s trade %d %s fill reached gateway after %d ms", bot_id, trade_id, side, latency)
        self.cache.clear()
        await self.publish_risk(bot)

    async def publish_risk(self, bot: BotRef) -> None:
        risk = await self.risk(bot)
        summary = {
            key: risk[key] for key in ("equity", "daily_loss_pct", "drawdown_pct", "entries_allowed", "breaches")
        }
        if self.last_risk.get(bot.id) != summary:
            self.last_risk[bot.id] = summary
            self.hub.emit("gw.risk", summary, bot=bot.id)

    async def candle_snapshot(self, pair: str, limit: int) -> list[list[Any]]:
        bot = self.primary()
        frame = await self.upstreams[bot.id].get(
            "/pair_candles", pair=pair, timeframe=self.engine_settings(bot).exchange.timeframe, limit=limit
        )
        return candle_rows(frame)

    async def push_candles(self, pair: str) -> None:
        rows = await self.candle_snapshot(pair, 3)
        if not rows:
            return
        timeframe = self.engine_settings(self.primary()).exchange.timeframe
        previous = self.last_candle.get(pair)
        self.last_candle[pair] = rows[-1][0]
        gap = (
            previous is not None
            and (datetime.fromisoformat(rows[-1][0]) - datetime.fromisoformat(previous)).total_seconds()
            > 2 * CANDLE_SECONDS
        )
        if gap:
            for client in list(self.hub.clients.values()):
                if "gw.candles" in client.topics and pair in client.candles:
                    snapshot = await self.candle_snapshot(pair, client.candles[pair])
                    self.hub.direct(
                        client,
                        "gw.candles",
                        {"pair": pair, "timeframe": timeframe, "reset": True, "snapshot": True, "candles": snapshot},
                    )
            return
        self.hub.emit("gw.candles", {"pair": pair, "timeframe": timeframe, "candles": rows[-2:]}, pair=pair)

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task) -> None:
        with suppress(ValueError):
            self.tasks.remove(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("gateway task failed: %r", task.exception())

    async def every(self, seconds: float, action: Any) -> None:
        while True:
            try:
                await action()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("periodic %s failed: %r", getattr(action, "__name__", action), exc)
            await asyncio.sleep(seconds)

    async def watch_heartbeats(self) -> None:
        now = time.monotonic()
        for bot in self.settings.bots:
            state = self.bot_health(bot)
            previous = self.heartbeats.get(bot.id, {})
            if state["heartbeat_lost"] and not previous.get("lost"):
                self.hub.emit(
                    "gw.heartbeat_lost", {k: state[k] for k in ("id", "heartbeat_at", "heartbeat_age_s")}, bot=bot.id
                )
            if previous.get("starts") is not None and state["starts"] not in (None, previous["starts"]):
                self.hub.emit("gw.bot_restart", {"starts": state["starts"]}, bot=bot.id)
            emit_beat = not state["heartbeat_lost"] and now - previous.get("emitted", 0) >= HEARTBEAT_EVENT_S
            if emit_beat:
                self.hub.emit(
                    "gw.heartbeat",
                    {
                        k: state[k]
                        for k in (
                            "heartbeat_at",
                            "heartbeat_age_s",
                            "starts",
                            "startup_checked",
                            "open_trades",
                            "feed_connected",
                        )
                    },
                    bot=bot.id,
                )
            self.heartbeats[bot.id] = {
                "lost": state["heartbeat_lost"],
                "starts": state["starts"] if state["starts"] is not None else previous.get("starts"),
                "emitted": now if emit_beat else previous.get("emitted", 0),
            }

    async def watch_decisions(self) -> None:
        for bot in self.settings.bots:
            store = self.store(bot)
            if store is None:
                continue
            last = self.decision_seq.get(bot.id)
            if last is None:
                self.decision_seq[bot.id] = store.last_settle_seq()
                continue
            for seq, decision in store.settled_after(last):
                self.decision_seq[bot.id] = seq
                self.hub.emit("gw.decision", decision, bot=bot.id)

    async def watch_risk(self) -> None:
        for bot in self.settings.bots:
            with suppress(ApiError):
                await self.publish_risk(bot)

    async def watch_config(self) -> None:
        for bot in self.settings.bots:
            raw_bytes = Path(bot.config).read_bytes()
            digest = hashlib.sha256(raw_bytes).hexdigest()
            known = self.ledger.config_hash(bot.id)
            if known and known[0] == digest:
                continue
            raw = yaml.safe_load(raw_bytes) or {}
            snapshot = {
                key: ("<set>" if value else None) if key.rsplit(".", 1)[-1] in SECRET_KEYS else value
                for key, value in flatten(raw).items()
            }
            try:
                load_settings(bot.config)
                valid, error = True, None
            except ConfigError as exc:
                valid, error = False, str(exc).splitlines()[0][:300]
            detail = {
                "file": bot.config,
                "old_sha256": known[0] if known else None,
                "new_sha256": digest,
                "valid": valid,
                "error": error,
                "changes": config_changes(known[1], snapshot) if known else [],
            }
            row = self.ledger.audit(
                actor="file",
                action="config.changed" if known else "config.observed",
                targets=[bot.id],
                result="ok" if valid else "invalid",
                detail=detail,
            )
            self.ledger.store_config_hash(bot.id, digest, snapshot)
            self.hub.emit("gw.audit", row, bot=bot.id)

    async def probe_exchange(self) -> None:
        if not self.settings.exchange_probe_url:
            return
        started = time.perf_counter()
        try:
            response = await self.http.get(self.settings.exchange_probe_url)
            reachable = response.status_code == 200
        except httpx.HTTPError:
            reachable = False
        self.exchange.update(
            reachable=reachable,
            latency_ms=round((time.perf_counter() - started) * 1000) if reachable else None,
            checked_at=now_iso(),
        )

    async def probe_shadows(self) -> None:
        for bot in self.settings.bots:
            if not bot.shadow_url:
                continue
            try:
                response = await self.http.get(bot.shadow_url + "/health", timeout=3.0)
                self.shadow_health[bot.id] = {"reachable": response.status_code == 200, **response.json()}
            except (httpx.HTTPError, ValueError):
                self.shadow_health[bot.id] = {"reachable": False}

    async def sample_cpu(self) -> None:
        self.cpu_recent = round(self.process.cpu_percent(None), 2)

    async def start(self) -> None:
        for upstream in self.upstreams.values():
            self.tasks.append(asyncio.create_task(upstream.run(self.on_message, self.on_state)))
        for seconds, action in (
            (15, self.watch_heartbeats),
            (5, self.watch_decisions),
            (60, self.watch_risk),
            (10, self.watch_config),
            (60, self.probe_exchange),
            (30, self.probe_shadows),
            (10, self.sample_cpu),
            (60, self.analyst.tick),
        ):
            self.tasks.append(asyncio.create_task(self.every(seconds, action)))

    async def stop(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for upstream in self.upstreams.values():
            await upstream.aclose()
        await self.http.aclose()
        await self.analyst.aclose()
        for store in self.stores.values():
            store.close()
        self.ledger.close()

    def check_password(self, password: str) -> bool:
        return secrets.compare_digest(password.encode(), self.password.encode())

    def token_of(self, request: Request | WebSocket) -> str | None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return request.query_params.get("token") if isinstance(request, WebSocket) else None


def create_app(gateway: Gateway) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await gateway.start()
        yield
        await gateway.stop()

    app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.retry_after_ms)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", []))
        return error_response(400, "invalid_request", f"{where}: {first.get('msg', 'invalid request')}")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "invalid_request"
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(ConfigError)
    async def config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return error_response(503, "upstream_error", str(exc).splitlines()[0][:300])

    async def reader(request: Request) -> str:
        token = gateway.token_of(request)
        if not token or gateway.ledger.session_scope(token) is None:
            raise ApiError(401, "unauthorized", "sign in again")
        return token

    @app.post("/gw/v1/session")
    async def login(body: Login, request: Request) -> dict[str, str]:
        ip = request.client.host if request.client else None
        wait = gateway.throttle.blocked_for()
        if wait > 0:
            raise ApiError(429, "rate_limited", "too many failed sign-ins", int(wait * 1000))
        if not gateway.check_password(body.password):
            gateway.throttle.fail()
            gateway.ledger.audit(actor="anonymous", ip=ip, action="session.create", targets=[], result="denied")
            raise ApiError(401, "unauthorized", "wrong password")
        token, expires = gateway.ledger.create_session("read", gateway.settings.session_days, ip)
        gateway.ledger.audit(actor="owner", ip=ip, action="session.create", targets=[], result="ok")
        return {"token": token, "expires_at": expires}

    @app.delete("/gw/v1/session")
    async def logout(request: Request, token: str = Depends(reader)) -> dict[str, bool]:
        gateway.ledger.delete_session(token)
        ip = request.client.host if request.client else None
        gateway.ledger.audit(actor="owner", ip=ip, action="session.delete", targets=[], result="ok")
        return {"ok": True}

    @app.get("/gw/v1/health", dependencies=[Depends(reader)])
    async def health() -> dict[str, Any]:
        return await gateway.health()

    @app.get("/gw/v1/overview", dependencies=[Depends(reader)])
    async def overview(bot: str | None = None) -> dict[str, Any]:
        return await gateway.overview(gateway.bot(bot))

    @app.get("/gw/v1/trades/open", dependencies=[Depends(reader)])
    async def trades_open(bot: str | None = None) -> list[dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        return [open_trade(trade, now_ms) for trade in await gateway.ft(gateway.bot(bot), "/status")]

    @app.get("/gw/v1/trades", dependencies=[Depends(reader)])
    async def trades(
        bot: str | None = None, limit: int = Query(100, ge=1, le=500), pair: str | None = None
    ) -> list[dict[str, Any]]:
        closed, opened = await gateway.closed_and_open(gateway.bot(bot))
        rows = [trade for trade in [*opened, *closed] if pair is None or trade.get("pair") == pair]
        rows.sort(key=lambda trade: trade.get("trade_id", 0), reverse=True)
        return rows[:limit]

    @app.get("/gw/v1/trades/{trade_id}", dependencies=[Depends(reader)])
    async def trade(trade_id: int, bot: str | None = None) -> dict[str, Any]:
        return await gateway.upstreams[gateway.bot(bot).id].get(f"/trade/{trade_id}")

    @app.get("/gw/v1/balance", dependencies=[Depends(reader)])
    async def balance(bot: str | None = None) -> dict[str, Any]:
        data = await gateway.ft(gateway.bot(bot), "/balance")
        return {
            "stake_currency": data.get("stake"),
            "total": data.get("total"),
            "total_bot": data.get("total_bot"),
            "starting_capital": data.get("starting_capital"),
            "starting_capital_pct": data.get("starting_capital_pct"),
            "note": data.get("note"),
            "currencies": [item for item in data.get("currencies", []) if item.get("is_bot_managed")],
        }

    @app.get("/gw/v1/profit", dependencies=[Depends(reader)])
    async def profit(
        bot: str | None = None,
        window: str = Query("total", pattern="^(total|daily|weekly|monthly)$"),
        timescale: int = Query(7, ge=1, le=366),
    ) -> dict[str, Any]:
        ref = gateway.bot(bot)
        if window == "total":
            return {"window": "total", **await gateway.ft(ref, "/profit")}
        return {"window": window, **await gateway.ft(ref, f"/{window}", timescale=timescale)}

    @app.get("/gw/v1/stats", dependencies=[Depends(reader)])
    async def stats(bot: str | None = None) -> dict[str, Any]:
        return await gateway.ft(gateway.bot(bot), "/stats")

    @app.get("/gw/v1/performance", dependencies=[Depends(reader)])
    async def performance(bot: str | None = None, pair: str | None = None) -> dict[str, Any]:
        ref = gateway.bot(bot)
        per_pair, by_tag, by_exit = await asyncio.gather(
            gateway.ft(ref, "/performance"),
            gateway.ft(ref, "/entries", pair=pair),
            gateway.ft(ref, "/exits", pair=pair),
        )
        return {
            "per_pair": [row for row in per_pair if pair is None or row.get("pair") == pair],
            "by_enter_tag": by_tag,
            "by_exit_reason": by_exit,
        }

    @app.get("/gw/v1/candles", dependencies=[Depends(reader)])
    async def candles(pair: str, timeframe: str = "1h", limit: int = Query(300, ge=1, le=1500)) -> dict[str, Any]:
        ref = gateway.primary()
        settings = gateway.engine_settings(ref)
        if timeframe != settings.exchange.timeframe:
            raise ApiError(400, "invalid_request", f"only timeframe {settings.exchange.timeframe} is served")
        whitelist = (await gateway.ft(ref, "/whitelist")).get("whitelist", [])
        if pair not in whitelist:
            raise ApiError(404, "not_found", f"{pair} is not on the whitelist")
        frame = await gateway.upstreams[ref.id].get("/pair_candles", pair=pair, timeframe=timeframe, limit=limit)
        return candle_frame(frame)

    @app.get("/gw/v1/pairs", dependencies=[Depends(reader)])
    async def pairs(bot: str | None = None) -> dict[str, Any]:
        ref = gateway.bot(bot)
        whitelist, blacklist, locks = await asyncio.gather(
            gateway.ft(ref, "/whitelist"), gateway.ft(ref, "/blacklist"), gateway.ft(ref, "/locks")
        )
        return {"whitelist": whitelist, "blacklist": blacklist, "locks": locks}

    @app.get("/gw/v1/risk", dependencies=[Depends(reader)])
    async def risk(bot: str | None = None) -> dict[str, Any]:
        return await gateway.risk(gateway.bot(bot))

    @app.get("/gw/v1/logs", dependencies=[Depends(reader)])
    async def logs(bot: str | None = None, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        data = await gateway.ft(gateway.bot(bot), "/logs", limit=limit)
        return {
            **data,
            "logs": [
                [redact(field) if isinstance(field, str) else field for field in line] for line in data.get("logs", [])
            ],
        }

    @app.get("/gw/v1/sysinfo", dependencies=[Depends(reader)])
    async def sysinfo(bot: str | None = None) -> dict[str, Any]:
        return await gateway.ft(gateway.bot(bot), "/sysinfo")

    @app.get("/gw/v1/settings", dependencies=[Depends(reader)])
    async def settings_view(bot: str | None = None) -> dict[str, Any]:
        return redacted_settings(gateway.engine_settings(gateway.bot(bot)))

    @app.get("/gw/v1/equity", dependencies=[Depends(reader)])
    async def equity(window: str = Query("day", pattern="^(day|7d)$"), bots: str | None = None) -> dict[str, Any]:
        ids = [item for item in (bots or gateway.primary().id).split(",") if item]
        return await gateway.equity(window, ids)

    @app.get("/gw/v1/decisions", dependencies=[Depends(reader)])
    async def decisions(bot: str | None = None, limit: int = Query(20, ge=1, le=500)) -> list[dict[str, Any]]:
        refs = [gateway.bot(bot)] if bot else gateway.settings.bots
        rows = []
        for ref in refs:
            store = gateway.store(ref)
            if store is not None:
                rows += store.recent(limit)
        rows.sort(key=lambda row: row["ts"], reverse=True)
        return rows[:limit]

    @app.get("/gw/v1/costs", dependencies=[Depends(reader)])
    async def costs(window: str = Query("day", pattern="^(day|7d|total)$")) -> dict[str, Any]:
        return gateway.costs(window)

    @app.get("/gw/v1/audit", dependencies=[Depends(reader)])
    async def audit(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        return gateway.ledger.audit_rows(limit)

    @app.get("/gw/v1/metrics", dependencies=[Depends(reader)])
    async def metrics() -> dict[str, Any]:
        return {
            "fill_latency_ms": gateway.ledger.fill_latency(),
            "gateway": gateway.load(),
            "upstreams": {
                bot_id: {
                    "connected": upstream.connected,
                    "messages": upstream.messages,
                    "reconnects": upstream.reconnects,
                    "last_event_at": upstream.last_event_at,
                }
                for bot_id, upstream in gateway.upstreams.items()
            },
            "feed": {"sequence": gateway.hub.seq, "clients": len(gateway.hub.clients)},
        }

    @app.websocket("/gw/v1/events")
    async def events(socket: WebSocket) -> None:
        token = gateway.token_of(socket)
        await socket.accept()
        if not token or gateway.ledger.session_scope(token) is None:
            await socket.close(4401, "unauthorized")
            return
        client = gateway.hub.add()
        sender = asyncio.create_task(send_loop(socket, client))
        try:
            await hello(client)
            while True:
                frame = await socket.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                try:
                    message = json.loads(frame.get("text") or "")
                except ValueError:
                    continue
                if isinstance(message, dict):
                    await handle(client, message)
        except WebSocketDisconnect:
            pass
        finally:
            gateway.hub.remove(client)
            sender.cancel()
            with suppress(asyncio.CancelledError):
                await sender

    async def send_loop(socket: WebSocket, client: Client) -> None:
        while True:
            message = await client.queue.get()
            if client.overflow:
                await socket.close(1013, "client too slow")
                return
            await socket.send_text(json.dumps(message))

    async def hello(client: Client) -> None:
        ref = gateway.primary()
        try:
            version, config, whitelist = await asyncio.gather(
                gateway.ft(ref, "/version"), gateway.ft(ref, "/show_config"), gateway.ft(ref, "/whitelist")
            )
        except ApiError:
            version, config, whitelist = {}, {}, {}
        gateway.hub.direct(
            client,
            "gw.hello",
            {
                "gateway_version": VERSION,
                "freqtrade_version": version.get("version"),
                "dry_run": config.get("dry_run"),
                "whitelist": whitelist.get("whitelist", []),
                "sequence_resume_window": 200,
                "sample_data": False,
                "bots": [{"id": bot.id, "label": bot.label, "strategy": bot.strategy} for bot in gateway.settings.bots],
            },
        )

    async def handle(client: Client, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "ping":
            client.put({"type": "pong", "ts": now_iso()})
        elif kind == "subscribe":
            previous = set(client.candles)
            client.topics = {topic for topic in message.get("topics") or [] if isinstance(topic, str)}
            client.candles = {}
            for item in message.get("candles") or []:
                if not isinstance(item, dict) or not isinstance(item.get("pair"), str):
                    continue
                try:
                    limit = int(item.get("limit") or 300)
                except (TypeError, ValueError):
                    continue
                client.candles[item["pair"]] = max(1, min(1500, limit))
            if "gw.candles" in client.topics:
                timeframe = gateway.engine_settings(gateway.primary()).exchange.timeframe
                for pair, limit in client.candles.items():
                    if pair in previous:
                        continue
                    try:
                        rows = await gateway.candle_snapshot(pair, limit)
                    except ApiError as exc:
                        gateway.hub.direct(client, "gw.error", {"code": exc.code, "message": exc.message})
                        continue
                    gateway.hub.direct(
                        client, "gw.candles", {"pair": pair, "timeframe": timeframe, "snapshot": True, "candles": rows}
                    )
        elif kind == "resume":
            try:
                last = int(message.get("last_seq"))
            except (TypeError, ValueError):
                return
            if gateway.hub.replay(client, last):
                return
            await hello(client)
            ref = gateway.primary()
            try:
                opened, whitelist, balance = await asyncio.gather(
                    gateway.ft(ref, "/status"), gateway.ft(ref, "/whitelist"), gateway.ft(ref, "/balance")
                )
            except ApiError as exc:
                gateway.hub.direct(client, "gw.error", {"code": exc.code, "message": exc.message})
                return
            now_ms = int(time.time() * 1000)
            gateway.hub.direct(
                client,
                "gw.resync",
                {
                    "whitelist": whitelist.get("whitelist", []),
                    "open_trades": [open_trade(trade, now_ms) for trade in opened],
                    "balance": balance_summary(balance),
                },
            )

    install_analyst(app, gateway, reader, reader)
    install_mode(app, gateway, reader)
    return app
