from __future__ import annotations

import asyncio

import httpx
import pytest

from analytics.errors import AnalyticsError
from analytics.freqtrade import AnalysisClient, backtest_view, signals_view

COLUMNS = ["date", "open", "high", "low", "close", "enter_long", "exit_long", "enter_tag", "exit_tag"]


def client(handler) -> AnalysisClient:
    return AnalysisClient("http://127.0.0.1:8099", "user", "secret", transport=httpx.MockTransport(handler))


def history(rows):
    return {
        "strategy": "SwingEmaRsi",
        "pair": "BTC/IDR",
        "timeframe": "1h",
        "columns": COLUMNS,
        "data": rows,
        "data_start": "2026-10-01",
        "data_stop": "2026-10-02",
        "enter_long_signals": 1,
        "exit_long_signals": 1,
    }


class TestClient:
    def test_pair_history_is_requested_with_basic_auth_and_the_given_window(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=history([]))

        result = asyncio.run(client(handler).pair_history("BTC/IDR", "1h", "20261001-20261002", "SwingEmaRsi"))
        assert result["pair"] == "BTC/IDR"
        request = seen[0]
        assert request.url.path == "/api/v1/pair_history"
        assert dict(request.url.params) == {
            "pair": "BTC/IDR",
            "timeframe": "1h",
            "timerange": "20261001-20261002",
            "strategy": "SwingEmaRsi",
        }
        assert request.headers["authorization"].startswith("Basic ")

    @pytest.mark.parametrize(
        ("status", "code", "fragment"),
        [
            (503, "upstream_unavailable", "webserver mode"),
            (401, "upstream_error", "credentials"),
            (404, "not_found", "/pair_history"),
            (422, "invalid_request", "bad timerange"),
            (502, "upstream_error", "boom"),
        ],
    )
    def test_upstream_statuses_map_to_gateway_error_codes(self, status, code, fragment):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"detail": "bad timerange" if status == 422 else "boom"})

        with pytest.raises(AnalyticsError) as error:
            asyncio.run(client(handler).pair_history("BTC/IDR", "1h", "20261001-20261002", "S"))
        assert error.value.code == code
        assert fragment in error.value.message

    def test_a_refused_connection_is_reported_as_unavailable_with_a_retry_hint(self):
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with pytest.raises(AnalyticsError) as error:
            asyncio.run(client(handler).backtest_status())
        assert error.value.status == 503 and error.value.retry_after_ms == 2000

    def test_upstream_detail_is_truncated_so_paths_and_traces_do_not_leak_whole(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"detail": "x" * 5000})

        with pytest.raises(AnalyticsError) as error:
            asyncio.run(client(handler).pair_history("BTC/IDR", "1h", "20261001-", "S"))
        assert len(error.value.message) == 200


class TestViews:
    def test_signals_view_lists_candles_and_marks_entries_and_exits(self):
        rows = [
            [1, 10, 11, 9, 10, 0, 0, None, None],
            [2, 10, 12, 10, 11, 1, 0, "ema_cross_up", None],
            [3, 11, 11, 8, 9, 0, 1, None, "exit_signal"],
        ]
        view = signals_view(history(rows))
        assert view["candles"] == [[1, 10, 11, 9, 10], [2, 10, 12, 10, 11], [3, 11, 11, 8, 9]]
        assert view["signals"] == [
            {"ts": 2, "kind": "enter", "rate": 11, "tag": "ema_cross_up"},
            {"ts": 3, "kind": "exit", "rate": 9, "tag": "exit_signal"},
        ]
        assert "not orders" in view["note"]

    def test_signals_view_names_the_columns_a_payload_lacks(self):
        payload = history([])
        payload["columns"] = ["date", "open"]
        with pytest.raises(AnalyticsError) as error:
            signals_view(payload)
        assert "enter_long" in error.value.message

    def test_backtest_view_drops_trade_lists_and_keeps_the_headline_figures(self):
        status = {
            "status": "ended",
            "running": False,
            "status_msg": "Backtest ended",
            "step": "finished",
            "progress": 1.0,
            "trade_count": 3,
            "backtest_result": {
                "strategy": {
                    "SwingEmaRsi": {
                        "total_trades": 3,
                        "profit_total_abs": -120.5,
                        "trades": [{"pair": "BTC/IDR"}] * 3,
                        "locks": [],
                        "exit_reason_summary": [{"exit_reason": "roi"}],
                        "results_per_pair": [{"key": "BTC/IDR"}],
                    }
                }
            },
        }
        view = backtest_view(status, "SwingEmaRsi")
        assert view["result"]["total_trades"] == 3
        assert view["result"]["profit_total_abs"] == -120.5
        assert "trades" not in view["result"] and "locks" not in view["result"]
        assert view["result"]["results_per_pair"] == [{"key": "BTC/IDR"}]

    def test_backtest_view_of_a_running_job_has_no_result(self):
        view = backtest_view({"status": "running", "running": True, "progress": 0.4, "backtest_result": None}, "S")
        assert view["running"] is True and "result" not in view
