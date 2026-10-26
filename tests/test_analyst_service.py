from __future__ import annotations

import pytest
import yaml

from engine import analyst_service
from engine.exitcodes import REFUSED
from tests.conftest import EXAMPLE

KEY = "sk-analyst-0123456789abcdef"
TOKEN = "t" * 40


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr(analyst_service.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    return calls


def prepare(monkeypatch, tmp_path, mutate=None, env=None):
    raw = yaml.safe_load(EXAMPLE.read_text())
    raw["providers"][0]["base_url"] = "http://127.0.0.1:1/v1"
    if mutate:
        mutate(raw)
    config = tmp_path / "bot-b.yaml"
    config.write_text(yaml.safe_dump(raw))
    for name in ("ANALYST_TOKEN", "NUTARALINE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {"ANALYST_TOKEN": TOKEN, "NUTARALINE_API_KEY": KEY, **(env or {})}.items():
        if value is not None:
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRADING_BOT_CONFIG", str(config))
    monkeypatch.setenv("TRADING_BOT_USERDIR", str(tmp_path / "userdir"))


def test_service_starts_on_the_configured_loopback_port(monkeypatch, tmp_path, started):
    prepare(monkeypatch, tmp_path)
    assert analyst_service.main() == 0
    assert started[0]["host"] == "127.0.0.1" and started[0]["port"] == 8092


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({"ANALYST_TOKEN": None}, "ANALYST_TOKEN"),
        ({"ANALYST_TOKEN": "short"}, "32 characters"),
        ({"NUTARALINE_API_KEY": None}, "NUTARALINE_API_KEY"),
    ],
)
def test_service_refuses_to_start_without_its_token_or_model_key(monkeypatch, tmp_path, started, capsys, env, fragment):
    prepare(monkeypatch, tmp_path, env=env)
    assert analyst_service.main() == REFUSED
    assert started == []
    err = capsys.readouterr().err
    assert fragment in err and KEY not in err and TOKEN not in err


def test_service_refuses_a_config_without_an_analyst_section(monkeypatch, tmp_path, started, capsys):
    prepare(monkeypatch, tmp_path, mutate=lambda raw: raw.pop("analyst"))
    assert analyst_service.main() == REFUSED and started == []
    assert "no analyst section" in capsys.readouterr().err


def test_service_refuses_a_provider_without_a_resolvable_base_url(monkeypatch, tmp_path, started, capsys):
    prepare(monkeypatch, tmp_path, mutate=lambda raw: raw["providers"][0].update(base_url="from_import"))
    assert analyst_service.main() == REFUSED and started == []
    assert "base_url" in capsys.readouterr().err
