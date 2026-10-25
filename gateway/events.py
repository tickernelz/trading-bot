"""Translate Freqtrade WebSocket messages into gateway feed events."""

from __future__ import annotations

import json
from typing import Any

FREQTRADE_TOPICS = [
    "entry",
    "entry_fill",
    "entry_cancel",
    "exit",
    "exit_fill",
    "exit_cancel",
    "status",
    "warning",
    "exception",
    "strategy_msg",
    "protection_trigger",
    "protection_trigger_global",
    "whitelist",
    "new_candle",
]
PASS_THROUGH = frozenset(FREQTRADE_TOPICS) - {"strategy_msg", "whitelist", "new_candle"}
STRATEGY_EVENTS = {"risk_guard_denied": "gw.risk_denied", "startup_check": "gw.startup_check"}
FILL_SIDES = {"entry_fill": "buy", "exit_fill": "sell"}


def translate(message: dict[str, Any]) -> tuple[str, Any] | None:
    """Return (event type, data) for the PWA feed, or None when the message is not forwarded."""
    kind = message.get("type")
    if kind in PASS_THROUGH:
        return kind, {key: value for key, value in message.items() if key != "type"}
    if kind == "whitelist":
        return "whitelist", message.get("data")
    if kind == "strategy_msg":
        raw = message.get("msg")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("event") in STRATEGY_EVENTS:
            return STRATEGY_EVENTS[payload["event"]], {k: v for k, v in payload.items() if k != "event"}
        return "strategy_msg", {"msg": raw}
    return None
