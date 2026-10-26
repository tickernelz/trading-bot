import json
import os

import pytest

from tb_swarm.agents import read_only_tools
from tb_swarm.snapshot import decision_row, swarm_by_day, trade_row, write_snapshot

CLOSED = {
    "trade_id": 7,
    "pair": "BTC/IDR",
    "is_open": False,
    "open_timestamp": 1_792_947_986_000,
    "close_timestamp": 1_792_951_586_000,
    "profit_abs": -1333.5,
    "exit_reason": "stoploss",
    "api_secret": "must-not-travel",
}
OPEN = {"trade_id": 8, "pair": "ETH/IDR", "is_open": True, "open_timestamp": 1_792_955_186_000, "profit_abs": 12.0}
DECISION = {
    "decision_id": "dec_1",
    "ts": "2026-10-25T17:02:05Z",
    "pair": "BTC/IDR",
    "verdict": "lewati",
    "request": {"state": "private market state"},
    "voters": [{"voter_id": "v1", "provider": "p", "status": "timeout", "error_text": "Bearer abcdef0123456789"}],
}


def test_closed_trade_is_stamped_with_its_close_time_and_keeps_only_allowlisted_fields():
    row = trade_row(CLOSED)
    assert row["ts"] == "2026-10-25T18:06:26Z"
    assert "api_secret" not in row and row["exit_reason"] == "stoploss"


def test_open_trade_is_stamped_with_its_open_time():
    assert trade_row(OPEN)["ts"] == "2026-10-25T19:06:26Z"


def test_trade_without_a_timestamp_is_refused():
    with pytest.raises(ValueError):
        trade_row({"trade_id": 9, "pair": "BTC/IDR", "is_open": True})


def test_decision_row_keeps_usage_and_drops_the_request_and_voter_error_text():
    row = decision_row({**DECISION, "usage": {"input_tokens": 12, "cost": None}})
    assert row["usage"] == {"input_tokens": 12, "cost": None}
    assert "request" not in row
    assert row["voters"] == [
        {
            "voter_id": "v1",
            "provider": "p",
            "model": None,
            "status": "timeout",
            "latency_s": None,
            "error_kind": None,
            "answers": None,
        }
    ]


def test_snapshot_is_what_the_analyst_tools_read(tmp_path):
    write_snapshot(tmp_path, metrics={"win_rate": 0.4}, trades=[OPEN, CLOSED], decisions=[DECISION])
    tools = {t.name: t for t in read_only_tools(tmp_path)}
    trades = [json.loads(line) for line in tools["get_trade_history"].invoke({}).splitlines()]
    assert [t["trade_id"] for t in trades] == [7, 8]
    assert [
        t["trade_id"]
        for t in json.loads(
            "["
            + ",".join(tools["get_trade_history"].invoke({"day": "2026-10-26", "pair": "ETH/IDR"}).splitlines())
            + "]"
        )
    ] == [8]
    assert json.loads(tools["get_voter_log"].invoke({"decision_id": "dec_1"}))["verdict"] == "lewati"
    assert json.loads(tools["get_metrics"].invoke({"name": "win_rate"})) == {"win_rate": 0.4}
    assert "Bearer" not in "".join(p.read_text() for p in tmp_path.iterdir())


def test_snapshot_replaces_files_atomically_and_leaves_no_temp_files(tmp_path, monkeypatch):
    write_snapshot(tmp_path, metrics={"v": 1}, trades=[CLOSED], decisions=[])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            write_snapshot(tmp_path, metrics={"v": 2}, trades=[CLOSED, OPEN], decisions=[])
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_swarm_by_day_counts_per_local_day_and_lists_the_skips():
    rows = [
        {
            "decision_id": "a",
            "ts": "2026-10-25T18:30:00Z",
            "pair": "BTC/IDR",
            "status": "skip",
            "reason": "quorum_not_met",
            "answered": 2,
            "required": 5,
            "verdict": "lewati",
            "voters": [{"voter_id": "v1", "status": "timeout"}, {"voter_id": "v2", "status": "ok"}],
        },
        {
            "decision_id": "b",
            "ts": "2026-10-25T16:30:00Z",
            "pair": "BTC/IDR",
            "status": "ok",
            "verdict": "izinkan",
            "voters": [{"voter_id": "v1", "status": "ok"}],
        },
        {
            "decision_id": "c",
            "ts": "2026-10-26T03:00:00Z",
            "pair": "ETH/IDR",
            "status": "ok",
            "verdict": "izinkan",
            "voters": [],
        },
    ]
    days = swarm_by_day(rows, "Asia/Jakarta")
    assert sorted(days) == ["2026-10-25", "2026-10-26"]
    mon = days["2026-10-26"]
    assert (
        mon["decisions"] == 2
        and mon["by_status"] == {"skip": 1, "ok": 1}
        and mon["by_verdict"] == {"lewati": 1, "izinkan": 1}
    )
    assert mon["voters"] == {"v1": {"calls": 1, "not_ok": 1}, "v2": {"calls": 1, "not_ok": 0}}
    assert mon["by_pair"]["BTC/IDR"] == {"decisions": 1, "verdicts": {"lewati": 1}}
    assert mon["skips"] == [
        {
            "decision_id": "a",
            "pair": "BTC/IDR",
            "ts_local": "2026-10-26T01:30:00+07:00",
            "status": "skip",
            "reason": "quorum_not_met",
            "answered": 2,
            "required": 5,
        }
    ]
    assert days["2026-10-25"]["decisions"] == 1 and days["2026-10-25"]["skips"] == []


def test_swarm_by_day_keeps_only_recent_days_and_caps_the_skip_list():
    rows = [
        {
            "decision_id": f"d{n}",
            "ts": f"2026-10-{n:02d}T05:00:00Z",
            "pair": "BTC/IDR",
            "status": "skip",
            "verdict": "lewati",
        }
        for n in range(1, 21)
    ]
    assert len(swarm_by_day(rows)) == 14 and "2026-10-01" not in swarm_by_day(rows)
    many = [
        {"decision_id": f"x{n}", "ts": "2026-10-26T05:00:00Z", "pair": "BTC/IDR", "status": "skip"} for n in range(80)
    ]
    assert len(swarm_by_day(many)["2026-10-26"]["skips"]) == 30


def test_snapshot_metrics_carry_the_daily_totals_next_to_the_given_metrics(tmp_path):
    write_snapshot(tmp_path, metrics={"win_rate": 0.4}, trades=[], decisions=[DECISION])
    saved = json.loads((tmp_path / "metrics.json").read_text())
    assert saved["win_rate"] == 0.4 and saved["swarm_by_day"]["2026-10-26"]["by_verdict"] == {"lewati": 1}
