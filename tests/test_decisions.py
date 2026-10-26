from __future__ import annotations

import sqlite3

import pytest

from datetime import UTC, datetime

from engine.decisions import SHADOW_KEY, DecisionStore


def _pending(store: DecisionStore, decision_id: str, pair: str = "BTC/IDR") -> None:
    store.add_pending(
        decision_id=decision_id,
        bot="B",
        pair=pair,
        timeframe="1h",
        candle="2026-10-25T17:00:00+00:00",
        rate=1_463_933_000.0,
        mode="shadow",
        required=5,
        iqr_limit=None,
        request={"state": {"pair": pair}},
    )


def _voter(voter_id: str, status: str, latency: float, tokens: int = 100, cost: float | None = None) -> dict:
    return {
        "voter_id": voter_id,
        "provider": "nutaraline",
        "model": "deepseek-v4.1-flash-1017",
        "status": status,
        "latency_s": latency,
        "error_kind": None if status == "ok" else "timeout",
        "error": None if status == "ok" else "no answer within 30s",
        "answers": {"verdict": {"type": "choice", "choice": "izinkan"}} if status == "ok" else None,
        "usage": {"input_tokens": tokens, "output_tokens": tokens // 10, "reasoning_tokens": 0, "cost": cost},
    }


@pytest.fixture
def store(tmp_path):
    instance = DecisionStore(tmp_path / "decisions.sqlite")
    yield instance
    instance.close()


def test_settled_decision_is_public_without_voter_errors_or_request(store):
    _pending(store, "a" * 32)
    assert store.recent(10) == []
    store.settle(
        "a" * 32,
        status="skip",
        reason="quorum_not_met",
        answered=1,
        verdict="lewati",
        aggregate=None,
        voters=[_voter("v1", "ok", 2.0), _voter("v2", "timeout", 30.0)],
    )
    [decision] = store.recent(10)
    assert decision["verdict"] == "lewati"
    assert decision["status"] == "skip"
    assert decision["usage"]["input_tokens"] == 200
    assert "request" not in decision
    assert all("error" not in voter and "usage" not in voter for voter in decision["voters"])
    assert decision["voters"][1]["error_kind"] == "timeout"


def test_settled_after_returns_new_decisions_in_order(store):
    for index, decision_id in enumerate(("1" * 32, "2" * 32)):
        _pending(store, decision_id)
        store.settle(decision_id, status="ok", reason=None, answered=5, verdict="izinkan", aggregate=None, voters=[])
        assert store.last_settle_seq() == index + 1
    assert [row[1]["decision_id"] for row in store.settled_after(1)] == ["2" * 32]


def test_restart_interrupts_pending_decisions_once(store):
    _pending(store, "b" * 32)
    assert store.interrupt_pending("shadow_restart") == 1
    assert store.interrupt_pending("shadow_restart") == 0
    [decision] = store.recent(1)
    assert decision["reason"] == "shadow_restart"
    store.settle("b" * 32, status="ok", reason=None, answered=7, verdict="izinkan", aggregate=None, voters=[])
    assert store.recent(1)[0]["status"] == "skip"


def test_usage_and_provider_health_count_every_voter_call(store):
    _pending(store, "c" * 32)
    store.settle(
        "c" * 32,
        status="ok",
        reason=None,
        answered=2,
        verdict="izinkan",
        aggregate=None,
        voters=[
            _voter("v1", "ok", 2.0, cost=0.001),
            _voter("v2", "ok", 4.0, cost=0.002),
            _voter("v3", "timeout", 30.0),
        ],
    )
    usage = store.usage()
    assert usage["decisions"] == 1
    assert usage["voter_calls"] == 3
    assert usage["input_tokens"] == 300
    assert usage["cost"] == pytest.approx(0.003)
    [health] = store.provider_health()
    assert health["calls"] == 3
    assert health["ok"] == 2
    assert health["latency_p50_s"] == 3.0
    assert store.first_real_answer_at() is not None


def test_no_real_answer_means_no_shadow_clock(store):
    _pending(store, "d" * 32)
    store.settle(
        "d" * 32,
        status="skip",
        reason="quorum_not_met",
        answered=0,
        verdict="lewati",
        aggregate=None,
        voters=[_voter("v1", "timeout", 30.0)],
    )
    assert store.first_real_answer_at() is None


def test_outcomes_join_trades_through_custom_data(store, tmp_path):
    _pending(store, "e" * 32)
    store.settle("e" * 32, status="ok", reason=None, answered=7, verdict="lewati", aggregate=None, voters=[])
    _pending(store, "f" * 32, pair="ETH/IDR")
    store.settle("f" * 32, status="ok", reason=None, answered=7, verdict="izinkan", aggregate=None, voters=[])
    trades_db = tmp_path / "trades.sqlite"
    with sqlite3.connect(trades_db) as db:
        db.executescript(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, is_open BOOLEAN, close_profit_abs REAL, close_profit REAL);"
            "CREATE TABLE trade_custom_data (id INTEGER PRIMARY KEY, ft_trade_id INTEGER, cd_key TEXT, cd_value TEXT);"
        )
        db.execute("INSERT INTO trades VALUES (7, 0, -10000.0, -0.032)")
        db.execute("INSERT INTO trade_custom_data VALUES (1, 7, ?, ?)", (SHADOW_KEY, "e" * 32))
    skipped, allowed = store.outcomes(trades_db)
    assert (skipped.verdict, skipped.trade_id, skipped.profit_abs, skipped.is_open) == ("lewati", 7, -10000.0, False)
    assert (allowed.trade_id, allowed.profit_abs) == (None, None)


def test_recent_sorts_with_an_index_instead_of_a_temp_btree(store):
    seen: list[str] = []
    store._db.set_trace_callback(seen.append)
    try:
        store.recent(20, before=datetime(2026, 10, 26, tzinfo=UTC))
    finally:
        store._db.set_trace_callback(None)
    sql = next(statement for statement in seen if statement.lstrip().upper().startswith("SELECT"))
    plan = " ".join(row["detail"] for row in store._db.execute("EXPLAIN QUERY PLAN " + sql))
    assert "TEMP B-TREE" not in plan
    assert "decisions_candle_seq" in plan
