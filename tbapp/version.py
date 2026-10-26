from __future__ import annotations

import platform
import sys

try:
    from tbapp._build import TARGET, VERSION
except ImportError:
    VERSION = "0.0.0+dev"
    TARGET = "source"

SOURCE_URL = "https://github.com/tickernelz/trading-bot"


def machine() -> str:
    arch = platform.machine().lower()
    return "arm64" if arch in {"arm64", "aarch64"} else "x64" if arch in {"x86_64", "amd64"} else arch


def system() -> str:
    return {"win32": "win", "darwin": "mac"}.get(sys.platform, sys.platform if sys.platform != "linux" else "linux")


def describe() -> str:
    return f"trading-bot {VERSION} ({TARGET}, running on {system()}-{machine()})"
