from __future__ import annotations

import asyncio
import json
import shutil
import time

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gateway.app import Gateway, create_app
from gateway.events import translate
from gateway.feed import Hub
from gateway.settings import GatewaySettings
from tests.conftest import EXAMPLE

PASSWORD = "correct horse battery"
ENV = {"GW_PASSWORD": PASSWORD, "FT_API_USERNAME": "bot", "FT_API_PASSWORD": "pw"}
NOW_MS = int(time.time() * 1000)
FILLED_MS = NOW_MS - 5_000


class FakeFreqtrade:
    def __init__(self) -> None:
        self.down = False
        self.closed = [
            {
                "trade_id": 7,
                "pair": "BTC/IDR",
                "is_open": False,
                "close_timestamp": NOW_MS - 60_000,
                "close_profit_abs": -25_000.0,
            }
        ]
        self.paths: list[str] = []
        self.logs = [
            [
                "2026-10-26 00:17:53",
                1792973873000.0,
                "uvicorn.error",
                "INFO",
                '127.0.0.1:41506 - "WebSocket /api/v1/message/ws?token=eyJhbGciOi.secret" [accepted]',
            ]
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        path = request.url.path.removeprefix("/api/v1")
        self.paths.append(path)
        if path == "/trades":
            assert request.url.params["order_by_id"] == "true"
            limit, offset = int(request.url.params["limit"]), int(request.url.params["offset"])
            page = sorted(self.closed, key=lambda trade: trade["trade_id"])[offset : offset + min(limit, 500)]
            return httpx.Response(
                200,
                json={"trades": page, "trades_count": len(page), "offset": offset, "total_trades": len(self.closed)},
            )
        if path == "/logs":
            return httpx.Response(200, json={"log_count": len(self.logs), "logs": self.logs})
        routes = {
            "/version": {"version": "2026.9"},
            "/show_config": {
                "dry_run": True,
                "state": "running",
                "exchange": "indodax",
                "tradable_balance_ratio": 0.99,
            },
            "/health": {"last_process": "2026-10-25 17:07:33.618830+00:00", "bot_start": "2026-10-25 17:05:23+00:00"},
            "/status": [
                {
                    "trade_id": 9,
                    "pair": "ETH/IDR",
                    "open_trade_value": 200_000.0,
                    "profit_abs": -2_000.0,
                    "open_timestamp": NOW_MS - 60_000,
                    "is_open": True,
                }
            ],
            "/trade/7": {
                "trade_id": 7,
                "orders": [
                    {"ft_order_side": "buy", "order_filled_timestamp": FILLED_MS - 3_600_000},
                    {"ft_order_side": "sell", "order_filled_timestamp": FILLED_MS},
                ],
            },
            "/whitelist": {"whitelist": ["BTC/IDR", "ETH/IDR"]},
            "/blacklist": {"blacklist": []},
            "/locks": {"lock_count": 0, "locks": []},
            "/count": {"current": 1, "max": 3},
            "/profit": {
                "profit_all_coin": -27_000.0,
                "profit_all_percent": -1.35,
                "closed_trade_count": 1,
                "winrate": 0,
            },
            "/balance": {
                "stake": "IDR",
                "total": 1_973_000.0,
                "total_bot": 1_953_000.0,
                "note": "Simulated balances",
                "currencies": [
                    {"currency": "IDR", "is_bot_managed": True},
                    {"currency": "DOGE", "is_bot_managed": False},
                ],
            },
            "/pair_candles": {
                "pair": "BTC/IDR",
                "timeframe": "1h",
                "strategy": "SwingEmaRsi",
                "length": 1,
                "last_analyzed": "2026-10-25 17:00:05+00:00",
                "columns": [
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "ema_fast",
                    "ema_slow",
                    "rsi",
                    "enter_long",
                    "exit_long",
                    "enter_tag",
                    "__date_ts",
                ],
                "data": [
                    [
                        "2026-10-25 16:00:00+00:00",
                        1.0,
                        2.0,
                        0.5,
                        1.5,
                        10.0,
                        1.1,
                        1.0,
                        50.0,
                        None,
                        1,
                        None,
                        1792944000000,
                    ]
                ],
            },
        }
        if path not in routes:
            return httpx.Response(404, json={"detail": "nope"})
        return httpx.Response(200, json=routes[path])


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
                "strategy": "aturan saja",
                "api_url": "http://127.0.0.1:8080",
                "config": str(config),
                "userdir": str(tmp_path / "bot-a"),
            }
        ],
    )
    gateway = Gateway(settings, ENV)
    fake = FakeFreqtrade()
    upstream = gateway.upstreams["A"]
    upstream.client = httpx.AsyncClient(base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(fake))
    client = TestClient(create_app(gateway))
    yield gateway, fake, client, config
    gateway.ledger.close()


