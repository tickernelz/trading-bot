from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def pwa_dir() -> Path | None:
    candidate = bundle_root() / ("pwa" if frozen() else "pwa/dist")
    return candidate if (candidate / "index.html").is_file() else None


def data_home() -> Path:
    override = os.environ.get("TRADING_BOT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "TradingBot"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TradingBot"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "trading-bot"
