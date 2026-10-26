"""Client for the Freqtrade instance in webserver mode, the only mode that serves pair_history and backtest."""

from __future__ import annotations

import re
from typing import Any

import httpx

from analytics.errors import AnalyticsError

TIMERANGE = re.compile(r"^(\d{8}-(\d{8})?|-\d{8})$")
DETAIL_LIMIT = 200
TRADE_LIST_KEYS = ("trades", "locks", "best_pair", "worst_pair")


def error_for(response: httpx.Response, path: str) -> AnalyticsError:
    status = response.status_code
    if status == 503:
        return AnalyticsError(503, "upstream_unavailable", "Freqtrade is not running in webserver mode", 2000)
    if status in (401, 403):
        return AnalyticsError(502, "upstream_error", "Freqtrade rejected the gateway credentials")
    if status == 404:
        return AnalyticsError(404, "not_found", f"Freqtrade has no {path}")
    try:
        detail = str(response.json().get("detail", ""))[:DETAIL_LIMIT]
    except ValueError:
        detail = ""
    if status in (400, 422):
        return AnalyticsError(422, "invalid_request", detail or "Freqtrade rejected the request")
    return AnalyticsError(502, "upstream_error", detail or f"Freqtrade answered {status} for {path}")


class AnalysisClient:
    def __init__(
        self,
        api_url: str,
        username: str,
        password: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client = httpx.AsyncClient(
            base_url=api_url.rstrip("/") + "/api/v1", auth=(username, password), timeout=timeout, transport=transport
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise AnalyticsError(
                503, "upstream_unavailable", "Freqtrade webserver did not answer in time", 2000
            ) from exc
        except httpx.HTTPError as exc:
            raise AnalyticsError(503, "upstream_unavailable", "Freqtrade webserver is not reachable", 2000) from exc
        if response.status_code >= 400:
            raise error_for(response, path)
        return response.json()

    async def pair_history(self, pair: str, timeframe: str, timerange: str, strategy: str) -> dict[str, Any]:
        params = {"pair": pair, "timeframe": timeframe, "timerange": timerange, "strategy": strategy}
        return await self.request("GET", "/pair_history", params=params)

    async def backtest_start(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/backtest", json=body)

    async def backtest_status(self) -> dict[str, Any]:
        return await self.request("GET", "/backtest")

    async def backtest_abort(self) -> dict[str, Any]:
        return await self.request("GET", "/backtest/abort")

    async def backtest_reset(self) -> dict[str, Any]:
        return await self.request("DELETE", "/backtest")

    async def backtest_history(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/backtest/history")

    async def backtest_history_result(self, filename: str, strategy: str) -> dict[str, Any]:
        return await self.request(
            "GET", "/backtest/history/result", params={"filename": filename, "strategy": strategy}
        )

    async def aclose(self) -> None:
        await self.client.aclose()


def signals_view(history: dict[str, Any]) -> dict[str, Any]:
    """Turn a pair_history payload into candles and entry or exit markers for a chart."""
    columns = history["columns"]
    index = {name: position for position, name in enumerate(columns)}
    missing = [
        name for name in ("date", "open", "high", "low", "close", "enter_long", "exit_long") if name not in index
    ]
    if missing:
        raise AnalyticsError(502, "upstream_error", f"pair_history lacks columns {', '.join(missing)}")
    candles = []
    signals = []
    for row in history["data"]:
        stamp = row[index["date"]]
        candles.append([stamp, *(row[index[name]] for name in ("open", "high", "low", "close"))])
        close = row[index["close"]]
        if row[index["enter_long"]] == 1:
            tag = row[index["enter_tag"]] if "enter_tag" in index else None
            signals.append({"ts": stamp, "kind": "enter", "rate": close, "tag": tag})
        if row[index["exit_long"]] == 1:
            tag = row[index["exit_tag"]] if "exit_tag" in index else None
            signals.append({"ts": stamp, "kind": "exit", "rate": close, "tag": tag})
    return {
        "strategy": history.get("strategy"),
        "pair": history.get("pair"),
        "timeframe": history.get("timeframe"),
        "data_start": history.get("data_start"),
        "data_stop": history.get("data_stop"),
        "candles": candles,
        "signals": signals,
        "enter_signals": history.get("enter_long_signals"),
        "exit_signals": history.get("exit_long_signals"),
        "note": "Strategy signals on historical data, not orders the bot placed.",
    }


def backtest_view(status: dict[str, Any], strategy: str) -> dict[str, Any]:
    """Return the backtest job state with the strategy's headline figures and without the trade list."""
    view = {key: status.get(key) for key in ("status", "running", "status_msg", "step", "progress", "trade_count")}
    result = status.get("backtest_result")
    if result:
        stats = (result.get("strategy") or {}).get(strategy) or {}
        view["result"] = {
            key: value
            for key, value in stats.items()
            if key not in TRADE_LIST_KEYS and not isinstance(value, (list, dict))
        }
        view["result"]["exit_reason_summary"] = stats.get("exit_reason_summary")
        view["result"]["results_per_pair"] = stats.get("results_per_pair")
    return view
