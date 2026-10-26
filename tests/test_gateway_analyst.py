from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tb_swarm.agents import build_analyst
from tb_swarm.analyst import AnalystRunner, ReportStore

from engine.analyst_service import TOKEN_HEADER, AnalystService
from engine.analyst_service import create_app as create_service
from engine.decisions import DecisionStore
from gateway.app import Gateway, create_app
from gateway.settings import GatewaySettings
from tests.conftest import EXAMPLE
from tests.scripted import ScriptedModel, tool_call
from tests.test_gateway import ENV, PASSWORD, FakeFreqtrade

TOKEN = "t" * 40
KEY = "sk-analyst-0123456789abcdef"
TZ = ZoneInfo("Asia/Jakarta")
TODAY = datetime.now(TZ).date().isoformat()
GOOD = {
    "summary": "One closed trade and one open trade.",
    "anomalies": [{"title": "Loss", "detail": "Trade 7 lost money.", "evidence": ["7"]}],
    "suggestions": [],
}


def answer(payload):
    return AIMessage(content=json.dumps(payload) if not isinstance(payload, str) else payload)


class Rig:
    def __init__(self, tmp_path, report_at="23:59"):
        raw = yaml.safe_load(EXAMPLE.read_text())
        raw["analyst"]["report_at"] = report_at
        self.config = tmp_path / "bot-b.yaml"
        self.config.write_text(yaml.safe_dump(raw))
        self.userdir = tmp_path / "bot-b"
        self.userdir.mkdir()
        self.decisions = tmp_path / "decisions.sqlite"
        store = DecisionStore(self.decisions)
        store.add_pending(
            decision_id="a" * 32,
            bot="B",
            pair="BTC/IDR",
            timeframe="1h",
            candle="2026-10-26T00:00:00Z",
            rate=1.0,
            mode="shadow",
            required=5,
            iqr_limit=None,
            request={"state": "private"},
        )
        store.settle(
            "a" * 32,
            status="skip",
            reason="quorum_not_met",
            answered=2,
            verdict="lewati",
            aggregate=None,
            voters=[{"voter_id": "v1", "provider": "p", "model": "m", "status": "timeout", "latency_s": 30.0}],
        )
        store.close()
        self.settings = GatewaySettings(
            state_dir=str(tmp_path / "state"),
            exchange_probe_url=None,
            bots=[
                {
                    "id": "B",
                    "label": "Bot B",
                    "strategy": "swarm",
                    "api_url": "http://127.0.0.1:8081",
                    "config": str(self.config),
                    "userdir": str(self.userdir),
                    "decisions": str(self.decisions),
                }
            ],
        )
        self.gateway = Gateway(self.settings, {**ENV, "ANALYST_TOKEN": TOKEN})
        self.fake = FakeFreqtrade()
        upstream = self.gateway.upstreams["B"]
        upstream.client = httpx.AsyncClient(
            base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(self.fake)
        )
        self.sent = 0
        self.model = ScriptedModel(script=[], offered=[])
        data_dir = self.userdir / "analyst_data"
        runner = AnalystRunner(build_analyst(self.model, data_dir), model_id="test-model", secrets=(KEY,), timeout_s=20)
        self.service = AnalystService(runner, ReportStore(self.userdir / "analyst_reports"), "p:m")
        self.service_calls = []
        self.service_app = create_service(self.service, TOKEN)
        self.service_down = False
        asgi = httpx.ASGITransport(app=self.service_app)

        async def route(request):
            self.service_calls.append((request.method, request.url.path))
            if self.service_down:
                raise httpx.ConnectError("refused", request=request)
            return await asgi.handle_async_request(request)

        self.gateway.analyst.http = httpx.AsyncClient(transport=httpx.MockTransport(route), timeout=30)
        self.client = TestClient(create_app(self.gateway), client=("127.0.0.1", 50000))
        response = self.client.post("/gw/v1/session", json={"password": PASSWORD})
        self.headers = {"Authorization": f"Bearer {response.json()['token']}"}

    def get(self, path):
        return self.client.get(path, headers=self.headers)

    def post(self, path, body, key=None):
        self.sent += 1
        headers = {**self.headers, "Idempotency-Key": key or f"rig-key-{self.sent:06d}"}
        return self.client.post(path, json=body, headers=headers)

    def data_file(self, name):
        return (self.userdir / "analyst_data" / name).read_text()


@pytest.fixture
def rig(tmp_path):
    made = Rig(tmp_path)
    yield made
    made.gateway.ledger.close()


