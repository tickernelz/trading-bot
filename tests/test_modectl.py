from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from engine import modectl
from engine.modectl import Confirmation, ModeController, ModeRefused, read_mode

KEY = "ix-key-0123456789"
SECRET = "ix-secret-0123456789"
ENV = {"INDODAX_API_KEY": KEY, "INDODAX_API_SECRET": SECRET}
OWNER = "owner@127.0.0.1"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


def controller(tmp_path, clock, environ=None, proven=True):
    return ModeController(
        tmp_path / "mode.json", environ=ENV if environ is None else environ, live_engine_proven=proven, clock=clock
    )


def refusal(call):
    with pytest.raises(ModeRefused) as caught:
        call()
    return caught.value


def test_default_state_is_dry_run_and_names_what_blocks_live(tmp_path, clock):
    status = controller(tmp_path, clock, environ={}, proven=False).status()
    assert status["mode"] == "dry_run" and status["live_allowed"] is False
    assert [item["code"] for item in status["blockers"]] == ["exchange_key_missing", "live_engine_unproven"]
    assert "INDODAX_API_KEY" in status["blockers"][0]["message"]


def test_shipped_default_never_allows_live_even_with_exchange_keys(tmp_path, clock):
    shipped = ModeController(tmp_path / "mode.json", environ=ENV, clock=clock)
    assert modectl.LIVE_ENGINE_PROVEN is False
    error = refusal(lambda: shipped.request("live", OWNER))
    assert error.code == "live_blocked" and [b["code"] for b in error.blockers] == ["live_engine_unproven"]
    assert not (tmp_path / "mode.json").exists()


def test_live_without_exchange_key_is_refused_with_a_clear_reason(tmp_path, clock):
    error = refusal(lambda: controller(tmp_path, clock, environ={}).request("live", OWNER))
    assert error.code == "live_blocked" and error.blockers[0]["code"] == "exchange_key_missing"
    assert "INDODAX_API_KEY" in error.message and "INDODAX_API_SECRET" in error.message
    assert not (tmp_path / "mode.json").exists()


@pytest.mark.parametrize(
    "environ",
    [{"INDODAX_API_KEY": KEY}, {"INDODAX_API_SECRET": SECRET}, {"INDODAX_API_KEY": KEY, "INDODAX_API_SECRET": "  "}],
)
def test_a_partial_or_blank_exchange_key_counts_as_missing(tmp_path, clock, environ):
    error = refusal(lambda: controller(tmp_path, clock, environ=environ).request("live", OWNER))
    assert error.blockers[0]["code"] == "exchange_key_missing"


def test_live_needs_two_steps_and_the_first_changes_nothing(tmp_path, clock):
    ctl = controller(tmp_path, clock)
    step_one = ctl.request("live", OWNER)
    assert isinstance(step_one, Confirmation) and step_one.id.startswith("cf_")
    assert step_one.action == "mode.live" and step_one.targets == ("live",)
    assert step_one.expires_at == clock.now + timedelta(seconds=60)
    assert ctl.status()["mode"] == "dry_run" and not (tmp_path / "mode.json").exists()
    done = ctl.confirm(step_one.id, OWNER)
    assert done["mode"] == "live" and read_mode(tmp_path / "mode.json") == ("live", None)
    saved = json.loads((tmp_path / "mode.json").read_text())
    assert saved["actor"] == OWNER and saved["mode"] == "live"


def test_confirmation_is_single_use(tmp_path, clock):
    ctl = controller(tmp_path, clock)
    confirmation = ctl.request("live", OWNER)
    ctl.confirm(confirmation.id, OWNER)
    ctl.request("dry_run", OWNER)
    assert refusal(lambda: ctl.confirm(confirmation.id, OWNER)).code == "confirmation_invalid"
    assert ctl.status()["mode"] == "dry_run"


