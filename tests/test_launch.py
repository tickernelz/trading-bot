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
    "SHADOW_TOKEN": "s" * 32,
}


@pytest.fixture
def exec_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(launch, "run_freqtrade", lambda argv, env: calls.append((argv[0], argv, env)) or 0)
    return calls


def test_rendered_config_passes_freqtrade_validation(tmp_path):
    rendered = launch.freqtrade_config(load_settings(EXAMPLE))
    rendered["api_server"].update(username="bot", password="pw", jwt_secret_key="j" * 32, ws_token="w")
    rendered.update(
        runmode=RunMode.DRY_RUN,
        strategy=load_settings(EXAMPLE).strategy.name,
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
    assert rendered["fee"] == pytest.approx(0.0031055)
    assert rendered["apiserver"] == {"allow_custom_messages": True}
    assert rendered["trading_bot"]["compounding"] is True


def _loaded_strategy(settings, tmp_path):
    rendered = launch.freqtrade_config(settings, serve_api=False)
    rendered.update(
        runmode=RunMode.BACKTEST,
        strategy=settings.strategy.name,
        strategy_path=str(launch.ENGINE_ROOT / "strategies"),
        user_data_dir=tmp_path,
    )
    return StrategyResolver.load_strategy(rendered)


def test_default_rule_strategy_fills_its_take_profit_at_the_gross_target(tmp_path):
    settings = load_settings(EXAMPLE)
    strategy = _loaded_strategy(settings, tmp_path)
    fee = settings.exchange.fee_pct / 100
    assert type(strategy).__name__ == "RuleStrategy"
    assert strategy.stoploss == settings.strategy.rule.stoploss
    gross = 1 + settings.strategy.rule.take_profit
    assert gross * (1 - fee) / (1 + fee) - 1 == pytest.approx(strategy.minimal_roi[0])
    assert strategy.rule == settings.strategy.rule


def test_swing_strategy_is_still_selectable(example_raw, write_config, tmp_path, monkeypatch, exec_calls):
    example_raw["strategy"] = {"name": "SwingEmaRsi"}
    path = write_config(example_raw)
    strategy = _loaded_strategy(load_settings(path), tmp_path)
    assert (type(strategy).__name__, strategy.stoploss) == ("SwingEmaRsi", -0.03)
    assert strategy.minimal_roi == {0: 0.05, 480: 0.025, 1440: 0.012}
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(path))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    launch.main(["backtesting"])
    [(_, argv, _)] = exec_calls
    assert argv[argv.index("--strategy") + 1] == "SwingEmaRsi"
    rendered = json.loads((tmp_path / "user_data" / "trading-bot.freqtrade.json").read_text(encoding="utf-8"))
    assert "rule" not in rendered["trading_bot"]


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
    assert ("--strategy" in argv) is (command == "trade")
    assert ("--strategy-path" in argv) is (command == "trade")
    rendered = json.loads((tmp_path / "user_data" / "trading-bot.freqtrade.json").read_text(encoding="utf-8"))
    assert rendered["strategy_path"] == str(launch.ENGINE_ROOT / "strategies")


def test_valid_config_execs_freqtrade_with_strategy(monkeypatch, tmp_path, exec_calls):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    launch.main(["trade", "--dry-run"])
    [(program, argv, env)] = exec_calls
    assert program == "freqtrade"
    assert argv[:2] == ["freqtrade", "trade"]
    assert argv[argv.index("--strategy") + 1] == "RuleStrategy"
    assert argv[-1] == "--dry-run"
    assert env["FREQTRADE__API_SERVER__PASSWORD"] == "pw-example"
    rendered = json.loads((tmp_path / "user_data" / "trading-bot.freqtrade.json").read_text(encoding="utf-8"))
    assert "pw-example" not in json.dumps(rendered)
    assert rendered["db_url"] == f"sqlite:///{tmp_path / 'user_data' / 'tradesv3.dryrun.sqlite'}"
    assert rendered["trading_bot"]["shadow_url"] == "http://127.0.0.1:8091"
    assert rendered["trading_bot"]["bot_id"] == "A"


def test_swarm_bot_refuses_to_start_without_shadow_token(monkeypatch, tmp_path, exec_calls, capsys):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SHADOW_TOKEN")
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    assert launch.main(["trade"]) == 2
    assert exec_calls == []
    assert "SHADOW_TOKEN" in capsys.readouterr().err


def test_rules_only_bot_starts_without_shadow_token(monkeypatch, tmp_path, example_raw, write_config, exec_calls):
    example_raw["swarm"]["enabled"] = False
    del example_raw["shadow"]
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SHADOW_TOKEN")
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(write_config(example_raw)))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    launch.main(["trade"])
    assert len(exec_calls) == 1


def test_recorded_live_mode_stops_the_engine_before_it_starts(monkeypatch, tmp_path, exec_calls):
    userdir = tmp_path / "user_data"
    userdir.mkdir()
    (userdir / "mode.json").write_text('{"mode": "live"}')
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(userdir))
    assert launch.main(["trade"]) == 2
    assert exec_calls == [] and not (userdir / "trading-bot.freqtrade.json").exists()


@pytest.mark.parametrize("content", [None, '{"mode": "dry_run"}', "{broken"])
def test_dry_run_or_unreadable_mode_state_still_starts_dry_run(monkeypatch, tmp_path, exec_calls, content):
    userdir = tmp_path / "user_data"
    userdir.mkdir()
    if content is not None:
        (userdir / "mode.json").write_text(content)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(userdir))
    launch.main(["trade"])
    [(_, argv, _)] = exec_calls
    assert argv[1] == "trade"
    assert json.loads((userdir / "trading-bot.freqtrade.json").read_text())["dry_run"] is True


@pytest.mark.parametrize(
    ("keys", "expected"), [({}, False), ({"INDODAX_API_KEY": "k-1", "INDODAX_API_SECRET": "s-1"}, True)]
)
def test_launch_records_whether_exchange_keys_exist_without_their_values(
    monkeypatch, tmp_path, exec_calls, keys, expected
):
    userdir = tmp_path / "user_data"
    for name in ("INDODAX_API_KEY", "INDODAX_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**SECRETS, **keys}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(userdir))
    launch.main(["trade"])
    recorded = json.loads((userdir / "capabilities.json").read_text())
    assert recorded["exchange_key_configured"] is expected
    assert "k-1" not in json.dumps(recorded) and "s-1" not in json.dumps(recorded)


@pytest.mark.parametrize("command", ["webserver", "backtesting"])
def test_only_trade_renders_the_shadow_service(monkeypatch, tmp_path, exec_calls, command):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SHADOW_TOKEN")
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(EXAMPLE))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "user_data"))
    launch.main([command])
    assert len(exec_calls) == 1
    rendered = json.loads((tmp_path / "user_data" / "trading-bot.freqtrade.json").read_text(encoding="utf-8"))
    assert rendered["trading_bot"]["shadow_url"] is None
    assert rendered["trading_bot"]["shadow_token_env"] is None
