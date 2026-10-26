from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from engine.settings import load_settings
from gateway.settings import load_gateway_settings
from tbapp import paths
from tbapp.provision import read_env_file

REFUSED = 2
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASS)$", re.IGNORECASE)
LOG_LIMIT = 10 * 1024 * 1024
STOP_GRACE_S = 25
HEALTHY_AFTER_S = 60
MAX_BACKOFF_S = 60


@dataclass
class Child:
    name: str
    config: Path
    userdir: Path
    secret_files: tuple[str, ...]
    extra_env: dict[str, str] = field(default_factory=dict)
    proc: subprocess.Popen | None = None
    log: IO[bytes] | None = None
    started_at: float = 0.0
    failures: int = 0
    retry_at: float | None = None
    refused: bool = False


def component_command(name: str) -> list[str]:
    if paths.frozen():
        return [sys.executable, "component", name]
    return [sys.executable, "-m", "tbapp", "component", name]


def inherited_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not SECRET_NAME.search(key)}


def build_children(home: Path) -> list[Child]:
    config = home / "config"
    run = home / "run"
    secrets = home / "secrets"
    bot_b = load_settings(config / "bot-b.yaml")
    children = [
        Child("bot-a", config / "bot-a.yaml", run / "bot-a", ("ft.env",)),
        Child("bot-b", config / "bot-b.yaml", run / "bot-b", ("ft.env", "shadow.env")),
    ]
    if bot_b.swarm.enabled and bot_b.shadow is not None:
        children.append(Child("shadow", config / "bot-b.yaml", run / "bot-b", ("shadow.env", "swarm.env")))
    if bot_b.analyst is not None:
        children.append(Child("analyst", config / "bot-b.yaml", run / "bot-b", ("analyst.env",)))
    pwa = paths.pwa_dir()
    gateway_env = {"GATEWAY_CONFIG": str(config / "gateway.yaml")}
    if pwa is not None:
        gateway_env["TRADING_BOT_PWA_DIR"] = str(pwa)
    children.append(Child("gateway", config / "gateway.yaml", run / "gateway", ("gateway.env",), gateway_env))
    for child in children:
        child.extra_env["TRADING_BOT_SECRETS"] = str(secrets)
    return children


def child_environment(child: Child, home: Path) -> dict[str, str]:
    env = inherited_environment()
    env.update(
        TRADING_BOT_CONFIG=str(child.config),
        TRADING_BOT_USERDIR=str(child.userdir),
        TRADING_BOT_HOME=str(home),
        PYTHONUNBUFFERED="1",
        PYTHONUTF8="1",
    )
    for name in child.secret_files:
        env.update(read_env_file(home / "secrets" / name))
    env.update(child.extra_env)
    return env


def configured_ports(home: Path) -> dict[str, int]:
    config = home / "config"
    bot_a = load_settings(config / "bot-a.yaml")
    bot_b = load_settings(config / "bot-b.yaml")
    ports = {
        "bot-a": bot_a.api.port,
        "bot-b": bot_b.api.port,
        "gateway": load_gateway_settings(config / "gateway.yaml").port,
    }
    if bot_b.swarm.enabled and bot_b.shadow is not None:
        ports["shadow"] = bot_b.shadow.port
    if bot_b.analyst is not None:
        ports["analyst"] = bot_b.analyst.port
    return ports


def busy_ports(ports: dict[str, int]) -> dict[str, int]:
    busy = {}
    for name, port in ports.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                busy[name] = port
    return busy


def accepting(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


class Supervisor:
    def __init__(self, home: Path):
        self.home = home
        self.children = build_children(home)
        self.gateway_port = load_gateway_settings(home / "config" / "gateway.yaml").port
        self.stopping = False
        self.announced = False

    def say(self, name: str, message: str) -> None:
        print(f"[{name}] {message}", flush=True)

    def open_log(self, child: Child) -> IO[bytes]:
        path = self.home / "logs" / f"{child.name}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_LIMIT:
            path.replace(path.with_suffix(".log.old"))
        return open(path, "ab")

    def start(self, child: Child) -> None:
        child.log = self.open_log(child)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        child.proc = subprocess.Popen(
            component_command(child.name),
            env=child_environment(child, self.home),
            stdin=subprocess.DEVNULL,
            stdout=child.log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        child.started_at = time.monotonic()
        child.retry_at = None
        self.say(child.name, f"started, log {child.log.name}")

    def exited(self, child: Child, code: int) -> None:
        if child.log is not None:
            child.log.close()
        child.proc = None
        if code == REFUSED:
            child.refused = True
            self.say(child.name, f"refused to start; see {self.home / 'logs' / (child.name + '.log')}")
            return
        lived = time.monotonic() - child.started_at
        child.failures = 0 if lived >= HEALTHY_AFTER_S else child.failures + 1
        delay = min(MAX_BACKOFF_S, 5 * 2 ** max(0, child.failures - 1))
        child.retry_at = time.monotonic() + delay
        self.say(child.name, f"exited with {code}, restarting in {delay}s")

    def stop(self, *_: object) -> None:
        self.stopping = True

    def install_signals(self) -> None:
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            number = getattr(signal, name, None)
            if number is not None:
                signal.signal(number, self.stop)

    def terminate(self) -> None:
        live = [child for child in self.children if child.proc is not None]
        for child in live:
            try:
                if sys.platform == "win32":
                    child.proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    child.proc.terminate()
            except OSError:
                pass
        deadline = time.monotonic() + STOP_GRACE_S
        for child in live:
            try:
                child.proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.proc.kill()
                child.proc.wait()
            if child.log is not None:
                child.log.close()
            self.say(child.name, "stopped")

    def run(self) -> int:
        self.install_signals()
        for child in self.children:
            self.start(child)
        try:
            while not self.stopping:
                now = time.monotonic()
                for child in self.children:
                    if child.proc is not None:
                        code = child.proc.poll()
                        if code is not None:
                            self.exited(child, code)
                    elif child.retry_at is not None and now >= child.retry_at:
                        self.start(child)
                if not self.announced and accepting(self.gateway_port):
                    self.announced = True
                    print(f"ready: http://127.0.0.1:{self.gateway_port}", flush=True)
                time.sleep(0.5)
        finally:
            self.terminate()
        return 0
