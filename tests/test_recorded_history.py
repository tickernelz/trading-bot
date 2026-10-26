from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from engine.decisions import DecisionStore
from engine.launch import DRY_RUN_DB
from gateway.app import Gateway, create_app
from gateway.settings import GatewaySettings
from tests.conftest import EXAMPLE

DATA = Path(__file__).resolve().parent / "data" / "stage2c"
PASSWORD = "correct horse battery"
ENV = {"GW_PASSWORD": PASSWORD, "FT_API_USERNAME": "bot", "FT_API_PASSWORD": "pw"}
BTC_FIRST = "c59379cf6c83405aa91898467d700b11"
ETH = "a691f6edbc464e1fafe267daf1aa3698"
SOL = "c678a9b6492f40fab84c09f97aadea02"
BTC_SECOND = "da2b92e0dfd246d2ade92edc2688c52f"


def recorded(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class RecordedFreqtrade:
    """Replays the Freqtrade answers captured by scripts/record_fixture.py."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/pair_candles":
            key = f"/pair_candles?pair={request.url.params['pair']}"
            return httpx.Response(200, json=self.answers[key]) if key in self.answers else httpx.Response(502)
        if path == "/trades" and int(request.url.params.get("offset", 0)) > 0:
            total = self.answers["/trades"]["total_trades"]
            return httpx.Response(200, json={"trades": [], "trades_count": 0, "total_trades": total})
        if path not in self.answers:
            return httpx.Response(404, json={"detail": "not recorded"})
        return httpx.Response(200, json=self.answers[path])


def restore_userdir(userdir: Path, bot: dict, unlinked: set[str]) -> str | None:
    userdir.mkdir(parents=True)
    trades = sqlite3.connect(userdir / DRY_RUN_DB)
    trades.executescript(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, is_open INTEGER, close_profit_abs REAL, close_profit REAL);"
        "CREATE TABLE trade_custom_data (id INTEGER PRIMARY KEY, ft_trade_id INTEGER, cd_key TEXT, cd_type TEXT,"
        " cd_value TEXT);"
    )
    trades.executemany("INSERT INTO trades VALUES (:id, :is_open, :close_profit_abs, :close_profit)", bot["trades"])
    trades.executemany(
        "INSERT INTO trade_custom_data (ft_trade_id, cd_key, cd_type, cd_value)"
        " VALUES (:ft_trade_id, :cd_key, :cd_type, :cd_value)",
        [link for link in bot["custom_data"] if link["cd_value"] not in unlinked],
    )
    trades.commit()
    trades.close()
    if not bot["decisions"]:
        return None
    path = userdir / "swarm_decisions.sqlite"
    DecisionStore(path).close()
    db = sqlite3.connect(path)
    columns = list(bot["decisions"][0])
    db.executemany(
        f"INSERT INTO decisions ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})",
        bot["decisions"],
    )
    db.commit()
    db.close()
    return str(path)


@pytest.fixture
def replay(tmp_path):
    clients = []

    def start(unlinked: frozenset[str] = frozenset()) -> tuple[TestClient, dict[str, str]]:
        base = tmp_path / str(len(clients))
        bots = []
        fakes = {}
        for name, label, strategy in (
            ("bot-a", "Bot A", "rules only"),
            ("bot-b", "Bot B", "rules + shadow swarm"),
        ):
            bot = recorded(f"{name}.json")
            config = base / f"{name}.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(EXAMPLE, config)
            userdir = base / name
            bots.append(
                {
                    "id": bot["id"],
                    "label": label,
                    "strategy": strategy,
                    "api_url": f"http://127.0.0.1:{8180 + len(bots)}",
                    "config": str(config),
                    "userdir": str(userdir),
                    "decisions": restore_userdir(userdir, bot, set(unlinked)),
                }
            )
            fakes[bot["id"]] = RecordedFreqtrade(bot["answers"])
        settings = GatewaySettings(state_dir=str(base / "state"), exchange_probe_url=None, bots=bots)
        gateway = Gateway(settings, ENV)
        for bot_id, fake in fakes.items():
            upstream = gateway.upstreams[bot_id]
            upstream.client = httpx.AsyncClient(
                base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(fake)
            )
        recorded_at = datetime.fromisoformat(recorded("run.json")["recorded_at"])
        gateway.clock = lambda: recorded_at
        client = TestClient(create_app(gateway))
        client.last_userdir = base / "bot-b"
        clients.append(gateway)
        token = client.post("/gw/v1/session", json={"password": PASSWORD}).json()["token"]
        return client, {"Authorization": f"Bearer {token}"}

    yield start
    for gateway in clients:
        gateway.ledger.close()


def test_decision_detail_shows_every_voter_the_quorum_and_what_followed(replay):
    client, headers = replay()
    decision = client.get(f"/gw/v1/decisions/{BTC_FIRST}", headers=headers).json()
    assert [(voter["voter_id"], voter["answers"]["verdict"]["choice"]) for voter in decision["voters"]] == [
        (f"v{index}", "skip") for index in range(1, 8)
    ]
    verdict = decision["aggregate"]["questions"]["verdict"]
    assert verdict["median_probabilities"] == {"allow": 0.0, "reduce": 0.0, "skip": 1.0}
    assert verdict["spread"]["iqr"] == 0.0
    assert decision["quorum"] == {"required": 5, "answered": 7, "met": True}
    assert decision["would_take"] == {"verdict": "skip", "action": "stay out", "applied": False}
    outcome = decision["outcome"]
    assert {key: outcome[key] for key in ("state", "basis", "trade_id", "is_open", "profit_abs", "profit_pct")} == {
        "state": "settled",
        "basis": "trade",
        "trade_id": 1,
        "is_open": False,
        "profit_abs": -981.93363272,
        "profit_pct": -0.3326,
    }
    assert outcome["effect"] == "avoided_loss"
    assert outcome["trade"]["exit_reason"] == "force_exit"
    first, second, fourth = outcome["forward"]
    assert first == {
        "candles": 1,
        "until": "2026-10-26T01:00:00Z",
        "state": "settled",
        "close": 1453999000.0,
        "return_pct": -0.0001,
        "net_pct": -0.8201,
        "max_up_pct": 0.1843,
        "max_down_pct": -0.0417,
    }
    assert (second["close"], second["return_pct"], second["max_down_pct"]) == (1449038000.0, -0.3413, -0.619)
    assert fourth == {"candles": 4, "until": "2026-10-26T04:00:00Z", "state": "pending"}
    assert (outcome["horizon_h"], outcome["price_at"], outcome["price_after"]) == (4, 1454000000.0, None)


def test_skipped_entry_without_a_trade_is_judged_by_price_after_costs(replay):
    client, headers = replay(frozenset({ETH}))
    decision = client.get(f"/gw/v1/decisions/{ETH}?horizons=1", headers=headers).json()
    assert decision["aggregate"]["questions"]["verdict"]["votes"] == {"allow": 0, "reduce": 1, "skip": 6}
    outcome = decision["outcome"]
    assert {key: outcome[key] for key in ("state", "basis", "horizon_h", "price_after", "trade_id")} == {
        "state": "settled",
        "basis": "price",
        "horizon_h": 1,
        "price_after": 42260000.0,
        "trade_id": None,
    }
    assert (outcome["return_pct"], outcome["return_after_fees_pct"], outcome["effect"]) == (
        0.261,
        -0.559,
        "avoided_loss",
    )
    free = client.get(f"/gw/v1/decisions/{ETH}?horizons=1&cost_pct=0", headers=headers).json()["outcome"]
    assert (free["return_after_fees_pct"], free["effect"]) == (0.261, "missed_gain")
    later = client.get(f"/gw/v1/decisions/{ETH}", headers=headers).json()["outcome"]
    assert (later["state"], later["settles_at"], later["effect"]) == ("pending", "2026-10-26T04:00:00Z", "pending")


def test_failed_quorum_skips_and_an_open_trade_is_not_judged_yet(replay):
    client, headers = replay()
    decision = client.get(f"/gw/v1/decisions/{SOL}", headers=headers).json()
    assert (decision["status"], decision["reason"]) == ("skip", "quorum_not_met")
    assert decision["quorum"] == {"required": 5, "answered": 3, "met": False}
    assert [voter["status"] for voter in decision["voters"]].count("failed") == 4
    assert decision["would_take"]["verdict"] == "skip"
    outcome = decision["outcome"]
    assert (outcome["state"], outcome["basis"], outcome["is_open"], outcome["effect"]) == (
        "pending",
        "trade",
        True,
        "pending",
    )


def test_decision_list_filters_and_carries_outcomes(replay):
    client, headers = replay()
    rows = client.get("/gw/v1/decisions?bot=B", headers=headers).json()
    assert [row["decision_id"] for row in rows] == [BTC_SECOND, ETH, SOL, BTC_FIRST]
    assert all(row["outcome"]["basis"] == "trade" for row in rows)
    latest = client.get("/gw/v1/decisions?bot=B&limit=1&horizons=1,2", headers=headers).json()[0]
    assert latest["outcome"]["trade_id"] == 4
    assert [point["state"] for point in latest["outcome"]["forward"]] == ["settled", "pending"]
    assert latest["outcome"]["forward"][0]["return_pct"] == -0.2759

    def ids(query: str) -> list[str]:
        return [row["decision_id"] for row in client.get(f"/gw/v1/decisions?{query}", headers=headers).json()]

    assert ids("status=skip") == [SOL]
    assert ids("pair=BTC/IDR") == [BTC_SECOND, BTC_FIRST]
    assert ids("before=2026-10-26T01:00:00Z") == [BTC_SECOND, ETH, SOL, BTC_FIRST]
    assert ids("before=2026-10-26T00:00:00Z") == [ETH, SOL, BTC_FIRST]
    assert client.get("/gw/v1/decisions/0123", headers=headers).json()["error"]["code"] == "not_found"
    assert client.get("/gw/v1/decisions?horizons=0", headers=headers).status_code == 400


def test_daily_weekly_monthly_follow_the_risk_timezone(replay):
    client, headers = replay()
    daily = client.get("/gw/v1/profit?bot=B&window=daily&timescale=2", headers=headers).json()
    assert daily["timezone"] == "Asia/Jakarta"
    assert daily["data"] == [
        {
            "date": "2026-10-26",
            "start": "2026-10-25T17:00:00Z",
            "abs_profit": -4857.38042602,
            "starting_balance": 2000000.0,
            "rel_profit": -0.00242869,
            "trade_count": 3,
            "wins": 0,
            "losses": 3,
            "draws": 0,
        },
        {
            "date": "2026-10-25",
            "start": "2026-10-24T17:00:00Z",
            "abs_profit": 0.0,
            "starting_balance": 2000000.0,
            "rel_profit": 0.0,
            "trade_count": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        },
    ]
    weekly = client.get("/gw/v1/profit?bot=B&window=weekly&timescale=1", headers=headers).json()
    assert (weekly["data"][0]["date"], weekly["data"][0]["trade_count"]) == ("2026-10-26", 3)
    monthly = client.get("/gw/v1/profit?bot=B&window=monthly&timescale=1", headers=headers).json()
    assert (monthly["data"][0]["date"], monthly["data"][0]["abs_profit"]) == ("2026-10-01", -4857.38042602)


def test_history_exit_reasons_and_entry_tags_come_from_the_recorded_bot(replay):
    client, headers = replay()

    def trade_ids(query: str) -> list[int]:
        return [trade["trade_id"] for trade in client.get(f"/gw/v1/trades?bot=B&{query}", headers=headers).json()]

    assert trade_ids("limit=2&state=closed") == [4, 2]
    assert trade_ids("offset=2&state=closed") == [1]
    assert trade_ids("limit=10") == [4, 3, 2, 1]
    performance = client.get("/gw/v1/performance?bot=B", headers=headers).json()
    assert {row["mix_tag"]: (row["count"], row["profit_pct"]) for row in performance["by_mix_tag"]} == {
        "recorded_test force_exit": (2, -0.95),
        "force_entry force_exit": (1, -0.69),
    }
    assert {row["enter_tag"]: row["profit_abs"] for row in performance["by_enter_tag"]} == {
        "force_entry": -2049.413504,
        "recorded_test": -2807.96692202,
    }
    stats = client.get("/gw/v1/stats?bot=B", headers=headers).json()
    assert stats["exit_reasons"] == {"force_exit": {"wins": 0, "losses": 3, "draws": 0}}


def test_total_equity_stacks_both_bots_from_the_first_bot_start(replay):
    client, headers = replay()
    equity = client.get("/gw/v1/equity?window=total&bots=A,B", headers=headers).json()
    assert equity["start"] == "2026-10-26T00:54:49Z"
    curves = {series["bot"]: [point[1] for point in series["points"]] for series in equity["series"]}
    assert curves == {
        "A": [2000000.0, 1999018.07, 1996780.8, 1994954.95, 1992500.3],
        "B": [2000000.0, 1999018.07, 1996968.65, 1995142.62, 1992687.99],
    }
    assert {series["points"][0][0] for series in equity["series"]} == {"2026-10-26T00:54:49.005Z"}
    assert [series["start_equity"] for series in equity["series"]] == [2000000.0, 2000000.0]


def test_pages_union_to_every_decision_on_a_shared_candle(replay):
    client, headers = replay()
    first = client.get("/gw/v1/decisions", headers=headers, params={"bot": "B", "limit": 3}).json()
    second = client.get(
        "/gw/v1/decisions",
        headers=headers,
        params={"bot": "B", "limit": 3, "before": first[-1]["candle"]},
    ).json()
    assert [row["decision_id"] for row in first] == [BTC_SECOND, ETH, SOL]
    assert [row["decision_id"] for row in second] == [ETH, SOL, BTC_FIRST]
    assert len(first) == 3 and len(second) == 3
    assert {row["decision_id"] for row in first + second} == {
        row["decision_id"] for row in client.get("/gw/v1/decisions?bot=B", headers=headers).json()
    }
    seen = {row["decision_id"] for row in first}
    assert [row["decision_id"] for row in first] + [
        row["decision_id"] for row in second if row["decision_id"] not in seen
    ] == [BTC_SECOND, ETH, SOL, BTC_FIRST]


def test_a_locked_trade_database_answers_503_instead_of_hanging(replay):
    client, headers = replay()
    holder = sqlite3.connect(Path(client.last_userdir) / DRY_RUN_DB, timeout=5)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        started = time.monotonic()
        response = client.get("/gw/v1/decisions?bot=B&limit=4", headers=headers)
        elapsed = time.monotonic() - started
    finally:
        holder.rollback()
        holder.close()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_error"
    assert elapsed < 2.0
    assert client.get("/gw/v1/decisions?bot=B&limit=4", headers=headers).status_code == 200