def test_report_is_built_from_a_fresh_snapshot_and_stored(rig):
    rig.model.script = [tool_call("get_trade_history", {}, "c1"), answer(GOOD)]
    response = rig.post("/gw/v1/analyst/reports", {"day": TODAY})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["day"] == TODAY and report["summary"] == GOOD["summary"]
    assert report["anomalies"][0]["grounded"] is True
    assert rig.get("/gw/v1/analyst/reports").json() == {"bot": "B", "report_at": "23:59", "days": [TODAY]}
    assert rig.get(f"/gw/v1/analyst/reports/{TODAY}").json()["summary"] == GOOD["summary"]
    [row] = [item for item in rig.gateway.ledger.audit_rows(10) if item["action"] == "analyst.report"]
    assert row["result"] == "ok" and row["detail"]["params"] == {"day": TODAY} and row["actor"] == "owner"
    assert row["detail"]["model"] == report["model"] and row["detail"]["latency_s"] == report["latency_s"]
    assert row["detail"]["tokens"] == report["usage"]


def test_snapshot_carries_trades_decisions_and_risk_but_no_secrets(rig):
    rig.model.script = [answer(GOOD)]
    assert rig.post("/gw/v1/analyst/reports", {"day": TODAY}).status_code == 200
    trades = [json.loads(line) for line in rig.data_file("trades.jsonl").splitlines()]
    assert sorted(trade["trade_id"] for trade in trades) == [7, 9]
    [decision] = [json.loads(line) for line in rig.data_file("voter_decisions.jsonl").splitlines()]
    assert decision["decision_id"] == "a" * 32 and "request" not in decision
    metrics = json.loads(rig.data_file("metrics.json"))
    assert metrics["risk"]["daily_pnl"] == -27_000.0 and metrics["profit"]["closed_trade_count"] == 1
    assert "swarm_by_day" in metrics
    everything = "".join(path.read_text() for path in (rig.userdir / "analyst_data").iterdir())
    assert PASSWORD not in everything and TOKEN not in everything and "pw" not in metrics["bot"].values()


def test_ask_answers_through_the_read_tools_only(rig):
    rig.model.script = [
        tool_call("get_voter_log", {"pair": "BTC/IDR"}, "c1"),
        tool_call("write_file", {"file_path": "/x", "content": "y"}, "c2"),
        answer("Skipped because only 2 voters answered."),
    ]
    response = rig.post("/gw/v1/analyst/ask", {"question": "Why was BTC skipped?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"].startswith("Skipped") and [use["name"] for use in body["tools_used"]][0] == "get_voter_log"
    assert {tuple(names) for names in rig.model.offered} == {("get_metrics", "get_trade_history", "get_voter_log")}
    [row] = [item for item in rig.gateway.ledger.audit_rows(10) if item["action"] == "analyst.ask"]
    assert row["result"] == "ok" and "Why was BTC" not in json.dumps(row)


def counted(content, tokens_in, tokens_out):
    usage = {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out}
    return AIMessage(content=content, usage_metadata=usage)


def row(calls, tokens_in, tokens_out, reasoning=0):
    return {
        "calls": calls,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "reasoning_tokens": reasoning,
        "cost": None,
    }


def test_costs_list_analyst_tokens_in_their_own_rows_per_window(rig):
    rig.model.script = [counted(json.dumps(GOOD), 100, 10), counted("Skipped.", 300, 30)]
    assert rig.post("/gw/v1/analyst/reports", {"day": TODAY}).status_code == 200
    assert rig.post("/gw/v1/analyst/ask", {"question": "Why was BTC skipped?"}).status_code == 200
    ledger = rig.gateway.ledger
    ledger.audit(actor="owner", action="analyst.ask", targets=["B"], result="error", detail={"code": "provider_error"})
    detail = {"day": "2026-10-01", "tokens": {"input_tokens": 1000, "output_tokens": 100, "reasoning_tokens": 7}}
    with ledger._db:
        ledger._db.execute(
            "INSERT INTO audit (ts, actor, action, targets, result, detail) VALUES (?, ?, ?, ?, ?, ?)",
            ("2020-01-01T00:00:00.000Z", "scheduler", "analyst.report", '["B"]', "ok", json.dumps(detail)),
        )
    costs = {window: rig.get(f"/gw/v1/costs?window={window}").json() for window in ("day", "7d", "total")}
    for window in ("day", "7d"):
        assert costs[window]["analyst"] == {"reports": row(1, 100, 10), "asks": row(1, 300, 30)}
    assert costs["total"]["analyst"] == {"reports": row(2, 1100, 110, 7), "asks": row(1, 300, 30)}
    assert costs["total"]["input_tokens"] == 0


def test_ask_is_rate_limited_per_minute(rig):
    for _ in range(6):
        assert rig.post("/gw/v1/analyst/ask", {"question": "hi"}).status_code == 200
    blocked = rig.post("/gw/v1/analyst/ask", {"question": "hi"})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.json()["error"]["retry_after_ms"] > 0


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/gw/v1/analyst/reports", None),
        ("get", f"/gw/v1/analyst/reports/{TODAY}", None),
        ("post", "/gw/v1/analyst/reports", {}),
        ("post", "/gw/v1/analyst/ask", {"question": "hi"}),
        ("get", "/gw/v1/mode", None),
        ("post", "/gw/v1/control/mode", {"mode": "dry_run"}),
    ],
)
def test_every_new_endpoint_needs_a_session(rig, method, path, body):
    response = rig.client.request(method, path, json=body)
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


