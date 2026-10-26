from __future__ import annotations

import logging

import pytest

from engine.launch import freqtrade_config
from engine.logredact import TokenFilter, redact
from engine.settings import load_settings
from engine.strategies.swing_ema_rsi import SwingEmaRsi
from tests.conftest import EXAMPLE

ACCEPT = '%s - "WebSocket %s" [accepted]'


@pytest.fixture
def captured():
    records: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = Collect()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.INFO)
    yield records
    root.removeHandler(handler)
    root.setLevel(previous)
    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        for item in [item for item in logger.filters if isinstance(item, TokenFilter)]:
            logger.removeFilter(item)


def test_loading_the_strategy_masks_websocket_tokens_before_root_handlers(captured):
    SwingEmaRsi(freqtrade_config(load_settings(EXAMPLE)))
    logging.getLogger("uvicorn.error").info(ACCEPT, "127.0.0.1:41506", "/api/v1/message/ws?token=eyJhbGciOi.secret")
    assert captured == ['127.0.0.1:41506 - "WebSocket /api/v1/message/ws?token=<redacted>" [accepted]']


def test_redact_keeps_other_query_parameters():
    assert redact("/ws?token=abc&x=1 and token=def") == "/ws?token=<redacted>&x=1 and token=<redacted>"
    assert redact("no secret here") == "no secret here"
