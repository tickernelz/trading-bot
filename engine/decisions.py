"""SQLite store of swarm shadow decisions and the trades they would have filtered."""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SHADOW_KEY = "shadow_decision_id"
PUBLIC_VOTER_FIELDS = ("voter_id", "provider", "model", "status", "latency_s", "error_kind", "answers")

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    bot TEXT NOT NULL,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    candle TEXT NOT NULL,
    rate REAL NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    required INTEGER NOT NULL,
    answered INTEGER NOT NULL DEFAULT 0,
    verdict TEXT,
    iqr_limit REAL,
    request TEXT NOT NULL,
    aggregate TEXT,
    voters TEXT,
    settle_seq INTEGER,
    settled_at TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS decisions_settle_seq ON decisions(settle_seq);
"""


@dataclass(frozen=True)
class Outcome:
    decision_id: str
    pair: str
    verdict: str | None
    status: str
    trade_id: int | None
    is_open: bool | None
    profit_abs: float | None
    profit_ratio: float | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class DecisionStore:
    def __init__(self, path: str | Path, *, readonly: bool = False) -> None:
        self.path = Path(path)
        if readonly:
            self._db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
        self._db.row_factory = sqlite3.Row

    def close(self) -> None:
        self._db.close()

    def add_pending(
        self,
        *,
        decision_id: str,
        bot: str,
        pair: str,
        timeframe: str,
        candle: str,
        rate: float,
        mode: str,
        required: int,
        iqr_limit: float | None,
        request: dict[str, Any],
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO decisions (decision_id, ts, bot, pair, timeframe, candle, rate, mode, status, required,"
                " iqr_limit, request) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (
                    decision_id,
                    _now(),
                    bot,
                    pair,
                    timeframe,
                    candle,
                    rate,
                    mode,
                    required,
                    iqr_limit,
                    json.dumps(request),
                ),
            )

    def settle(
        self,
        decision_id: str,
        *,
        status: str,
        reason: str | None,
        answered: int,
        verdict: str,
        aggregate: dict[str, Any] | None,
        voters: list[dict[str, Any]],
    ) -> None:
        usage = [voter.get("usage") or {} for voter in voters]
        costs = [item["cost"] for item in usage if item.get("cost") is not None]
        with self._db:
            self._db.execute(
                "UPDATE decisions SET status = ?, reason = ?, answered = ?, verdict = ?, aggregate = ?, voters = ?,"
                " settled_at = ?, settle_seq = (SELECT COALESCE(MAX(settle_seq), 0) + 1 FROM decisions),"
                " input_tokens = ?, output_tokens = ?, reasoning_tokens = ?, cost = ?"
                " WHERE decision_id = ? AND status = 'pending'",
                (
                    status,
                    reason,
                    answered,
                    verdict,
                    json.dumps(aggregate) if aggregate is not None else None,
                    json.dumps(voters),
                    _now(),
                    sum(item.get("input_tokens", 0) for item in usage),
                    sum(item.get("output_tokens", 0) for item in usage),
                    sum(item.get("reasoning_tokens", 0) for item in usage),
                    sum(costs) if costs else None,
                    decision_id,
                ),
            )

    def interrupt_pending(self, reason: str) -> int:
        pending = [
            row["decision_id"] for row in self._db.execute("SELECT decision_id FROM decisions WHERE status = 'pending'")
        ]
        for decision_id in pending:
            self.settle(
                decision_id, status="skip", reason=reason, answered=0, verdict="lewati", aggregate=None, voters=[]
            )
        return len(pending)

    def pending_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM decisions WHERE status = 'pending'").fetchone()[0]

    def recent(
        self, limit: int, *, pair: str | None = None, before: datetime | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Newest settled decisions first, optionally for one pair, one status, or candles before a moment."""
        where = ["settle_seq IS NOT NULL"]
        params: list[Any] = []
        if pair is not None:
            where.append("pair = ?")
            params.append(pair)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if before is not None:
            where.append("candle < ?")
            params.append(before.astimezone(UTC).isoformat())
        rows = self._db.execute(
            f"SELECT * FROM decisions WHERE {' AND '.join(where)} ORDER BY settle_seq DESC LIMIT ?", (*params, limit)
        )
        return [public_decision(row) for row in rows]

    def settled_after(self, settle_seq: int) -> list[tuple[int, dict[str, Any]]]:
        rows = self._db.execute(
            "SELECT * FROM decisions WHERE settle_seq > ? ORDER BY settle_seq", (settle_seq,)
        ).fetchall()
        return [(row["settle_seq"], public_decision(row)) for row in rows]

    def last_settle_seq(self) -> int:
        return self._db.execute("SELECT COALESCE(MAX(settle_seq), 0) FROM decisions").fetchone()[0]

    def counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT status, COUNT(*) AS n FROM decisions GROUP BY status")
        return {row["status"]: row["n"] for row in rows}

    def first_real_answer_at(self) -> str | None:
        rows = self._db.execute("SELECT settled_at, voters FROM decisions WHERE answered > 0 ORDER BY settle_seq")
        for row in rows:
            if any(voter.get("status") == "ok" for voter in json.loads(row["voters"] or "[]")):
                return row["settled_at"]
        return None

    def usage(self, since: str | None = None) -> dict[str, Any]:
        where, params = ("WHERE settled_at >= ?", (since,)) if since else ("WHERE settled_at IS NOT NULL", ())
        totals = {"decisions": 0, "voter_calls": 0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
        providers: dict[tuple[str, str], dict[str, Any]] = {}
        cost_total = 0.0
        cost_seen = False
        for row in self._db.execute(f"SELECT voters FROM decisions {where}", params):
            totals["decisions"] += 1
            for voter in json.loads(row["voters"] or "[]"):
                usage = voter.get("usage") or {}
                key = (voter.get("provider") or "?", voter.get("model") or voter.get("configured_model") or "?")
                bucket = providers.setdefault(
                    key,
                    {
                        "provider": key[0],
                        "model": key[1],
                        "calls": 0,
                        "ok": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                        "cost": None,
                    },
                )
                totals["voter_calls"] += 1
                bucket["calls"] += 1
                bucket["ok"] += voter.get("status") == "ok"
                for field in ("input_tokens", "output_tokens", "reasoning_tokens"):
                    totals[field] += usage.get(field, 0)
                    bucket[field] += usage.get(field, 0)
                if usage.get("cost") is not None:
                    cost_seen = True
                    cost_total += usage["cost"]
                    bucket["cost"] = (bucket["cost"] or 0.0) + usage["cost"]
        return {**totals, "cost": cost_total if cost_seen else None, "providers": list(providers.values())}

    def provider_health(self, window: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT voters FROM decisions WHERE settle_seq IS NOT NULL ORDER BY settle_seq DESC LIMIT ?", (window,)
        )
        samples: dict[str, dict[str, Any]] = {}
        for row in rows:
            for voter in json.loads(row["voters"] or "[]"):
                entry = samples.setdefault(
                    voter.get("provider") or "?",
                    {
                        "provider": voter.get("provider") or "?",
                        "latencies": [],
                        "calls": 0,
                        "ok": 0,
                        "last_status": None,
                    },
                )
                entry["calls"] += 1
                entry["ok"] += voter.get("status") == "ok"
                entry["last_status"] = entry["last_status"] or voter.get("status")
                if voter.get("status") == "ok":
                    entry["latencies"].append(voter.get("latency_s", 0.0))
        result = []
        for entry in samples.values():
            latencies = entry.pop("latencies")
            entry["latency_p50_s"] = statistics.median(latencies) if latencies else None
            entry["latency_max_s"] = max(latencies) if latencies else None
            result.append(entry)
        return result

    def get(self, decision_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM decisions WHERE decision_id = ? AND settle_seq IS NOT NULL", (decision_id,)
        ).fetchone()
        return public_decision(row) if row else None

    def outcomes(self, trades_db: str | Path) -> list[Outcome]:
        """Join each settled decision to the trade it shadowed, through the trade's custom data."""
        linked = linked_trades(trades_db)
        result = []
        for row in self._db.execute(
            "SELECT decision_id, pair, verdict, status FROM decisions WHERE settle_seq IS NOT NULL ORDER BY settle_seq"
        ):
            trade = linked.get(row["decision_id"])
            result.append(
                Outcome(
                    decision_id=row["decision_id"],
                    pair=row["pair"],
                    verdict=row["verdict"],
                    status=row["status"],
                    trade_id=trade["id"] if trade else None,
                    is_open=bool(trade["is_open"]) if trade else None,
                    profit_abs=trade["close_profit_abs"] if trade else None,
                    profit_ratio=trade["close_profit"] if trade else None,
                )
            )
        return result


def linked_trades(trades_db: str | Path) -> dict[str, sqlite3.Row]:
    """Trades keyed by the shadow decision id stored in their custom data; empty when the database is absent."""
    path = Path(trades_db)
    if not path.exists():
        return {}
    trades = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    trades.row_factory = sqlite3.Row
    try:
        return {
            row["cd_value"]: row
            for row in trades.execute(
                "SELECT d.cd_value, t.id, t.is_open, t.close_profit_abs, t.close_profit FROM trade_custom_data d"
                " JOIN trades t ON t.id = d.ft_trade_id WHERE d.cd_key = ?",
                (SHADOW_KEY,),
            )
        }
    finally:
        trades.close()


def public_decision(row: sqlite3.Row) -> dict[str, Any]:
    voters: Iterable[dict[str, Any]] = json.loads(row["voters"] or "[]")
    state = json.loads(row["request"]).get("state") or {}
    return {
        "decision_id": row["decision_id"],
        "ts": row["settled_at"] or row["ts"],
        "requested_at": row["ts"],
        "bot": row["bot"],
        "pair": row["pair"],
        "timeframe": row["timeframe"],
        "candle": row["candle"],
        "rate": row["rate"],
        "entry_tag": state.get("entry_tag"),
        "mode": row["mode"],
        "status": row["status"],
        "reason": row["reason"],
        "required": row["required"],
        "answered": row["answered"],
        "verdict": row["verdict"],
        "iqr_limit": row["iqr_limit"],
        "aggregate": json.loads(row["aggregate"]) if row["aggregate"] else None,
        "voters": [{field: voter.get(field) for field in PUBLIC_VOTER_FIELDS} for voter in voters],
        "usage": {
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "reasoning_tokens": row["reasoning_tokens"],
            "cost": row["cost"],
        },
    }
