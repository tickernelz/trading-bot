"""Fail-closed state of the dry_run and live mode, persisted next to the bot's data."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Mode = Literal["dry_run", "live"]

LIVE_ENGINE_PROVEN = False
MODE_FILE = "mode.json"
CAPABILITIES_FILE = "capabilities.json"
DEFAULT_KEY_ENVS = ("INDODAX_API_KEY", "INDODAX_API_SECRET")
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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = Path(state_path)
        self._key_probe = exchange_key_configured
        self._key_envs = key_envs
        self._proven = live_engine_proven
        self._clock = clock

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

    def ensure_live_allowed(self) -> None:
        blockers = self.blockers()
        if blockers:
            raise ModeRefused("live_blocked", blockers[0]["message"], blockers)

    def apply(self, mode: str, actor: str) -> dict[str, Any]:
        """Record the mode; live is re-checked here so no caller can reach it without every precondition."""
        if mode not in MODES:
            raise ModeRefused("invalid_request", f"mode must be one of {', '.join(MODES)}")
        if mode == "live":
            self.ensure_live_allowed()
        current, _ = read_mode(self._path)
        if mode == current:
            return self.status()
        record = {"mode": mode, "changed_at": _stamp(self._clock()), "actor": actor}
        _write_json(self._path, record)
        return {**self.status(), "changed_at": record["changed_at"]}
