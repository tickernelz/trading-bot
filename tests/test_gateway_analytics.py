from __future__ import annotations

import asyncio
import copy
import time
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from analytics.routes import PREFIX
from engine.launch import DRY_RUN_DB
from engine.settings import load_settings
from gateway.app import Gateway, create_app
from gateway.settings import GatewaySettings
from tests.analytics_support import closed_trade, record, write_decisions, write_trades
from tests.conftest import EXAMPLE
from tests.test_gateway import ENV, FakeFreqtrade


class PagedFreqtrade(FakeFreqtrade):
    def __init__(self) -> None:
        super().__init__()
        self.lie_about_total = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        response = super().__call__(request)
        if self.lie_about_total and request.url.path.endswith("/trades"):
            body = response.json()
            body["total_trades"] += 3
            return httpx.Response(200, json=body)
        return response


def drifting_book(tmp_path: Path) -> None:
    rows, outcomes = [], {}
    for index in range(40):
        profit = 100.0 if index % 2 == 0 else -100.0
        voters = [record(f"v{n}", "izinkan", take=0.9 if profit > 0 else 0.1) for n in range(1, 8)]
        voters[0] = record("v1", "lewati" if profit > 0 else "izinkan", take=0.1 if profit > 0 else 0.9)
        rows.append({"decision_id": f"x{index:02d}", "voters": voters})
        outcomes[f"x{index:02d}"] = (profit, False)
    write_decisions(tmp_path / "decisions.sqlite", rows)
    write_trades(tmp_path / "bot-b" / DRY_RUN_DB, outcomes)


def build(tmp_path: Path, example_raw: dict, auto_disable: bool):
    raw = copy.deepcopy(example_raw)
    raw["analytics"] = {"scoreboard": {"auto_disable": auto_disable}}
    config = tmp_path / "bot-b.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    (tmp_path / "bot-b").mkdir()
    drifting_book(tmp_path)
    plain = tmp_path / "bot-a.yaml"
    plain.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = GatewaySettings(
        state_dir=str(tmp_path / "state"),
        exchange_probe_url=None,
        bots=[
            {
                "id": "A",
                "label": "Bot A",
                "strategy": "aturan saja",
                "api_url": "http://127.0.0.1:8080",
                "config": str(plain),
                "userdir": str(tmp_path / "bot-a"),
            },
            {
                "id": "B",
                "label": "Bot B",
                "strategy": "aturan + swarm bayangan",
                "api_url": "http://127.0.0.1:8081",
                "config": str(config),
                "userdir": str(tmp_path / "bot-b"),
                "decisions": str(tmp_path / "decisions.sqlite"),
            },
        ],
    )
    gateway = Gateway(settings, ENV)
    fake = PagedFreqtrade()
    for upstream in gateway.upstreams.values():
        upstream.client = httpx.AsyncClient(
            base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(fake)
        )
    return gateway, fake, config


@pytest.fixture
def stack(tmp_path, example_raw):
    gateway, fake, config = build(tmp_path, example_raw, auto_disable=False)
    yield gateway, fake, config
    gateway.ledger.close()


def token_of(gateway: Gateway) -> str:
    return gateway.ledger.create_session("read", 1, None)[0]


def call(gateway: Gateway, method: str, path: str, host: str = "127.0.0.1", **kwargs) -> httpx.Response:
    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(gateway), client=(host, 51000))
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as http:
            return await http.request(method, path, **kwargs)

    return asyncio.run(go())


def bearer(gateway: Gateway) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_of(gateway)}"}


def voters_enabled(config: Path) -> dict[str, bool]:
    return {voter.id: voter.enabled for voter in load_settings(config).swarm.voters}


def test_analytics_reads_need_a_gateway_session(stack):
    gateway, _, _ = stack
    assert call(gateway, "GET", f"{PREFIX}/scoreboard?bot=B").status_code == 401
    ok = call(gateway, "GET", f"{PREFIX}/scoreboard?bot=B", headers=bearer(gateway))
    assert ok.status_code == 200
    assert ok.json()["plan"]["recommended"] == ["v1"]


def test_unknown_bot_and_bot_without_decisions_use_the_gateway_envelope(stack):
    gateway, _, _ = stack
    unknown = call(gateway, "GET", f"{PREFIX}/scoreboard?bot=Z", headers=bearer(gateway))
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "not_found")
    plain = call(gateway, "GET", f"{PREFIX}/scoreboard?bot=A", headers=bearer(gateway))
    assert (plain.status_code, plain.json()["error"]["code"]) == (404, "not_found")


def test_trade_book_pages_past_one_page_and_keeps_open_positions(stack):
    gateway, fake, _ = stack
    fake.closed = [closed_trade(1.0, trade_id=index) for index in range(100, 601)]
    book = asyncio.run(gateway.analytics.trades("A"))
    assert len(book) == 502
    assert sum(1 for trade in book if trade["is_open"]) == 1
    assert len({trade["trade_id"] for trade in book}) == 502


def test_trade_book_fails_closed_when_pages_do_not_add_up(stack):
    gateway, fake, _ = stack
    fake.closed = [closed_trade(1.0, trade_id=index) for index in range(1, 4)]
    fake.lie_about_total = True
    response = call(gateway, "GET", f"{PREFIX}/export/trades.csv?bot=A", headers=bearer(gateway))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"


