from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from gateway.app import Gateway, create_app
from gateway.push import (
    CATALOGS,
    DEFAULT_LANG,
    KINDS,
    LOCALES,
    MAX_SUBSCRIPTIONS,
    format_number,
    load_catalogs,
    render,
    resolve_lang,
)
from gateway.settings import GatewaySettings
from tests.conftest import EXAMPLE
from tests.test_gateway import ENV, PASSWORD, FakeFreqtrade

PARAMS = {
    "fill": {"side": "buy", "pair": "BTC/IDR", "amount": 333323.4, "rate": 1463933000.0},
    "risk_breach": {"metric": "daily_loss", "value": 1.02, "limit": 1.0},
    "kill_switch": {"bot": "Bot A"},
    "heartbeat_lost": {"bot": "Bot A", "minutes": 3},
    "quorum_failed": {"pair": "ETH/IDR", "answered": 2, "required": 5},
    "daily_summary": {"bot": "Bot A", "pnl_pct": -0.31, "closed": 2},
}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Device:
    def __init__(self) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)

    @property
    def keys(self) -> dict[str, str]:
        point = self.private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return {"p256dh": _b64(point), "auth": _b64(self.auth)}

    def open(self, body: bytes) -> dict:
        return json.loads(http_ece.decrypt(body, private_key=self.private, auth_secret=self.auth))


class Freqtrade(FakeFreqtrade):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"status": "paused, no more entries will occur from now."})
        return super().__call__(request)


