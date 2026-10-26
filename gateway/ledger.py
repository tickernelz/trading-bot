"""Gateway-owned SQLite state: sessions, append-only audit log, idempotent control results, fills, config hashes."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    ip TEXT,
    action TEXT NOT NULL,
    targets TEXT NOT NULL,
    idempotency_key TEXT,
    result TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS audit_action_ts ON audit(action, ts);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    side TEXT NOT NULL,
    filled_ms INTEGER NOT NULL,
    received_ms INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS config_hashes (
    bot TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    status INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entry_stops (
    bot TEXT PRIMARY KEY,
    stopped INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""
IDEMPOTENCY_KEEP = timedelta(days=1)


ANALYST_USAGE_ACTIONS = {"analyst.report": "reports", "analyst.ask": "asks"}


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Ledger:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def create_session(self, scope: str, days: int, ip: str | None) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires = iso(now + timedelta(days=days))
        with self._db:
            self._db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", (_hash(token), scope, iso(now), expires, ip)
            )
        return token, expires

    def session_scope(self, token: str) -> str | None:
        row = self._db.execute(
            "SELECT scope, expires_at FROM sessions WHERE token_hash = ?", (_hash(token),)
        ).fetchone()
        if row is None or row["expires_at"] <= iso(datetime.now(UTC)):
            return None
        return row["scope"]

    def delete_session(self, token: str) -> bool:
        with self._db:
            return self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),)).rowcount > 0

    def audit(
        self,
        *,
        actor: str,
        action: str,
        targets: list[str],
        result: str,
        ip: str | None = None,
        idempotency_key: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "ts": iso(datetime.now(UTC)),
            "actor": actor,
            "ip": ip,
            "action": action,
            "targets": targets,
            "idempotency_key": idempotency_key,
            "result": result,
            "detail": detail,
        }
        with self._db:
            cursor = self._db.execute(
                "INSERT INTO audit (ts, actor, ip, action, targets, idempotency_key, result, detail)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["ts"],
                    actor,
                    ip,
                    action,
                    json.dumps(targets),
                    idempotency_key,
                    result,
                    json.dumps(detail) if detail is not None else None,
                ),
            )
        return {"id": cursor.lastrowid, **row}

    def audit_rows(
        self,
        limit: int,
        *,
        before_id: int | None = None,
        action: str | None = None,
        result: str | None = None,
        actor: str | None = None,
        target: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if before_id is not None:
            clauses.append("id < ?")
            args.append(before_id)
        if action is not None:
            clauses.append("substr(action, 1, ?) = ?")
            args += [len(action), action]
        for column, value in (("result", result), ("actor", actor)):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        if target is not None:
            clauses.append("EXISTS (SELECT 1 FROM json_each(audit.targets) WHERE json_each.value = ?)")
            args.append(target)
        if since is not None:
            clauses.append("ts >= ?")
            args.append(since)
        if until is not None:
            clauses.append("ts < ?")
            args.append(until)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        rows = self._db.execute(f"SELECT * FROM audit {where}ORDER BY id DESC LIMIT ?", (*args, limit))
        return [
            {
                **dict(row),
                "targets": json.loads(row["targets"]),
                "detail": json.loads(row["detail"]) if row["detail"] else None,
            }
            for row in rows
        ]

    def analyst_usage(self, since: str | None) -> dict[str, dict[str, Any]]:
        usage = {
            kind: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cost": None}
            for kind in ANALYST_USAGE_ACTIONS.values()
        }
        marks = ",".join("?" for _ in ANALYST_USAGE_ACTIONS)
        where, params = f"action IN ({marks}) AND result = 'ok'", list(ANALYST_USAGE_ACTIONS)
        if since:
            where, params = f"{where} AND ts >= ?", [*params, since]
        sums = ", ".join(
            f"COALESCE(SUM(json_extract(detail, '$.tokens.{field}')), 0) AS {field}"
            for field in ("input_tokens", "output_tokens", "reasoning_tokens")
        )
        query = (
            f"SELECT action, COUNT(*) AS calls, {sums}, SUM(json_extract(detail, '$.tokens.cost')) AS cost"
            f" FROM audit WHERE {where} GROUP BY action"
        )
        for row in self._db.execute(query, params):
            usage[ANALYST_USAGE_ACTIONS[row["action"]]] = {
                "calls": row["calls"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "reasoning_tokens": row["reasoning_tokens"],
                "cost": row["cost"],
            }
        return usage

    def stored_result(self, key: str) -> tuple[str, int, Any] | None:
        row = self._db.execute("SELECT request_hash, status, body FROM idempotency WHERE key = ?", (key,)).fetchone()
        return (row["request_hash"], row["status"], json.loads(row["body"])) if row else None

    def store_result(self, key: str, request_hash: str, status: int, body: Any) -> None:
        now = datetime.now(UTC)
        with self._db:
            self._db.execute("DELETE FROM idempotency WHERE created_at < ?", (iso(now - IDEMPOTENCY_KEEP),))
            self._db.execute(
                "INSERT INTO idempotency VALUES (?, ?, ?, ?, ?)",
                (key, request_hash, status, json.dumps(body), iso(now)),
            )

    def entries_stopped(self, bot: str) -> bool:
        row = self._db.execute("SELECT stopped FROM entry_stops WHERE bot = ?", (bot,)).fetchone()
        return bool(row and row["stopped"])

    def set_entries_stopped(self, bot: str, stopped: bool) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO entry_stops VALUES (?, ?, ?) ON CONFLICT(bot) DO UPDATE SET stopped = excluded.stopped,"
                " updated_at = excluded.updated_at",
                (bot, int(stopped), iso(datetime.now(UTC))),
            )

    def config_hash(self, bot: str) -> tuple[str, dict[str, Any]] | None:
        row = self._db.execute("SELECT sha256, snapshot FROM config_hashes WHERE bot = ?", (bot,)).fetchone()
        return (row["sha256"], json.loads(row["snapshot"])) if row else None

    def store_config_hash(self, bot: str, sha256: str, snapshot: dict[str, Any]) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO config_hashes VALUES (?, ?, ?) ON CONFLICT(bot) DO UPDATE SET sha256 = excluded.sha256,"
                " snapshot = excluded.snapshot",
                (bot, sha256, json.dumps(snapshot)),
            )

    def add_fill(self, bot: str, trade_id: int, side: str, filled_ms: int, received_ms: int) -> int:
        latency = received_ms - filled_ms
        with self._db:
            self._db.execute(
                "INSERT INTO fills (bot, trade_id, side, filled_ms, received_ms, latency_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (bot, trade_id, side, filled_ms, received_ms, latency),
            )
        return latency

    def fill_latency(self, limit: int = 500) -> dict[str, Any]:
        rows = self._db.execute(
            "SELECT bot, trade_id, side, filled_ms, received_ms, latency_ms FROM fills ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        values = sorted(row["latency_ms"] for row in rows)
        summary: dict[str, Any] = {"n": len(values)}
        if values:
            summary.update(
                p50=statistics.median(values),
                p95=values[min(len(values) - 1, int(0.95 * len(values)))],
                min=values[0],
                max=values[-1],
            )
        summary["recent"] = [dict(row) for row in rows[:20]]
        return summary


class LoginThrottle:
    def __init__(self, failures: int = 5, window_s: float = 60.0) -> None:
        self.failures = failures
        self.window_s = window_s
        self._recent: list[float] = []

    def blocked_for(self) -> float:
        now = time.monotonic()
        self._recent = [moment for moment in self._recent if now - moment < self.window_s]
        if len(self._recent) < self.failures:
            return 0.0
        return self.window_s - (now - self._recent[0])

    def fail(self) -> None:
        self._recent.append(time.monotonic())
