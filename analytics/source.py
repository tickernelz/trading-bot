"""Read-only access to the swarm decision store and the trade outcomes joined to it."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from tb_swarm.models import DecisionRequest
from tb_swarm.outcome import VoterRecord

from analytics.errors import AnalyticsError

SHADOW_KEY = "shadow-decision-id"
DECISION_COLUMNS = "decision_id, settled_at, pair, status, reason, verdict, required, iqr_limit, request, voters"


@dataclass(frozen=True)
class RecordedDecision:
    decision_id: str
    settled_at: str
    pair: str
    status: str
    reason: str | None
    verdict: str | None
    required: int
    iqr_limit: float | None
    request: DecisionRequest
    voters: tuple[VoterRecord, ...]
    profit_abs: float | None = None
    is_open: bool | None = None

    @property
    def closed_profit(self) -> float | None:
        return self.profit_abs if self.is_open is False else None


@dataclass(frozen=True)
class Loaded:
    decisions: tuple[RecordedDecision, ...]
    invalid: int


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise AnalyticsError(404, "not_found", f"{path.name} does not exist")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def trade_outcomes(trades_db: Path) -> dict[str, tuple[float | None, bool]]:
    db = connect(trades_db)
    try:
        rows = db.execute(
            "SELECT d.cd_value AS decision_id, t.close_profit_abs AS profit, t.is_open AS is_open"
            " FROM trade_custom_data d JOIN trades t ON t.id = d.ft_trade_id WHERE d.cd_key = ?",
            (SHADOW_KEY,),
        ).fetchall()
    finally:
        db.close()
    return {row["decision_id"]: (row["profit"], bool(row["is_open"])) for row in rows}


def parse_decision(row: sqlite3.Row, outcomes: dict[str, tuple[float | None, bool]]) -> RecordedDecision:
    profit, is_open = outcomes.get(row["decision_id"], (None, None))
    return RecordedDecision(
        decision_id=row["decision_id"],
        settled_at=row["settled_at"],
        pair=row["pair"],
        status=row["status"],
        reason=row["reason"],
        verdict=row["verdict"],
        required=row["required"],
        iqr_limit=row["iqr_limit"],
        request=DecisionRequest.model_validate(json.loads(row["request"])),
        voters=tuple(VoterRecord.model_validate(item) for item in json.loads(row["voters"] or "[]")),
        profit_abs=profit,
        is_open=is_open,
    )


def load_decisions(decisions_db: Path, trades_db: Path | None = None, limit: int = 500) -> Loaded:
    """Load the newest settled decisions, each with its trade outcome when a trades database is given."""
    outcomes = trade_outcomes(trades_db) if trades_db is not None else {}
    db = connect(decisions_db)
    try:
        rows = db.execute(
            f"SELECT {DECISION_COLUMNS} FROM decisions WHERE settle_seq IS NOT NULL ORDER BY settle_seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        db.close()
    decisions: list[RecordedDecision] = []
    invalid = 0
    for row in rows:
        try:
            decisions.append(parse_decision(row, outcomes))
        except (ValidationError, ValueError, KeyError, TypeError):
            invalid += 1
    return Loaded(tuple(reversed(decisions)), invalid)


def table_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]


def describe(decisions_db: Path) -> dict[str, Any]:
    db = connect(decisions_db)
    try:
        return {"columns": table_columns(db, "decisions")}
    finally:
        db.close()