class PushService:
    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.requests: list[tuple[str, dict[str, str], bytes]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                service.requests.append((self.path, dict(self.headers), body))
                self.send_response(service.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def endpoint(self, name: str) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/{name}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def rig(tmp_path):
    config = tmp_path / "bot-a.yaml"
    shutil.copy(EXAMPLE, config)
    settings = GatewaySettings(
        state_dir=str(tmp_path / "state"),
        exchange_probe_url=None,
        push_allow_local_endpoints=True,
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
    upstream = gateway.upstreams["A"]
    upstream.client = httpx.AsyncClient(
        base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(Freqtrade())
    )
    client = TestClient(create_app(gateway), base_url="http://127.0.0.1:8090", client=("127.0.0.1", 41000))
    token = client.post("/gw/v1/session", json={"password": PASSWORD}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    service = PushService()
    yield gateway, client, service
    service.close()
    gateway.ledger.close()


def _subscribe(client, endpoint: str, device: Device, **extra):
    body = {"subscription": {"endpoint": endpoint, "keys": device.keys}, **extra}
    return client.post("/gw/v1/push/subscriptions", json=body)


@pytest.mark.parametrize("lang", sorted(CATALOGS))
@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_renders_in_every_language(kind, lang):
    text = render(kind, PARAMS[kind], lang)
    assert text["lang"] == lang
    assert text["title"] and text["body"]
    assert "{" not in text["title"] + text["body"]


@pytest.mark.parametrize("kind", KINDS)
def test_indonesian_text_differs_from_english(kind):
    english, indonesian = render(kind, PARAMS[kind], "en"), render(kind, PARAMS[kind], "id")
    assert english["title"] != indonesian["title"]
    assert english["body"] != indonesian["body"]


def test_numbers_follow_the_language_style():
    assert render("fill", PARAMS["fill"], "en")["body"] == "Dry run: Rp 333,323 at 1,463,933,000."
    assert render("fill", PARAMS["fill"], "id")["body"] == "Dry-run: Rp 333.323 di 1.463.933.000."
    assert render("daily_summary", PARAMS["daily_summary"], "id")["body"] == "Bot A: -0,31% kemarin, trade ditutup: 2."
    assert format_number(0.5, {"group": ",", "decimal": "."}, signed=True) == "+0.50"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (None, "en"),
        ("", "en"),
        ("   ", "en"),
        ("xx", "en"),
        ("id", "id"),
        ("ID", "id"),
        ("id-ID", "id"),
        ("pt_BR", "en"),
    ],
)
def test_unknown_or_empty_language_falls_back_to_english(code, expected):
    assert resolve_lang(code) == expected


def test_a_language_is_one_catalog_file(tmp_path):
    for name in ("en", "id"):
        shutil.copy(LOCALES / f"{name}.json", tmp_path / f"{name}.json")
    french = json.loads((LOCALES / "en.json").read_text())
    french["kinds"]["kill_switch"]["title"] = "Coupe-circuit actif"
    french["number"] = {"group": " ", "decimal": ","}
    (tmp_path / "fr.json").write_text(json.dumps(french))
    catalogs = load_catalogs(tmp_path)
    assert resolve_lang("fr-CA", catalogs) == "fr"
    assert render("kill_switch", PARAMS["kill_switch"], "fr", catalogs)["title"] == "Coupe-circuit actif"
    assert resolve_lang("fr") == DEFAULT_LANG


def test_a_catalog_missing_a_kind_is_refused(tmp_path):
    shutil.copy(LOCALES / "en.json", tmp_path / "en.json")
    broken = json.loads((LOCALES / "en.json").read_text())
    del broken["kinds"]["fill"]
    (tmp_path / "de.json").write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="locale de"):
        load_catalogs(tmp_path)


def test_default_catalog_is_required(tmp_path):
    shutil.copy(LOCALES / "id.json", tmp_path / "id.json")
    with pytest.raises(ValueError, match="locale en is missing"):
        load_catalogs(tmp_path)


def test_push_routes_need_a_session(rig):
    _, client, _ = rig
    anonymous = TestClient(client.app)
    assert anonymous.get("/gw/v1/push/key").status_code == 401
    assert anonymous.post("/gw/v1/push/test").status_code == 401


def test_key_is_stable_across_restarts(rig, tmp_path):
    gateway, client, _ = rig
    first = client.get("/gw/v1/push/key").json()["public_key"]
    assert len(base64.urlsafe_b64decode(first + "==")) == 65
    assert oct((tmp_path / "state" / "vapid_private.pem").stat().st_mode & 0o777) == "0o600"
    from gateway.push import Courier

    assert Courier(tmp_path / "state" / "vapid_private.pem", "mailto:a@b.c").public_key == first


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        ({"lang": "id"}, "id"),
        ({"lang": "id-ID"}, "id"),
        ({}, "en"),
        ({"lang": ""}, "en"),
        ({"lang": "xx"}, "en"),
        ({"lang": None}, "en"),
    ],
)
def test_subscription_stores_the_resolved_language(rig, sent, stored):
    gateway, client, service = rig
    response = _subscribe(client, service.endpoint("a"), Device(), kinds=["fill", "daily_summary"], **sent)
    assert response.status_code == 201
    assert response.json() == {"endpoint": service.endpoint("a"), "kinds": ["fill", "daily_summary"], "lang": stored}
    [item] = gateway.ledger.push_subscriptions("fill")
    assert item["lang"] == stored


def test_resubscribing_replaces_the_language_and_kinds(rig):
    gateway, client, service = rig
    device = Device()
    _subscribe(client, service.endpoint("a"), device, lang="id")
    _subscribe(client, service.endpoint("a"), device, lang="en", kinds=["fill"])
    assert [item["lang"] for item in gateway.ledger.push_subscriptions("fill")] == ["en"]
    assert gateway.ledger.push_subscriptions("kill_switch") == []


def test_unsubscribe_removes_the_subscription(rig):
    gateway, client, service = rig
    _subscribe(client, service.endpoint("a"), Device())
    removed = client.request("DELETE", "/gw/v1/push/subscriptions", json={"endpoint": service.endpoint("a")})
    assert removed.json() == {"removed": True}
    again = client.request("DELETE", "/gw/v1/push/subscriptions", json={"endpoint": service.endpoint("a")})
    assert again.json() == {"removed": False}