def test_bad_input_is_rejected_before_any_model_call(rig):
    assert rig.post("/gw/v1/analyst/reports", {"day": "yesterday"}).status_code == 400
    assert rig.post("/gw/v1/analyst/ask", {"question": ""}).status_code == 400
    assert rig.post("/gw/v1/analyst/ask", {"question": "x" * 2001}).status_code == 400
    assert (
        rig.post("/gw/v1/analyst/ask", {"question": "ok", "history": [{"role": "system", "content": "x"}]}).status_code
        == 400
    )
    assert rig.model.offered == []
    assert rig.get("/gw/v1/analyst/reports/2026-02-30").status_code == 400
    assert rig.get("/gw/v1/analyst/reports/latest").status_code == 400
    assert [path for _, path in rig.service_calls] == ["/reports/2026-02-30"]
    assert rig.get("/gw/v1/analyst/reports/2020-01-01").status_code == 404
    assert rig.post("/gw/v1/analyst/ask", {"question": "hi", "bot": "Z"}).status_code == 404


def test_manual_report_days_are_limited_to_the_last_two_weeks_and_never_reach_the_model(rig):
    today = datetime.now(TZ).date()
    for day in (today - timedelta(days=14), today + timedelta(days=1), today - timedelta(days=400)):
        response = rig.post("/gw/v1/analyst/reports", {"day": day.isoformat()})
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
    assert rig.post("/gw/v1/analyst/reports", {"day": "2026-02-30"}).status_code == 400
    assert rig.service_calls == [] and rig.model.offered == []
    rig.model.script = [answer(GOOD)]
    oldest = (today - timedelta(days=13)).isoformat()
    assert rig.post("/gw/v1/analyst/reports", {"day": oldest}).status_code == 200


def relayed_token(rig):
    return rig.client.post(
        "/gw/v1/session", json={"password": PASSWORD}, headers={"CF-Connecting-IP": "203.0.113.9"}
    ).json()["token"]


def test_a_read_session_cannot_start_a_report_even_from_loopback(rig):
    headers = {"Authorization": f"Bearer {relayed_token(rig)}", "Idempotency-Key": "read-scope-9"}
    response = rig.client.post("/gw/v1/analyst/reports", json={"day": TODAY}, headers=headers)
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden_local_only"
    assert rig.service_calls == [] and rig.model.offered == []


@pytest.mark.parametrize("header", ["CF-Ray", "X-Forwarded-Host", "X-Forwarded-For"])
def test_a_relayed_report_request_is_refused_before_the_model(rig, header):
    headers = {**rig.headers, "Idempotency-Key": "relayed-key-1", header: "value"}
    response = rig.client.post("/gw/v1/analyst/reports", json={"day": TODAY}, headers=headers)
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden_local_only"
    assert rig.service_calls == []


def test_a_report_request_needs_a_well_formed_idempotency_key(rig):
    for headers in ({}, {"Idempotency-Key": "short"}, {"Idempotency-Key": "bad key with spaces"}):
        response = rig.client.post("/gw/v1/analyst/reports", json={"day": TODAY}, headers={**rig.headers, **headers})
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
    assert rig.service_calls == []
    assert all(row["idempotency_key"] is None for row in rig.gateway.ledger.audit_rows(20))


def test_replaying_a_report_request_costs_one_model_run_and_another_day_is_refused(rig):
    rig.model.script = [answer(GOOD)]
    first = rig.post("/gw/v1/analyst/reports", {"day": TODAY}, key="report-key-1")
    again = rig.post("/gw/v1/analyst/reports", {"day": TODAY}, key="report-key-1")
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert len([call for call in rig.service_calls if call == ("POST", "/reports")]) == 1
    other = rig.post(
        "/gw/v1/analyst/reports", {"day": str(datetime.now(TZ).date() - timedelta(days=1))}, key="report-key-1"
    )
    assert other.status_code == 409 and other.json()["error"]["code"] == "invalid_request"


