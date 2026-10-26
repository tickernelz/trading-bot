from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from analytics.errors import AnalyticsError
from analytics.freqtrade import AnalysisClient
from analytics.routes import PREFIX, install, make_router
from analytics.service import BotSource
from engine.settings import Settings, load_settings
from tests.analytics_support import closed_trade, open_trade, record, write_decisions, write_trades

AUTH = {"Authorization": "Bearer ok"}
EXPECTED_ROUTES = {
    ("GET", f"{PREFIX}/limits/whatif"),
    ("POST", f"{PREFIX}/replay"),
    ("GET", f"{PREFIX}/signals"),
    ("GET", f"{PREFIX}/scoreboard"),
    ("POST", f"{PREFIX}/scoreboard/apply"),
    ("GET", f"{PREFIX}/stress"),
    ("GET", f"{PREFIX}/portfolio"),
    ("GET", f"{PREFIX}/export/trades.csv"),
    ("GET", f"{PREFIX}/export/tax"),
    ("POST", f"{PREFIX}/backtest"),
    ("GET", f"{PREFIX}/backtest"),
    ("DELETE", f"{PREFIX}/backtest"),
    ("GET", f"{PREFIX}/backtest/history"),
    ("GET", f"{PREFIX}/backtest/history/result"),
}


def reader(request: Request) -> None:
    if request.headers.get("authorization") != "Bearer ok":
        raise HTTPException(401, "unauthorized")


class FakeContext:
    def __init__(self, source: BotSource, trades: list[dict[str, Any]], client: AnalysisClient | None) -> None:
        self.bot = source
        self.book = trades
        self.client = client
        self.audits: list[tuple[str, dict[str, Any]]] = []

    def source(self, bot: str | None) -> BotSource:
        if bot not in (None, self.bot.bot_id):
            raise AnalyticsError(404, "not_found", f"unknown bot {bot}")
        return self.bot

    async def trades(self, bot: str, limit: int) -> list[dict[str, Any]]:
        return self.book

    def analysis(self) -> AnalysisClient | None:
        return self.client

    def audit(self, action: str, detail: dict[str, Any]) -> None:
        self.audits.append((action, detail))


def split_vote():
    return [record("v1"), record("v2"), record("v3"), record("v4", "lewati"), record("v5", "lewati")]


@pytest.fixture
def upstream_calls() -> list[httpx.Request]:
    return []


