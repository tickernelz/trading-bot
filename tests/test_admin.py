from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from engine.settings import Provider
from gateway import configstore
from gateway.admin import Admin
from gateway.app import Gateway, create_app
from gateway.control import Confirmations, is_local
from gateway.providers import ProviderTester, build_test_request
from gateway.redact import REDACTED, SecretRegistry, install_log_redaction, key_last4, registry
from gateway.settings import GatewaySettings
from tests.conftest import EXAMPLE
from tests.test_gateway import ENV, PASSWORD, FakeFreqtrade

MARK = "TBMARK-7c1f9a52e0d84b3f-ZQ91"
LITERAL_MARK = "TBLIT-5e2d7a91c3b84f60-QW42"
PEER = ("203.0.113.9", 50000)
LOCAL = ("127.0.0.1", 50000)
LOCAL_URL = "http://127.0.0.1:8090"
EXEMPT = {("POST", "/gw/v1/session"), ("DELETE", "/gw/v1/session"), ("POST", "/gw/v1/providers/{provider_id}/test")}
GUARDED_READS = {("GET", "/gw/v1/providers/import")}
ADMIN_PREFIXES = ("/gw/v1/settings", "/gw/v1/providers", "/gw/v1/voters", "/gw/v1/roles")

install_log_redaction()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Rig:
    def __init__(self, tmp_path: Path, config_dir: Path | None = None) -> None:
        directory = config_dir or tmp_path
        self.config = directory / "bot-a.yaml"
        shutil.copy(EXAMPLE, self.config)
        raw = yaml.safe_load(self.config.read_text())
        raw["providers"][0]["base_url"] = "https://nutaraline.example.test/v1"
        self.config.write_text(yaml.safe_dump(raw, sort_keys=False))
        self.models = tmp_path / "models.yml"
        self.models.write_text(
            yaml.safe_dump(
                {
                    "providers": {
                        "nutaraline": {
                            "baseUrl": "https://nutaraline.example.test/v1",
                            "api": "openai-completions",
                            "auth": "apiKey",
                            "apiKey": LITERAL_MARK,
                            "models": [{"id": "deepseek-v4.1-flash-1017"}, {"id": "other-model"}],
                        },
                        "fresh-one": {
                            "baseUrl": "https://fresh.example.test/v1",
                            "api": "anthropic-messages",
                            "apiKey": LITERAL_MARK + "-fresh",
                            "models": [{"id": "claude-x"}, {"id": "claude-y"}],
                        },
                        "env-one": {
                            "baseUrl": "https://env.example.test/v1",
                            "api": "openai-responses",
                            "apiKey": "ENV_ONE_SECRET",
                            "models": [{"id": "gpt-x"}],
                        },
                        "cmd-one": {
                            "baseUrl": "https://cmd.example.test/v1",
                            "api": "openai-completions",
                            "apiKey": "!pass show cmd-one",
                            "models": [{"id": "m"}],
                        },
                        "keyless": {
                            "baseUrl": "https://keyless.example.test/v1",
                            "api": "openai-completions",
                            "models": [{"id": "m"}],
                        },
                        "odd-api": {
                            "baseUrl": "https://odd.example.test/v1",
                            "api": "carrier-pigeon",
                            "apiKey": LITERAL_MARK + "-odd",
                            "models": [{"id": "m"}],
                        },
                    }
                }
            )
        )
        settings = GatewaySettings(
            state_dir=str(tmp_path / "state"),
            exchange_probe_url=None,
            bots=[
                {
                    "id": "A",
                    "label": "Bot A",
                    "strategy": "rules only",
                    "api_url": "http://127.0.0.1:8080",
                    "config": str(self.config),
                    "userdir": str(tmp_path / "bot-a"),
                }
            ],
        )
        self.env = {**ENV, "NUTARALINE_API_KEY": "env-key-0123456789abcdef"}
        self.gateway = Gateway(settings, self.env)
        self.fake = FakeFreqtrade()
        upstream = self.gateway.upstreams["A"]
        upstream.client = httpx.AsyncClient(
            base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(self.fake)
        )
        self.clock = Clock()
        self.provider_calls: list[httpx.Request] = []
        self.provider_reply = lambda request: httpx.Response(200, json={"id": "x", "choices": []})
        self.tester = ProviderTester(transport=httpx.MockTransport(self.handle_provider))
        self.gateway.confirmations = Confirmations(clock=self.clock)
        self.admin = Admin(self.gateway, tester=self.tester, models_yml=self.models)
        self.keys = 0
        self.app = create_app(self.gateway, self.admin)
        self.local = TestClient(self.app, base_url=LOCAL_URL, client=LOCAL)
        self.remote = TestClient(self.app, base_url="http://bot.example.test", client=PEER)
        self.owner = self.login(self.local)
        self.reader = self.login(self.remote)

    def handle_provider(self, request: httpx.Request) -> httpx.Response:
        self.provider_calls.append(request)
        return self.provider_reply(request)

    def login(self, client: TestClient, **headers: str) -> str:
        response = client.post("/gw/v1/session", json={"password": PASSWORD}, headers=headers)
        assert response.status_code == 200
        return response.json()["token"]

    def call(self, method: str, path: str, token: str | None = None, client: TestClient | None = None, **kwargs: Any):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token or self.owner}"
        if kwargs.pop("auto_key", True) and method != "GET" and not path.endswith("/test"):
            if not any(name.lower() == "idempotency-key" for name in headers):
                self.keys += 1
                headers["Idempotency-Key"] = f"auto-key-{self.keys:06d}"
        return (client or self.local).request(method, path, headers=headers, **kwargs)

    def patch(self, changes: dict, key: str | None = None, confirm: str | None = None, **kwargs: Any):
        body: dict[str, Any] = {"changes": changes}
        if confirm:
            body["confirm"] = confirm
        headers = {"Idempotency-Key": key} if key else {}
        return self.call("PATCH", "/gw/v1/settings", json=body, headers=headers, **kwargs)

    def raw(self) -> dict:
        return yaml.safe_load(self.config.read_text())

    def audit(self, limit: int = 500) -> list[dict]:
        return self.gateway.ledger.audit_rows(limit)

    def close(self) -> None:
        self.gateway.ledger.close()


@pytest.fixture
def rig(tmp_path):
    instance = Rig(tmp_path)
    yield instance
    instance.close()


def error_code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


