from __future__ import annotations

import copy
import hashlib
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
from engine.settings import ConfigError, Settings, load_settings
from tests.analytics_support import closed_trade, open_trade, record, write_decisions, write_trades

AUTH = {"Authorization": "Bearer ok"}
CONTROL = {**AUTH, "x-scope": "control"}
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
        self.audits: list[dict[str, Any]] = []

    def source(self, bot: str | None) -> BotSource:
        if bot not in (None, self.bot.bot_id):
            raise AnalyticsError(404, "not_found", f"unknown bot {bot}")
        return self.bot

    async def trades(self, bot: str) -> list[dict[str, Any]]:
        return self.book

    def analysis(self) -> AnalysisClient | None:
        return self.client

    def can_control(self, request: Request) -> bool:
        return request.headers.get("x-scope") == "control"

    def audit(
        self, action: str, result: str, *, request: Request | None, targets: list[str], detail: dict[str, Any]
    ) -> None:
        ip = request.client.host if request is not None and request.client else None
        self.audits.append({"action": action, "result": result, "ip": ip, "targets": targets, "detail": detail})


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
                    "strategy": "RuleStrategy",
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
    return TestClient(app, headers=CONTROL), context, app, config


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
        assert params["strategy"] == "RuleStrategy" and params["timeframe"] == "1h"

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
        assert body["strategy"] == "RuleStrategy" and body["timeframe"] == "1h"
        assert body["dry_run_wallet"] == 2_000_000 and body["max_open_trades"] == 3
        assert body["enable_protections"] is False
        assert [(row["action"], row["result"]) for row in context.audits] == [("analytics.backtest.start", "ok")]
        assert context.audits[0]["targets"] == ["default"] and context.audits[0]["ip"] is not None

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

    def test_apply_with_nothing_drifting_changes_nothing_but_is_still_audited(self, env):
        client, context, _, config = env
        before = config.read_text(encoding="utf-8")
        assert client.post(f"{PREFIX}/scoreboard/apply").json()["applied"] == []
        assert config.read_text(encoding="utf-8") == before
        assert [(row["action"], row["result"], row["detail"]["voters"]) for row in context.audits] == [
            ("analytics.scoreboard.apply", "ok", [])
        ]

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
        assert [(row["action"], row["result"], row["detail"]["voters"]) for row in context.audits] == [
            ("analytics.scoreboard.apply", "ok", ["v1"])
        ]
        reloaded: Settings = load_settings(config)
        assert {voter.id: voter.enabled for voter in reloaded.swarm.voters}["v1"] is False


class TestControlScope:
    def read_client(self, app):
        return TestClient(app, headers=AUTH)

    def test_a_read_session_cannot_apply_the_scoreboard_and_the_config_bytes_do_not_change(self, env, tmp_path):
        _, context, app, config = env
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
        before = hashlib.sha256(config.read_bytes()).hexdigest()
        response = self.read_client(app).post(f"{PREFIX}/scoreboard/apply")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden_local_only"
        assert hashlib.sha256(config.read_bytes()).hexdigest() == before
        assert [(row["action"], row["result"]) for row in context.audits] == [
            ("analytics.scoreboard.apply", "forbidden")
        ]
        control = TestClient(app, headers=CONTROL).post(f"{PREFIX}/scoreboard/apply")
        assert control.status_code == 200 and control.json()["applied"] == ["v1"]
        assert hashlib.sha256(config.read_bytes()).hexdigest() != before

    def test_a_read_session_cannot_start_or_stop_a_backtest(self, env, upstream_calls):
        _, context, app, _ = env
        read = self.read_client(app)
        assert read.post(f"{PREFIX}/backtest", json={"timerange": "20261001-20261020"}).status_code == 403
        assert read.delete(f"{PREFIX}/backtest").status_code == 403
        assert upstream_calls == []
        assert [(row["action"], row["result"]) for row in context.audits] == [
            ("analytics.backtest.start", "forbidden"),
            ("analytics.backtest.stop", "forbidden"),
        ]

    def test_reads_stay_open_to_a_read_session(self, env):
        _, _, app, _ = env
        read = self.read_client(app)
        for path in ("/limits/whatif", "/stress", "/portfolio", "/scoreboard", "/export/tax", "/backtest"):
            assert read.get(PREFIX + path).status_code == 200, path

    def test_stopping_a_backtest_is_audited_with_its_result(self, env):
        client, context, *_ = env
        assert client.delete(f"{PREFIX}/backtest").status_code == 200
        assert [(row["action"], row["result"]) for row in context.audits] == [("analytics.backtest.stop", "ok")]

    def test_a_failed_backtest_start_is_audited_as_failed(self, env):
        client, context, _, _ = env
        context.client = AnalysisClient(
            "http://127.0.0.1:8099",
            "u",
            "p",
            transport=httpx.MockTransport(lambda request: httpx.Response(503, json={})),
        )
        assert client.post(f"{PREFIX}/backtest", json={"timerange": "20261001-20261020"}).status_code == 503
        assert [(row["action"], row["result"], row["detail"]["error"]) for row in context.audits] == [
            ("analytics.backtest.start", "failed", "upstream_unavailable")
        ]

    def test_a_config_that_changed_under_the_switch_is_a_conflict_not_a_crash_and_is_audited(self, env, monkeypatch):
        client, context, *_ = env

        def refuse(path, voters):
            raise ConfigError("changed while the voter switch was being prepared")

        monkeypatch.setattr("analytics.service.apply_disables", refuse)
        response = client.post(f"{PREFIX}/scoreboard/apply")
        assert response.status_code == 409
        assert context.audits[-1]["result"] == "failed"


