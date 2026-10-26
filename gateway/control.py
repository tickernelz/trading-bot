"""Local-only rule, two-step confirmation and idempotency for gateway control actions."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

from gateway.upstream import ApiError

CONFIRM_TTL_S = 60.0
CONFIRM_GRACE_S = 600.0
CONFIRM_LIMIT = 256
LOOPBACK = frozenset({"127.0.0.1", "::1"})
FORWARD_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-real-ip",
    "cf-connecting-ip",
    "cf-ray",
    "true-client-ip",
    "x-forwarded-proto",
    "x-forwarded-server",
    "x-original-forwarded-for",
    "via",
    "cdn-loop",
    "cf-visitor",
    "cf-ipcountry",
)
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
SECRET_PARTS = ("key", "password", "secret", "token")
RISK_LIMITS = ("max_daily_loss_pct", "max_total_drawdown_pct", "risk_per_trade_pct", "max_open_trades")


def loopback_name(host: str | None) -> bool:
    if not host:
        return False
    name = host.strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def is_local(connection: HTTPConnection) -> bool:
    """True for a loopback peer with no forwarding header, a loopback Host, and a loopback Origin when one is sent."""
    host = connection.client.host if connection.client else None
    if host not in LOOPBACK or any(name in connection.headers for name in FORWARD_HEADERS):
        return False
    if not loopback_name(urlsplit("//" + connection.headers.get("host", "")).hostname):
        return False
    origin = connection.headers.get("origin")
    return origin is None or loopback_name(urlsplit(origin).hostname)


def loggable_key(raw: str | None) -> str | None:
    """The Idempotency-Key header when it is well formed, else None, so client text never reaches the audit log."""
    return raw if raw is not None and IDEMPOTENCY_KEY.match(raw) else None


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<set>" if item is not None else None)
            if any(part in str(key).lower() for part in SECRET_PARTS)
            else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def idempotency_key(raw: str | None) -> str:
    if raw is None or not IDEMPOTENCY_KEY.match(raw):
        raise ApiError(400, "invalid_request", "Idempotency-Key header must hold 8-128 characters of [A-Za-z0-9_-]")
    return raw


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def risky_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Config keys whose change needs two-step confirmation: a raised risk limit, a mode switch, enabling forced entries."""
    changes = []
    if old.get("mode") != new.get("mode"):
        changes.append("mode")
    old_risk, new_risk = old.get("risk") or {}, new.get("risk") or {}
    for key in RISK_LIMITS:
        before, after = _number(old_risk.get(key)), _number(new_risk.get(key))
        if after is not None and (before is None or after > before):
            changes.append(f"risk.{key}")
    if not (old.get("api") or {}).get("force_entry") and (new.get("api") or {}).get("force_entry"):
        changes.append("api.force_entry")
    return changes


@dataclass(frozen=True)
class Pending:
    id: str
    action: str
    targets: list[str]
    summary: str
    binding: str
    expires: float
    expires_at: str

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "targets": self.targets,
            "summary": self.summary,
            "expires_at": self.expires_at,
        }


class Confirmations:
    """Single-use confirmation tokens bound to one action, its parameters and the session that asked."""

    def __init__(self, ttl_s: float = CONFIRM_TTL_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self.clock = clock
        self._pending: dict[str, Pending] = {}

    def _prune(self, now: float) -> None:
        for key in [key for key, item in self._pending.items() if item.expires + CONFIRM_GRACE_S <= now]:
            del self._pending[key]
        while len(self._pending) >= CONFIRM_LIMIT:
            del self._pending[next(iter(self._pending))]

    def issue(self, action: str, targets: list[str], summary: str, binding: str) -> Pending:
        now = self.clock()
        self._prune(now)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_s)
        pending = Pending(
            id="cf_" + secrets.token_urlsafe(16),
            action=action,
            targets=targets,
            summary=summary,
            binding=binding,
            expires=now + self.ttl_s,
            expires_at=expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        )
        self._pending[pending.id] = pending
        return pending

    def redeem(self, confirm_id: str, binding: str) -> Pending:
        pending = self._pending.get(confirm_id)
        if pending is None:
            raise ApiError(409, "confirmation_invalid", "confirmation is unknown or already used")
        if pending.expires <= self.clock():
            del self._pending[confirm_id]
            raise ApiError(409, "confirmation_expired", "confirmation expired; ask for a new one")
        if not secrets.compare_digest(pending.binding, binding):
            raise ApiError(409, "confirmation_invalid", "confirmation was issued for another action or parameters")
        del self._pending[confirm_id]
        return pending