def test_subscription_count_is_capped(rig):
    gateway, client, service = rig
    for number in range(MAX_SUBSCRIPTIONS):
        assert _subscribe(client, service.endpoint(str(number)), Device()).status_code == 201
    over = _subscribe(client, service.endpoint("over"), Device())
    assert (over.status_code, over.json()["error"]["code"]) == (409, "push_limit")
    assert _subscribe(client, service.endpoint("0"), Device(), lang="id").status_code == 201


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://push.example.com/x",
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://10.0.0.5/x",
        "https://user:pw@push.example.com/x",
    ],
)
def test_endpoints_that_could_reach_this_machine_are_refused(tmp_path, endpoint):
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
                "userdir": str(tmp_path / "a"),
            }
        ],
    )
    gateway = Gateway(settings, ENV)
    try:
        client = TestClient(create_app(gateway))
        token = client.post("/gw/v1/session", json={"password": PASSWORD}).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        response = _subscribe(client, endpoint, Device())
        assert (response.status_code, response.json()["error"]["code"]) == (400, "invalid_request")
        assert gateway.ledger.push_subscriptions("fill") == []
    finally:
        gateway.ledger.close()


def test_malformed_subscription_is_refused(rig):
    _, client, service = rig
    bad = {"subscription": {"endpoint": service.endpoint("a"), "keys": {"p256dh": "not base64!", "auth": "x"}}}
    assert client.post("/gw/v1/push/subscriptions", json=bad).status_code == 400
    unknown = {"subscription": {"endpoint": service.endpoint("a"), "keys": Device().keys}, "kinds": ["nope"]}
    assert client.post("/gw/v1/push/subscriptions", json=unknown).status_code == 400


def test_test_push_reaches_each_device_in_its_own_language(rig):
    gateway, client, service = rig
    english, indonesian = Device(), Device()
    _subscribe(client, service.endpoint("en"), english, lang="en")
    _subscribe(client, service.endpoint("id"), indonesian, lang="id")
    assert client.post("/gw/v1/push/test").json() == {"sent": 2, "failed": 0}
    delivered = {path: (headers, body) for path, headers, body in service.requests}
    en = english.open(delivered["/en"][1])
    id_ = indonesian.open(delivered["/id"][1])
    assert (en["kind"], en["lang"], en["title"], en["body"]) == (
        "daily_summary",
        "en",
        "Daily summary",
        "Bot A: -0.31% yesterday, trades closed: 2.",
    )
    assert (id_["lang"], id_["title"], id_["body"]) == (
        "id",
        "Ringkasan harian",
        "Bot A: -0,31% kemarin, trade ditutup: 2.",
    )
    assert en["url"] == "/#ringkas" and en["id"] and en["ts"]
    headers = {name.lower(): value for name, value in delivered["/en"][0].items()}
    key = client.get("/gw/v1/push/key").json()["public_key"]
    assert headers["authorization"].startswith("vapid t=") and f"k={key}" in headers["authorization"]
    assert headers["urgency"] == "normal" and headers["ttl"] == "600"


def test_each_kind_is_delivered_only_to_subscribers_of_that_kind(rig):
    gateway, client, service = rig
    device = Device()
    _subscribe(client, service.endpoint("a"), device, kinds=["fill"], lang="id")
    assert asyncio.run(gateway.push.notify("daily_summary", PARAMS["daily_summary"])) == {"sent": 0, "failed": 0}
    assert asyncio.run(gateway.push.notify("fill", PARAMS["fill"])) == {"sent": 1, "failed": 0}
    payload = device.open(service.requests[0][2])
    assert (payload["kind"], payload["title"]) == ("fill", "Beli BTC/IDR terisi")
    assert service.requests[0][1]["urgency"] == "high"


def test_a_gone_subscription_is_dropped_and_a_failing_one_kept(rig):
    gateway, client, service = rig
    _subscribe(client, service.endpoint("a"), Device())
    service.status = 410
    assert asyncio.run(gateway.push.notify("kill_switch", PARAMS["kill_switch"])) == {"sent": 0, "failed": 1}
    assert gateway.ledger.push_subscriptions("kill_switch") == []
    _subscribe(client, service.endpoint("b"), Device())
    service.status = 500
    assert asyncio.run(gateway.push.notify("kill_switch", PARAMS["kill_switch"])) == {"sent": 0, "failed": 1}
    assert len(gateway.ledger.push_subscriptions("kill_switch")) == 1


