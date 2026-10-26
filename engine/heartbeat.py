"""Bot liveness files: an atomically replaced heartbeat and an append-only start log."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HEARTBEAT_FILE = "heartbeat.json"
STARTS_FILE = "starts.jsonl"


def write_heartbeat(userdir: str | os.PathLike[str], payload: dict[str, Any]) -> None:
    target = Path(userdir) / HEARTBEAT_FILE
    staging = target.with_suffix(".json.tmp")
    staging.write_text(json.dumps({"ts": datetime.now(UTC).isoformat(), **payload}), encoding="utf-8")
    os.replace(staging, target)


def read_heartbeat(userdir: str | os.PathLike[str]) -> dict[str, Any] | None:
    try:
        return json.loads((Path(userdir) / HEARTBEAT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def record_start(userdir: str | os.PathLike[str], pid: int) -> int:
    """Append one start and return how many starts the log now holds."""
    path = Path(userdir) / STARTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "pid": pid}) + "\n")
    return count_starts(userdir)


def count_starts(userdir: str | os.PathLike[str]) -> int:
    try:
        with (Path(userdir) / STARTS_FILE).open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0