def test_unknown_and_foreign_confirmations_change_nothing(tmp_path, clock):
    ctl = controller(tmp_path, clock)
    confirmation = ctl.request("live", OWNER)
    assert refusal(lambda: ctl.confirm("cf_unknown", OWNER)).code == "confirmation_invalid"
    assert refusal(lambda: ctl.confirm(confirmation.id, "someone-else")).code == "confirmation_invalid"
    assert ctl.status()["mode"] == "dry_run"
    assert ctl.confirm(confirmation.id, OWNER)["mode"] == "live"


def test_expired_confirmation_is_refused_and_burned(tmp_path, clock):
    ctl = controller(tmp_path, clock)
    confirmation = ctl.request("live", OWNER)
    clock.advance(60)
    assert refusal(lambda: ctl.confirm(confirmation.id, OWNER)).code == "confirmation_expired"
    assert ctl.status()["mode"] == "dry_run"
    assert refusal(lambda: ctl.confirm(confirmation.id, OWNER)).code == "confirmation_invalid"


def test_confirm_checks_the_preconditions_again(tmp_path, clock):
    environ = dict(ENV)
    ctl = controller(tmp_path, clock, environ=environ)
    confirmation = ctl.request("live", OWNER)
    del environ["INDODAX_API_SECRET"]
    error = refusal(lambda: ctl.confirm(confirmation.id, OWNER))
    assert error.code == "live_blocked" and error.blockers[0]["code"] == "exchange_key_missing"
    assert ctl.status()["mode"] == "dry_run" and not (tmp_path / "mode.json").exists()


def test_leaving_live_takes_one_step_and_repeating_a_mode_is_a_no_op(tmp_path, clock):
    ctl = controller(tmp_path, clock)
    assert ctl.request("dry_run", OWNER)["mode"] == "dry_run" and not (tmp_path / "mode.json").exists()
    ctl.confirm(ctl.request("live", OWNER).id, OWNER)
    assert ctl.request("live", OWNER)["mode"] == "live"
    assert ctl.request("dry_run", OWNER)["mode"] == "dry_run"
    assert read_mode(tmp_path / "mode.json")[0] == "dry_run"


@pytest.mark.parametrize("target", ["", "paper", "LIVE", "live ", None])
def test_unknown_target_is_invalid(tmp_path, clock, target):
    assert refusal(lambda: controller(tmp_path, clock).request(target, OWNER)).code == "invalid_request"


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("{not json", "unreadable"),
        ('{"mode": "paper"}', "'paper'"),
        ("[]", "unreadable"),
        ('{"nomode": 1}', "unreadable"),
    ],
)
def test_unreadable_or_unknown_state_reads_as_dry_run(tmp_path, clock, content, fragment):
    (tmp_path / "mode.json").write_text(content)
    mode, problem = read_mode(tmp_path / "mode.json")
    assert mode == "dry_run" and fragment in problem
    assert controller(tmp_path, clock).status()["state_problem"] == problem


def test_status_never_carries_credential_values(tmp_path, clock):
    ctl = controller(tmp_path, clock)
    confirmation = ctl.request("live", OWNER)
    ctl.confirm(confirmation.id, OWNER)
    dump = json.dumps(ctl.status()) + (tmp_path / "mode.json").read_text()
    assert KEY not in dump and SECRET not in dump
    fresh = ModeController(
        tmp_path / "fresh.json", environ={"INDODAX_API_KEY": KEY}, live_engine_proven=False, clock=clock
    )
    leaked = refusal(lambda: fresh.request("live", OWNER))
    assert KEY not in leaked.message and KEY not in json.dumps(leaked.blockers)


def test_failed_write_leaves_the_old_mode_in_place(tmp_path, clock, monkeypatch):
    ctl = controller(tmp_path, clock)
    ctl.confirm(ctl.request("live", OWNER).id, OWNER)
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            ctl.request("dry_run", OWNER)
    assert read_mode(tmp_path / "mode.json")[0] == "live"
    assert [p.name for p in tmp_path.iterdir()] == ["mode.json"]