def test_valid_patch_is_written_audited_and_visible_in_the_change_log(rig):
    rig.fake.closed = []
    response = rig.patch({"risk": {"max_daily_loss_pct": 0.8}, "exchange": {"fee_pct": 0.1}})
    assert response.status_code == 200
    body = response.json()
    assert body["restart_required"] is True
    assert {item["key"] for item in body["changes"]} == {"risk.max_daily_loss_pct", "exchange.fee_pct"}
    assert rig.raw()["risk"]["max_daily_loss_pct"] == 0.8
    row = rig.audit()[0]
    assert (row["action"], row["actor"], row["ip"], row["result"]) == ("config.update", "owner", "127.0.0.1", "ok")
    changes = {item["key"]: item for item in row["detail"]["changes"]}
    assert changes["risk.max_daily_loss_pct"]["old"] == 1.0
    assert changes["risk.max_daily_loss_pct"]["new"] == 0.8
    listed = rig.call("GET", "/gw/v1/settings/changes?bot=A").json()
    entry = next(item for item in listed if item["key"] == "risk.max_daily_loss_pct")
    assert (entry["actor"], entry["ip"], entry["old"], entry["new"]) == ("owner", "127.0.0.1", 1.0, 0.8)
    assert entry["ts"].endswith("Z")
    assert rig.call("GET", "/gw/v1/settings").json()["risk"]["max_daily_loss_pct"] == 0.8


def test_noop_patch_writes_nothing(rig):
    before = rig.config.read_bytes()
    response = rig.patch({"risk": {"max_daily_loss_pct": 1.0}})
    assert response.status_code == 200
    assert response.json() == {"bot": "A", "changes": [], "restart_required": False}
    assert rig.config.read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"risk": {"max_daily_loss_pct": 0.1}},
        {"risk": {"leverage": "5x"}},
        {"risk": {"max_open_trades": 0}},
        {"exchange": {"pairs": ["BTC/USDT"]}},
        {"nonsense": 1},
        {"risk": {"nonsense": 1}},
        {"mode": "live"},
        {"api": {"port": 9000}},
        {"shadow": {"port": 9000}},
        {"providers": []},
        {"swarm": {"voters": []}},
        {"llm": {"analyst_model": "ghost:model"}},
    ],
)
def test_invalid_or_frozen_changes_are_rejected_and_leave_the_file_alone(rig, changes):
    before = rig.config.read_bytes()
    response = rig.patch(changes)
    assert response.status_code == 400
    assert error_code(response) == "invalid_request"
    assert rig.config.read_bytes() == before
    assert not [row for row in rig.audit() if row["action"].startswith("config.") and row["result"] == "ok"]


def test_validation_errors_do_not_echo_submitted_values(rig):
    response = rig.patch({"risk": {"leverage": MARK}})
    assert response.status_code == 400
    assert MARK not in response.text
    assert MARK not in json.dumps(rig.audit())


def test_raising_a_limit_needs_a_second_step_bound_to_the_exact_change_and_session(rig):
    before = rig.config.read_bytes()
    first = rig.patch({"risk": {"max_daily_loss_pct": 2.0}}, key="raise-0001")
    assert first.status_code == 409
    assert error_code(first) == "confirmation_required"
    confirmation = first.json()["error"]["confirmation"]
    assert confirmation["id"].startswith("cf_")
    assert confirmation["targets"] == ["A"]
    assert "risk.max_daily_loss_pct 1.0 -> 2.0" in confirmation["summary"]
    assert rig.config.read_bytes() == before

    other = rig.patch({"risk": {"max_daily_loss_pct": 3.0}}, key="raise-0002", confirm=confirmation["id"])
    assert other.status_code == 409
    assert error_code(other) == "confirmation_invalid"
    assert rig.config.read_bytes() == before

    second_session = rig.login(rig.local)
    stolen = rig.patch(
        {"risk": {"max_daily_loss_pct": 2.0}}, key="raise-0003", confirm=confirmation["id"], token=second_session
    )
    assert stolen.status_code == 409
    assert error_code(stolen) == "confirmation_invalid"
    assert rig.config.read_bytes() == before

    done = rig.patch({"risk": {"max_daily_loss_pct": 2.0}}, key="raise-0004", confirm=confirmation["id"])
    assert done.status_code == 200
    assert rig.raw()["risk"]["max_daily_loss_pct"] == 2.0
    row = next(item for item in rig.audit() if item["action"] == "config.update" and item["result"] == "ok")
    assert row["detail"]["confirmed"] is True
    results = [item["result"] for item in rig.audit() if item["action"] == "config.update"]
    assert results == ["ok", "rejected", "rejected", "confirmation_required"]


def test_a_confirmation_is_single_use_and_expires(rig):
    first = rig.patch({"risk": {"max_open_trades": 5}}).json()["error"]["confirmation"]
    assert rig.patch({"risk": {"max_open_trades": 5}}, confirm=first["id"]).status_code == 200
    rig.patch({"risk": {"max_open_trades": 3}})
    again = rig.patch({"risk": {"max_open_trades": 5}}, confirm=first["id"])
    assert again.status_code == 409
    assert error_code(again) == "confirmation_invalid"
    assert rig.raw()["risk"]["max_open_trades"] == 3

    pending = rig.patch({"risk": {"max_open_trades": 5}}).json()["error"]["confirmation"]
    rig.clock.now += 61
    late = rig.patch({"risk": {"max_open_trades": 5}}, confirm=pending["id"])
    assert late.status_code == 409
    assert error_code(late) == "confirmation_expired"
    assert rig.raw()["risk"]["max_open_trades"] == 3


def test_a_mixed_change_that_raises_anything_needs_the_second_step(rig):
    rig.fake.closed = []
    response = rig.patch({"risk": {"max_daily_loss_pct": 2.0, "risk_per_trade_pct": 0.3}})
    assert response.status_code == 409
    assert rig.raw()["risk"]["risk_per_trade_pct"] == 0.5


def test_lowering_a_limit_applies_directly_and_raising_initial_capital_does_not(rig):
    rig.fake.closed = []
    assert rig.patch({"risk": {"risk_per_trade_pct": 0.3}}).status_code == 200
    assert rig.patch({"capital": {"initial_idr": 1_000_000}}).status_code == 200
    assert rig.patch({"capital": {"initial_idr": 3_000_000}}).status_code == 409
    assert rig.patch({"notify": {"web_push": False}}).status_code == 200


