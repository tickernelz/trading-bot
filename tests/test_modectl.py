from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest

from engine import modectl
from engine.modectl import (
    ModeController,
    ModeRefused,
    read_exchange_key_configured,
    read_mode,
    write_capabilities,
)

KEY = "ix-key-0123456789"
SECRET = "ix-secret-0123456789"
ENV = {"INDODAX_API_KEY": KEY, "INDODAX_API_SECRET": SECRET}
OWNER = "owner"


def clock():
    return datetime(2026, 10, 26, 3, 0, tzinfo=UTC)


def has_keys(environ):
    return lambda: all((environ.get(name) or "").strip() for name in modectl.DEFAULT_KEY_ENVS)


def controller(tmp_path, environ=None, proven=True):
    environ = ENV if environ is None else environ
    return ModeController(
        tmp_path / "mode.json", exchange_key_configured=has_keys(environ), live_engine_proven=proven, clock=clock
    )


def refusal(call):
    with pytest.raises(ModeRefused) as caught:
        call()
    return caught.value


def test_default_state_is_dry_run_and_names_what_blocks_live(tmp_path):
    status = controller(tmp_path, environ={}, proven=False).status()
    assert status["mode"] == "dry_run" and status["live_allowed"] is False
    assert [item["code"] for item in status["blockers"]] == ["exchange_key_missing", "live_engine_unproven"]
    assert "INDODAX_API_KEY" in status["blockers"][0]["message"]


def test_shipped_default_never_allows_live_even_with_exchange_keys(tmp_path):
    shipped = ModeController(tmp_path / "mode.json", exchange_key_configured=has_keys(ENV), clock=clock)
    assert modectl.LIVE_ENGINE_PROVEN is False
    error = refusal(lambda: shipped.apply("live", OWNER))
    assert error.code == "live_blocked" and [b["code"] for b in error.blockers] == ["live_engine_unproven"]
    assert not (tmp_path / "mode.json").exists()


def test_live_without_exchange_key_is_refused_with_a_clear_reason(tmp_path):
    error = refusal(lambda: controller(tmp_path, environ={}).apply("live", OWNER))
    assert error.code == "live_blocked" and error.blockers[0]["code"] == "exchange_key_missing"
    assert "INDODAX_API_KEY" in error.message and "INDODAX_API_SECRET" in error.message
    assert not (tmp_path / "mode.json").exists()


@pytest.mark.parametrize(
    "environ",
    [{"INDODAX_API_KEY": KEY}, {"INDODAX_API_SECRET": SECRET}, {"INDODAX_API_KEY": KEY, "INDODAX_API_SECRET": "  "}],
)
def test_a_partial_or_blank_exchange_key_counts_as_missing(tmp_path, environ):
    error = refusal(lambda: controller(tmp_path, environ=environ).apply("live", OWNER))
    assert error.blockers[0]["code"] == "exchange_key_missing"


def test_apply_checks_the_preconditions_itself_so_no_caller_can_skip_them(tmp_path):
    environ = dict(ENV)
    ctl = controller(tmp_path, environ=environ)
    ctl.ensure_live_allowed()
    del environ["INDODAX_API_SECRET"]
    error = refusal(lambda: ctl.apply("live", OWNER))
    assert error.code == "live_blocked" and error.blockers[0]["code"] == "exchange_key_missing"
    assert ctl.status()["mode"] == "dry_run" and not (tmp_path / "mode.json").exists()


def test_apply_records_mode_actor_and_time_and_repeating_a_mode_is_a_no_op(tmp_path):
    ctl = controller(tmp_path)
    assert ctl.apply("dry_run", OWNER)["mode"] == "dry_run" and not (tmp_path / "mode.json").exists()
    done = ctl.apply("live", OWNER)
    assert done["mode"] == "live" and done["changed_at"] == "2026-10-26T03:00:00Z"
    assert json.loads((tmp_path / "mode.json").read_text()) == {
        "mode": "live",
        "changed_at": "2026-10-26T03:00:00Z",
        "actor": OWNER,
    }
    assert ctl.apply("live", "someone-else")["mode"] == "live"
    assert json.loads((tmp_path / "mode.json").read_text())["actor"] == OWNER
    assert ctl.apply("dry_run", OWNER)["mode"] == "dry_run"
    assert read_mode(tmp_path / "mode.json")[0] == "dry_run"


@pytest.mark.parametrize("target", ["", "paper", "LIVE", "live ", None])
def test_unknown_target_is_invalid(tmp_path, target):
    assert refusal(lambda: controller(tmp_path).apply(target, OWNER)).code == "invalid_request"


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("{not json", "unreadable"),
        ('{"mode": "paper"}', "'paper'"),
        ("[]", "unreadable"),
        ('{"nomode": 1}', "unreadable"),
    ],
)
def test_unreadable_or_unknown_state_reads_as_dry_run(tmp_path, content, fragment):
    (tmp_path / "mode.json").write_text(content)
    mode, problem = read_mode(tmp_path / "mode.json")
    assert mode == "dry_run" and fragment in problem
    assert controller(tmp_path).status()["state_problem"] == problem


def test_status_never_carries_credential_values(tmp_path):
    ctl = controller(tmp_path)
    ctl.apply("live", OWNER)
    dump = json.dumps(ctl.status()) + (tmp_path / "mode.json").read_text()
    assert KEY not in dump and SECRET not in dump
    fresh = ModeController(
        tmp_path / "fresh.json",
        exchange_key_configured=has_keys({"INDODAX_API_KEY": KEY}),
        live_engine_proven=False,
        clock=clock,
    )
    leaked = refusal(lambda: fresh.apply("live", OWNER))
    assert KEY not in leaked.message and KEY not in json.dumps(leaked.blockers)


def test_failed_write_leaves_the_old_mode_in_place(tmp_path, monkeypatch):
    ctl = controller(tmp_path)
    ctl.apply("live", OWNER)
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            ctl.apply("dry_run", OWNER)
    assert read_mode(tmp_path / "mode.json")[0] == "live"
    assert [p.name for p in tmp_path.iterdir()] == ["mode.json"]


def test_capabilities_file_records_only_whether_the_keys_are_set(tmp_path):
    write_capabilities(tmp_path, ENV, clock=clock)
    text = (tmp_path / "capabilities.json").read_text()
    assert read_exchange_key_configured(tmp_path) is True
    assert KEY not in text and SECRET not in text
    write_capabilities(tmp_path, {"INDODAX_API_KEY": KEY}, clock=clock)
    assert read_exchange_key_configured(tmp_path) is False


@pytest.mark.parametrize(
    "content", [None, "{broken", "[]", '{"exchange_key_configured": "yes"}', '{"exchange_key_configured": 1}']
)
def test_a_missing_or_malformed_capabilities_file_reads_as_no_keys(tmp_path, content):
    if content is not None:
        (tmp_path / "capabilities.json").write_text(content)
    assert read_exchange_key_configured(tmp_path) is False


def test_the_probe_is_asked_again_at_every_check(tmp_path):
    state = {"keys": True}
    ctl = ModeController(
        tmp_path / "mode.json", exchange_key_configured=lambda: state["keys"], live_engine_proven=True, clock=clock
    )
    assert ctl.status()["live_allowed"] is True
    state["keys"] = False
    assert ctl.status()["live_allowed"] is False