def _token(client: TestClient) -> str:
    response = client.post("/gw/v1/session", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["token"]


def _get(client: TestClient, path: str, token: str) -> httpx.Response:
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_gateway_refuses_short_password(setup):
    gateway = setup[0]
    with pytest.raises(Exception, match="at least 12"):
        Gateway(gateway.settings, {**ENV, "GW_PASSWORD": "short"})


def test_wrong_password_is_audited_then_rate_limited(setup):
    gateway, _, client, _ = setup
    for _ in range(5):
        response = client.post("/gw/v1/session", json={"password": "wrong-password"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
    blocked = client.post("/gw/v1/session", json={"password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert [row["result"] for row in gateway.ledger.audit_rows(10)] == ["denied"] * 5


def test_read_endpoints_need_a_live_session(setup):
    _, _, client, _ = setup
    assert client.get("/gw/v1/risk").json()["error"]["code"] == "unauthorized"
    token = _token(client)
    assert _get(client, "/gw/v1/risk", token).status_code == 200
    assert client.request("DELETE", "/gw/v1/session", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert _get(client, "/gw/v1/risk", token).status_code == 401


def test_concurrent_authenticated_requests_share_the_ledger_safely(setup):
    gateway, _, client, _ = setup
    token = _token(client)
    app = client.app

    async def burst():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as http:
            headers = {"Authorization": f"Bearer {token}"}
            responses = await asyncio.gather(*(http.get("/gw/v1/audit?limit=5", headers=headers) for _ in range(300)))
        return [response.status_code for response in responses]

    assert set(asyncio.run(burst())) == {200}


def test_risk_combines_todays_closed_loss_and_open_pnl(setup):
    _, _, client, _ = setup
    risk = _get(client, "/gw/v1/risk", _token(client)).json()
    assert risk["daily_pnl"] == -27_000.0
    assert risk["breaches"] == ["daily_loss"]
    assert risk["entries_allowed"] is False
    assert risk["limits"]["max_daily_loss_pct"] == 1.0


def test_overview_summarises_one_bot(setup):
    _, _, client, _ = setup
    token = _token(client)
    overview = _get(client, "/gw/v1/overview", token).json()
    assert overview["mode"] == "dry_run"
    assert overview["balance"]["bot_owned"] == 1_953_000.0
    assert overview["open_trades"] == {"count": 1, "max": 3}
    assert overview["risk"]["entries_allowed"] is False
    assert _get(client, "/gw/v1/overview?bot=Z", token).status_code == 404
    assert [item["currency"] for item in _get(client, "/gw/v1/balance", token).json()["currencies"]] == ["IDR"]


def test_open_trades_carry_derived_fields(setup):
    _, _, client, _ = setup
    [trade] = _get(client, "/gw/v1/trades/open", _token(client)).json()
    assert trade["profit_pct_now"] == -1.0
    assert 59 <= trade["age_s"] <= 120


def test_candles_follow_contract_columns_and_reject_other_timeframes(setup):
    _, _, client, _ = setup
    token = _token(client)
    frame = _get(client, "/gw/v1/candles?pair=BTC/IDR&timeframe=1h&limit=300", token).json()
    assert frame["columns"][-2:] == ["enter_long", "exit_long"]
    assert frame["data"] == [["2026-10-25T16:00:00Z", 1.0, 2.0, 0.5, 1.5, 10.0, 1.1, 1.0, 50.0, None, 1]]
    assert _get(client, "/gw/v1/candles?pair=BTC/IDR&timeframe=4h", token).json()["error"]["code"] == "invalid_request"
    assert _get(client, "/gw/v1/candles?pair=DOGE/IDR", token).status_code == 404


def test_unreachable_freqtrade_answers_upstream_unavailable(setup):
    _, fake, client, _ = setup
    token = _token(client)
    fake.down = True
    response = _get(client, "/gw/v1/health", token)
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "upstream_unavailable",
        "message": "Freqtrade API is not reachable",
        "retry_after_ms": 2000,
    }


def test_fill_latency_is_measured_from_freqtrade_fill_time(setup):
    gateway = setup[0]
    asyncio.run(gateway.record_fill("A", 7, "sell", FILLED_MS + 42))
    latency = gateway.ledger.fill_latency()
    assert latency["n"] == 1
    assert latency["p50"] == 42
    assert latency["recent"][0]["side"] == "sell"


def test_config_changes_are_audited_without_secret_values(setup):
    gateway, _, client, config = setup
    asyncio.run(gateway.watch_config())
    asyncio.run(gateway.watch_config())
    raw = yaml.safe_load(config.read_text())
    raw["risk"]["max_daily_loss_pct"] = 0.8
    raw["providers"][0]["api_key"] = "sk-not-for-logs"
    config.write_text(yaml.safe_dump(raw))
    asyncio.run(gateway.watch_config())
    changed, observed = gateway.ledger.audit_rows(10)
    assert observed["action"] == "config.observed"
    assert changed["action"] == "config.changed"
    assert changed["result"] == "ok"
    changes = {item["key"]: item for item in changed["detail"]["changes"]}
    assert changes["risk.max_daily_loss_pct"] == {"key": "risk.max_daily_loss_pct", "old": 1.0, "new": 0.8}
    assert changes["providers[nutaraline].api_key"]["new"] == "<set>"
    assert "sk-not-for-logs" not in json.dumps(_get(client, "/gw/v1/audit", _token(client)).json())
    assert _get(client, "/gw/v1/settings", _token(client)).json()["providers"][0]["api_key_configured"] is True


def test_invalid_config_edit_is_audited_as_invalid(setup):
    gateway, _, _, config = setup
    asyncio.run(gateway.watch_config())
    raw = yaml.safe_load(config.read_text())
    raw["mode"] = "live"
    config.write_text(yaml.safe_dump(raw))
    asyncio.run(gateway.watch_config())
    latest = gateway.ledger.audit_rows(1)[0]
    assert latest["result"] == "invalid"
    assert latest["detail"]["valid"] is False


def test_feed_rejects_unknown_token(setup):
    _, _, client, _ = setup
    with client.websocket_connect("/gw/v1/events?token=nope") as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 4401


def test_feed_hello_candle_snapshot_and_resume(setup):
    gateway, _, client, _ = setup
    for index in range(250):
        gateway.hub.emit("entry_fill", {"trade_id": index}, bot="A")
    token = _token(client)
    with client.websocket_connect(f"/gw/v1/events?token={token}") as socket:
        hello = socket.receive_json()
        assert hello["type"] == "gw.hello"
        assert hello["data"]["sample_data"] is False
        assert hello["data"]["whitelist"] == ["BTC/IDR", "ETH/IDR"]
        socket.send_json(
            {
                "type": "subscribe",
                "topics": ["entry_fill", "gw.candles"],
                "candles": [{"pair": "BTC/IDR", "timeframe": "1h", "limit": 1}],
            }
        )
        snapshot = socket.receive_json()
        assert snapshot["type"] == "gw.candles"
        assert snapshot["data"]["snapshot"] is True
        socket.send_json({"type": "resume", "last_seq": 247})
        replayed = [socket.receive_json() for _ in range(3)]
        assert [event["seq"] for event in replayed] == [248, 249, 250]
        assert replayed[0]["bot"] == "A"
        socket.send_json({"type": "resume", "last_seq": 3})
        assert socket.receive_json()["type"] == "gw.hello"
        resync = socket.receive_json()
        assert resync["type"] == "gw.resync"
        assert resync["data"]["open_trades"][0]["trade_id"] == 9
        socket.send_json({"type": "ping"})
        assert socket.receive_json()["type"] == "pong"


def test_strategy_messages_become_gateway_events():
    denied = translate({"type": "strategy_msg", "msg": json.dumps({"event": "risk_guard_denied", "pair": "ETH/IDR"})})
    assert denied == ("gw.risk_denied", {"pair": "ETH/IDR"})
    check = translate({"type": "strategy_msg", "msg": json.dumps({"event": "startup_check", "open_trades": []})})
    assert check == ("gw.startup_check", {"open_trades": []})
    assert translate({"type": "strategy_msg", "msg": "free text"}) == ("strategy_msg", {"msg": "free text"})
    assert translate({"type": "entry_fill", "trade_id": 1, "pair": "BTC/IDR"}) == (
        "entry_fill",
        {"trade_id": 1, "pair": "BTC/IDR"},
    )
    assert translate({"type": "new_candle", "data": ["BTC/IDR", "1h", "spot"]}) is None
    assert translate({"type": "analyzed_df", "data": {}}) is None


def test_hub_routes_candles_only_to_clients_of_that_pair():
    async def scenario():
        hub = Hub()
        btc, eth = hub.add(), hub.add()
        btc.topics = eth.topics = {"gw.candles"}
        btc.candles, eth.candles = {"BTC/IDR": 300}, {"ETH/IDR": 300}
        hub.emit("gw.candles", {"pair": "BTC/IDR"}, pair="BTC/IDR")
        hub.emit("gw.error", {"code": "upstream_unavailable"})
        return [btc.queue.get_nowait()["type"] for _ in range(btc.queue.qsize())], eth.queue.qsize()

    btc_events, eth_count = asyncio.run(scenario())
    assert btc_events == ["gw.candles", "gw.error"]
    assert eth_count == 1


def test_risk_and_history_page_past_freqtrades_500_trade_limit(setup):
    _, fake, client, _ = setup
    fake.closed = [
        {
            "trade_id": index,
            "pair": "SOL/IDR",
            "is_open": False,
            "close_timestamp": NOW_MS - 10 * 86_400_000,
            "close_profit_abs": 10.0,
        }
        for index in range(1, 1201)
    ]
    fake.closed.append(
        {
            "trade_id": 1201,
            "pair": "BTC/IDR",
            "is_open": False,
            "close_timestamp": NOW_MS - 60_000,
            "close_profit_abs": -25_000.0,
        }
    )
    token = _token(client)
    risk = _get(client, "/gw/v1/risk", token).json()
    assert risk["breaches"] == ["daily_loss"]
    assert risk["daily_pnl"] == -27_000.0
    newest = _get(client, "/gw/v1/trades?limit=3", token).json()
    assert [trade["trade_id"] for trade in newest] == [1201, 1200, 1199]
    assert _get(client, "/gw/v1/trades?limit=1&pair=ETH/IDR", token).json()[0]["trade_id"] == 9


def test_short_trade_page_fails_closed(setup):
    gateway, fake, client, _ = setup
    fake.closed = [
        {"trade_id": index, "pair": "SOL/IDR", "is_open": False, "close_timestamp": NOW_MS, "close_profit_abs": 0.0}
        for index in range(1, 600)
    ]
    real = fake.__call__

    class Shrinking(FakeFreqtrade):
        def __call__(self, request):
            response = real(request)
            if request.url.path.endswith("/trades") and request.url.params["offset"] != "0":
                body = response.json()
                body["trades"] = body["trades"][:10]
                return httpx.Response(200, json=body)
            return response

    upstream = gateway.upstreams["A"]
    upstream.client = httpx.AsyncClient(
        base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(Shrinking())
    )
    response = _get(client, "/gw/v1/risk", _token(client))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"


def test_logs_never_carry_websocket_tokens(setup):
    _, _, client, _ = setup
    [line] = _get(client, "/gw/v1/logs?limit=5", _token(client)).json()["logs"]
    assert line[4] == '127.0.0.1:41506 - "WebSocket /api/v1/message/ws?token=<redacted>" [accepted]'


def test_feed_survives_binary_frames_and_bad_limits(setup):
    _, _, client, _ = setup
    token = _token(client)
    with client.websocket_connect(f"/gw/v1/events?token={token}") as socket:
        assert socket.receive_json()["type"] == "gw.hello"
        socket.send_bytes(b"\x00\x01")
        socket.send_json({"type": "subscribe", "topics": ["status"], "candles": [{"pair": "BTC/IDR", "limit": "abc"}]})
        socket.send_json({"type": "ping"})
        assert socket.receive_json()["type"] == "pong"


def test_cache_drops_expired_entries(setup):
    gateway = setup[0]

    async def calls():
        for limit in range(1, 6):
            await gateway.ft(gateway.primary(), "/logs", ttl=0, limit=limit)

    asyncio.run(calls())
    assert len(gateway.cache) == 1