def test_lowering_below_the_loss_already_taken_is_refused_with_a_matching_control(rig):
    raw = rig.raw()
    raw["risk"]["max_daily_loss_pct"] = 5.0
    rig.config.write_text(yaml.safe_dump(raw, sort_keys=False))
    before = rig.config.read_bytes()
    refused = rig.patch({"risk": {"max_daily_loss_pct": 1.2}})
    assert refused.status_code == 409
    assert error_code(refused) == "risk_limit_breached"
    assert "daily_loss_pct" in refused.json()["error"]["message"]
    assert rig.config.read_bytes() == before
    assert rig.patch({"risk": {"max_total_drawdown_pct": 1.3, "max_daily_loss_pct": 1.0}}).status_code == 409
    assert rig.audit()[0]["result"] == "rejected"

    rig.fake.closed = []
    rig.gateway.cache.clear()
    assert rig.patch({"risk": {"max_daily_loss_pct": 1.2}}).status_code == 200
    assert rig.patch({"risk": {"max_total_drawdown_pct": 1.3}}).status_code == 200


def test_lowering_still_works_when_freqtrade_is_down_and_says_the_check_was_skipped(rig):
    rig.fake.down = True
    response = rig.patch({"risk": {"max_daily_loss_pct": 0.8}})
    assert response.status_code == 200
    assert rig.audit()[0]["detail"]["risk_check"] == "skipped_upstream_unavailable"


def test_idempotency_key_is_required_replayed_from_the_ledger_and_refuses_a_different_request(rig):
    rig.fake.closed = []
    missing = rig.call("PATCH", "/gw/v1/settings", json={"changes": {"exchange": {"fee_pct": 0.1}}}, auto_key=False)
    assert missing.status_code == 400
    assert rig.raw()["exchange"]["fee_pct"] == 0.2
    first = rig.patch({"exchange": {"fee_pct": 0.1}}, key="idem-0001")
    assert first.status_code == 200
    assert rig.gateway.ledger.stored_result("idem-0001")[1] == 200
    writes = len([row for row in rig.audit() if row["action"] == "config.update" and row["result"] == "ok"])
    replay = rig.patch({"exchange": {"fee_pct": 0.1}}, key="idem-0001")
    assert replay.json() == first.json()
    assert rig.audit()[0]["result"] == "replayed"
    assert len([row for row in rig.audit() if row["action"] == "config.update" and row["result"] == "ok"]) == writes
    clash = rig.patch({"exchange": {"fee_pct": 0.15}}, key="idem-0001")
    assert clash.status_code == 409
    assert rig.raw()["exchange"]["fee_pct"] == 0.1
    assert rig.patch({"exchange": {"fee_pct": 0.15}}, key="short").status_code == 400
    assert rig.patch({"exchange": {"fee_pct": 0.15}}, key="has.dots.in.it").status_code == 400


def test_a_key_still_running_is_not_started_twice(rig):
    rig.gateway.inflight.add("busy-key-01")
    response = rig.patch({"exchange": {"fee_pct": 0.1}}, key="busy-key-01")
    assert response.status_code == 409
    assert "still running" in response.json()["error"]["message"]
    assert rig.raw()["exchange"]["fee_pct"] == 0.2


def test_our_own_write_is_not_reported_again_by_the_file_watcher(rig):
    asyncio.run(rig.gateway.watch_config())
    rig.fake.closed = []
    assert rig.patch({"exchange": {"fee_pct": 0.1}}).status_code == 200
    asyncio.run(rig.gateway.watch_config())
    actions = [row["action"] for row in rig.audit(5)]
    assert actions.count("config.update") == 1
    assert "config.changed" not in actions


def test_write_is_atomic_and_private(rig, monkeypatch):
    rig.fake.closed = []
    before = rig.config.read_bytes()
    monkeypatch.setattr(
        configstore.os, "replace", lambda *_: (_ for _ in ()).throw(OSError(30, "Read-only file system"))
    )
    failed = rig.patch({"exchange": {"fee_pct": 0.1}})
    assert failed.status_code == 500
    assert error_code(failed) == "config_unwritable"
    assert rig.config.read_bytes() == before
    assert sorted(path.name for path in rig.config.parent.glob(".bot-a*")) == []
    monkeypatch.undo()
    assert rig.patch({"exchange": {"fee_pct": 0.1}}).status_code == 200
    assert oct(rig.config.stat().st_mode & 0o777) == "0o600"


def test_concurrent_edits_do_not_lose_updates_and_the_lock_is_what_prevents_it(rig, monkeypatch):
    rig.fake.closed = []
    original = rig.gateway.risk

    async def slow_risk(ref):
        await asyncio.sleep(0.05)
        return await original(ref)

    monkeypatch.setattr(rig.gateway, "risk", slow_risk)

    async def race() -> list[int]:
        transport = httpx.ASGITransport(app=rig.app, client=LOCAL)
        async with httpx.AsyncClient(transport=transport, base_url=LOCAL_URL) as http:
            token = (await http.post("/gw/v1/session", json={"password": PASSWORD})).json()["token"]
            headers = {"Authorization": f"Bearer {token}"}
            second = {**headers, "Idempotency-Key": "race-key-0002"}
            first = {**headers, "Idempotency-Key": "race-key-0001"}
            replies = await asyncio.gather(
                http.patch("/gw/v1/settings", headers=first, json={"changes": {"risk": {"max_daily_loss_pct": 0.8}}}),
                http.patch("/gw/v1/settings", headers=second, json={"changes": {"data": {"fear_greed": False}}}),
            )
        return [reply.status_code for reply in replies]

    assert asyncio.run(race()) == [200, 200]
    raw = rig.raw()
    assert raw["risk"]["max_daily_loss_pct"] == 0.8
    assert raw["data"]["fear_greed"] is False

    shutil.copy(EXAMPLE, rig.config)
    rig.gateway.bot_settings.clear()
    monkeypatch.setattr(Admin, "lock", lambda self, bot_id: asyncio.Lock())
    assert asyncio.run(race()) == [200, 200]
    raw = rig.raw()
    assert not (raw["risk"]["max_daily_loss_pct"] == 0.8 and raw["data"]["fear_greed"] is False)