class TestCompleteHistory:
    def test_more_than_a_thousand_closed_trades_all_reach_the_risk_figures(self, env):
        client, context, *_ = env
        context.book = [closed_trade(-10.0, trade_id=index, close_date="2026-10-25 01:00:00") for index in range(1001)]
        body = client.get(f"{PREFIX}/limits/whatif").json()
        assert body["equity"] == pytest.approx(2_000_000 - 10_010)

    def test_csv_and_tax_cover_every_trade_handed_over(self, env):
        client, context, *_ = env
        context.book = [closed_trade(1.0, trade_id=index, close_date="2026-10-25 01:00:00") for index in range(1001)]
        assert len(client.get(f"{PREFIX}/export/trades.csv").text.strip().split("\n")) == 1002
        assert client.get(f"{PREFIX}/export/tax").json()["total"]["trades"] == 1001


class TestOneAuditRowPerControlCall:
    def rows(self, context):
        return [(row["action"], row["result"]) for row in context.audits]

    def test_a_malformed_timerange_is_audited_as_failed(self, env, upstream_calls):
        client, context, *_ = env
        assert client.post(f"{PREFIX}/backtest", json={"timerange": "abc"}).status_code == 422
        assert self.rows(context) == [("analytics.backtest.start", "failed")]
        assert upstream_calls == []

    def test_an_unknown_bot_is_audited_as_failed_for_apply_and_backtest(self, env):
        client, context, *_ = env
        assert client.post(f"{PREFIX}/scoreboard/apply", params={"bot": "X"}).status_code == 404
        assert client.post(f"{PREFIX}/backtest", json={"bot": "X", "timerange": "20261001-20261020"}).status_code == 404
        assert self.rows(context) == [
            ("analytics.scoreboard.apply", "failed"),
            ("analytics.backtest.start", "failed"),
        ]
        assert context.audits[0]["targets"] == ["X"]

    def test_a_config_that_cannot_be_written_is_audited_and_is_not_a_bare_500(self, env, monkeypatch):
        client, context, *_ = env

        def broken(path, voters):
            raise PermissionError("read-only")

        monkeypatch.setattr("analytics.service.apply_disables", broken)
        monkeypatch.setattr(
            "analytics.service.plan_disables",
            lambda board, settings: {"disable": [], "recommended": ["v1"], "kept_for_quorum": []},
        )
        response = client.post(f"{PREFIX}/scoreboard/apply")
        assert response.status_code == 500
        assert response.json()["error"]["message"] == "could not write the config: PermissionError"
        assert self.rows(context) == [("analytics.scoreboard.apply", "failed")]
        assert context.audits[0]["detail"]["error"] == "PermissionError"


class TestComputeStaysOffTheEventLoop:
    def test_the_heavy_views_run_in_a_worker_thread(self, env, monkeypatch):
        import threading

        client, context, *_ = env
        loop_threads = []
        original_trades = context.trades

        async def trades(bot):
            loop_threads.append(threading.get_ident())
            return await original_trades(bot)

        monkeypatch.setattr(context, "trades", trades)
        seen = {}
        from analytics import routes

        def wrap(name):
            original = getattr(routes, name)

            def inner(*args, **kwargs):
                seen[name] = threading.get_ident()
                return original(*args, **kwargs)

            monkeypatch.setattr(routes, name, inner)

        for name in ("whatif_limits", "stress", "portfolio", "trades_csv", "tax_summary"):
            wrap(name)
        for path in ("/limits/whatif", "/stress", "/portfolio", "/export/trades.csv", "/export/tax"):
            assert client.get(PREFIX + path).status_code == 200
        assert set(seen) == {"whatif_limits", "stress", "portfolio", "trades_csv", "tax_summary"}
        assert len(set(loop_threads)) == 1
        assert all(ident != loop_threads[0] for ident in seen.values())
