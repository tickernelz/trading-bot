from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock
from urllib.parse import parse_qs

import pytest
from freqtrade.configuration.config_validation import validate_config_schema
from freqtrade.configuration.environment_vars import environment_vars_to_dict
from freqtrade.enums import State
from freqtrade.misc import deep_merge_dicts
from freqtrade.persistence import init_db
from freqtrade.rpc import RPC
from freqtrade.rpc.telegram import Telegram
from telegram.ext import Application

from engine import launch
from engine.settings import ConfigError, load_settings
from tests.conftest import EXAMPLE
from tests.test_launch import SECRETS

TOKEN = "123456:stub-token"
OWNER = 4242
STRANGER = 999


class StubBotApi:
    """Minimal Telegram Bot API double that serves queued updates and records replies."""

    def __init__(self) -> None:
        self.lock = threading.Condition()
        self.pending: list[dict] = []
        self.sent: list[dict] = []
        self.polled = threading.Event()
        self.next_update = 1
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/bot"

    def command(self, chat_id: int, text: str) -> None:
        name = text.split()[0]
        with self.lock:
            self.pending.append(
                {
                    "update_id": self.next_update,
                    "message": {
                        "message_id": self.next_update,
                        "date": int(time.time()),
                        "chat": {"id": chat_id, "type": "private"},
                        "from": {"id": chat_id, "is_bot": False, "first_name": "owner"},
                        "text": text,
                        "entities": [{"type": "bot_command", "offset": 0, "length": len(name)}],
                    },
                }
            )
            self.next_update += 1

    def wait_sent(self, count: int, timeout: float = 20) -> list[dict]:
        with self.lock:
            assert self.lock.wait_for(lambda: len(self.sent) >= count, timeout), self.sent
            return list(self.sent)

    def _reply(self, method: str, params: dict):
        if method == "getMe":
            return {"id": 1, "is_bot": True, "first_name": "trading-bot", "username": "trading_bot_stub"}
        if method == "getUpdates":
            self.polled.set()
            with self.lock:
                updates, self.pending = self.pending, []
            if not updates:
                time.sleep(0.1)
            return updates
        if method == "sendMessage":
            with self.lock:
                self.sent.append(params)
                self.lock.notify_all()
            return {
                "message_id": 1000 + len(self.sent),
                "date": int(time.time()),
                "chat": {"id": int(params["chat_id"]), "type": "private"},
                "text": params["text"],
            }
        return True

    def _handler(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                if self.headers.get("Content-Type", "").startswith("application/json"):
                    params = json.loads(body or "{}")
                else:
                    params = {key: values[0] for key, values in parse_qs(body).items()}
                if not self.path.startswith(f"/bot{TOKEN}/"):
                    self.send_response(401)
                    self.end_headers()
                    return
                payload = json.dumps({"ok": True, "result": stub._reply(self.path.rsplit("/", 1)[1], params)})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload.encode())

            def log_message(self, *args):
                pass

        return Handler


def enabled_settings(example_raw, write_config):
    example_raw["notify"]["telegram"] = {
        "enabled": True,
        "token_env": "TELEGRAM_BOT_TOKEN",
        "chat_id": str(OWNER),
        "authorized_users": [str(OWNER)],
    }
    return load_settings(write_config(example_raw))


def test_channel_is_off_by_default():
    settings = load_settings(EXAMPLE)
    assert settings.notify.telegram.enabled is False
    assert "telegram" not in launch.freqtrade_config(settings, True, launch.telegram_enabled(settings, "trade"))


@pytest.mark.parametrize("missing", ["chat_id", "authorized_users"])
def test_enabled_channel_must_name_chat_and_users(example_raw, write_config, missing):
    example_raw["notify"]["telegram"] = {"enabled": True, "chat_id": "1", "authorized_users": ["1"]}
    example_raw["notify"]["telegram"][missing] = None if missing == "chat_id" else []
    with pytest.raises(ConfigError, match=missing):
        load_settings(write_config(example_raw))


def test_enabled_channel_refuses_to_start_without_token(monkeypatch, tmp_path, example_raw, write_config):
    calls = []
    monkeypatch.setattr(launch, "run_freqtrade", lambda argv, env: calls.append((argv[0], argv, env)) or 0)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    enabled_settings(example_raw, write_config)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    assert launch.main(["trade"]) == 2
    assert calls == []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    launch.main(["trade"])
    [(_, _, env)] = calls
    assert env["FREQTRADE__TELEGRAM__TOKEN"] == TOKEN
    rendered = (tmp_path / "user_data" / "trading-bot.freqtrade.json").read_text(encoding="utf-8")
    assert TOKEN not in rendered
    assert json.loads(rendered)["telegram"]["chat_id"] == str(OWNER)


def test_webserver_ignores_channel(example_raw, write_config):
    settings = enabled_settings(example_raw, write_config)
    assert launch.telegram_enabled(settings, "webserver") is False
    assert "FREQTRADE__TELEGRAM__TOKEN" not in launch.secret_env(settings, SECRETS)


def test_builtin_commands_answer_only_the_owner_through_stub(monkeypatch, example_raw, write_config):
    settings = enabled_settings(example_raw, write_config)
    environ = {**SECRETS, "FT_API_JWT_SECRET": "j" * 32, "TELEGRAM_BOT_TOKEN": TOKEN}
    for name, value in launch.secret_env(settings, environ, telegram=True).items():
        monkeypatch.setenv(name, value)
    config = deep_merge_dicts(environment_vars_to_dict(), launch.freqtrade_config(settings, True, telegram=True))
    validate_config_schema(config)
    assert config["telegram"]["token"] == TOKEN

    stub = StubBotApi()
    monkeypatch.setattr(
        Telegram,
        "_init_telegram_app",
        lambda self: Application.builder().token(self._config["telegram"]["token"]).base_url(stub.base_url).build(),
    )
    init_db("sqlite://")
    bot = MagicMock()
    bot.config = config
    bot.state = State.RUNNING
    channel = Telegram(RPC(bot), config)
    try:
        assert stub.polled.wait(20)
        stub.command(STRANGER, "/stopentry")
        stub.command(OWNER, "/status")
        [status] = stub.wait_sent(1)
        assert status["chat_id"] in (OWNER, str(OWNER))
        assert "no active trade" in status["text"]
        assert bot.state == State.RUNNING

        stub.command(OWNER, "/stopentry")
        stub.command(OWNER, "/help")
        sent = stub.wait_sent(3)
        assert bot.state == State.PAUSED
        assert "paused" in sent[1]["text"]
        assert "/stopentry" in sent[2]["text"]
        assert all(str(message["chat_id"]) == str(OWNER) for message in sent)
    finally:
        channel.cleanup()
        stub.server.shutdown()
