from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_swarm.models import ChoiceAnswer, ChoiceQuestion, DecisionRequest
from tb_swarm.outcome import VoterRecord

from engine.decisions import SHADOW_KEY

DECISIONS_SCHEMA = """
CREATE TABLE decisions (
    decision_id TEXT PRIMARY KEY, ts TEXT NOT NULL, bot TEXT NOT NULL, pair TEXT NOT NULL,
    timeframe TEXT NOT NULL, candle TEXT NOT NULL, rate REAL NOT NULL, mode TEXT NOT NULL,
    status TEXT NOT NULL, reason TEXT, required INTEGER NOT NULL, answered INTEGER NOT NULL DEFAULT 0,
    verdict TEXT, iqr_limit REAL, request TEXT, aggregate TEXT, voters TEXT, settle_seq INTEGER,
    settled_at TEXT, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0, cost REAL
);
CREATE UNIQUE INDEX decisions_settle_seq ON decisions(settle_seq) WHERE settle_seq IS NOT NULL;
"""
TRADES_SCHEMA = """
CREATE TABLE trades (id INTEGER PRIMARY KEY, close_profit_abs REAL, is_open INTEGER NOT NULL);
CREATE TABLE trade_custom_data (id INTEGER PRIMARY KEY, ft_trade_id INTEGER, cd_key TEXT, cd_value TEXT);
"""
OPTIONS = {"allow": "take", "reduce": "half", "skip": "skip"}
NOW = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)


def request() -> DecisionRequest:
    return DecisionRequest(state="s", questions={"verdict": ChoiceQuestion(instructions="?", criteria=OPTIONS)})


def answer(choice: str, take: float | None = None) -> ChoiceAnswer:
    if take is None:
        return ChoiceAnswer(type="choice", choice=choice)
    probabilities = {"allow": take * 0.8, "reduce": take * 0.2, "skip": 1 - take}
    return ChoiceAnswer(type="choice", choice=choice, probabilities=probabilities)


def record(voter_id: str, choice: str | None = "allow", take: float | None = None, status: str = "ok") -> VoterRecord:
    answers = {"verdict": answer(choice, take)} if status == "ok" and choice else None
    return VoterRecord(voter_id=voter_id, status=status, latency_s=0.5, answers=answers)


def open_trade(
    pair: str = "BTC/IDR",
    trade_id: int = 1,
    stake: float = 300_000.0,
    rate: float = 1_000_000.0,
    stop_pct: float = -3.0,
    current: float | None = None,
) -> dict[str, Any]:
    amount = stake / rate
    fee = 0.002
    cost = stake * (1 + fee)
    now_rate = rate if current is None else current
    return {
        "trade_id": trade_id,
        "pair": pair,
        "is_open": True,
        "amount": amount,
        "stake_amount": stake,
        "open_trade_value": cost,
        "open_rate": rate,
        "current_rate": now_rate,
        "fee_open": fee,
        "fee_close": fee,
        "stop_loss_pct": stop_pct,
        "stop_loss_abs": rate * (1 + stop_pct / 100),
        "profit_abs": amount * now_rate * (1 - fee) - cost,
        "enter_tag": "ema_cross_up",
    }


def closed_trade(
    profit: float,
    close_date: str = "2026-10-26 02:00:00",
    pair: str = "BTC/IDR",
    trade_id: int = 10,
    close_rate: float = 1_000_000.0,
    amount: float = 0.0003,
    exit_reason: str = "exit_signal",
) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "pair": pair,
        "is_open": False,
        "amount": amount,
        "stake_amount": amount * close_rate,
        "open_rate": close_rate,
        "close_rate": close_rate,
        "open_date": "2026-10-25 20:00:00",
        "close_date": close_date,
        "fee_open": 0.002,
        "fee_close": 0.002,
        "profit_abs": profit,
        "close_profit_abs": profit,
        "close_profit_pct": round(profit / (amount * close_rate) * 100, 4),
        "enter_tag": "ema_cross_up",
        "exit_reason": exit_reason,
    }


def write_decisions(path: Path, rows: list[dict[str, Any]]) -> None:
    db = sqlite3.connect(path)
    db.executescript(DECISIONS_SCHEMA)
    for seq, row in enumerate(rows, start=1):
        voters = row["voters"]
        db.execute(
            "INSERT INTO decisions (decision_id, ts, bot, pair, timeframe, candle, rate, mode, status, reason, required,"
            " answered, verdict, iqr_limit, request, aggregate, voters, settle_seq, settled_at)"
            " VALUES (?, ?, 'B', ?, '1h', '2026-10-26T01:00:00Z', 1.0, 'shadow', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
            (
                row["decision_id"],
                row.get("ts", "2026-10-26T01:00:00Z"),
                row.get("pair", "BTC/IDR"),
                row.get("status", "ok"),
                row.get("reason"),
                row.get("required", 5),
                sum(1 for voter in voters if voter.status == "ok"),
                row.get("verdict", "allow"),
                row.get("iqr_limit"),
                row.get("request") or json.dumps(request().model_dump(mode="json")),
                json.dumps([voter.model_dump(mode="json") for voter in voters]),
                seq,
                row.get("settled_at", f"2026-10-26T01:{seq % 60:02d}:00Z"),
            ),
        )
    db.commit()
    db.close()


def write_trades(path: Path, outcomes: dict[str, tuple[float | None, bool]]) -> None:
    db = sqlite3.connect(path)
    db.executescript(TRADES_SCHEMA)
    for index, (decision_id, (profit, is_open)) in enumerate(outcomes.items(), start=1):
        db.execute("INSERT INTO trades (id, close_profit_abs, is_open) VALUES (?, ?, ?)", (index, profit, int(is_open)))
        db.execute(
            "INSERT INTO trade_custom_data (ft_trade_id, cd_key, cd_value) VALUES (?, ?, ?)",
            (index, SHADOW_KEY, decision_id),
        )
    db.commit()
    db.close()
