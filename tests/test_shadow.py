from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from engine.settings import load_settings
from engine.shadow import create_app
from engine.shadow_client import TOKEN_HEADER
from tests.conftest import EXAMPLE

TOKEN = "t" * 32
CANDIDATE = {
    "decision_id": "a" * 32,
    "bot": "B",
    "pair": "BTC/IDR",
    "timeframe": "1h",
    "candle": "2026-10-25T17:00:00+00:00",
    "rate": 1_463_933_000.0,
    "entry_tag": "ema_cross_up",
    "risk": {"equity": 2_000_000.0},
    "candles": [],
}


class FakeService:
    def __init__(self, error: Exception | None = None) -> None:
        self.settings = load_settings(EXAMPLE)
        self.store = SimpleNamespace(interrupt_pending=lambda reason: 0, pending_count=lambda: 0)
        self.submitted: list[str] = []
        self.error = error

    def submit(self, candidate) -> None:
        if self.error:
            raise self.error
        self.submitted.append(candidate.decision_id)

    async def aclose(self) -> None:
        return None


def _post(service: FakeService, headers: dict[str, str]):
    with TestClient(create_app(service, TOKEN), raise_server_exceptions=False) as client:
        return client.post("/candidates", json=CANDIDATE, headers=headers)


def test_candidates_need_the_shared_token():
    service = FakeService()
    assert _post(service, {}).status_code == 401
    assert _post(service, {TOKEN_HEADER: "x" * 32}).status_code == 401
    assert service.submitted == []
    assert _post(service, {TOKEN_HEADER: TOKEN}).status_code == 202
    assert service.submitted == ["a" * 32]


def test_only_a_duplicate_decision_is_reported_as_conflict():
    duplicate = FakeService(sqlite3.IntegrityError("UNIQUE constraint failed: decisions.decision_id"))
    assert _post(duplicate, {TOKEN_HEADER: TOKEN}).status_code == 409
    full_disk = FakeService(sqlite3.OperationalError("database or disk is full"))
    assert _post(full_disk, {TOKEN_HEADER: TOKEN}).status_code == 500
