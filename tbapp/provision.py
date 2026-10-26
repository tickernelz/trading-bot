from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MIN_PORT_BASE = 1024
MAX_PORT_BASE = 65000
DEFAULT_PORT_BASE = 8080


@dataclass(frozen=True)
class Ports:
    base: int = DEFAULT_PORT_BASE

    @property
    def bot_a(self) -> int:
        return self.base

    @property
    def bot_b(self) -> int:
        return self.base + 1

    @property
    def gateway(self) -> int:
        return self.base + 10

    @property
    def shadow(self) -> int:
        return self.base + 11

    @property
    def analyst(self) -> int:
        return self.base + 12

    def all(self) -> dict[str, int]:
        return {
            "bot-a": self.bot_a,
            "bot-b": self.bot_b,
            "gateway": self.gateway,
            "shadow": self.shadow,
            "analyst": self.analyst,
        }


def check_port_base(base: int) -> int:
    if not MIN_PORT_BASE <= base <= MAX_PORT_BASE:
        raise ValueError(f"port base must be between {MIN_PORT_BASE} and {MAX_PORT_BASE}")
    return base


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, _, value = text.partition("=")
        values[name.strip()] = value.strip().strip("\"'")
    return values


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def env_text(values: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in values.items())


def dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def bot_configs(example: dict[str, Any], ports: Ports) -> tuple[dict[str, Any], dict[str, Any]]:
    bot_a = yaml.safe_load(yaml.safe_dump(example))
    bot_a["bot_id"] = "A"
    bot_a["api"]["port"] = ports.bot_a
    bot_a["swarm"]["enabled"] = False
    bot_a.pop("shadow", None)
    bot_a.pop("analyst", None)
    bot_b = yaml.safe_load(yaml.safe_dump(example))
    bot_b["bot_id"] = "B"
    bot_b["api"]["port"] = ports.bot_b
    bot_b["shadow"]["port"] = ports.shadow
    bot_b["analyst"]["port"] = ports.analyst
    return bot_a, bot_b


def gateway_config(example: dict[str, Any], home: Path, ports: Ports) -> dict[str, Any]:
    run = home / "run"
    config = home / "config"
    result = yaml.safe_load(yaml.safe_dump(example))
    result["port"] = ports.gateway
    result["state_dir"] = str(run / "gateway")
    result["analysis_url"] = f"http://127.0.0.1:{ports.analyst}"
    for bot in result["bots"]:
        key = bot["id"].lower()
        bot["api_url"] = f"http://127.0.0.1:{ports.bot_a if key == 'a' else ports.bot_b}"
        bot["config"] = str(config / f"bot-{key}.yaml")
        bot["userdir"] = str(run / f"bot-{key}")
        if key == "b":
            bot["shadow_url"] = f"http://127.0.0.1:{ports.shadow}"
            bot["decisions"] = str(run / "bot-b" / "swarm_decisions.sqlite")
    return result


def provision(home: Path, root: Path, ports: Ports) -> str | None:
    """Create the data folder on first run; return the gateway password when it was created, else None."""
    gateway_file = home / "config" / "gateway.yaml"
    if gateway_file.exists():
        return None
    example = yaml.safe_load((root / "config" / "config.example.yaml").read_text(encoding="utf-8"))
    gateway_example = yaml.safe_load((root / "config" / "gateway.example.yaml").read_text(encoding="utf-8"))
    bot_a, bot_b = bot_configs(example, ports)
    for name in ("bot-a", "bot-b", "gateway", "analyst"):
        (home / "run" / name).mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    dump(home / "config" / "bot-a.yaml", bot_a)
    dump(home / "config" / "bot-b.yaml", bot_b)
    ft = {
        "FT_API_USERNAME": "bot",
        "FT_API_PASSWORD": secrets.token_urlsafe(24),
        "FT_API_JWT_SECRET": secrets.token_urlsafe(32),
    }
    analyst_token = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(12)
    secret_dir = home / "secrets"
    write_private(secret_dir / "ft.env", env_text(ft))
    write_private(secret_dir / "shadow.env", env_text({"SHADOW_TOKEN": secrets.token_urlsafe(32)}))
    write_private(secret_dir / "swarm.env", "")
    write_private(secret_dir / "analyst.env", env_text({"ANALYST_TOKEN": analyst_token}))
    write_private(
        secret_dir / "gateway.env",
        env_text(
            {
                "GW_PASSWORD": password,
                "FT_API_USERNAME": ft["FT_API_USERNAME"],
                "FT_API_PASSWORD": ft["FT_API_PASSWORD"],
                "ANALYST_TOKEN": analyst_token,
            }
        ),
    )
    dump(gateway_file, gateway_config(gateway_example, home, ports))
    return password
