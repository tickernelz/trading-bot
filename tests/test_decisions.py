from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
        "answers": {"verdict": {"type": "choice", "choice": "allow"}} if status == "ok" else None,
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
        verdict="skip",
        aggregate=None,
        voters=[_voter("v1", "ok", 2.0), _voter("v2", "timeout", 30.0)],
    )
    [decision] = store.recent(10)
    assert decision["verdict"] == "skip"
    assert decision["status"] == "skip"
    assert decision["usage"]["input_tokens"] == 200
    assert "request" not in decision
    assert all("error" not in voter and "usage" not in voter for voter in decision["voters"])
    assert decision["voters"][1]["error_kind"] == "timeout"


def test_settled_after_returns_new_decisions_in_order(store):
    for index, decision_id in enumerate(("1" * 32, "2" * 32)):
        _pending(store, decision_id)
        store.settle(decision_id, status="ok", reason=None, answered=5, verdict="allow", aggregate=None, voters=[])
        assert store.last_settle_seq() == index + 1
    assert [row[1]["decision_id"] for row in store.settled_after(1)] == ["2" * 32]


def test_restart_interrupts_pending_decisions_once(store):
    _pending(store, "b" * 32)
    assert store.interrupt_pending("shadow_restart") == 1
    assert store.interrupt_pending("shadow_restart") == 0
    [decision] = store.recent(1)
    assert decision["reason"] == "shadow_restart"
    store.settle("b" * 32, status="ok", reason=None, answered=7, verdict="allow", aggregate=None, voters=[])
    assert store.recent(1)[0]["status"] == "skip"


def test_usage_and_provider_health_count_every_voter_call(store):
    _pending(store, "c" * 32)
    store.settle(
        "c" * 32,
        status="ok",
        reason=None,
        answered=2,
        verdict="allow",
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
        verdict="skip",
        aggregate=None,
        voters=[_voter("v1", "timeout", 30.0)],
    )
    assert store.first_real_answer_at() is None


def test_outcomes_join_trades_through_custom_data(store, tmp_path):
    _pending(store, "e" * 32)
    store.settle("e" * 32, status="ok", reason=None, answered=7, verdict="skip", aggregate=None, voters=[])
    _pending(store, "f" * 32, pair="ETH/IDR")
    store.settle("f" * 32, status="ok", reason=None, answered=7, verdict="allow", aggregate=None, voters=[])
    trades_db = tmp_path / "trades.sqlite"
    with sqlite3.connect(trades_db) as db:
        db.executescript(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, is_open BOOLEAN, close_profit_abs REAL, close_profit REAL);"
            "CREATE TABLE trade_custom_data (id INTEGER PRIMARY KEY, ft_trade_id INTEGER, cd_key TEXT, cd_value TEXT);"
        )
        db.execute("INSERT INTO trades VALUES (7, 0, -10000.0, -0.032)")
        db.execute("INSERT INTO trade_custom_data VALUES (1, 7, ?, ?)", (SHADOW_KEY, "e" * 32))
    skipped, allowed = store.outcomes(trades_db)
    assert (skipped.verdict, skipped.trade_id, skipped.profit_abs, skipped.is_open) == ("skip", 7, -10000.0, False)
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


LEGACY_NAMES = {"allow": "izinkan", "reduce": "kecilkan", "skip": "lewati"}
LEGACY_COLUMNS = ("request", "aggregate", "voters")
FIXTURE = Path(__file__).resolve().parent / "data" / "stage2c" / "bot-b.json"


def _legacy(text: str | None) -> str | None:
    if text is None:
        return None
    for new, old in LEGACY_NAMES.items():
        text = text.replace(f'"{new}"', f'"{old}"').replace(f'\\"{new}\\"', f'\\"{old}\\"')
    return text


def _legacy_database(path, rows: list[dict]) -> None:
    DecisionStore(path).close()
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 0")
    columns = list(rows[0])
    db.executemany(
        f"INSERT INTO decisions ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})",
        [
            {
                **row,
                **{name: _legacy(row[name]) for name in LEGACY_COLUMNS},
                "verdict": LEGACY_NAMES.get(row["verdict"]),
            }
            for row in rows
        ],
    )
    db.commit()
    db.close()