def test_login_scope_follows_where_the_sign_in_came_from(rig):
    ledger = rig.gateway.ledger
    assert ledger.session_scope(rig.owner) == "control"
    assert ledger.session_scope(rig.reader) == "read"
    relayed = rig.login(rig.local, **{"X-Forwarded-For": "203.0.113.9"})
    assert ledger.session_scope(relayed) == "read"
    foreign_host = rig.login(rig.local, Host="bot.example.test")
    assert ledger.session_scope(foreign_host) == "read"
    foreign_origin = rig.login(rig.local, Origin="https://evil.example")
    assert ledger.session_scope(foreign_origin) == "read"
    refused = rig.call("POST", "/gw/v1/control/pause", headers={"Host": "bot.example.test"})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden_local_only"


RELAYED = [
    pytest.param({"client": PEER, "headers": {}, "base": "http://bot.example.test"}, id="remote-peer"),
    pytest.param(
        {"client": LOCAL, "headers": {"X-Forwarded-For": "203.0.113.9"}, "base": LOCAL_URL}, id="x-forwarded-for"
    ),
    pytest.param({"client": LOCAL, "headers": {"CF-Connecting-IP": "203.0.113.9"}, "base": LOCAL_URL}, id="cloudflare"),
    pytest.param({"client": LOCAL, "headers": {"Forwarded": "for=203.0.113.9"}, "base": LOCAL_URL}, id="forwarded"),
    pytest.param({"client": LOCAL, "headers": {}, "base": "http://bot.example.test"}, id="foreign-host-header"),
    pytest.param(
        {"client": LOCAL, "headers": {"Origin": "https://evil.example"}, "base": LOCAL_URL}, id="foreign-origin"
    ),
]


@pytest.mark.parametrize("variant", RELAYED)
def test_owner_token_used_through_a_relay_cannot_change_config_or_keys(rig, variant):
    client = TestClient(rig.app, base_url=variant["base"], client=variant["client"])
    before = rig.config.read_bytes()
    patched = rig.call(
        "PATCH",
        "/gw/v1/settings",
        client=client,
        json={"changes": {"notify": {"web_push": False}}},
        headers=variant["headers"],
    )
    keyed = rig.call(
        "PUT", "/gw/v1/providers/nutaraline/key", client=client, json={"api_key": MARK}, headers=variant["headers"]
    )
    for response in (patched, keyed):
        assert response.status_code == 403
        assert error_code(response) == "forbidden_local_only"
        assert MARK not in response.text
    assert rig.config.read_bytes() == before
    assert MARK not in json.dumps(rig.audit())
    assert rig.audit()[0]["action"] == "admin.denied"
    assert rig.audit()[0]["result"] == "forbidden"
    rig.fake.closed = []
    assert rig.patch({"notify": {"web_push": False}}).status_code == 200


def test_a_read_scope_token_is_refused_even_on_the_local_machine(rig):
    response = rig.call("PUT", "/gw/v1/providers/nutaraline/key", token=rig.reader, json={"api_key": MARK})
    assert response.status_code == 403
    assert "control scope" in response.json()["error"]["message"]
    assert MARK not in rig.config.read_text()


def test_every_state_changing_route_is_guarded_for_remote_callers(rig):
    candidates = [
        route
        for entry in rig.app.routes
        for route in (entry.original_router.routes if hasattr(entry, "original_router") else [entry])
    ]
    routes = [
        (method, route.path)
        for route in candidates
        if isinstance(route, APIRoute) and route.path.startswith(ADMIN_PREFIXES)
        for method in route.methods
        if (method != "GET" or (method, route.path) in GUARDED_READS) and (method, route.path) not in EXEMPT
    ]
    assert len(routes) >= 10
    before = rig.config.read_bytes()
    for method, path in routes:
        concrete = path.replace("{provider_id}", "nutaraline").replace("{voter_id}", "v1")
        for token in (rig.owner, rig.reader):
            blocked = rig.call(method, concrete, token=token, client=rig.remote, json={} if method != "GET" else None)
            assert blocked.status_code == 403, (method, path)
            assert error_code(blocked) == "forbidden_local_only", (method, path)
        anonymous = rig.remote.request(method, concrete, json={} if method != "GET" else None)
        assert anonymous.status_code == 401, (method, path)
        assert rig.config.read_bytes() == before, (method, path)
        reached = rig.call(method, concrete, json={} if method != "GET" else None)
        assert reached.status_code not in (401, 403), (method, path)
        rig.config.write_bytes(before)
        rig.gateway.bot_settings.clear()


