"""Fan-out of gateway events to PWA clients with a bounded resume buffer."""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

ALWAYS = frozenset({"gw.error"})
RESUME_WINDOW = 200
QUEUE_LIMIT = 2000


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Client:
    id: int
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_LIMIT))
    topics: set[str] = field(default_factory=set)
    candles: dict[str, int] = field(default_factory=dict)
    overflow: bool = False

    def wants(self, event: dict[str, Any]) -> bool:
        if event["type"] in ALWAYS:
            return True
        if event["type"] not in self.topics:
            return False
        pair = event.get("pair")
        return pair is None or pair in self.candles

    def put(self, message: dict[str, Any]) -> None:
        if self.overflow:
            return
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflow = True


class Hub:
    def __init__(self) -> None:
        self.seq = 0
        self.buffer: deque[dict[str, Any]] = deque(maxlen=RESUME_WINDOW)
        self.clients: dict[int, Client] = {}
        self.last_event_at: str | None = None
        self._ids = itertools.count(1)

    def add(self) -> Client:
        client = Client(next(self._ids))
        self.clients[client.id] = client
        return client

    def remove(self, client: Client) -> None:
        self.clients.pop(client.id, None)

    def emit(self, type_: str, data: Any, *, bot: str | None = None, pair: str | None = None) -> dict[str, Any]:
        self.seq += 1
        event: dict[str, Any] = {"type": type_, "seq": self.seq, "ts": now_iso(), "data": data}
        if bot is not None:
            event["bot"] = bot
        routed = {**event, "pair": pair} if pair is not None else event
        self.buffer.append(routed)
        self.last_event_at = event["ts"]
        for client in self.clients.values():
            if client.wants(routed):
                client.put(event)
        return event

    def direct(self, client: Client, type_: str, data: Any) -> None:
        client.put({"type": type_, "seq": self.seq, "ts": now_iso(), "data": data})

    def replay(self, client: Client, last_seq: int) -> bool:
        """Queue buffered events after last_seq; False when the buffer no longer reaches back that far."""
        first = self.buffer[0]["seq"] if self.buffer else self.seq + 1
        if last_seq + 1 < first:
            return False
        for routed in self.buffer:
            if routed["seq"] > last_seq and client.wants(routed):
                client.put({key: value for key, value in routed.items() if key != "pair"})
        return True

    def candle_pairs(self) -> set[str]:
        return {pair for client in self.clients.values() if "gw.candles" in client.topics for pair in client.candles}
