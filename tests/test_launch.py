from __future__ import annotations

import json

import pytest
from freqtrade.configuration.config_validation import validate_config_consistency, validate_config_schema
from freqtrade.enums import RunMode
from freqtrade.resolvers import StrategyResolver

from engine import launch
from engine.settings import load_settings
from tests.conftest import EXAMPLE

SECRETS = {
    "FT_API_USERNAME": "bot",
    "FT_API_PASSWORD": "pw-example",
    "FT_API_JWT_SECRET": "jwt-example",
    "FT_API_WS_TOKEN": "ws-example",
}


@pytest.fixture
def exec_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.os, "execvpe", lambda *args: calls.append(args))
    return calls


def test_rendered_config_passes_freqtrade_validation(tmp_path):
    rendered = launch.freqtrade_config(load_settings(EXAMPLE))
    rendered["api_server"].update(username="bot", password="pw", jwt_secret_key="j" * 32, ws_token="w")
    rendered.update(
        runmode=RunMode.DRY_RUN,
        strategy=launch.STRATEGY,
        strategy_path=str(launch.ENGINE_ROOT / "strategies"),
        user_data_dir=tmp_path,
    )
    StrategyResolver.load_strategy(rendered)
    validate_config_schema(rendered)
    validate_config_consistency(rendered)
    assert rendered["stake_amount"] == "unlimited"
    assert rendered["tradable_balance_ratio"] == 0.99
    assert rendered["dry_run"] is True
    assert rendered["dry_run_wallet"] == 2_000_000
    assert rendered["fee"] == 0.002
    assert rendered["apiserver"] == {"allow_custom_messages": True}
    assert rendered["trading_bot"]["compounding"] is True


@pytest.mark.parametrize("command", ["download-data", "backtesting", "show-config"])
def test_offline_commands_run_without_api_server_or_secrets(monkeypatch, tmp_path, exec_calls, command):
    for name in SECRETS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    launch.main([command])
    [(_, argv, env)] = exec_calls
    assert argv[1] == command
    assert not any(key.startswith("FREQTRADE__API_SERVER__") for key in env)
    rendered = json.loads((tmp_path / "user_data" / "trading-bot.freqtrade.json").read_text(encoding="utf-8"))
    assert "api_server" not in rendered
    assert "apiserver" not in rendered


def test_rendered_config_has_no_secrets():
    rendered = json.dumps(launch.freqtrade_config(load_settings(EXAMPLE)))
    for key in ("password", "jwt_secret_key", "ws_token", "username"):
        assert key not in rendered


def test_invalid_config_refuses_to_start(monkeypatch, tmp_path, example_raw, write_config, exec_calls, capsys):
    example_raw["risk"]["max_daily_loss_pct"] = 0
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(write_config(example_raw)))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    assert launch.main(["trade"]) == 2
    assert exec_calls == []
    assert not (tmp_path / "user_data").exists()
    assert "refusing to start" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["trade", "webserver"])
def test_missing_api_secret_refuses_to_start(monkeypatch, tmp_path, exec_calls, command):
    for name in SECRETS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    assert launch.main([command]) == 2
    assert exec_calls == []


@pytest.mark.parametrize("command", ["trade", "webserver"])
def test_serving_commands_pass_api_secrets_through_env(monkeypatch, tmp_path, exec_calls, command):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    launch.main([command])
    [(_, argv, env)] = exec_calls
    assert argv[1] == command
    assert env["FREQTRADE__API_SERVER__WS_TOKEN"] == "ws-example"
    assert ("--strategy" in argv) is (command in launch.STRATEGY_COMMANDS)


def test_valid_config_execs_freqtrade_with_strategy(monkeypatch, tmp_path, exec_calls):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    launch.main(["trade", "--dry-run"])
    [(program, argv, env)] = exec_calls
    assert program == "freqtrade"
    assert argv[:2] == ["freqtrade", "trade"]
    assert argv[argv.index("--strategy") + 1] == "SwingEmaRsi"
    assert argv[-1] == "--dry-run"
    assert env["FREQTRADE__API_SERVER__PASSWORD"] == "pw-example"
    rendered = json.loads((tmp_path / "user_data" / "trading-bot.freqtrade.json").read_text(encoding="utf-8"))
    assert "pw-example" not in json.dumps(rendered)