def test_marker_key_never_appears_in_responses_logs_audit_or_snapshots(rig, caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    surfaces: list[str] = []
    put = rig.call(
        "PUT", "/gw/v1/providers/nutaraline/key", json={"api_key": MARK}, headers={"Idempotency-Key": "key-write-01"}
    )
    assert put.status_code == 200
    surfaces.append(put.text)
    rig.provider_reply = lambda request: httpx.Response(
        401, json={"error": {"message": f"bad credential {MARK} rejected"}}
    )
    tested = rig.call("POST", "/gw/v1/providers/nutaraline/test", client=rig.remote, token=rig.reader)
    assert tested.status_code == 200
    assert tested.json()["ok"] is False
    surfaces.append(tested.text)
    for path in (
        "/gw/v1/providers",
        "/gw/v1/settings",
        "/gw/v1/audit?limit=500",
        "/gw/v1/settings/changes?limit=500",
        "/gw/v1/voters",
        "/gw/v1/roles",
    ):
        for client, token in ((rig.local, rig.owner), (rig.remote, rig.reader)):
            surfaces.append(rig.call("GET", path, client=client, token=token).text)
    surfaces.append(json.dumps(rig.audit()))
    surfaces.append(json.dumps(rig.gateway.ledger.config_hash("A")))
    surfaces.append(caplog.text)
    joined = "\n".join(surfaces)
    assert MARK not in joined
    assert MARK[:-4] not in joined
    providers = {item["id"]: item for item in rig.call("GET", "/gw/v1/providers").json()["providers"]}
    assert providers["nutaraline"]["key"] == {
        "source": "config",
        "configured": True,
        "last4": "ZQ91",
        "env_name": None,
        "env_set": None,
    }
    assert rig.call("GET", "/gw/v1/settings").json()["providers"][0]["api_key_last4"] == "ZQ91"
    assert rig.call("GET", "/gw/v1/settings").json()["providers"][0]["api_key"] is None
    assert MARK in rig.config.read_text()
    assert oct(rig.config.stat().st_mode & 0o777) == "0o600"
    key_change = (
        rig.audit()[-1] if False else next(row for row in rig.audit() if row["action"] == "config.provider.key")
    )
    assert key_change["detail"]["changes"][0]["new"] == "****ZQ91"


def test_upstream_error_that_echoes_the_key_is_scrubbed_only_because_of_the_registry(rig, monkeypatch):
    provider = Provider(
        id="p", type="openai-completions", base_url="https://p.example.test/v1", models=["m"], api_key=MARK
    )
    rig.provider_reply = lambda request: httpx.Response(
        401, json={"error": {"message": f"bad credential {MARK} rejected"}}
    )
    monkeypatch.setattr(registry, "_ordered", ())
    leaked = asyncio.run(rig.tester.run(provider, "m", MARK))
    assert MARK in leaked["detail"]
    registry.add(MARK)
    scrubbed = asyncio.run(rig.tester.run(provider, "m", MARK))
    assert MARK not in json.dumps(scrubbed)
    assert REDACTED in scrubbed["detail"]


def test_invalid_key_submission_is_rejected_without_echoing_it(rig):
    before = rig.config.read_bytes()
    for body in (
        {"api_key": f"{MARK} with spaces"},
        {"api_key": "short"},
        {"api_key": MARK, "api_key_env": "SOME_ENV"},
        {},
        {"api_key_env": "lower_case"},
        {"api_key": MARK, "extra": MARK},
    ):
        response = rig.call("PUT", "/gw/v1/providers/nutaraline/key", json=body)
        assert response.status_code == 400, body
        assert MARK not in response.text
    assert rig.config.read_bytes() == before
    assert MARK not in json.dumps(rig.audit())


def test_key_sources_are_exclusive_and_short_keys_show_no_tail(rig):
    put = rig.call("PUT", "/gw/v1/providers/nutaraline/key", json={"api_key": "abcdefgh"})
    assert put.json()["provider"]["key"] == {
        "source": "config",
        "configured": True,
        "last4": None,
        "env_name": None,
        "env_set": None,
    }
    assert rig.raw()["providers"][0]["api_key_env"] is None
    env = rig.call("PUT", "/gw/v1/providers/nutaraline/key", json={"api_key_env": "NUTARALINE_API_KEY"})
    assert env.json()["provider"]["key"] == {
        "source": "env",
        "configured": True,
        "last4": None,
        "env_name": "NUTARALINE_API_KEY",
        "env_set": True,
    }
    assert rig.raw()["providers"][0]["api_key"] is None
    cleared = rig.call("DELETE", "/gw/v1/providers/nutaraline/key")
    assert cleared.json()["provider"]["key"]["source"] == "none"
    assert rig.call("PUT", "/gw/v1/providers/ghost/key", json={"api_key_env": "X_KEY"}).status_code == 404


def test_log_redaction_covers_authorization_tokens_and_registered_values(caplog):
    caplog.set_level(logging.INFO)
    logger = logging.getLogger("trading_bot.test")
    logger.info("calling with Authorization: Bearer abcdefghijkl and url /gw/v1/events?token=sessiontoken123&x=1")
    logger.info("header %s", {"authorization": "Basic Zm9vOmJhcg==", "x-api-key": "plainkey-123456"})
    logger.info("oauth access_token=oauthvalue123456 and refresh_token=refreshvalue123456 end")
    registry.add(MARK)
    logger.info("registered %s inside text", MARK)
    try:
        raise RuntimeError(f"boom {MARK}")
    except RuntimeError:
        logger.exception("failed")
    for secret in (
        "abcdefghijkl",
        "sessiontoken123",
        "Zm9vOmJhcg==",
        "plainkey-123456",
        "oauthvalue123456",
        "refreshvalue123456",
        MARK,
    ):
        assert secret not in caplog.text
    assert "x=1" in caplog.text


def test_secret_registry_and_tail_rules():
    local = SecretRegistry()
    local.add("tiny", "a-long-secret-value", None, "")
    assert local.redact("tiny a-long-secret-value") == f"tiny {REDACTED}"
    assert key_last4("0123456789ab") == "89ab"
    assert key_last4("0123456789a") is None
    assert key_last4(None) is None


@pytest.mark.parametrize(
    ("host", "headers", "client", "expected"),
    [
        ("127.0.0.1:8090", {}, "127.0.0.1", True),
        ("localhost:8090", {}, "::1", True),
        ("[::1]:8090", {}, "::ffff:127.0.0.1", False),
        ("127.0.0.1:8090", {"origin": "http://localhost:5173"}, "127.0.0.1", True),
        ("127.0.0.1:8090", {}, "10.0.0.5", False),
        ("localhost.evil.example", {}, "127.0.0.1", False),
        ("127.0.0.1:8090", {"via": "1.1 proxy"}, "127.0.0.1", False),
        ("127.0.0.1:8090", {"origin": "null"}, "127.0.0.1", False),
        ("", {}, "127.0.0.1", False),
    ],
)
def test_locality_rules(host, headers, client, expected):
    from starlette.requests import Request

    raw_headers = [(b"host", host.encode())] if host else []
    raw_headers += [(name.encode(), value.encode()) for name, value in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (client, 1),
        "query_string": b"",
    }
    assert is_local(Request(scope)) is expected


@pytest.mark.parametrize(
    ("type_", "base", "url", "header"),
    [
        (
            "openai-completions",
            "https://h.example.test/v1",
            "https://h.example.test/v1/chat/completions",
            "authorization",
        ),
        ("openai-responses", "https://h.example.test/v1/", "https://h.example.test/v1/responses", "authorization"),
        ("anthropic-messages", "https://h.example.test/v1", "https://h.example.test/v1/messages", "x-api-key"),
        ("anthropic-messages", "https://lucif.example.test", "https://lucif.example.test/v1/messages", "x-api-key"),
        ("systemone", "https://d.example.test", "https://d.example.test/v1/systemone", "authorization"),
        ("openai-decisions", "https://d.example.test/", "https://d.example.test/v1/decisions", "authorization"),
        (
            "openrouter-decisions",
            "https://d.example.test",
            "https://d.example.test/api/alpha/decisions",
            "authorization",
        ),
    ],
)
def test_connection_test_builds_one_small_call_per_api_type(rig, type_, base, url, header):
    provider = Provider(id="p", type=type_, base_url=base, models=["m"], api_key="plainkey-123456")
    result = asyncio.run(rig.tester.run(provider, "m", "plainkey-123456"))
    assert result["ok"] is True
    [request] = rig.provider_calls
    assert str(request.url) == url
    assert request.headers[header].endswith("plainkey-123456")
    body = json.loads(request.content)
    assert body["model"] == "m"
    assert "ping" not in json.dumps(body).lower()
    if provider.type.endswith("decisions") or provider.type == "systemone":
        assert "questions" in body and "messages" not in body
    else:
        assert max(value for name, value in body.items() if name.startswith("max")) == 16
    assert build_test_request(provider, "m", "k")[0] == url


def test_connection_test_reports_latency_and_persists_the_last_result(rig):
    response = rig.call("POST", "/gw/v1/providers/nutaraline/test", client=rig.remote, token=rig.reader)
    body = response.json()
    assert response.status_code == 200
    assert (body["ok"], body["status"], body["model"]) == (True, 200, "deepseek-v4.1-flash-1017")
    assert isinstance(body["latency_ms"], int)
    [request] = rig.provider_calls
    assert request.headers["authorization"] == "Bearer env-key-0123456789abcdef"
    row = next(item for item in rig.audit() if item["action"] == "provider.test")
    assert (row["actor"], row["targets"], row["result"]) == ("remote", ["A", "nutaraline"], "ok")
    rig.admin.test_started.clear()
    second = rig.call("POST", "/gw/v1/providers/nutaraline/test")
    assert second.status_code == 200
    local_row = next(item for item in rig.audit() if item["action"] == "provider.test")
    assert local_row["actor"] == "owner"
    view = rig.call("GET", "/gw/v1/providers", client=rig.remote, token=rig.reader).json()["providers"][0]
    assert view["last_test"]["ok"] is True
    assert view["last_test"]["tested_at"].endswith("Z")
    restarted = Admin(rig.gateway, models_yml=rig.models)
    assert restarted.last_test("A", "nutaraline")["latency_ms"] == second.json()["latency_ms"]
    assert view["active_models"] == ["deepseek-v4.1-flash-1017"]
    assert view["host"] == "nutaraline.example.test"


def test_connection_test_failure_classes_and_cooldown(rig, monkeypatch):
    replies = {
        401: "unauthorized",
        403: "unauthorized",
        404: "not_found",
        429: "rate_limited",
        400: "rejected",
        503: "upstream_error",
    }
    for status, expected in replies.items():
        rig.admin.test_started.clear()
        rig.provider_reply = lambda request, status=status: httpx.Response(status, text="plain failure")
        body = rig.call("POST", "/gw/v1/providers/nutaraline/test").json()
        assert (body["ok"], body["status"], body["error"]) == (False, status, expected)
    rig.admin.test_started.clear()
    rig.provider_reply = lambda request: httpx.Response(200, text="<html>not json</html>")
    assert rig.call("POST", "/gw/v1/providers/nutaraline/test").json()["error"] == "invalid_response"

    def boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    rig.admin.test_started.clear()
    rig.provider_reply = boom
    assert rig.call("POST", "/gw/v1/providers/nutaraline/test").json()["error"] == "timeout"
    rig.admin.test_started.clear()
    rig.provider_reply = lambda request: (_ for _ in ()).throw(httpx.ConnectError("no route", request=request))
    assert rig.call("POST", "/gw/v1/providers/nutaraline/test").json()["error"] == "connect_error"

    limited = rig.call("POST", "/gw/v1/providers/nutaraline/test")
    assert limited.status_code == 429
    assert error_code(limited) == "rate_limited"
    assert limited.json()["error"]["retry_after_ms"] > 0

    rig.admin.test_started.clear()
    rig.env.pop("NUTARALINE_API_KEY")
    calls = len(rig.provider_calls)
    assert rig.call("POST", "/gw/v1/providers/nutaraline/test").json()["error"] == "no_key"
    assert len(rig.provider_calls) == calls
    rig.admin.test_started.clear()
    assert rig.call("POST", "/gw/v1/providers/ghost/test").status_code == 404
    assert rig.call("POST", "/gw/v1/providers/nutaraline/test", json={"model": "ghost"}).status_code == 400


def test_a_provider_whose_base_url_is_still_from_import_is_not_called(rig):
    raw = rig.raw()
    raw["providers"][0]["base_url"] = "from_import"
    rig.config.write_text(yaml.safe_dump(raw, sort_keys=False))
    body = rig.call("POST", "/gw/v1/providers/nutaraline/test").json()
    assert (body["ok"], body["error"]) == (False, "base_url_unresolved")
    assert rig.provider_calls == []
    assert rig.call("GET", "/gw/v1/providers").json()["providers"][0]["host"] is None


def test_connection_test_never_follows_redirects_with_the_key(rig):
    rig.provider_reply = lambda request: httpx.Response(302, headers={"location": "https://elsewhere.example/steal"})
    body = rig.call("POST", "/gw/v1/providers/nutaraline/test").json()
    assert (body["ok"], body["status"], body["error"]) == (False, 302, "rejected")
    assert len(rig.provider_calls) == 1


def test_provider_registry_add_update_and_delete(rig):
    initial = [item["id"] for item in rig.raw()["providers"]]
    created = rig.call(
        "PUT",
        "/gw/v1/providers/new-one",
        json={"type": "openai-responses", "base_url": "https://api.example.test/v1", "models": ["m1", "m2"]},
    )
    assert created.status_code == 200
    view = created.json()["provider"]
    assert (view["host"], view["models"], view["key"]["env_name"], view["key"]["env_set"]) == (
        "api.example.test",
        ["m1", "m2"],
        "NEW_ONE_API_KEY",
        False,
    )
    updated = rig.call(
        "PUT",
        "/gw/v1/providers/new-one",
        json={"type": "anthropic-messages", "base_url": "https://api.example.test:8443/v1", "models": ["m3"]},
    )
    assert updated.json()["provider"]["host"] == "api.example.test:8443"
    assert [item["id"] for item in rig.raw()["providers"]] == [*initial, "new-one"]
    assert rig.call("DELETE", "/gw/v1/providers/new-one").status_code == 200
    assert [item["id"] for item in rig.raw()["providers"]] == initial
    before = rig.config.read_bytes()
    referenced = rig.call("DELETE", "/gw/v1/providers/nutaraline")
    assert referenced.status_code == 400
    assert "unknown provider" in referenced.json()["error"]["message"]
    assert rig.config.read_bytes() == before
    assert rig.call("DELETE", "/gw/v1/providers/ghost").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"type": "openai-completions", "base_url": "https://user:pw@api.example.test/v1", "models": ["m"]},
        {"type": "carrier-pigeon", "base_url": "https://api.example.test/v1", "models": ["m"]},
        {"type": "openai-completions", "base_url": "ftp://api.example.test", "models": ["m"]},
        {"type": "openai-completions", "base_url": "https://api.example.test/v1", "models": []},
        {"type": "openai-completions", "base_url": "https://api.example.test/v1", "models": ["m"], "api_key": MARK},
    ],
)
def test_provider_edits_reject_bad_shapes_and_keys_in_the_body(rig, body):
    before = rig.config.read_bytes()
    response = rig.call("PUT", "/gw/v1/providers/new-one", json=body)
    assert response.status_code == 400
    assert MARK not in response.text
    assert rig.config.read_bytes() == before