def _snapshot(path) -> list[tuple]:
    db = sqlite3.connect(path)
    rows = db.execute(
        "SELECT decision_id, verdict, request, aggregate, voters FROM decisions ORDER BY decision_id"
    ).fetchall()
    version = db.execute("PRAGMA user_version").fetchone()[0]
    db.close()
    return [version, *rows]


def _fixture_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text())["decisions"]


def test_legacy_database_built_from_the_fixture_is_migrated_on_open(tmp_path):
    rows = _fixture_rows()
    path = tmp_path / "legacy.sqlite"
    _legacy_database(path, rows)
    before = _snapshot(path)
    assert before[0] == 0
    assert all("izinkan" in row[2] and row[1] == "lewati" for row in before[1:])
    DecisionStore(path).close()
    after = _snapshot(path)
    assert after[0] == 1
    expected = sorted(rows, key=lambda row: row["decision_id"])
    for row, source in zip(after[1:], expected, strict=True):
        assert row == (
            source["decision_id"],
            source["verdict"],
            source["request"],
            source["aggregate"],
            source["voters"],
        )
    assert not any(name in str(after) for name in LEGACY_NAMES.values())


def test_migration_is_idempotent_and_survives_reopening(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _legacy_database(path, _fixture_rows())
    DecisionStore(path).close()
    once = _snapshot(path)
    DecisionStore(path).close()
    DecisionStore(path, readonly=True).close()
    assert _snapshot(path) == once
    store = DecisionStore(path)
    assert {decision["verdict"] for decision in store.recent(10)} == {"skip"}
    store.close()


def test_every_legacy_verdict_and_pending_row_is_renamed(tmp_path):
    base = _fixture_rows()[0]
    rows = []
    for index, verdict in enumerate(("allow", "reduce", "skip", None)):
        rows.append(
            {
                **base,
                "decision_id": f"{index:032x}",
                "settle_seq": index + 1 if verdict else None,
                "verdict": verdict,
                "status": "ok" if verdict else "pending",
                "aggregate": base["aggregate"] if verdict else None,
                "voters": base["voters"] if verdict else None,
            }
        )
    path = tmp_path / "legacy.sqlite"
    _legacy_database(path, rows)
    store = DecisionStore(path)
    verdicts = [row[0] for row in store._db.execute("SELECT verdict FROM decisions ORDER BY decision_id")]
    assert verdicts == ["allow", "reduce", "skip", None]
    pending = store._db.execute("SELECT request FROM decisions WHERE status = 'pending'").fetchone()[0]
    assert '"allow"' in pending and "izinkan" not in pending
    store.close()


def test_migration_touches_only_whole_json_tokens(tmp_path):
    row = {**_fixture_rows()[0]}
    voters = json.dumps(
        [{"voter_id": "v1", "reasoning": 'said "izinkan" and izinkan', "answers": {"verdict": {"choice": "izinkan"}}}]
    )
    row["voters"] = voters
    path = tmp_path / "legacy.sqlite"
    _legacy_database(path, [row])
    DecisionStore(path).close()
    [migrated] = json.loads(_snapshot(path)[1][4])
    assert migrated["answers"]["verdict"]["choice"] == "allow"
    assert migrated["reasoning"] == 'said "izinkan" and izinkan'


def test_reader_opening_a_legacy_database_migrates_it_once(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _legacy_database(path, _fixture_rows())
    reader = DecisionStore(path, readonly=True)
    assert {decision["verdict"] for decision in reader.recent(10)} == {"skip"}
    reader.close()
    assert _snapshot(path)[0] == 1


def test_new_databases_start_at_the_current_version(tmp_path):
    DecisionStore(tmp_path / "new.sqlite").close()
    assert _snapshot(tmp_path / "new.sqlite") == [1]
