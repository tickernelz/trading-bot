from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from engine.modectl import ModeController, read_mode, write_capabilities
from gateway.app import create_app
from tests.test_gateway import PASSWORD
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


def switch(rig, body, key="key-000001", headers=None, client=None):
    client = client or rig.client
    return client.post(
        "/gw/v1/control/mode", json=body, headers={**rig.headers, "Idempotency-Key": key, **(headers or {})}
    )


def audit(rig):
    return [item for item in rig.gateway.ledger.audit_rows(30) if item["action"] == "mode.change"]


def to_live(rig, first="step-one-1", second="step-two-1"):
    confirmation = switch(rig, LIVE, key=first).json()["error"]["confirmation"]
    return switch(rig, {**LIVE, "confirm": confirmation["id"]}, key=second)


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
    assert row["result"] == "rejected" and row["idempotency_key"] == "key-000001"
    assert row["detail"]["error"] == "live_blocked"


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
    first = switch(rig, LIVE, key="step-one-1")
    assert first.status_code == 409 and first.json()["error"]["code"] == "confirmation_required"
    confirmation = first.json()["error"]["confirmation"]
    assert confirmation["action"] == "mode.change" and confirmation["targets"] == ["live"]
    assert confirmation["id"].startswith("cf_") and confirmation["expires_at"].endswith("Z")
    assert not (rig.userdir / "mode.json").exists()
    second = switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="step-two-1")
    assert second.status_code == 200 and second.json()["mode"] == "live"
    assert read_mode(rig.userdir / "mode.json")[0] == "live"
    assert [row["result"] for row in audit(rig)] == ["ok", "confirmation_required"]


def test_repeating_the_confirming_call_replays_the_result_without_a_second_change(rig):
    proven_controller(rig)
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    body = {**LIVE, "confirm": confirmation["id"]}
    first = switch(rig, body, key="same-key-1")
    again = switch(rig, body, key="same-key-1")
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert [row["result"] for row in audit(rig)].count("ok") == 1


def test_a_reused_key_with_another_request_is_refused_by_the_stage_2a_rule(rig):
    proven_controller(rig)
    first = switch(rig, {"mode": "dry_run"}, key="shared-key-1")
    assert first.status_code == 200
    other = switch(rig, LIVE, key="shared-key-1")
    assert other.status_code == 409 and other.json()["error"]["code"] == "invalid_request"
    assert "another request" in other.json()["error"]["message"]
    assert switch(rig, {"mode": "dry_run"}, key="shared-key-1").json() == first.json()


def test_a_used_confirmation_is_refused_with_confirmation_invalid(rig):
    proven_controller(rig)
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    assert switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="use-once-1").status_code == 200
    switch(rig, {"mode": "dry_run"}, key="back-dry-1")
    reuse = switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="use-twice-1")
    assert reuse.status_code == 409 and reuse.json()["error"]["code"] == "confirmation_invalid"
    assert read_mode(rig.userdir / "mode.json")[0] == "dry_run"


def test_unknown_confirmation_and_a_malformed_request_change_nothing(rig):
    proven_controller(rig)
    unknown = switch(rig, {**LIVE, "confirm": "cf_nothing"}, key="unknown-1")
    assert unknown.status_code == 409 and unknown.json()["error"]["code"] == "confirmation_invalid"
    assert switch(rig, {"mode": "paper"}, key="paper-key-1").status_code == 400
    assert switch(rig, {"mode": "live", "confirm": ""}, key="empty-confirm").status_code == 400
    assert not (rig.userdir / "mode.json").exists()


def test_a_confirmation_cannot_be_redeemed_by_another_session(rig):
    proven_controller(rig)
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    token = rig.client.post("/gw/v1/session", json={"password": PASSWORD}).json()["token"]
    other = {"Authorization": f"Bearer {token}", "Idempotency-Key": "other-session"}
    response = rig.client.post("/gw/v1/control/mode", json={**LIVE, "confirm": confirmation["id"]}, headers=other)
    assert response.status_code == 409 and response.json()["error"]["code"] == "confirmation_invalid"
    assert not (rig.userdir / "mode.json").exists()


def test_leaving_live_is_one_step(rig):
    proven_controller(rig)
    assert to_live(rig).status_code == 200
    back = switch(rig, {"mode": "dry_run"}, key="to-dry-key")
    assert back.status_code == 200 and back.json()["mode"] == "dry_run"


def test_losing_the_exchange_key_between_the_steps_blocks_the_switch(rig):
    holder = {"keys": True}
    rig.gateway.modes.controllers["B"] = ModeController(
        rig.userdir / "mode.json", exchange_key_configured=lambda: holder["keys"], live_engine_proven=True
    )
    confirmation = switch(rig, LIVE).json()["error"]["confirmation"]
    holder["keys"] = False
    response = switch(rig, {**LIVE, "confirm": confirmation["id"]}, key="late-key-1")
    assert response.status_code == 422 and response.json()["error"]["blockers"][0]["code"] == "exchange_key_missing"
    assert read_mode(rig.userdir / "mode.json")[0] == "dry_run"


@pytest.mark.parametrize(
    "headers",
    [
        {"CF-Connecting-IP": "203.0.113.9"},
        {"X-Forwarded-For": "203.0.113.9"},
        {"Forwarded": "for=203.0.113.9"},
        {"CF-Ray": "8a1b2c3d4e5f"},
        {"X-Forwarded-Host": "bot.example.com"},
    ],
)
def test_a_request_relayed_through_a_tunnel_is_never_local(rig, headers):
    proven_controller(rig)
    response = switch(rig, LIVE, headers=headers)
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden_local_only"
    assert audit(rig)[0]["result"] == "forbidden" and not (rig.userdir / "mode.json").exists()


def test_a_read_session_from_loopback_cannot_change_the_mode(rig):
    proven_controller(rig)
    relayed = rig.client.post(
        "/gw/v1/session", json={"password": PASSWORD}, headers={"CF-Connecting-IP": "203.0.113.9"}
    ).json()
    assert relayed["scope"] == "read"
    headers = {"Authorization": f"Bearer {relayed['token']}", "Idempotency-Key": "read-scope-1"}
    response = rig.client.post("/gw/v1/control/mode", json=LIVE, headers=headers)
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden_local_only"
    assert rig.get("/gw/v1/mode").status_code == 200


def test_a_remote_client_address_is_refused(rig):
    proven_controller(rig)
    remote = TestClient(create_app(rig.gateway), client=("192.0.2.10", 40000))
    token = remote.post("/gw/v1/session", json={"password": PASSWORD}).json()["token"]
    response = remote.post(
        "/gw/v1/control/mode", json=LIVE, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "remote-1"}
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden_local_only"


@pytest.mark.parametrize("key", ["short", "has space in it", "x" * 129, "semi;colon-key"])
def test_the_idempotency_key_must_match_the_stage_2a_format_and_never_reaches_the_audit(rig, key):
    proven_controller(rig)
    response = switch(rig, LIVE, key=key)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
    assert all(row["idempotency_key"] is None for row in audit(rig))
    assert not (rig.userdir / "mode.json").exists()


def test_a_missing_idempotency_key_is_refused(rig):
    proven_controller(rig)
    response = rig.client.post("/gw/v1/control/mode", json=LIVE, headers=rig.headers)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