def test_provider_id_import_is_reserved_and_path_ids_are_validated(rig):
    body = {"type": "openai-completions", "base_url": "https://api.example.test/v1", "models": ["m"]}
    assert rig.call("PUT", "/gw/v1/providers/import", json=body).status_code in (400, 405)
    assert rig.call("PUT", "/gw/v1/providers/Bad_Id", json=body).status_code == 400


def test_import_preview_lists_names_types_urls_and_models_but_no_key_values(rig):
    response = rig.call("GET", "/gw/v1/providers/import")
    assert response.status_code == 200
    assert LITERAL_MARK not in response.text
    assert "ENV_ONE_SECRET" not in response.text
    rows = {item["name"]: item for item in response.json()["providers"]}
    assert rows["nutaraline"]["exists"] is True
    assert rows["fresh-one"]["models"] == ["claude-x", "claude-y"]
    assert rows["fresh-one"]["key_source"] == "literal"
    assert rows["env-one"]["key_source"] == "env"
    assert rows["cmd-one"]["key_source"] == "command"
    assert rows["keyless"]["key_source"] == "none"
    assert rows["odd-api"]["blocker"] == "unsupported api type 'carrier-pigeon'"
    assert rig.call("GET", "/gw/v1/providers/import?path=/etc/passwd").json() == response.json()
    rig.models.unlink()
    assert rig.call("GET", "/gw/v1/providers/import").status_code == 404


