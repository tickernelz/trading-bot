"""Reads, validates, diffs and atomically writes a bot configuration file."""

from __future__ import annotations

import copy
import hashlib
import os
import secrets
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from engine.settings import Settings
from gateway.control import risky_changes
from gateway.redact import key_last4
from gateway.upstream import ApiError
from gateway.views import flatten

BREACH_KEYS = {
    "risk.max_daily_loss_pct": "daily_loss_pct",
    "risk.max_total_drawdown_pct": "drawdown_pct",
}
FROZEN_ROOTS = frozenset({"mode", "bot_id", "api", "shadow", "providers"})
SECRET_LEAF = "api_key"
GIT_TIMEOUT_S = 5


def validation_message(exc: ValidationError) -> str:
    parts = []
    for item in exc.errors(include_input=False, include_url=False, include_context=False)[:5]:
        where = ".".join(str(part) for part in item["loc"])
        parts.append(f"{where}: {item['msg']}" if where else item["msg"])
    return "; ".join(parts)


def read_raw(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ApiError(503, "upstream_error", f"config file cannot be read: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ApiError(503, "upstream_error", "config file is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise ApiError(503, "upstream_error", "config file top level must be a mapping")
    return raw


def validate(raw: dict[str, Any]) -> Settings:
    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ApiError(400, "invalid_request", validation_message(exc)) from exc


def validate_or_none(raw: dict[str, Any]) -> Settings | None:
    try:
        return Settings.model_validate(raw)
    except ValidationError:
        return None


def check_patch(changes: dict[str, Any]) -> None:
    frozen = FROZEN_ROOTS.intersection(changes)
    if frozen:
        name = sorted(frozen)[0]
        hint = " (use the providers endpoints)" if name == "providers" else ""
        raise ApiError(400, "invalid_request", f"{name} cannot be changed through settings{hint}")
    swarm = changes.get("swarm")
    if isinstance(swarm, dict) and "voters" in swarm:
        raise ApiError(
            400, "invalid_request", "swarm.voters cannot be changed through settings (use the voters endpoints)"
        )


def merge(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)

    def descend(target: dict[str, Any], patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                descend(target[key], value)
            else:
                target[key] = copy.deepcopy(value)

    descend(merged, changes)
    return merged


def shown(key: str, value: Any) -> Any:
    if key.rsplit(".", 1)[-1] != SECRET_LEAF or value is None:
        return value
    tail = key_last4(value) if isinstance(value, str) else None
    return f"****{tail}" if tail else "<set>"


def diff(old_raw: dict[str, Any], new_raw: dict[str, Any]) -> list[dict[str, Any]]:
    old, new = flatten(old_raw), flatten(new_raw)
    return [
        {"key": key, "old": shown(key, old.get(key)), "new": shown(key, new.get(key))}
        for key in sorted(set(old) | set(new))
        if old.get(key) != new.get(key)
    ]


def snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ("<set>" if value else None) if key.rsplit(".", 1)[-1] == SECRET_LEAF else value
        for key, value in flatten(raw).items()
    }


def inline_keys(raw: dict[str, Any]) -> list[str]:
    secrets_found = []
    for provider in raw.get("providers") or []:
        value = provider.get(SECRET_LEAF) if isinstance(provider, dict) else None
        if isinstance(value, str) and value:
            secrets_found.append(value)
    return secrets_found


def lookup(settings: Settings, dotted: str) -> Any:
    value: Any = settings
    for part in dotted.split("."):
        value = getattr(value, part)
    return value


def raising_keys(old_raw: dict[str, Any], new_raw: dict[str, Any]) -> list[str]:
    """Keys that need the two-step confirmation: control.risky_changes plus a larger capital.initial_idr."""
    keys = risky_changes(old_raw, new_raw)
    before, after = (old_raw.get("capital") or {}).get("initial_idr"), (new_raw.get("capital") or {}).get("initial_idr")
    numbers = isinstance(before, int | float) and isinstance(after, int | float)
    if numbers and not isinstance(before, bool) and not isinstance(after, bool) and after > before:
        keys.append("capital.initial_idr")
    return keys


def breached_limits(new: Settings, old: Settings | None, risk: dict[str, Any]) -> list[str]:
    hits = []
    for key, field in BREACH_KEYS.items():
        limit = lookup(new, key)
        previous = lookup(old, key) if old is not None else None
        current = risk.get(field)
        if current and current > 0 and limit <= current and (previous is None or limit < previous):
            hits.append(f"{key} {limit} is not above the {field} already reached ({current})")
    return hits


def write_raw(path: str | os.PathLike[str], raw: dict[str, Any]) -> str:
    """Replaces the file atomically with mode 0600 and returns the SHA-256 of what was written."""
    target = Path(path)
    payload = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True).encode("utf-8")
    temp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        if os.name != "nt":
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError as exc:
        with suppress(FileNotFoundError):
            os.unlink(temp)
        raise ApiError(500, "config_unwritable", f"config file cannot be written: {exc.strerror}") from exc
    return hashlib.sha256(payload).hexdigest()


def unsafe_for_inline_key(path: str | os.PathLike[str]) -> bool:
    """True when the file sits in a git work tree and is not ignored, or git cannot say."""
    directory = Path(path).resolve().parent
    if not any((candidate / ".git").exists() for candidate in (directory, *directory.parents)):
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "check-ignore", "-q", "--", Path(path).name],
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return result.returncode != 0
