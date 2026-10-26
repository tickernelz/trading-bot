"""One REST client and one WebSocket connection to a Freqtrade bot."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import websockets

from gateway.events import FREQTRADE_TOPICS
from gateway.feed import now_iso
from gateway.settings import BotRef

logger = logging.getLogger("trading_bot.gateway.upstream")

MessageHandler = Callable[[str, dict[str, Any], int], Awaitable[None]]
StateHandler = Callable[[str, bool], Awaitable[None]]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after_ms: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after_ms = retry_after_ms


class Upstream:
    def __init__(self, bot: BotRef, username: str, password: str) -> None:
        self.bot = bot
        self.client = httpx.AsyncClient(base_url=bot.api_url + "/api/v1", auth=(username, password), timeout=5.0)
        self.ws_url = bot.api_url.replace("http://", "ws://", 1) + "/api/v1/message/ws"
        self.connected = False
        self.last_event_at: str | None = None
        self.messages = 0
        self.reconnects = 0

    async def get(self, path: str, **params: Any) -> Any:
        try:
            response = await self.client.get(path, params={k: v for k, v in params.items() if v is not None})
        except httpx.TimeoutException as exc:
            raise ApiError(503, "upstream_unavailable", "Freqtrade API did not answer within 5s", 2000) from exc
        except httpx.HTTPError as exc:
            raise ApiError(503, "upstream_unavailable", "Freqtrade API is not reachable", 2000) from exc
        if response.status_code == 404:
            raise ApiError(404, "not_found", f"Freqtrade has no {path}")
        if response.status_code >= 400:
            raise ApiError(502, "upstream_error", f"Freqtrade answered {response.status_code} for {path}")
        return response.json()

    async def access_token(self) -> str:
        """Fetch a 15-minute JWT so Freqtrade's access log never holds a long-lived token."""
        response = await self.client.post("/token/login")
        response.raise_for_status()
        return response.json()["access_token"]

    async def run(self, on_message: MessageHandler, on_state: StateHandler) -> None:
        backoff = 1.0
        while True:
            try:
                token = await self.access_token()
                async with websockets.connect(
                    f"{self.ws_url}?token={token}", max_size=2**24, ping_interval=20, open_timeout=10
                ) as socket:
                    await socket.send(json.dumps({"type": "subscribe", "data": FREQTRADE_TOPICS}))
                    self.connected = True
                    backoff = 1.0
                    await on_state(self.bot.id, True)
                    async for raw in socket:
                        received_ms = int(time.time() * 1000)
                        self.messages += 1
                        self.last_event_at = now_iso()
                        try:
                            message = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(message, dict):
                            await on_message(self.bot.id, message, received_ms)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("bot %s websocket: %s: %s", self.bot.id, type(exc).__name__, exc)
            if self.connected:
                self.connected = False
                await on_state(self.bot.id, False)
            self.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def aclose(self) -> None:
        await self.client.aclose()
