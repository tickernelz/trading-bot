from __future__ import annotations

import shutil
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.app import TRADE_PAGE, Gateway, create_app
from gateway.settings import GatewaySettings
from tests.conftest import EXAMPLE

PASSWORD = "correct horse battery"
ENV = {"GW_PASSWORD": PASSWORD, "FT_API_USERNAME": "bot", "FT_API_PASSWORD": "pw"}
TRADES = 1203
NOW_MS = int(time.time() * 1000)


class PagedFreqtrade:
    """Answers /trades like Freqtrade 2026.9: closed trades in id order, sliced by limit and offset."""

    def __init__(self) -> None:
        self.trades = [
            {
                "trade_id": index + 1,
                "pair": "BTC/IDR",
                "is_open": False,
                "close_timestamp": NOW_MS - (TRADES - index) * 60_000,
                "close_profit_abs": 100.0 if index == TRADES - 1 else -1.0,
                "close_profit": 0.001 if index == TRADES - 1 else -0.00001,
            }
            for index in range(TRADES)
        ]
        self.offsets: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/trades":
            limit = int(request.url.params["limit"])
            offset = int(request.url.params["offset"])
            assert request.url.params["order_by_id"] == "true"
            self.offsets.append(offset)
            page = self.trades[offset : offset + limit]
            return httpx.Response(
                200, json={"trades": page, "trades_count": len(page), "offset": offset, "total_trades": TRADES}
            )
        if path == "/status":
            return httpx.Response(200, json=[])
        if path == "/show_config":
            return httpx.Response(200, json={"stake_currency": "IDR"})
        return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture
def paged(tmp_path):
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
    fake = PagedFreqtrade()
    upstream = gateway.upstreams["A"]
    upstream.client = httpx.AsyncClient(base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(fake))
    client = TestClient(create_app(gateway))
    token = client.post("/gw/v1/session", json={"password": PASSWORD}).json()["token"]
    yield fake, client, {"Authorization": f"Bearer {token}"}
    gateway.ledger.close()


def test_history_and_risk_read_every_page_of_closed_trades(paged):
    fake, client, headers = paged
    latest = client.get("/gw/v1/trades?limit=2", headers=headers).json()
    assert [trade["trade_id"] for trade in latest] == [TRADES, TRADES - 1]
    assert fake.offsets == [0, TRADE_PAGE, 2 * TRADE_PAGE]
    page = client.get("/gw/v1/trades?limit=3&offset=1200", headers=headers).json()
    assert [trade["trade_id"] for trade in page] == [3, 2, 1]
    risk = client.get("/gw/v1/risk", headers=headers).json()
    assert risk["equity"] == round(2_000_000 - (TRADES - 1) * 1.0 + 100.0, 2)
