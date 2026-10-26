from __future__ import annotations

import copy
import sqlite3
from dataclasses import replace

import pytest
import yaml
from tb_swarm.outcome import settle

from analytics.errors import AnalyticsError
from analytics.replay import replay_decision, verdict_of, whatif_replay
from analytics.scoreboard import apply_disables, plan_disables, scoreboard
from analytics.source import RecordedDecision, load_decisions
from engine.settings import ConfigError, Settings, load_settings
from tests.analytics_support import record, request, write_decisions, write_trades

WEIGHTS = {f"v{index}": 1.0 for index in range(1, 6)}


def recorded(
    decision_id: str,
    voters,
    required: int = 5,
    max_spread: float | None = None,
    profit: float | None = None,
    is_open: bool | None = False,
) -> RecordedDecision:
    outcome = settle(request(), decision_id, voters, WEIGHTS, required, max_spread)
    return RecordedDecision(
        decision_id=decision_id,
        settled_at="2026-10-26T01:00:00Z",
        pair="BTC/IDR",
        status=outcome.status,
        reason=outcome.reason,
        verdict=verdict_of(outcome),
        required=required,
        iqr_limit=max_spread,
        request=request(),
        voters=tuple(voters),
        profit_abs=profit,
        is_open=None if profit is None else is_open,
    )


def split_vote(timeouts: int = 0):
    voters = [record("v1"), record("v2"), record("v3"), record("v4", "lewati"), record("v5", "lewati")]
    for index in range(timeouts):
        voters[-1 - index] = record(voters[-1 - index].voter_id, None, status="timeout")
    return voters


def unanimous():
    return [record(f"v{index}") for index in range(1, 6)]


class TestReplay:
    def test_unchanged_parameters_reproduce_every_recorded_verdict(self):
        decisions = (
            recorded("a", unanimous()),
            recorded("b", split_vote()),
            recorded("c", split_vote(timeouts=2)),
        )
        result = whatif_replay(decisions, WEIGHTS, 5, None)
        assert result["changed_total"] == 0
        assert result["recorded_verdicts"] == result["replayed_verdicts"]

    def test_a_lower_quorum_lets_a_decision_that_missed_quorum_through(self):
        decision = recorded("q", split_vote(timeouts=2))
        assert decision.verdict == "lewati" and decision.reason == "quorum_not_met"
        result = whatif_replay((decision,), WEIGHTS, 3, None)
        assert result["transitions"] == {"lewati->izinkan": 1}
        assert result["changed"][0]["replayed"]["status"] == "ok"

    def test_a_tighter_spread_limit_turns_a_split_vote_into_a_skip(self):
        decision = recorded("s", split_vote())
        assert decision.verdict == "izinkan"
        result = whatif_replay((decision,), WEIGHTS, 5, 0.1)
        assert result["transitions"] == {"izinkan->lewati": 1}
        assert result["changed"][0]["replayed"]["reason"].startswith("spread_exceeded")

    def test_a_unanimous_vote_passes_the_same_tight_spread_limit(self):
        assert whatif_replay((recorded("u", unanimous()),), WEIGHTS, 5, 0.1)["changed_total"] == 0

    def test_excluding_the_dissenting_voters_with_a_lower_quorum_restores_a_clean_take(self):
        decision = recorded("e", split_vote(), max_spread=0.1)
        assert decision.reason and decision.reason.startswith("spread_exceeded")
        outcome = replay_decision(decision, WEIGHTS, 3, 0.1, frozenset({"v4", "v5"}))
        assert outcome.proceed and verdict_of(outcome) == "izinkan"

    def test_decisions_without_voter_records_are_not_replayed(self):
        interrupted = recorded("i", [])
        result = whatif_replay((interrupted, recorded("a", unanimous())), WEIGHTS, 5, None)
        assert result["not_replayable"] == 1
        assert result["replayed"] == 1

    def test_trade_groups_sum_closed_profit_by_recorded_and_replayed_side_without_a_verdict_on_it(self):
        decisions = (
            recorded("keep", unanimous(), profit=500.0),
            recorded("cut", split_vote(), profit=-300.0),
            recorded("open", split_vote(), profit=999.0, is_open=True),
        )
        result = whatif_replay(decisions, WEIGHTS, 5, 0.1)
        assert result["trade_groups"]["take->take"] == {"trades": 1, "profit_abs_idr": 500.0}
        assert result["trade_groups"]["take->skip"] == {"trades": 1, "profit_abs_idr": -300.0}
        assert "bukan kesimpulan" in result["note"]

    def test_a_voter_missing_from_the_current_config_is_reported_and_weighted_one(self):
        decision = recorded("w", unanimous())
        result = whatif_replay((decision,), {"v1": 1.0}, 5, None)
        assert result["unknown_voters"] == ["v2", "v3", "v4", "v5"]
        assert result["changed_total"] == 0