def _record(gateway) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    async def notify(kind, params):
        calls.append((kind, params))
        return {"sent": 0, "failed": 0}

    gateway.push.notify = notify
    return calls


def test_fill_events_become_fill_notifications(rig):
    gateway, _, _ = rig
    calls = _record(gateway)

    async def scenario():
        message = {
            "type": "entry_fill",
            "trade_id": 7,
            "pair": "BTC/IDR",
            "stake_amount": 333323.0,
            "open_rate": 1.46e9,
        }
        await gateway.on_message("A", message, 0)
        await gateway.on_message("A", {"type": "exit_fill", "trade_id": 7, "pair": "BTC/IDR"}, 0)
        await asyncio.gather(*gateway.tasks, return_exceptions=True)

    asyncio.run(scenario())
    assert calls == [("fill", {"side": "buy", "pair": "BTC/IDR", "amount": 333323.0, "rate": 1.46e9})]


def test_a_lost_heartbeat_is_announced_once(rig):
    gateway, _, _ = rig
    calls = _record(gateway)

    async def scenario():
        await gateway.watch_heartbeats()
        await gateway.watch_heartbeats()
        await asyncio.gather(*gateway.tasks)

    asyncio.run(scenario())
    assert calls == [("heartbeat_lost", {"bot": "Bot A", "minutes": 3})]


def test_only_new_breaches_are_announced(rig):
    gateway, _, _ = rig
    calls = _record(gateway)
    bot = gateway.bot("A")
    risk = {"daily_loss_pct": 1.2, "drawdown_pct": 11.0}

    async def scenario():
        gateway.notify_breaches(bot, {"daily_loss"}, risk)
        gateway.notify_breaches(bot, {"total_drawdown", "unknown"}, risk)
        await asyncio.gather(*gateway.tasks)

    asyncio.run(scenario())
    assert [kind for kind, _ in calls] == ["risk_breach", "risk_breach"]
    assert calls[0][1] == {"metric": "daily_loss", "value": 1.2, "limit": 1.0}
    assert calls[1][1]["metric"] == "total_drawdown"


def test_stopping_entries_is_announced_as_the_kill_switch(rig):
    gateway, client, _ = rig
    calls = _record(gateway)
    response = client.post("/gw/v1/control/stop-entry", headers={"Idempotency-Key": "k" * 16}, json={})
    assert response.status_code == 200, response.text
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)
    assert calls == [("kill_switch", {"bot": "Bot A"})]


def test_daily_summary_goes_out_once_after_the_day_changes(rig):
    gateway, _, _ = rig
    calls = _record(gateway)
    from datetime import UTC, datetime, timedelta

    start = datetime.now(UTC)

    async def scenario():
        gateway.clock = lambda: start
        await gateway.watch_daily_summary()
        assert calls == []
        await gateway.watch_daily_summary()
        gateway.clock = lambda: start + timedelta(days=1)
        await gateway.watch_daily_summary()
        await gateway.watch_daily_summary()
        await asyncio.gather(*gateway.tasks)

    asyncio.run(scenario())
    assert len(calls) == 1
    kind, params = calls[0]
    assert kind == "daily_summary" and params["bot"] == "Bot A" and set(params) == {"bot", "pnl_pct", "closed"}


def test_web_push_off_in_the_bot_config_sends_nothing(rig):
    gateway, _, _ = rig
    calls = _record(gateway)
    config = gateway.bot("A")
    import yaml

    raw = yaml.safe_load(open(config.config))
    raw["notify"]["web_push"] = False
    yaml.safe_dump(raw, open(config.config, "w"))
    gateway.bot_settings.clear()

    async def scenario():
        gateway.notify(config, "kill_switch", {"bot": "Bot A"})
        await asyncio.gather(*gateway.tasks)

    asyncio.run(scenario())
    assert calls == []