@pytest.fixture
def env(tmp_path, example_raw, upstream_calls):
    raw = copy.deepcopy(example_raw)
    raw["swarm"]["max_spread"] = 0.5
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    write_decisions(
        tmp_path / "decisions.sqlite",
        [{"decision_id": "d1", "voters": split_vote(), "verdict": "izinkan"}],
    )
    write_trades(tmp_path / "trades.sqlite", {"d1": (-200.0, False)})

    def handler(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(request)
        if request.url.path.endswith("/pair_history"):
            return httpx.Response(
                200,
                json={
                    "strategy": "SwingEmaRsi",
                    "pair": "BTC/IDR",
                    "timeframe": "1h",
                    "columns": ["date", "open", "high", "low", "close", "enter_long", "exit_long"],
                    "data": [[1, 1, 1, 1, 1, 1, 0]],
                },
            )
        return httpx.Response(
            200, json={"status": "running", "running": True, "progress": 0.1, "backtest_result": None}
        )

    client = AnalysisClient("http://127.0.0.1:8099", "u", "p", transport=httpx.MockTransport(handler))
    source = BotSource("B", config, tmp_path / "decisions.sqlite", tmp_path / "trades.sqlite")
    trades = [closed_trade(-12_000.0, close_date="2026-10-26 01:00:00"), open_trade("BTC/IDR", 1, stake=300_000)]
    context = FakeContext(source, trades, client)
    app = FastAPI()
    install(app, context, reader)
    return TestClient(app, headers=AUTH), context, app, config


class TestAuthentication:
    def test_every_analytics_route_refuses_requests_without_the_gateway_session(self, env):
        _, context, app, _ = env
        routes = make_router(context, reader).routes
        assert {(method, route.path) for route in routes for method in route.methods} == EXPECTED_ROUTES
        anonymous = TestClient(app)
        for route in routes:
            for method in route.methods - {"HEAD", "OPTIONS"}:
                response = anonymous.request(method, route.path, json={})
                assert response.status_code == 401, (method, route.path)


class TestLimitsAndStress:
    def test_limits_whatif_reports_both_scenarios_and_the_delta(self, env):
        client, *_ = env
        body = client.get(f"{PREFIX}/limits/whatif", params={"max_daily_loss_pct": 2.0}).json()
        assert body["delta_idr"]["max_daily_loss_idr"] == pytest.approx(20_000)
        assert body["open_positions"] == 1

    def test_an_invalid_combination_is_an_error_envelope_not_a_crash(self, env):
        client, *_ = env
        response = client.get(f"{PREFIX}/limits/whatif", params={"risk_per_trade_pct": 5})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    def test_out_of_range_query_values_are_refused(self, env):
        client, *_ = env
        assert client.get(f"{PREFIX}/limits/whatif", params={"max_open_trades": 0}).status_code == 422
        assert client.get(f"{PREFIX}/stress", params={"drop_pct": 150}).status_code == 422

    def test_stress_defaults_to_the_configured_drop_and_accepts_an_override(self, env):
        client, *_ = env
        assert client.get(f"{PREFIX}/stress").json()["drop_pct"] == 10.0
        assert client.get(f"{PREFIX}/stress", params={"drop_pct": 25}).json()["drop_pct"] == 25.0

    def test_an_unknown_bot_is_not_found(self, env):
        client, *_ = env
        response = client.get(f"{PREFIX}/stress", params={"bot": "Z"})
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


class TestReplayRoute:
    def test_absent_max_spread_keeps_the_configured_limit_and_explicit_null_removes_it(self, env):
        client, *_ = env
        kept = client.post(f"{PREFIX}/replay", json={}).json()
        assert kept["params"]["max_spread"] == 0.5
        assert kept["transitions"] == {"izinkan->lewati": 1}
        removed = client.post(f"{PREFIX}/replay", json={"max_spread": None}).json()
        assert removed["params"]["max_spread"] is None
        assert removed["changed_total"] == 0

    def test_a_new_quorum_and_excluded_voters_are_echoed_in_the_params(self, env):
        client, *_ = env
        body = client.post(
            f"{PREFIX}/replay", json={"min_voters_answered": 3, "max_spread": None, "exclude_voters": ["v4", "v5"]}
        ).json()
        assert body["params"] == {"min_voters_answered": 3, "max_spread": None, "exclude_voters": ["v4", "v5"]}
        assert body["trade_groups"]["take->take"]["trades"] == 1

    def test_unknown_fields_and_a_zero_quorum_are_refused(self, env):
        client, *_ = env
        assert client.post(f"{PREFIX}/replay", json={"quorum": 3}).status_code == 422
        assert client.post(f"{PREFIX}/replay", json={"min_voters_answered": 0}).status_code == 422


class TestSignalsRoute:
    def test_signals_ask_freqtrade_for_the_configured_timeframe_and_strategy(self, env, upstream_calls):
        client, *_ = env
        body = client.get(
            f"{PREFIX}/signals", params={"pair": "BTC/IDR", "from": "2026-10-01", "to": "2026-10-20"}
        ).json()
        assert body["signals"][0]["kind"] == "enter"
        params = dict(upstream_calls[0].url.params)
        assert params["timerange"] == "20261001-20261020"
        assert params["strategy"] == "SwingEmaRsi" and params["timeframe"] == "1h"

    def test_a_window_longer_than_sixty_days_is_refused_before_any_upstream_call(self, env, upstream_calls):
        client, *_ = env
        response = client.get(f"{PREFIX}/signals", params={"pair": "BTC/IDR", "from": "2026-08-01", "to": "2026-10-20"})
        assert response.status_code == 422
        assert upstream_calls == []

    def test_a_reversed_window_and_an_unconfigured_pair_are_refused(self, env, upstream_calls):
        client, *_ = env
        assert (
            client.get(
                f"{PREFIX}/signals", params={"pair": "BTC/IDR", "from": "2026-10-20", "to": "2026-10-01"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"{PREFIX}/signals", params={"pair": "DOGE/IDR", "from": "2026-10-01", "to": "2026-10-02"}
            ).status_code
            == 404
        )
        assert upstream_calls == []

    def test_without_a_webserver_instance_signals_report_not_found(self, env):
        client, context, *_ = env
        context.client = None
        response = client.get(f"{PREFIX}/signals", params={"pair": "BTC/IDR", "from": "2026-10-01", "to": "2026-10-02"})
        assert response.status_code == 404 and "webserver" in response.json()["error"]["message"]


class TestBacktestRoute:
    def test_start_sends_the_configured_strategy_and_capital_and_is_audited(self, env, upstream_calls):
        client, context, *_ = env
        response = client.post(f"{PREFIX}/backtest", json={"timerange": "20261001-20261020"})
        assert response.status_code == 202
        sent = upstream_calls[0]
        assert sent.method == "POST" and sent.url.path == "/api/v1/backtest"
        import json

        body = json.loads(sent.content)
        assert body["strategy"] == "SwingEmaRsi" and body["timeframe"] == "1h"
        assert body["dry_run_wallet"] == 2_000_000 and body["max_open_trades"] == 3
        assert body["enable_protections"] is False
        assert context.audits[0][0] == "backtest.start"

    @pytest.mark.parametrize("value", ["2026-10-01", "20261001", "20261001-20261020; rm", "abc-def"])
    def test_a_malformed_timerange_never_reaches_freqtrade(self, env, upstream_calls, value):
        client, *_ = env
        assert client.post(f"{PREFIX}/backtest", json={"timerange": value}).status_code == 422
        assert upstream_calls == []

    def test_stop_aborts_a_running_job_then_resets_it(self, env, upstream_calls):
        client, *_ = env
        client.delete(f"{PREFIX}/backtest")
        assert [(call.method, call.url.path) for call in upstream_calls] == [
            ("GET", "/api/v1/backtest"),
            ("GET", "/api/v1/backtest/abort"),
            ("DELETE", "/api/v1/backtest"),
        ]

    def test_history_result_filenames_cannot_traverse_paths(self, env, upstream_calls):
        client, *_ = env
        response = client.get(f"{PREFIX}/backtest/history/result", params={"filename": "../../etc/passwd"})
        assert response.status_code == 422
        assert upstream_calls == []


class TestExportRoutes:
    def test_trades_csv_is_served_as_a_download(self, env):
        client, *_ = env
        response = client.get(f"{PREFIX}/export/trades.csv")
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"].startswith('attachment; filename="trades-B-')
        assert len(response.text.strip().split("\n")) == 3

    def test_tax_summary_uses_the_configured_rate(self, env):
        client, *_ = env
        body = client.get(f"{PREFIX}/export/tax").json()
        assert body["rate_pct"] == 0.21
        assert body["total"]["trades"] == 1

    def test_portfolio_lists_every_configured_pair(self, env):
        client, *_ = env
        pairs = [row["pair"] for row in client.get(f"{PREFIX}/portfolio").json()["pairs"]]
        assert sorted(pairs) == ["BTC/IDR", "ETH/IDR", "SOL/IDR"]


class TestScoreboardRoutes:
    def test_reading_the_board_never_changes_the_config(self, env):
        client, _, _, config = env
        before = config.read_text(encoding="utf-8")
        body = client.get(f"{PREFIX}/scoreboard").json()
        assert body["applied"] == []
        assert config.read_text(encoding="utf-8") == before

    def test_apply_with_nothing_drifting_changes_nothing_and_writes_no_audit(self, env):
        client, context, _, config = env
        before = config.read_text(encoding="utf-8")
        assert client.post(f"{PREFIX}/scoreboard/apply").json()["applied"] == []
        assert config.read_text(encoding="utf-8") == before
        assert context.audits == []

    def test_apply_disables_a_drifting_voter_audits_it_and_keeps_the_config_valid(self, env, tmp_path):
        client, context, _, config = env
        rows = []
        outcomes = {}
        for index in range(40):
            profit = 100.0 if index % 2 == 0 else -100.0
            voters = [record(f"v{n}", "izinkan", take=0.9 if profit > 0 else 0.1) for n in range(1, 6)]
            voters[0] = record("v1", "lewati" if profit > 0 else "izinkan", take=0.1 if profit > 0 else 0.9)
            rows.append({"decision_id": f"x{index:02d}", "voters": voters})
            outcomes[f"x{index:02d}"] = (profit, False)
        (tmp_path / "decisions.sqlite").unlink()
        (tmp_path / "trades.sqlite").unlink()
        write_decisions(tmp_path / "decisions.sqlite", rows)
        write_trades(tmp_path / "trades.sqlite", outcomes)
        body = client.post(f"{PREFIX}/scoreboard/apply").json()
        assert body["applied"] == ["v1"]
        assert context.audits == [("scoreboard.apply", {"bot": "B", "voters": ["v1"]})]
        reloaded: Settings = load_settings(config)
        assert {voter.id: voter.enabled for voter in reloaded.swarm.voters}["v1"] is False