class TestSource:
    def test_decisions_are_loaded_oldest_first_with_trade_outcomes_joined(self, tmp_path):
        write_decisions(
            tmp_path / "d.sqlite",
            [
                {"decision_id": "d1", "voters": unanimous()},
                {"decision_id": "d2", "voters": split_vote()},
                {"decision_id": "d3", "voters": unanimous()},
            ],
        )
        write_trades(tmp_path / "t.sqlite", {"d1": (250.0, False), "d2": (None, True)})
        loaded = load_decisions(tmp_path / "d.sqlite", tmp_path / "t.sqlite")
        assert [decision.decision_id for decision in loaded.decisions] == ["d1", "d2", "d3"]
        assert loaded.decisions[0].closed_profit == 250.0
        assert loaded.decisions[1].closed_profit is None and loaded.decisions[1].is_open is True
        assert loaded.decisions[2].profit_abs is None
        assert loaded.invalid == 0

    def test_a_row_that_does_not_parse_is_counted_and_the_rest_still_load(self, tmp_path):
        write_decisions(
            tmp_path / "d.sqlite",
            [
                {"decision_id": "ok", "voters": unanimous()},
                {"decision_id": "bad", "voters": unanimous(), "request": "{}"},
            ],
        )
        loaded = load_decisions(tmp_path / "d.sqlite")
        assert [decision.decision_id for decision in loaded.decisions] == ["ok"]
        assert loaded.invalid == 1

    def test_limit_keeps_the_newest_decisions(self, tmp_path):
        write_decisions(
            tmp_path / "d.sqlite", [{"decision_id": f"d{index}", "voters": unanimous()} for index in range(5)]
        )
        loaded = load_decisions(tmp_path / "d.sqlite", limit=2)
        assert [decision.decision_id for decision in loaded.decisions] == ["d3", "d4"]

    def test_missing_databases_raise_not_found(self, tmp_path):
        with pytest.raises(AnalyticsError) as error:
            load_decisions(tmp_path / "absent.sqlite")
        assert error.value.status == 404

    def test_the_store_is_opened_read_only(self, tmp_path):
        from analytics.source import connect

        write_decisions(tmp_path / "d.sqlite", [{"decision_id": "d1", "voters": unanimous()}])
        db = connect(tmp_path / "d.sqlite")
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM decisions")
        db.close()


def scored(profits_and_takes, voter="x", closed=True):
    decisions = []
    for index, (profit, take) in enumerate(profits_and_takes):
        choice = "izinkan" if take >= 0.5 else "lewati"
        decisions.append(
            RecordedDecision(
                decision_id=f"{voter}{index}",
                settled_at="2026-10-26T01:00:00Z",
                pair="BTC/IDR",
                status="ok",
                reason=None,
                verdict=choice,
                required=1,
                iqr_limit=None,
                request=request(),
                voters=(record(voter, choice, take=take),),
                profit_abs=profit,
                is_open=not closed,
            )
        )
    return tuple(decisions)


@pytest.fixture
def settings(example_raw) -> Settings:
    return Settings.model_validate(example_raw)