def test_without_an_analysis_url_signals_and_backtest_reads_report_not_found(stack):
    gateway, _, _ = stack
    response = call(gateway, "GET", f"{PREFIX}/backtest", headers=bearer(gateway))
    assert (response.status_code, response.json()["error"]["code"]) == (404, "not_found")


def test_apply_from_loopback_disables_the_voter_and_writes_one_audit_row(stack):
    gateway, _, config = stack
    response = call(
        gateway, "POST", f"{PREFIX}/scoreboard/apply?bot=B", headers={**bearer(gateway), "Idempotency-Key": "k-1"}
    )
    assert response.status_code == 200
    assert response.json()["applied"] == ["v1"]
    assert voters_enabled(config)["v1"] is False
    rows = [row for row in gateway.ledger.audit_rows(10) if row["action"].startswith("analytics.")]
    assert [(row["action"], row["result"], row["actor"], row["ip"], row["idempotency_key"]) for row in rows] == [
        ("analytics.scoreboard.apply", "ok", "owner", "127.0.0.1", "k-1")
    ]
    assert rows[0]["targets"] == ["B"]


@pytest.mark.parametrize(
    ("host", "extra"),
    [
        ("192.168.1.20", {}),
        ("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"}),
        ("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"}),
        ("127.0.0.1", {"Forwarded": "for=203.0.113.9"}),
    ],
)
def test_apply_and_backtest_are_refused_off_the_machine_and_leave_the_config_untouched(stack, host, extra):
    gateway, _, config = stack
    before = config.read_bytes()
    headers = {**bearer(gateway), **extra}
    apply = call(gateway, "POST", f"{PREFIX}/scoreboard/apply?bot=B", host=host, headers=headers)
    start = call(
        gateway, "POST", f"{PREFIX}/backtest", host=host, headers=headers, json={"timerange": "20261003-20261025"}
    )
    stop = call(gateway, "DELETE", f"{PREFIX}/backtest", host=host, headers=headers)
    for response in (apply, start, stop):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden_local_only"
    assert config.read_bytes() == before
    rows = [row for row in gateway.ledger.audit_rows(10) if row["action"].startswith("analytics.")]
    assert sorted(row["action"] for row in rows) == [
        "analytics.backtest.start",
        "analytics.backtest.stop",
        "analytics.scoreboard.apply",
    ]
    assert {row["result"] for row in rows} == {"forbidden"}


def test_apply_without_a_session_is_unauthorized_and_unaudited(stack):
    gateway, _, config = stack
    before = config.read_bytes()
    response = call(gateway, "POST", f"{PREFIX}/scoreboard/apply?bot=B")
    assert response.status_code == 401
    assert config.read_bytes() == before
    assert not [row for row in gateway.ledger.audit_rows(10) if row["action"].startswith("analytics.")]


def test_failed_apply_on_a_bot_without_decisions_is_audited_as_failed(stack):
    gateway, _, _ = stack
    response = call(gateway, "POST", f"{PREFIX}/scoreboard/apply?bot=A", headers=bearer(gateway))
    assert response.status_code == 404
    rows = [row for row in gateway.ledger.audit_rows(10) if row["action"].startswith("analytics.")]
    assert [(row["result"], row["detail"]["error"]) for row in rows] == [("failed", "not_found")]


def wait_for(predicate, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_gateway_runs_the_auto_disable_loop_when_the_config_allows_it(tmp_path, example_raw):
    gateway, _, config = build(tmp_path, example_raw, auto_disable=True)
    try:
        with TestClient(create_app(gateway)):
            assert wait_for(lambda: voters_enabled(config)["v1"] is False)
            assert wait_for(
                lambda: any(row["action"].startswith("analytics.") for row in gateway.ledger.audit_rows(20))
            )
            rows = [row for row in gateway.ledger.audit_rows(20) if row["action"].startswith("analytics.")]
        assert [(row["result"], row["actor"], row["ip"], row["targets"]) for row in rows] == [
            ("ok", "gateway", None, ["B"])
        ]
        assert rows[0]["detail"] == {"voters": ["v1"]}
    finally:
        gateway.ledger.close()


def test_auto_disable_loop_is_restarted_after_an_unexpected_error(stack, monkeypatch):
    gateway, _, _ = stack
    calls = []

    async def flaky(sources, audit):
        calls.append([source.bot_id for source in sources])
        if len(calls) == 1:
            raise RuntimeError("boom")
        await asyncio.sleep(3600)

    monkeypatch.setattr("gateway.analytics_context.auto_disable_loop", flaky)
    monkeypatch.setattr("gateway.analytics_context.RESTART_DELAY_S", 0.05)

    async def run() -> None:
        task = asyncio.create_task(gateway.analytics.run_auto_disable())
        await asyncio.sleep(0.5)
        task.cancel()

    asyncio.run(run())
    assert calls == [["B"], ["B"]]


def test_gateway_leaves_voters_alone_when_auto_disable_is_off(tmp_path, example_raw):
    gateway, _, config = build(tmp_path, example_raw, auto_disable=False)
    try:
        before = config.read_bytes()
        with TestClient(create_app(gateway)):
            time.sleep(1.5)
            rows = [row for row in gateway.ledger.audit_rows(20) if row["action"].startswith("analytics.")]
        assert config.read_bytes() == before
        assert rows == []
    finally:
        gateway.ledger.close()
