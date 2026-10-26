"""Fail-closed, two-step switch between dry_run and live, persisted next to the bot's data."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

Mode = Literal["dry_run", "live"]

LIVE_ENGINE_PROVEN = False
MODE_FILE = "mode.json"
CAPABILITIES_FILE = "capabilities.json"
DEFAULT_KEY_ENVS = ("INDODAX_API_KEY", "INDODAX_API_SECRET")
CONFIRMATION_TTL_S = 60
MODES = ("dry_run", "live")

BLOCKER_MESSAGES = {
    "exchange_key_missing": "set {names} in the engine environment; live never starts without exchange credentials",
    "live_engine_unproven": "the engine has no proven live order path yet; live stays unavailable until it does",
}


class ModeRefused(Exception):
    """A switch request that was refused; code is stable, blockers lists every unmet precondition."""

    def __init__(self, code: str, message: str, blockers: tuple[dict[str, str], ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blockers = blockers


@dataclass(frozen=True)
class Confirmation:
    id: str
    action: str
    targets: tuple[str, ...]
    summary: str
    expires_at: datetime


@dataclass(frozen=True)
class _Pending:
    target: str
    actor: str
    expires_at: datetime


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def write_capabilities(
    userdir: str | os.PathLike[str],
    environ: Mapping[str, str],
    key_envs: tuple[str, ...] = DEFAULT_KEY_ENVS,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Record, without any value, whether this engine process was started with exchange credentials."""
    configured = all((environ.get(name) or "").strip() for name in key_envs)
    _write_json(Path(userdir) / CAPABILITIES_FILE, {"exchange_key_configured": configured, "at": _stamp(clock())})


def read_exchange_key_configured(userdir: str | os.PathLike[str]) -> bool:
    """True only when the engine recorded credentials; a missing, unreadable or malformed file reads as False."""
    try:
        data = json.loads((Path(userdir) / CAPABILITIES_FILE).read_text(encoding="utf-8"))
        return data["exchange_key_configured"] is True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def read_mode(path: str | os.PathLike[str]) -> tuple[Mode, str | None]:
    """The recorded mode and a problem string; anything missing, unreadable or unknown reads as dry_run."""
    file = Path(path)
    if not file.exists():
        return "dry_run", None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        mode = data["mode"]
    except (OSError, ValueError, KeyError, TypeError):
        return "dry_run", "mode state is unreadable; treated as dry_run"
    if mode not in MODES:
        return "dry_run", f"mode state holds {mode!r}; treated as dry_run"
    return mode, None


class ModeController:
    def __init__(
        self,
        state_path: str | os.PathLike[str],
        *,
        exchange_key_configured: Callable[[], bool],
        key_envs: tuple[str, ...] = DEFAULT_KEY_ENVS,
        live_engine_proven: bool = LIVE_ENGINE_PROVEN,
        ttl_s: float = CONFIRMATION_TTL_S,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = Path(state_path)
        self._key_probe = exchange_key_configured
        self._key_envs = key_envs
        self._proven = live_engine_proven
        self._ttl = timedelta(seconds=ttl_s)
        self._clock = clock
        self._pending: dict[str, _Pending] = {}

    def blockers(self) -> tuple[dict[str, str], ...]:
        found = []
        if not self._key_probe():
            message = BLOCKER_MESSAGES["exchange_key_missing"].format(names=" and ".join(self._key_envs))
            found.append({"code": "exchange_key_missing", "message": message})
        if not self._proven:
            found.append({"code": "live_engine_unproven", "message": BLOCKER_MESSAGES["live_engine_unproven"]})
        return tuple(found)

    def status(self) -> dict[str, Any]:
        mode, problem = read_mode(self._path)
        blockers = self.blockers()
        out: dict[str, Any] = {
            "mode": mode,
            "live_allowed": not blockers,
            "blockers": list(blockers),
            "exchange_key_configured": not any(item["code"] == "exchange_key_missing" for item in blockers),
        }
        if problem:
            out["state_problem"] = problem
        return out

    def request(self, target: str, actor: str) -> Confirmation | dict[str, Any]:
        """Ask for a switch; live returns a Confirmation to repeat within the TTL, dry_run applies at once."""
        if target not in MODES:
            raise ModeRefused("invalid_request", f"mode must be one of {', '.join(MODES)}")
        current, _ = read_mode(self._path)
        if target == current:
            return self.status()
        if target == "dry_run":
            return self._apply("dry_run", actor)
        blockers = self.blockers()
        if blockers:
            raise ModeRefused("live_blocked", blockers[0]["message"], blockers)
        now = self._clock()
        self._pending = {key: item for key, item in self._pending.items() if item.expires_at > now}
        confirmation = Confirmation(
            id=f"cf_{secrets.token_hex(8)}",
            action="mode.live",
            targets=("live",),
            summary=f"Switch {current} to live: orders will use real money",
            expires_at=now + self._ttl,
        )
        self._pending[confirmation.id] = _Pending("live", actor, confirmation.expires_at)
        return confirmation

    def confirm(self, confirmation_id: str, actor: str) -> dict[str, Any]:
        pending = self._pending.get(confirmation_id)
        if pending is None or pending.actor != actor:
            raise ModeRefused("confirmation_invalid", "unknown confirmation")
        del self._pending[confirmation_id]
        if pending.expires_at <= self._clock():
            raise ModeRefused("confirmation_expired", "confirmation expired; request the switch again")
        blockers = self.blockers()
        if blockers:
            raise ModeRefused("live_blocked", blockers[0]["message"], blockers)
        return self._apply(pending.target, actor)

    def _apply(self, mode: str, actor: str) -> dict[str, Any]:
        record = {"mode": mode, "changed_at": _stamp(self._clock()), "actor": actor}
        _write_json(self._path, record)
        return {**self.status(), "changed_at": record["changed_at"]}
