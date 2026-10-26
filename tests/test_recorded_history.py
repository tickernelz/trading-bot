from __future__ import annotations

import json
import shutil
import sqlite3
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


def restore_userdir(userdir: Path, bot: dict) -> str | None:
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
        bot["custom_data"],
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
    run = recorded("run.json")
    bots = []
    fakes = {}
    for name, label, strategy in (("bot-a", "Bot A", "aturan saja"), ("bot-b", "Bot B", "aturan + swarm bayangan")):
        bot = recorded(f"{name}.json")
        config = tmp_path / f"{name}.yaml"
        shutil.copy(EXAMPLE, config)
        userdir = tmp_path / name
        decisions = restore_userdir(userdir, bot)
        bots.append(
            {
                "id": bot["id"],
                "label": label,
                "strategy": strategy,
                "api_url": f"http://127.0.0.1:{8180 + len(bots)}",
                "config": str(config),
                "userdir": str(userdir),
                "decisions": decisions,
            }
        )
        fakes[bot["id"]] = RecordedFreqtrade(bot["answers"])
    gateway = Gateway(GatewaySettings(state_dir=str(tmp_path / "state"), exchange_probe_url=None, bots=bots), ENV)
    for bot_id, fake in fakes.items():
        upstream = gateway.upstreams[bot_id]
        upstream.client = httpx.AsyncClient(
            base_url=upstream.bot.api_url + "/api/v1", transport=httpx.MockTransport(fake)
        )
    recorded_at = datetime.fromisoformat(run["recorded_at"])
    gateway.clock = lambda: recorded_at
    client = TestClient(create_app(gateway))
    token = client.post("/gw/v1/session", json={"password": PASSWORD}).json()["token"]
    yield client, {"Authorization": f"Bearer {token}"}
    gateway.ledger.close()


BTC_FIRST = "c59379cf6c83405aa91898467d700b11"
ETH = "a691f6edbc464e1fafe267daf1aa3698"
SOL = "c678a9b6492f40fab84c09f97aadea02"
BTC_SECOND = "da2b92e0dfd246d2ade92edc2688c52f"


def test_decision_detail_shows_every_voter_the_quorum_and_what_followed(replay):
    client, headers = replay
    decision = client.get(f"/gw/v1/decisions/{BTC_FIRST}", headers=headers).json()
    assert [(voter["voter_id"], voter["answers"]["verdict"]["choice"]) for voter in decision["voters"]] == [
        (f"v{index}", "lewati") for index in range(1, 8)
    ]
    verdict = decision["aggregate"]["questions"]["verdict"]
    assert verdict["median_probabilities"] == {"izinkan": 0.0, "kecilkan": 0.0, "lewati": 1.0}
    assert verdict["spread"]["iqr"] == 0.0
    assert decision["quorum"] == {"required": 5, "answered": 7, "met": True}
    assert decision["would_take"] == {"verdict": "lewati", "action": "tidak masuk", "applied": False}
    outcome = decision["outcome"]
    assert outcome["trade"]["trade_id"] == 1
    assert outcome["trade"]["profit_abs"] == -981.93363272
    assert outcome["trade"]["profit_pct"] == -0.3326
    assert outcome["trade"]["result"] == "rugi"
    assert (outcome["effect"], outcome["basis"]) == ("menghindari_rugi", "trade")
    first, second, fourth = outcome["forward"]["horizons"]
    assert first == {
        "candles": 1,
        "until": "2026-10-26T01:00:00Z",
        "close": 1453999000.0,
        "return_pct": -0.0001,
        "net_pct": -0.8201,
        "max_up_pct": 0.1843,
        "max_down_pct": -0.0417,
        "result": "rugi",
    }
    assert (second["close"], second["return_pct"], second["max_down_pct"]) == (1449038000.0, -0.3413, -0.619)
    assert fourth == {"candles": 4, "until": "2026-10-26T04:00:00Z", "result": "belum_cukup_data"}