def test_import_without_key_uses_the_env_convention_and_never_reads_the_key(rig):
    response = rig.call(
        "POST",
        "/gw/v1/providers/import",
        json={"providers": [{"name": "fresh-one"}, {"name": "nutaraline"}, {"name": "odd-api"}, {"name": "ghost"}]},
    )
    assert response.status_code == 200
    assert LITERAL_MARK not in response.text
    results = {item["name"]: item for item in response.json()["results"]}
    assert results["fresh-one"] == {"name": "fresh-one", "id": "fresh-one", "result": "created", "with_key": False}
    assert results["nutaraline"]["reason"] == "provider already exists"
    assert results["odd-api"]["result"] == "skipped"
    assert results["ghost"]["reason"] == "not in models.yml"
    entry = next(item for item in rig.raw()["providers"] if item["id"] == "fresh-one")
    assert entry["api_key_env"] == "FRESH_ONE_API_KEY"
    assert entry["api_key"] is None
    assert entry["base_url"] == "https://fresh.example.test/v1"
    assert LITERAL_MARK not in rig.config.read_text()
    assert LITERAL_MARK not in json.dumps(rig.audit())


def test_import_with_key_copies_only_the_ticked_providers(rig):
    response = rig.call(
        "POST",
        "/gw/v1/providers/import",
        json={
            "providers": [
                {"name": "fresh-one", "with_key": True, "models": ["claude-y"]},
                {"name": "env-one", "with_key": True},
                {"name": "keyless"},
            ]
        },
    )
    assert response.status_code == 200
    assert LITERAL_MARK not in response.text
    by_id = {item["id"]: item for item in rig.raw()["providers"]}
    assert by_id["fresh-one"]["api_key"] == LITERAL_MARK + "-fresh"
    assert by_id["fresh-one"]["api_key_env"] is None
    assert by_id["fresh-one"]["models"] == ["claude-y"]
    assert (by_id["env-one"]["api_key"], by_id["env-one"]["api_key_env"]) == (None, "ENV_ONE_SECRET")
    assert by_id["keyless"]["api_key"] is None
    assert LITERAL_MARK not in json.dumps(rig.audit())
    assert LITERAL_MARK not in rig.call("GET", "/gw/v1/providers").text
    assert LITERAL_MARK not in rig.call("GET", "/gw/v1/settings").text


@pytest.mark.parametrize(
    "item",
    [
        {"name": "cmd-one", "with_key": True},
        {"name": "keyless", "with_key": True},
        {"name": "fresh-one", "models": ["not-there"]},
        {"name": "fresh-one", "models": []},
    ],
)
def test_import_refuses_unimportable_keys_and_bad_model_subsets_without_partial_writes(rig, item):
    before = rig.config.read_bytes()
    response = rig.call("POST", "/gw/v1/providers/import", json={"providers": [{"name": "env-one"}, item]})
    assert response.status_code == 400
    assert rig.config.read_bytes() == before


def test_import_replace_updates_an_existing_provider_but_keeps_its_key_unless_ticked(rig):
    rig.call("PUT", "/gw/v1/providers/nutaraline/key", json={"api_key": "keep-this-key-0001"})
    rig.call("POST", "/gw/v1/providers/import", json={"providers": [{"name": "nutaraline", "replace": True}]})
    entry = rig.raw()["providers"][0]
    assert entry["base_url"] == "https://nutaraline.example.test/v1"
    assert entry["api_key"] == "keep-this-key-0001"
    assert entry["models"] == ["deepseek-v4.1-flash-1017", "other-model"]