def test_manual_reports_share_the_per_minute_budget_with_questions(rig):
    for _ in range(3):
        assert rig.post("/gw/v1/analyst/ask", {"question": "hi"}).status_code == 200
    rig.model.script = [AIMessage(content="done")] * 3 + [answer(GOOD)] * 3
    for _ in range(3):
        assert rig.post("/gw/v1/analyst/reports", {"day": TODAY}).status_code == 200
    blocked = rig.post("/gw/v1/analyst/reports", {"day": TODAY})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"


def test_a_bot_without_an_analyst_section_has_no_analyst(rig):
    raw = yaml.safe_load(rig.config.read_text())
    del raw["analyst"]
    rig.config.write_text(yaml.safe_dump(raw))
    assert rig.get("/gw/v1/analyst/reports").status_code == 404
    assert rig.post("/gw/v1/analyst/ask", {"question": "hi"}).status_code == 404


def test_unreachable_service_and_missing_token_are_reported_not_hidden(rig):
    rig.service_down = True
    down = rig.post("/gw/v1/analyst/ask", {"question": "hi"})
    assert down.status_code == 503 and down.json()["error"]["code"] == "upstream_unavailable"
    rig.service_down = False
    del rig.gateway.env["ANALYST_TOKEN"]
    missing = rig.get("/gw/v1/analyst/reports")
    assert missing.status_code == 503 and "ANALYST_TOKEN" in missing.json()["error"]["message"]
    assert TOKEN not in missing.text


def test_wrong_service_token_never_reaches_the_analyst(rig):
    rig.gateway.env["ANALYST_TOKEN"] = "x" * 40
    response = rig.get("/gw/v1/analyst/reports")
    assert response.status_code == 502 and rig.model.offered == []


def test_service_requires_its_token_directly(rig):
    direct = TestClient(rig.service_app)
    assert direct.post("/ask", json={"question": "hi"}).status_code == 401
    assert direct.get("/reports", headers={TOKEN_HEADER: "wrong"}).status_code == 401
    assert direct.get("/health").json()["status"] == "ok"


def test_provider_failure_is_a_502_without_the_key(rig):
    rig.model.failure = f"upstream rejected {KEY}"
    response = rig.post("/gw/v1/analyst/ask", {"question": "hi"})
    assert response.status_code == 502 and response.json()["error"]["code"] == "upstream_error"
    assert KEY not in response.text
    [row] = [item for item in rig.gateway.ledger.audit_rows(10) if item["action"] == "analyst.ask"]
    assert row["result"] == "error" and KEY not in json.dumps(row)


def test_a_second_report_for_the_same_day_while_one_runs_is_refused(rig):
    rig.service.generating.add(TODAY)
    response = rig.post("/gw/v1/analyst/reports", {"day": TODAY})
    assert response.status_code == 409 and response.json()["error"]["code"] == "invalid_request"


def test_daily_timer_writes_yesterdays_report_once_and_backs_off_after_a_failure(tmp_path):
    rig = Rig(tmp_path, report_at="00:00")
    try:
        yesterday = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()
        rig.model.failure = "provider down"
        asyncio.run(rig.gateway.analyst.tick())
        calls_after_failure = len([call for call in rig.service_calls if call == ("POST", "/reports")])
        asyncio.run(rig.gateway.analyst.tick())
        assert len([call for call in rig.service_calls if call == ("POST", "/reports")]) == calls_after_failure == 1
        rig.gateway.analyst.attempted.clear()
        rig.model.failure = None
        rig.model.script = [answer(GOOD)]
        asyncio.run(rig.gateway.analyst.tick())
        assert rig.service.store.days() == [yesterday]
        asyncio.run(rig.gateway.analyst.tick())
        assert len([call for call in rig.service_calls if call == ("POST", "/reports")]) == 2
        audit = [item for item in rig.gateway.ledger.audit_rows(10) if item["action"] == "analyst.report"]
        assert [item["result"] for item in audit] == ["ok", "error"] and audit[0]["actor"] == "scheduler"
    finally:
        rig.gateway.ledger.close()


def test_timer_waits_until_the_configured_time(tmp_path):
    rig = Rig(tmp_path, report_at="23:59")
    try:
        if datetime.now(TZ).strftime("%H:%M") >= "23:59":
            pytest.skip("run too close to the configured time")
        asyncio.run(rig.gateway.analyst.tick())
        assert rig.service_calls == []
    finally:
        rig.gateway.ledger.close()
