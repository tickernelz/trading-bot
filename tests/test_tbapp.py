from __future__ import annotations

import re
import socket
import stat
import sys
from pathlib import Path

import pytest

from engine.settings import load_settings
from gateway.settings import load_gateway_settings
from tbapp import paths, supervisor
from tbapp.provision import Ports, check_port_base, provision, read_env_file

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def home(tmp_path):
    target = tmp_path / "home"
    password = provision(target, ROOT, Ports(31000))
    return target, password


def test_first_run_creates_valid_configs_on_the_chosen_ports(home):
    target, password = home
    config = target / "config"
    bot_a = load_settings(config / "bot-a.yaml")
    bot_b = load_settings(config / "bot-b.yaml")
    gateway = load_gateway_settings(config / "gateway.yaml")
    assert (bot_a.bot_id, bot_a.api.port, bot_a.swarm.enabled) == ("A", 31000, False)
    assert bot_a.shadow is None and bot_a.analyst is None
    assert (bot_b.bot_id, bot_b.api.port, bot_b.shadow.port, bot_b.analyst.port) == ("B", 31001, 31011, 31012)
    assert gateway.port == 31010 and gateway.analysis_url == "http://127.0.0.1:31012"
    by_id = {bot.id: bot for bot in gateway.bots}
    assert by_id["A"].api_url == "http://127.0.0.1:31000" and by_id["A"].shadow_url is None
    assert by_id["B"].shadow_url == "http://127.0.0.1:31011"
    assert by_id["B"].decisions == str(target / "run" / "bot-b" / "swarm_decisions.sqlite")
    assert Path(gateway.state_dir).is_relative_to(target)
    assert read_env_file(target / "secrets" / "gateway.env")["GW_PASSWORD"] == password
    assert len(password) >= 12


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_a_first_run_interrupted_after_the_secrets_can_be_repeated(home):
    target, _ = home
    (target / "config" / "gateway.yaml").unlink()
    stale = target / "secrets" / "ft.env"
    stale.write_text("FT_API_USERNAME=old\n", encoding="utf-8")
    password = provision(target, ROOT, Ports(31000))
    assert password is not None
    assert read_env_file(stale)["FT_API_USERNAME"] == "bot"
    assert stat.S_IMODE(stale.stat().st_mode) == 0o600
    assert sorted(path.name for path in (target / "secrets").iterdir()) == [
        "analyst.env", "ft.env", "gateway.env", "shadow.env", "swarm.env",
    ]


def test_second_run_keeps_existing_files(home):
    target, _ = home
    before = {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert provision(target, ROOT, Ports(41000)) is None
    assert before == {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_secret_files_are_private(home):
    target, _ = home
    assert stat.S_IMODE((target / "secrets").stat().st_mode) == 0o700
    for path in (target / "secrets").iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("base", [80, 1023, 65001])
def test_port_base_outside_the_unprivileged_range_is_rejected(base):
    with pytest.raises(ValueError):
        check_port_base(base)


def test_each_process_receives_only_its_own_secrets(home, monkeypatch):
    target, _ = home
    monkeypatch.setenv("SOME_PROVIDER_API_KEY", "from-the-shell")
    monkeypatch.setenv("KEPT_SETTING", "kept")
    children = {child.name: child for child in supervisor.build_children(target)}
    assert set(children) == {"bot-a", "bot-b", "shadow", "analyst", "gateway"}
    envs = {name: supervisor.child_environment(child, target) for name, child in children.items()}
    assert "FT_API_JWT_SECRET" in envs["bot-a"] and "SHADOW_TOKEN" not in envs["bot-a"]
    assert "SHADOW_TOKEN" in envs["bot-b"] and "GW_PASSWORD" not in envs["bot-b"]
    assert "SHADOW_TOKEN" in envs["shadow"] and "FT_API_PASSWORD" not in envs["shadow"]
    assert "ANALYST_TOKEN" in envs["analyst"] and "GW_PASSWORD" not in envs["analyst"]
    assert {"GW_PASSWORD", "FT_API_PASSWORD", "ANALYST_TOKEN"} <= set(envs["gateway"])
    assert "FT_API_JWT_SECRET" not in envs["gateway"] and "SHADOW_TOKEN" not in envs["gateway"]
    assert all("SOME_PROVIDER_API_KEY" not in env and env["KEPT_SETTING"] == "kept" for env in envs.values())
    assert envs["bot-b"]["TRADING_BOT_CONFIG"] == str(target / "config" / "bot-b.yaml")
    assert envs["gateway"]["GATEWAY_CONFIG"] == str(target / "config" / "gateway.yaml")


def _child():
    return supervisor.Child("bot-a", Path("c"), Path("u"), ())


@pytest.mark.parametrize("code", [1, 2, 137])
def test_a_child_that_fails_is_restarted_with_backoff(home, code):
    target, _ = home
    runner = supervisor.Supervisor(target)
    child = _child()
    child.started_at = supervisor.time.monotonic()
    runner.exited(child, code)
    assert child.retry_at is not None and not child.refused
    first = child.retry_at - supervisor.time.monotonic()
    child.started_at = supervisor.time.monotonic()
    runner.exited(child, code)
    assert child.retry_at - supervisor.time.monotonic() > first


def test_a_child_that_refuses_its_configuration_is_not_restarted(home):
    target, _ = home
    runner = supervisor.Supervisor(target)
    child = _child()
    runner.exited(child, supervisor.REFUSED)
    assert child.refused and child.retry_at is None


def test_the_refusal_code_is_not_one_freqtrade_uses():
    import freqtrade.main

    source = Path(freqtrade.main.__file__).read_text(encoding="utf-8")
    used = {int(token) for token in re.findall(r"return_code = (\d+)", source)}
    assert supervisor.REFUSED not in used


@pytest.mark.skipif(sys.platform == "win32", reason="running logs are rotated only on POSIX")
def test_a_log_over_the_limit_is_rotated_while_the_child_runs(home, monkeypatch):
    target, _ = home
    monkeypatch.setattr(supervisor, "LOG_LIMIT", 100)
    runner = supervisor.Supervisor(target)
    child = _child()
    child.log = runner.open_log(child)
    child.proc = object()
    child.log.write(b"x" * 500)
    child.log.flush()
    runner.rotate(child)
    child.log.write(b"after")
    child.log.flush()
    path = target / "logs" / "bot-a.log"
    assert path.read_bytes() == b"after"
    assert (target / "logs" / "bot-a.log.old").stat().st_size == 500
    child.log.close()


def test_children_get_no_path_to_the_secrets_folder(home):
    target, _ = home
    for child in supervisor.build_children(target):
        env = supervisor.child_environment(child, target)
        assert all(str(target / "secrets") not in value for value in env.values())


def test_busy_ports_are_reported_by_component(home):
    target, _ = home
    ports = supervisor.configured_ports(target)
    assert ports == {"bot-a": 31000, "bot-b": 31001, "gateway": 31010, "shadow": 31011, "analyst": 31012}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        taken = listener.getsockname()[1]
        assert supervisor.busy_ports({"gateway": taken, "bot-a": 1}) == {"gateway": taken}


def test_data_home_follows_the_override_and_the_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADING_BOT_HOME", str(tmp_path))
    assert paths.data_home() == tmp_path.resolve()
    monkeypatch.delenv("TRADING_BOT_HOME")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    expected = {
        "win32": tmp_path / "local" / "TradingBot",
        "darwin": Path.home() / "Library" / "Application Support" / "TradingBot",
    }
    assert paths.data_home() == expected.get(sys.platform, tmp_path / "xdg" / "trading-bot")