class TestScoreboard:
    def test_a_voter_that_follows_the_outcomes_is_ok_and_one_that_inverts_them_is_drifting(self, settings):
        outcomes = [(100.0 if index % 2 == 0 else -100.0) for index in range(40)]
        sharp = scored([(profit, 0.9 if profit > 0 else 0.1) for profit in outcomes], voter="sharp")
        inverted = scored([(profit, 0.1 if profit > 0 else 0.9) for profit in outcomes], voter="inverted")
        board = scoreboard(sharp + inverted, settings.analytics.scoreboard)
        rows = {row["voter_id"]: row for row in board["voters"]}
        assert rows["sharp"]["status"] == "ok"
        assert rows["sharp"]["accuracy"] == 1.0
        assert rows["sharp"]["brier"] == pytest.approx(0.01)
        assert rows["inverted"]["status"] == "drifting"
        assert rows["inverted"]["accuracy"] == 0.0
        assert rows["inverted"]["ece"] > 0.25
        assert len(rows["inverted"]["reasons"]) == 2

    def test_too_few_closed_trades_never_marks_a_voter_as_drifting(self, settings):
        board = scoreboard(scored([(-100.0, 0.9)] * 10), settings.analytics.scoreboard)
        row = board["voters"][0]
        assert row["samples"] == 10
        assert row["status"] == "insufficient"
        assert row["accuracy"] == 0.0

    def test_open_trades_and_decisions_without_trades_are_not_scored(self, settings):
        open_only = scored([(-100.0, 0.9)] * 40, closed=False)
        no_trade = scored([(None, 0.9)] * 40)
        board = scoreboard(open_only + no_trade, settings.analytics.scoreboard)
        assert board["with_outcome"] == 0
        assert board["voters"][0]["samples"] == 0
        assert board["voters"][0]["calls"] == 80

    def test_failed_voter_calls_lower_the_answer_rate_without_adding_samples(self, settings):
        decision = scored([(100.0, 0.9)])[0]
        failed = replace(decision, decision_id="f", voters=(record("x", None, status="timeout"),))
        row = scoreboard((decision, failed), settings.analytics.scoreboard)["voters"][0]
        assert row["calls"] == 2 and row["answered"] == 1 and row["samples"] == 1
        assert row["answer_rate"] == 0.5

    def test_calibration_bins_hold_every_sample_exactly_once(self, settings):
        samples = [(100.0 if index % 3 else -100.0, index / 39) for index in range(40)]
        row = scoreboard(scored(samples), settings.analytics.scoreboard)["voters"][0]
        assert sum(item["n"] for item in row["bins"]) == 40


def drifting_row(voter_id, excess):
    return {"voter_id": voter_id, "status": "drifting", "brier": 0.25 + excess, "brier_baseline": 0.25}


class TestAutoDisable:
    def board(self, settings, count):
        ids = [voter.id for voter in settings.swarm.voters if voter.enabled][:count]
        return {"voters": [drifting_row(voter_id, 0.1 * (index + 1)) for index, voter_id in enumerate(ids)]}

    def test_the_plan_never_drops_below_the_quorum_and_retires_the_worst_first(self, settings):
        enabled = sum(1 for voter in settings.swarm.voters if voter.enabled)
        spare = enabled - settings.swarm.min_voters_answered
        plan = plan_disables(self.board(settings, enabled), settings)
        assert len(plan["disable"]) == spare
        assert len(plan["kept_for_quorum"]) == enabled - spare
        worst = [row["voter_id"] for row in sorted(self.board(settings, enabled)["voters"], key=lambda r: -r["brier"])]
        assert plan["disable"] == worst[:spare]

    def test_auto_disable_off_recommends_but_disables_nothing(self, example_raw):
        raw = copy.deepcopy(example_raw)
        raw["analytics"] = {"scoreboard": {"auto_disable": False}}
        settings = Settings.model_validate(raw)
        plan = plan_disables(self.board(settings, 3), settings)
        assert plan["disable"] == []
        assert len(plan["recommended"]) > 0

    def test_a_voter_that_is_already_disabled_is_not_planned_again(self, example_raw):
        raw = copy.deepcopy(example_raw)
        raw["swarm"]["voters"][0]["enabled"] = False
        raw["swarm"]["min_voters_answered"] = 1
        settings = Settings.model_validate(raw)
        board = {"voters": [drifting_row(raw["swarm"]["voters"][0]["id"], 0.5)]}
        assert plan_disables(board, settings)["disable"] == []

    def test_apply_writes_enabled_false_and_the_file_still_loads(self, tmp_path, example_raw):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(example_raw, sort_keys=False), encoding="utf-8")
        target = example_raw["swarm"]["voters"][-1]["id"]
        assert apply_disables(path, [target]) == [target]
        reloaded = load_settings(path)
        assert {voter.id: voter.enabled for voter in reloaded.swarm.voters}[target] is False

    def test_apply_refuses_to_drop_below_quorum_and_leaves_the_file_untouched(self, tmp_path, example_raw):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(example_raw, sort_keys=False), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        every = [voter["id"] for voter in example_raw["swarm"]["voters"]]
        with pytest.raises(ConfigError):
            apply_disables(path, every)
        assert path.read_text(encoding="utf-8") == before
        assert not list(tmp_path.glob("*.tmp"))

    def test_apply_with_nothing_to_change_does_not_rewrite(self, tmp_path, example_raw):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(example_raw, sort_keys=False), encoding="utf-8")
        stamp = path.stat().st_mtime_ns
        assert apply_disables(path, ["no-such-voter"]) == []
        assert apply_disables(path, []) == []
        assert path.stat().st_mtime_ns == stamp