def test_gross_gain_below_the_round_trip_cost_counts_as_a_loss(replay):
    client, headers = replay
    decision = client.get(f"/gw/v1/decisions/{ETH}?horizons=1", headers=headers).json()
    assert decision["aggregate"]["questions"]["verdict"]["votes"] == {"izinkan": 0, "kecilkan": 1, "lewati": 6}
    (first,) = decision["outcome"]["forward"]["horizons"]
    assert (first["return_pct"], first["net_pct"], first["result"]) == (0.261, -0.559, "rugi")
    free = client.get(f"/gw/v1/decisions/{ETH}?horizons=1&cost_pct=0", headers=headers).json()
    assert free["outcome"]["forward"]["horizons"][0]["result"] == "untung"


def test_failed_quorum_skips_and_an_open_trade_is_not_judged_yet(replay):
    client, headers = replay
    decision = client.get(f"/gw/v1/decisions/{SOL}", headers=headers).json()
    assert (decision["status"], decision["reason"]) == ("skip", "quorum_not_met")
    assert decision["quorum"] == {"required": 5, "answered": 3, "met": False}
    assert [voter["status"] for voter in decision["voters"]].count("failed") == 4
    assert decision["would_take"]["verdict"] == "lewati"
    assert decision["outcome"]["trade"]["result"] == "masih_terbuka"
    assert (decision["outcome"]["effect"], decision["outcome"]["basis"]) == ("belum_cukup_data", None)


def test_decision_list_carries_outcomes_only_when_asked(replay):
    client, headers = replay
    plain = client.get("/gw/v1/decisions?bot=B", headers=headers).json()
    assert [row["decision_id"] for row in plain] == [BTC_SECOND, ETH, SOL, BTC_FIRST]
    assert "outcome" not in plain[0]
    rows = client.get("/gw/v1/decisions?bot=B&outcome=true&horizons=1,2", headers=headers).json()
    latest = rows[0]
    assert latest["outcome"]["trade"]["trade_id"] == 4
    assert [point["result"] for point in latest["outcome"]["forward"]["horizons"]] == ["rugi", "belum_cukup_data"]
    assert latest["outcome"]["forward"]["horizons"][0]["return_pct"] == -0.2759
    assert client.get("/gw/v1/decisions/0123", headers=headers).json()["error"]["code"] == "not_found"
    assert client.get("/gw/v1/decisions?horizons=0", headers=headers).status_code == 400


def test_daily_weekly_monthly_follow_the_risk_timezone(replay):
    client, headers = replay
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
    client, headers = replay
    trades = client.get("/gw/v1/trades?bot=B&limit=2", headers=headers).json()
    assert [trade["trade_id"] for trade in trades] == [4, 2]
    assert [trade["trade_id"] for trade in client.get("/gw/v1/trades?bot=B&offset=2", headers=headers).json()] == [1]
    performance = client.get("/gw/v1/performance?bot=B", headers=headers).json()
    assert {row["mix_tag"]: (row["count"], row["profit_pct"]) for row in performance["by_mix_tag"]} == {
        "uji_rekam force_exit": (2, -0.95),
        "force_entry force_exit": (1, -0.69),
    }
    assert {row["enter_tag"]: row["profit_abs"] for row in performance["by_enter_tag"]} == {
        "force_entry": -2049.413504,
        "uji_rekam": -2807.96692202,
    }
    stats = client.get("/gw/v1/stats?bot=B", headers=headers).json()
    assert stats["exit_reasons"] == {"force_exit": {"wins": 0, "losses": 3, "draws": 0}}


def test_run_equity_stacks_both_bots_from_the_first_bot_start(replay):
    client, headers = replay
    equity = client.get("/gw/v1/equity?window=run&bots=A,B", headers=headers).json()
    assert equity["start"] == "2026-10-26T00:54:49Z"
    curves = {series["bot"]: [point[1] for point in series["points"]] for series in equity["series"]}
    assert curves == {
        "A": [2000000.0, 1999018.07, 1996780.8, 1994954.95, 1992500.3],
        "B": [2000000.0, 1999018.07, 1996968.65, 1995142.62, 1992687.99],
    }
    assert {series["points"][0][0] for series in equity["series"]} == {"2026-10-26T00:54:49.005Z"}
    assert [series["start_equity"] for series in equity["series"]] == [2000000.0, 2000000.0]
