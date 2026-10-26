import json
from datetime import date

import pytest

from tb_swarm.agents import MAX_TOOL_CHARS, read_only_tools
from tb_swarm.snapshot import write_snapshot
from tb_swarm.synthetic import synthetic_decisions, synthetic_trades

END = date(2026, 10, 26)
TARGET = "2026-10-25"
DAYS = 14


def build(tmp_path, skip_rate, days=DAYS):
    decisions = synthetic_decisions(END, days, skip_rate)
    write_snapshot(tmp_path, metrics={"origin": "synthetic"}, trades=synthetic_trades(END, days), decisions=decisions)
    return {t.name: t for t in read_only_tools(tmp_path)}, decisions


def newest_id(decisions, day):
    return [row["decision_id"] for row in decisions if row["decision_id"].startswith(f"dec_{day[5:7]}{day[8:10]}")][-1]


def lines(text):
    return text.splitlines()


@pytest.mark.parametrize("limit", [20, 72, 500])
def test_voter_log_for_a_busy_day_keeps_the_newest_rows_and_says_what_is_missing(tmp_path, limit):
    tools, decisions = build(tmp_path, 0.1)
    out = tools["get_voter_log"].invoke({"day": TARGET, "limit": limit})
    rows = lines(out)
    assert len(out) <= MAX_TOOL_CHARS
    assert rows[0].startswith("[showing the newest ") and " of 72 matching rows" in rows[0]
    assert json.loads(rows[-1])["decision_id"] == newest_id(decisions, TARGET)
    ids = [json.loads(row)["decision_id"] for row in rows[1:]]
    assert ids == sorted(ids) and len(ids) == int(rows[0].split()[3])


def test_a_day_that_fits_the_budget_carries_no_missing_rows_note(tmp_path):
    tools, decisions = build(tmp_path, 0.0)
    out = tools["get_voter_log"].invoke({"day": TARGET, "pair": "BTC/IDR", "limit": 3})
    assert out.startswith("[showing the newest 3 of 24 ")
    one = tools["get_voter_log"].invoke({"decision_id": newest_id(decisions, TARGET)})
    assert not one.startswith("[showing") and len(lines(one)) == 1


@pytest.mark.parametrize("skip_rate", [0.0, 0.05, 0.1, 0.2, 0.5])
def test_metrics_always_carry_the_newest_days_and_name_the_omitted_ones(tmp_path, skip_rate):
    tools, _ = build(tmp_path, skip_rate)
    data = json.loads(tools["get_metrics"].invoke({}))
    shown = list(data["swarm_by_day"])
    assert shown[0] == "2026-10-26" and "2026-10-25" in shown
    assert shown == sorted(shown, reverse=True)
    omitted = data.get("swarm_by_day_omitted_days", [])
    assert sorted(shown + omitted) == sorted(f"2026-10-{n}" for n in range(13, 27))
    assert (not omitted) or "day=" in data["note"]


@pytest.mark.parametrize("skip_rate", [0.1, 0.2, 0.5])
def test_metrics_day_returns_that_day_even_when_the_full_view_would_drop_it(tmp_path, skip_rate):
    tools, _ = build(tmp_path, skip_rate)
    full = json.loads(tools["get_metrics"].invoke({}))
    oldest = "2026-10-13"
    assert oldest in full.get("swarm_by_day_omitted_days", []) or skip_rate == 0.1
    one = json.loads(tools["get_metrics"].invoke({"day": oldest}))
    assert list(one["swarm_by_day"]) == [oldest] and one["swarm_by_day"][oldest]["decisions"] == 72
    assert json.loads(tools["get_metrics"].invoke({"name": "swarm_by_day", "day": TARGET}))["swarm_by_day"][TARGET]


def test_metrics_day_without_data_lists_the_available_days(tmp_path):
    tools, _ = build(tmp_path, 0.1, days=3)
    data = json.loads(tools["get_metrics"].invoke({"day": "2020-01-01"}))
    assert data["swarm_by_day"] == {} and "2026-10-26" in data["note"]
    assert tools["get_metrics"].invoke({"day": "x"}) == "day must be YYYY-MM-DD"


def test_trade_history_over_many_days_keeps_the_newest_and_notes_the_cut(tmp_path):
    tools, _ = build(tmp_path, 0.0)
    out = lines(tools["get_trade_history"].invoke({"limit": 3}))
    assert out[0].startswith("[showing the newest 3 of ")
    last = json.loads(out[-1])
    assert last["ts_local"].startswith("2026-10-26") or last["ts_local"].startswith("2026-10-25")
