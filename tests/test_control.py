from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from gateway.app import Action, Gateway, create_app
from gateway.control import Confirmations, risky_changes
from gateway.settings import GatewaySettings
from tests.conftest import EXAMPLE
from tests.test_gateway import ENV, PASSWORD, FakeFreqtrade

LOCAL = ("127.0.0.1", 50000)


class CountingFreqtrade(FakeFreqtrade):
    """Fake Freqtrade REST that records every control call so a refused action can be proven to reach nothing."""

    def __init__(self) -> None:
        super().__init__()
        self.state = "running"
        self.calls: list[tuple[str, str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if request.method == "GET":
            if path == "/show_config":
                return httpx.Response(200, json={"dry_run": True, "state": self.state, "exchange": "indodax"})
            return super().__call__(request)
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        body = json.loads(request.content) if request.content else None
        query = request.url.params.get_list("pairs_to_delete")
        self.calls.append((request.method, path, body if body is not None else query or None))
        if path in ("/pause", "/stopentry"):
            self.state = "paused"
            return httpx.Response(200, json={"status": "paused, no more entries will occur from now."})
        if path == "/start":
            self.state = "running"
            return httpx.Response(200, json={"status": "starting trader ..."})
        if path == "/stop":
            self.state = "stopped"
            return httpx.Response(200, json={"status": "stopping trader ..."})
        if path == "/forceexit":
            if body["tradeid"] == "404":
                return httpx.Response(502, json={"error": "Error querying /api/v1/forceexit: invalid argument"})
            return httpx.Response(200, json={"result": f"Created exit order for trade {body['tradeid']}."})
        if path == "/forceenter":
            return httpx.Response(200, json={"trade_id": 11, "pair": body["pair"], "is_open": True})
        if path.startswith("/locks"):
            return httpx.Response(200, json={"lock_count": 0, "locks": []})
        if path == "/blacklist":
            return httpx.Response(200, json={"blacklist": body["blacklist"] if body else []})
        return httpx.Response(200, json={"status": "ok"})


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def setup(tmp_path):
    config = tmp_path / "bot-a.yaml"
    shutil.copy(EXAMPLE, config)
    settings = GatewaySettings(
        state_dir=str(tmp_path / "state"),
        exchange_probe_url=None,
        bots=[
            {
                "id": "A",
                "label": "Bot A",
                "strategy": "rules only",
                "api_url": "http://127.0.0.1:8080",
                "config": str(config),
                "userdir": str(tmp_path / "bot-a"),
            }
        ],
    )
    gateway = Gateway(settings, ENV)
    fake = CountingFreqtrade()
    upstream = gateway.upstreams["A"]
    upstream.client = httpx.AsyncClient(base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(fake))
    clock = Clock()
    gateway.confirmations = Confirmations(clock=clock)
    client = TestClient(create_app(gateway), base_url="http://127.0.0.1:8090", client=LOCAL)
    yield gateway, fake, client, clock, config
    gateway.ledger.close()


def login(client: TestClient, **headers: str) -> dict:
    response = client.post("/gw/v1/session", json={"password": PASSWORD}, headers=headers)
    assert response.status_code == 200
    return response.json()


def post(client: TestClient, path: str, token: str, key: str | None, body: dict | None = None, **headers: str):
    headers = {"Authorization": f"Bearer {token}", **headers}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(path, json=body, headers=headers)


def test_a_control_session_with_a_foreign_host_header_cannot_control(setup):
    gateway, fake, client, _, _ = setup
    token = login(client)["token"]
    response = client.post(
        "/gw/v1/control/stop-entry",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "key-foreign-host", "Host": "bot.example.test"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_local_only"
    assert fake.calls == []


def test_only_a_direct_loopback_login_may_control(setup):
    gateway, fake, client, _, _ = setup
    assert login(client)["scope"] == "control"
    tunnelled = login(client, **{"X-Forwarded-For": "203.0.113.9"})
    assert tunnelled["scope"] == "read"
    remote = TestClient(create_app(gateway), client=("10.0.0.5", 41000))
    remote_token = login(remote)["token"]
    assert remote.get("/gw/v1/risk", headers={"Authorization": f"Bearer {remote_token}"}).status_code == 200

    for token, headers in ((tunnelled["token"], {}), (login(client)["token"], {"CF-Connecting-IP": "203.0.113.9"})):
        response = post(client, "/gw/v1/control/pause", token, "key-forbidden-1", **headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden_local_only"
    junk = post(client, "/gw/v1/control/pause", tunnelled["token"], "x" * 4000)
    assert junk.status_code == 403
    assert fake.calls == []
    rows = gateway.ledger.audit_rows(3, action="control.")
    assert [row["result"] for row in rows] == ["forbidden"] * 3
    assert [row["idempotency_key"] for row in rows] == [None, "key-forbidden-1", "key-forbidden-1"]


def test_control_needs_an_idempotency_key(setup):
    _, fake, client, _, _ = setup
    response = post(client, "/gw/v1/control/stop-entry", login(client)["token"], None)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert fake.calls == []


def test_kill_switch_stops_entries_without_touching_trades_and_shows_in_the_feed(setup):
    gateway, fake, client, _, _ = setup
    token = login(client)["token"]
    with client.websocket_connect(f"/gw/v1/events?token={token}") as socket:
        assert socket.receive_json()["type"] == "gw.hello"
        socket.send_json({"type": "subscribe", "topics": ["gw.audit"]})
        response = post(client, "/gw/v1/control/stop-entry", token, "kill-switch-0001")
        event = socket.receive_json()
    assert response.status_code == 200
    assert fake.calls == [("POST", "/stopentry", None)]
    assert event["type"] == "gw.audit"
    assert event["bot"] == "A"
    assert (event["data"]["action"], event["data"]["result"]) == ("control.stop_entry", "ok")
    assert gateway.ledger.entries_stopped("A") is True

    assert post(client, "/gw/v1/control/resume", token, "resume-000001").status_code == 200
    assert fake.calls[-1] == ("POST", "/start", None)
    assert gateway.ledger.entries_stopped("A") is False


def test_risky_action_is_refused_until_a_matching_fresh_confirmation_arrives(setup):
    gateway, fake, client, clock, _ = setup
    token = login(client)["token"]

    first = post(client, "/gw/v1/trades/9/exit", token, "exit-9-attempt-1")
    assert first.status_code == 409
    error = first.json()["error"]
    assert error["code"] == "confirmation_required"
    assert error["confirmation"]["action"] == "trade.exit"
    assert error["confirmation"]["targets"] == ["9"]
    confirm = error["confirmation"]["id"]

    other_trade = post(client, "/gw/v1/trades/7/exit", token, "exit-7-attempt-1", {"confirm": confirm})
    assert other_trade.status_code == 409
    assert other_trade.json()["error"]["code"] == "confirmation_invalid"

    forged = post(client, "/gw/v1/trades/9/exit", token, "exit-9-attempt-2", {"confirm": "cf_made_up"})
    assert forged.json()["error"]["code"] == "confirmation_invalid"
    assert fake.calls == []

    done = post(client, "/gw/v1/trades/9/exit", token, "exit-9-attempt-3", {"confirm": confirm})
    assert done.status_code == 200
    assert fake.calls == [("POST", "/forceexit", {"tradeid": "9"})]

    reused = post(client, "/gw/v1/trades/9/exit", token, "exit-9-attempt-4", {"confirm": confirm})
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "confirmation_invalid"

    replay = post(client, "/gw/v1/trades/9/exit", token, "exit-9-attempt-3", {"confirm": confirm})
    assert replay.status_code == 200
    assert replay.json() == done.json()
    assert len(fake.calls) == 1

    stale = post(client, "/gw/v1/trades/9/exit", token, "exit-9-attempt-5").json()["error"]["confirmation"]["id"]
    clock.now += 61
    expired = post(client, "/gw/v1/trades/9/exit", token, "exit-9-attempt-5", {"confirm": stale})
    assert expired.json()["error"]["code"] == "confirmation_expired"
    assert len(fake.calls) == 1

    results = [row["result"] for row in reversed(gateway.ledger.audit_rows(20, action="trade.exit"))]
    assert results == [
        "confirmation_required",
        "rejected",
        "rejected",
        "ok",
        "rejected",
        "replayed",
        "confirmation_required",
        "rejected",
    ]


def test_confirmation_belongs_to_the_session_that_asked(setup):
    _, fake, client, _, _ = setup
    first, second = login(client)["token"], login(client)["token"]
    confirm = post(client, "/gw/v1/trades/exit-all", first, "exit-all-0001").json()["error"]["confirmation"]["id"]
    stolen = post(client, "/gw/v1/trades/exit-all", second, "exit-all-0002", {"confirm": confirm})
    assert stolen.json()["error"]["code"] == "confirmation_invalid"
    assert fake.calls == []
    assert post(client, "/gw/v1/trades/exit-all", first, "exit-all-0003", {"confirm": confirm}).status_code == 200
    assert fake.calls == [("POST", "/forceexit", {"tradeid": "all"})]


def test_idempotency_key_cannot_be_reused_for_another_request(setup):
    _, fake, client, _, _ = setup
    token = login(client)["token"]
    assert post(client, "/gw/v1/control/pause", token, "shared-key-001").status_code == 200
    clash = post(client, "/gw/v1/control/reload-config", token, "shared-key-001")
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "invalid_request"
    assert fake.calls == [("POST", "/pause", None)]


def confirmed(client: TestClient, path: str, token: str, key: str, body: dict | None = None, delete: bool = False):
    def send(payload: dict | None, attempt: str):
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": f"{key}-{attempt}"}
        if delete:
            return client.request("DELETE", path, json=payload, headers=headers)
        return client.post(path, json=payload, headers=headers)

    asked = send(body, "ask")
    assert asked.json()["error"]["code"] == "confirmation_required"
    return send({**(body or {}), "confirm": asked.json()["error"]["confirmation"]["id"]}, "do")


def test_locks_and_blacklist_follow_freqtrade_routes(setup):
    _, fake, client, _, _ = setup
    token = login(client)["token"]
    until = (datetime.now(UTC) + timedelta(hours=2)).replace(microsecond=0)
    locked = post(client, "/gw/v1/locks", token, "lock-btc-0001", {"pair": "BTC/IDR", "until": until.isoformat()})
    assert locked.status_code == 200
    assert fake.calls[-1][:2] == ("POST", "/locks")
    assert fake.calls[-1][2][0]["pair"] == "BTC/IDR"
    assert fake.calls[-1][2][0]["side"] == "*"

    assert confirmed(client, "/gw/v1/locks/3", token, "unlock-3", delete=True).status_code == 200
    assert fake.calls[-1] == ("DELETE", "/locks/3", None)
    assert confirmed(client, "/gw/v1/locks/delete", token, "unlock-btc", {"pair": "BTC/IDR"}).status_code == 200
    assert fake.calls[-1] == ("POST", "/locks/delete", {"pair": "BTC/IDR"})

    added = post(client, "/gw/v1/blacklist", token, "blacklist-sol-1", {"pairs": ["SOL/IDR"]})
    assert added.status_code == 200
    assert fake.calls[-1] == ("POST", "/blacklist", {"blacklist": ["SOL/IDR"]})
    removed = confirmed(client, "/gw/v1/blacklist?pairs=SOL/IDR", token, "unblacklist-sol", delete=True)
    assert removed.status_code == 200
    assert fake.calls[-1] == ("DELETE", "/blacklist", ["SOL/IDR"])

    calls = len(fake.calls)
    past = post(client, "/gw/v1/locks", token, "lock-btc-0002", {"pair": "BTC/IDR", "until": "2020-01-01T00:00:00Z"})
    assert past.status_code == 400
    assert len(fake.calls) == calls


def test_freqtrade_failure_is_audited_and_not_retried_under_the_same_key(setup):
    gateway, fake, client, _, _ = setup
    token = login(client)["token"]
    failed = confirmed(client, "/gw/v1/trades/404/exit", token, "exit-404")
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "upstream_error"
    assert "invalid argument" in failed.json()["error"]["message"]
    row = gateway.ledger.audit_rows(1)[0]
    assert (row["action"], row["result"], row["detail"]["error"]) == ("trade.exit", "failed", "upstream_error")

    replay = client.post(
        "/gw/v1/trades/404/exit",
        json={"confirm": "cf_ignored"},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "exit-404-do"},
    )
    assert replay.status_code == 502
    assert replay.json() == failed.json()
    assert len(fake.calls) == 1


def test_force_enter_respects_config_risk_and_whitelist(setup):
    gateway, fake, client, _, config = setup
    token = login(client)["token"]
    body = {"pair": "BTC/IDR"}
    disabled = post(client, "/gw/v1/trades", token, "enter-btc-0001", body)
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "invalid_request"

    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    raw["api"] = {**raw.get("api", {}), "force_entry": True}
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    breached = post(client, "/gw/v1/trades", token, "enter-btc-0002", body)
    assert breached.json()["error"]["code"] == "risk_limit_breached"
    off_list = post(client, "/gw/v1/trades", token, "enter-doge-001", {"pair": "DOGE/IDR"})
    assert off_list.status_code == 422
    assert fake.calls == []

    fake.closed = []
    gateway.cache.clear()
    entered = confirmed(client, "/gw/v1/trades", token, "enter-btc-0003", body)
    assert entered.status_code == 200
    assert entered.json()["trade_id"] == 11
    assert fake.calls == [
        ("POST", "/forceenter", {"pair": "BTC/IDR", "side": "long", "stakeamount": None, "entry_tag": None})
    ]


def test_stop_entry_is_sent_again_when_freqtrade_comes_back_running(setup):
    gateway, fake, client, _, _ = setup
    bot = gateway.settings.bots[0]
    asyncio.run(gateway.reapply_entry_stop(bot))
    assert fake.calls == []

    gateway.ledger.set_entries_stopped("A", True)
    asyncio.run(gateway.reapply_entry_stop(bot))
    assert fake.calls == [("POST", "/stopentry", None)]
    row = gateway.ledger.audit_rows(1)[0]
    assert (row["actor"], row["action"], row["result"]) == ("gateway", "control.stop_entry", "ok")

    asyncio.run(gateway.reapply_entry_stop(bot))
    assert len(fake.calls) == 1

    gateway.ledger.set_entries_stopped("A", False)
    token = login(client)["token"]
    assert confirmed(client, "/gw/v1/control/stop", token, "stop-bot-a").status_code == 200
    assert gateway.ledger.entries_stopped("A") is True
    fake.state = "running"
    asyncio.run(gateway.reapply_entry_stop(bot))
    assert fake.calls[-1] == ("POST", "/stopentry", None)


def test_audit_log_is_append_only_and_filtered_by_page(setup):
    gateway, _, client, _, _ = setup
    token = login(client)["token"]
    for index in range(5):
        post(client, "/gw/v1/control/pause", token, f"pause-key-{index:04d}")
    post(client, "/gw/v1/trades/9/exit", token, "exit-9-filter-1")

    headers = {"Authorization": f"Bearer {token}"}
    first = client.get("/gw/v1/audit?action=control.&limit=3", headers=headers).json()
    assert [row["action"] for row in first] == ["control.pause"] * 3
    second = client.get(f"/gw/v1/audit?action=control.&limit=3&before_id={first[-1]['id']}", headers=headers).json()
    assert len(second) == 2
    assert {row["id"] for row in first}.isdisjoint(row["id"] for row in second)
    pending = client.get("/gw/v1/audit?result=confirmation_required&target=9", headers=headers).json()
    assert [row["action"] for row in pending] == ["trade.exit"]
    later = client.get("/gw/v1/audit", params={"since": "2999-01-01T00:00:00Z"}, headers=headers).json()
    assert later == []
    assert client.get("/gw/v1/audit?since=yesterday", headers=headers).status_code == 400

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        gateway.ledger._db.execute("DELETE FROM audit")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        gateway.ledger._db.execute("UPDATE audit SET result = 'ok'")


def test_audit_never_holds_secret_values(setup):
    gateway, _, _, _, _ = setup
    action_params = {"provider": "nutaraline", "api_key": "sk-marker-not-for-logs", "nested": {"password": "pw-marker"}}
    row = gateway.audit_control(
        Action(
            name="test.secret",
            bot=gateway.settings.bots[0],
            params=action_params,
            targets=[],
            summary="",
            method="POST",
            path="/x",
        ),
        "ok",
    )
    stored = json.dumps(gateway.ledger.audit_rows(1)[0])
    assert "marker" not in stored
    assert row["detail"]["params"]["api_key"] == "<set>"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"risk": {"max_daily_loss_pct": 0.5}}, []),
        ({"risk": {"max_daily_loss_pct": 2.0}}, ["risk.max_daily_loss_pct"]),
        ({"risk": {"max_open_trades": 5, "risk_per_trade_pct": 0.25}}, ["risk.max_open_trades"]),
        ({"mode": "live"}, ["mode"]),
        ({"api": {"force_entry": True}}, ["api.force_entry"]),
    ],
)
def test_raising_risk_needs_confirmation_and_lowering_does_not(example_raw, change, expected):
    new = json.loads(json.dumps(example_raw))
    for section, values in change.items():
        if isinstance(values, dict):
            new[section] = {**new.get(section, {}), **values}
        else:
            new[section] = values
    assert risky_changes(example_raw, new) == expected
