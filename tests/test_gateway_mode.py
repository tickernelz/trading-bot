from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from engine.modectl import ModeController, read_mode, write_capabilities
from gateway.app import create_app
from tests.test_gateway_analyst import KEY, Rig

LIVE = {"mode": "live"}


@pytest.fixture
def rig(tmp_path):
    made = Rig(tmp_path)
    yield made
    made.gateway.ledger.close()


def proven_controller(rig, keys=True):
    ctl = ModeController(rig.userdir / "mode.json", exchange_key_configured=lambda: keys, live_engine_proven=True)
    rig.gateway.modes.controllers["B"] = ctl
    return ctl


def switch(rig, body, key="k1", headers=None):
    return rig.client.post(
        "/gw/v1/control/mode", json=body, headers={**rig.headers, "Idempotency-Key": key, **(headers or {})}
    )


def audit(rig):
    return [item for item in rig.gateway.ledger.audit_rows(20) if item["action"] == "mode.change"]


def test_fresh_bot_reports_dry_run_and_what_blocks_live(rig):
    status = rig.get("/gw/v1/mode").json()
    assert status["mode"] == "dry_run" and status["live_allowed"] is False
    assert [item["code"] for item in status["blockers"]] == ["exchange_key_missing", "live_engine_unproven"]


def test_live_without_exchange_key_is_refused_with_the_reason_and_changes_nothing(rig):
    response = switch(rig, LIVE)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "live_blocked" and error["blockers"][0]["code"] == "exchange_key_missing"
    assert "INDODAX_API_KEY" in error["message"]
    assert not (rig.userdir / "mode.json").exists()
    [row] = audit(rig)
    assert row["result"] == "refused" and row["idempotency_key"] == "k1" and row["detail"]["code"] == "live_blocked"


def test_shipped_build_refuses_live_even_when_the_engine_recorded_exchange_keys(rig):
    write_capabilities(rig.userdir, {"INDODAX_API_KEY": KEY, "INDODAX_API_SECRET": KEY})
    status = rig.get("/gw/v1/mode").json()
    assert status["exchange_key_configured"] is True and status["live_allowed"] is False
    response = switch(rig, LIVE)
    assert response.status_code == 422
    assert [item["code"] for item in response.json()["error"]["blockers"]] == ["live_engine_unproven"]
    assert read_mode(rig.userdir / "mode.json")[0] == "dry_run"
    assert KEY not in response.text and KEY not in json.dumps(audit(rig))


def test_live_takes_two_steps_and_the_first_changes_nothing(rig):
    proven_controller(rig)
    first = switch(rig, LIVE, key="step-1")
    assert first.status_code == 409
    confirmation = first.json()["error"]["confirmation"]
    assert first.json()["error"]["code"] == "confirmation_required"
    assert confirmation["action"] == "mode.live" and confirmation["targets"] == ["live"]
    assert confirmation["id"].startswith("cf_") and confirmation["expires_at"].endswith("Z")
    assert not (rig.userdir / "mode.json").exists()
    second = switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="step-2")
    assert second.status_code == 200 and second.json()["mode"] == "live"
    assert read_mode(rig.userdir / "mode.json")[0] == "live"
    assert [row["result"] for row in audit(rig)] == ["ok", "confirmation_required"]


def test_repeating_the_confirming_call_replays_the_result_without_a_second_change(rig):
    proven_controller(rig)
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    body = {**LIVE, "confirm": confirmation["id"]}
    first = switch(rig, body, key="same")
    again = switch(rig, body, key="same")
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert len([row for row in audit(rig) if row["result"] == "ok"]) == 1


def test_confirming_with_another_key_after_use_is_refused(rig):
    proven_controller(rig)
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    assert switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="a").status_code == 200
    reuse = switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="b")
    assert reuse.status_code == 409 and reuse.json()["error"]["code"] == "invalid_request"


def test_unknown_confirmation_and_mismatched_mode_change_nothing(rig):
    proven_controller(rig)
    assert switch(rig, {**LIVE, "confirm": "cf_" + "0" * 16}).status_code == 409
    assert switch(rig, {"mode": "dry_run", "confirm": "cf_" + "0" * 16}).status_code == 400
    assert switch(rig, {"mode": "paper"}).status_code == 400
    assert switch(rig, {**LIVE, "confirm": "nope"}).status_code == 400
    assert not (rig.userdir / "mode.json").exists()


def test_leaving_live_is_one_step(rig):
    proven_controller(rig)
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="to-live")
    back = switch(rig, {"mode": "dry_run"}, key="to-dry")
    assert back.status_code == 200 and back.json()["mode"] == "dry_run"


def test_losing_the_exchange_key_between_the_steps_blocks_the_switch(rig):
    holder = {"keys": True}
    rig.gateway.modes.controllers["B"] = ModeController(
        rig.userdir / "mode.json", exchange_key_configured=lambda: holder["keys"], live_engine_proven=True
    )
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    holder["keys"] = False
    response = switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="late")
    assert response.status_code == 422 and response.json()["error"]["blockers"][0]["code"] == "exchange_key_missing"
    assert read_mode(rig.userdir / "mode.json")[0] == "dry_run"


@pytest.mark.parametrize(
    "headers",
    [{"CF-Connecting-IP": "203.0.113.9"}, {"X-Forwarded-For": "203.0.113.9"}, {"Forwarded": "for=203.0.113.9"}],
)
def test_a_request_relayed_through_a_tunnel_is_never_local(rig, headers):
    proven_controller(rig)
    response = switch(rig, LIVE, headers=headers)
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden_local_only"
    assert audit(rig)[0]["result"] == "denied" and not (rig.userdir / "mode.json").exists()


def test_a_remote_client_address_is_refused(rig):
    proven_controller(rig)
    remote = TestClient(create_app(rig.gateway), client=("192.0.2.10", 40000))
    token = remote.post("/gw/v1/session", json={"password": "correct horse battery"}).json()["token"]
    response = remote.post(
        "/gw/v1/control/mode", json=LIVE, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "r"}
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden_local_only"


def test_the_idempotency_key_is_required(rig):
    proven_controller(rig)
    response = rig.client.post("/gw/v1/control/mode", json=LIVE, headers=rig.headers)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
    too_long = switch(rig, LIVE, key="k" * 129)
    assert too_long.status_code == 400