def test_voters_are_added_replaced_and_removed_through_configuration_only(rig):
    listing = rig.call("GET", "/gw/v1/voters").json()
    configured = rig.raw()["swarm"]["voters"]
    assert listing["swarm"]["enabled_voters"] == sum(1 for item in configured if item["enabled"])
    assert len(listing["voters"]) == len(configured)
    body = {
        "adapter": "llm_structured",
        "provider": "nutaraline",
        "model": "deepseek-v4.1-flash-1017",
        "variation": "temperature",
        "timeout_s": 45,
        "weight": 2.0,
        "enabled": True,
    }
    added = rig.call("PUT", "/gw/v1/voters/v8", json=body)
    assert added.status_code == 200
    assert [item["id"] for item in rig.raw()["swarm"]["voters"]][-1] == "v8"
    replaced = rig.call("PUT", "/gw/v1/voters/v8", json={**body, "weight": 1.5, "enabled": False})
    assert replaced.status_code == 200
    saved = next(item for item in rig.raw()["swarm"]["voters"] if item["id"] == "v8")
    assert (saved["weight"], saved["enabled"], saved["variation"]) == (1.5, False, "temperature")
    assert len([item for item in rig.raw()["swarm"]["voters"] if item["id"] == "v8"]) == 1
    assert rig.call("DELETE", "/gw/v1/voters/v8").status_code == 200
    assert rig.call("DELETE", "/gw/v1/voters/v8").status_code == 404
    assert len(rig.raw()["swarm"]["voters"]) == len(configured)


def test_voter_edits_that_break_references_or_quorum_are_rejected(rig):
    body = {
        "adapter": "llm_structured",
        "provider": "nutaraline",
        "model": "deepseek-v4.1-flash-1017",
        "variation": "option_order",
        "timeout_s": 30,
        "weight": 1.0,
        "enabled": True,
    }
    before = rig.config.read_bytes()
    assert rig.call("PUT", "/gw/v1/voters/v9", json={**body, "provider": "ghost"}).status_code == 400
    assert rig.call("PUT", "/gw/v1/voters/v9", json={**body, "model": "ghost"}).status_code == 400
    assert rig.call("PUT", "/gw/v1/voters/v9", json={**body, "adapter": "carrier"}).status_code == 400
    assert rig.call("PUT", "/gw/v1/voters/V9", json=body).status_code == 400
    assert rig.call("PUT", "/gw/v1/voters/v1", json={**body, "enabled": False}).status_code == 200
    assert rig.call("PUT", "/gw/v1/voters/v2", json={**body, "enabled": False}).status_code == 200
    after_two = rig.config.read_bytes()
    quorum = rig.call("PUT", "/gw/v1/voters/v3", json={**body, "enabled": False})
    assert quorum.status_code == 400
    assert "min_voters_answered" in quorum.json()["error"]["message"]
    assert rig.config.read_bytes() == after_two != before
    assert rig.call("DELETE", "/gw/v1/voters/v4").status_code == 400
    assert rig.config.read_bytes() == after_two


def test_roles_pick_provider_and_model_for_the_analyst_and_each_voter(rig):
    rig.call(
        "PUT",
        "/gw/v1/providers/second",
        json={"type": "openai-completions", "base_url": "https://second.example.test/v1", "models": ["m-a", "m-b"]},
    )
    before = rig.call("GET", "/gw/v1/roles").json()
    assert before["analyst"] == {"provider": "nutaraline", "model": "deepseek-v4.1-flash-1017"}
    response = rig.call(
        "PUT",
        "/gw/v1/roles",
        json={
            "analyst": {"provider": "second", "model": "m-a"},
            "voters": {"v1": {"provider": "second", "model": "m-b"}},
        },
    )
    assert response.status_code == 200
    after = rig.call("GET", "/gw/v1/roles").json()
    assert after["analyst"] == {"provider": "second", "model": "m-a"}
    assert next(item for item in after["voters"] if item["id"] == "v1")["provider"] == "second"
    view = {item["id"]: item for item in rig.call("GET", "/gw/v1/providers").json()["providers"]}
    assert view["second"]["active_models"] == ["m-a", "m-b"]
    config_before = rig.config.read_bytes()
    assert (
        rig.call("PUT", "/gw/v1/roles", json={"analyst": {"provider": "second", "model": "ghost"}}).status_code == 400
    )
    assert (
        rig.call("PUT", "/gw/v1/roles", json={"voters": {"zz": {"provider": "second", "model": "m-a"}}}).status_code
        == 404
    )
    assert rig.config.read_bytes() == config_before


def test_voters_listing_carries_the_last_connection_test_of_their_provider(rig):
    rig.call("POST", "/gw/v1/providers/nutaraline/test")
    voter = rig.call("GET", "/gw/v1/voters", client=rig.remote, token=rig.reader).json()["voters"][0]
    assert voter["last_test"]["ok"] is True
    assert "api_key" not in voter


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_inline_keys_are_refused_in_a_git_work_tree_unless_the_file_is_ignored(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    rig = Rig(tmp_path, config_dir=repo)
    try:
        before = rig.config.read_bytes()
        refused = rig.call("PUT", "/gw/v1/providers/nutaraline/key", json={"api_key": MARK})
        assert refused.status_code == 400
        assert "not ignored" in refused.json()["error"]["message"]
        assert MARK not in refused.text
        assert rig.config.read_bytes() == before
        assert (
            rig.call("PUT", "/gw/v1/providers/nutaraline/key", json={"api_key_env": "NUTARALINE_API_KEY"}).status_code
            == 200
        )
        (repo / ".gitignore").write_text("bot-a.yaml\n")
        allowed = rig.call("PUT", "/gw/v1/providers/nutaraline/key", json={"api_key": MARK})
        assert allowed.status_code == 200
        assert MARK in rig.config.read_text()
    finally:
        rig.close()


def test_a_hostile_idempotency_key_never_reaches_the_audit_table(rig):
    huge = "x" * 6000
    denied = rig.call(
        "PATCH",
        "/gw/v1/settings",
        token=rig.reader,
        client=rig.remote,
        json={"changes": {}},
        headers={"Idempotency-Key": huge},
    )
    assert denied.status_code == 403
    invalid = rig.call("PATCH", "/gw/v1/settings", json={"changes": {}}, headers={"Idempotency-Key": huge})
    assert invalid.status_code == 400
    rows = rig.audit(10)
    assert rows[0]["action"] == "config.update" and rows[1]["action"] == "admin.denied"
    assert [row["idempotency_key"] for row in rows[:2]] == [None, None]
    assert huge not in json.dumps(rows)


def test_bot_logs_forwarded_to_the_pwa_are_scrubbed_of_registered_provider_keys(rig):
    registry.add(MARK)
    rig.fake.logs = [
        ["2026-10-26 00:17:53", 1792973873000.0, "freqtrade", "INFO", f"provider said {MARK} and ws?token=abc123def"]
    ]
    text = rig.call("GET", "/gw/v1/logs?limit=5", client=rig.remote, token=rig.reader).text
    assert MARK not in text
    assert "abc123def" not in text
