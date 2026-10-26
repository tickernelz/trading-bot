"""Validate config/config.yaml, render the Freqtrade config, then exec Freqtrade."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from engine.settings import ConfigError, Settings, load_settings

STRATEGY = "SwingEmaRsi"
STRATEGY_COMMANDS = {"trade", "backtesting", "webserver"}
API_COMMANDS = {"trade", "webserver"}
ENGINE_ROOT = Path(__file__).resolve().parent
DRY_RUN_DB = "tradesv3.dryrun.sqlite"
TRADABLE_BALANCE_RATIO = 0.99


class MissingSecret(Exception):
    """Raised when a required environment variable is unset or empty."""


def freqtrade_config(settings: Settings, serve_api: bool = True) -> dict[str, Any]:
    """Translate validated settings into a Freqtrade configuration without secrets."""
    config: dict[str, Any] = {
        "bot_name": "trading-bot",
        "trading_mode": "spot",
        "margin_mode": "",
        "dry_run": True,
        "dry_run_wallet": settings.capital.initial_idr,
        "fee": settings.exchange.fee_pct / 100,
        "stake_currency": settings.exchange.stake_currency,
        "stake_amount": "unlimited",
        "tradable_balance_ratio": TRADABLE_BALANCE_RATIO,
        "max_open_trades": settings.risk.max_open_trades,
        "timeframe": settings.exchange.timeframe,
        "cancel_open_orders_on_exit": False,
        "initial_state": "running",
        "force_entry_enable": settings.api.force_entry,
        "unfilledtimeout": {"entry": 10, "exit": 10, "exit_timeout_count": 0, "unit": "minutes"},
        "entry_pricing": {
            "price_side": "other",
            "use_order_book": True,
            "order_book_top": 1,
            "price_last_balance": 0.0,
            "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1},
        },
        "exit_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "exchange": {
            "name": settings.exchange.name,
            "key": "",
            "secret": "",
            "ccxt_config": {},
            "ccxt_async_config": {},
            "pair_whitelist": list(settings.exchange.pairs),
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
        "internals": {"process_throttle_secs": 5},
        "trading_bot": {
            "bot_id": settings.bot_id,
            "shadow_url": settings.shadow.url if settings.swarm.enabled and settings.shadow else None,
            "shadow_token_env": settings.shadow.token_env if settings.shadow else None,
            "initial_capital": settings.capital.initial_idr,
            "compounding": settings.capital.compounding,
            "risk": settings.risk.model_dump(),
        },
    }
    if serve_api:
        config["api_server"] = {
            "enabled": True,
            "listen_ip_address": settings.api.listen,
            "listen_port": settings.api.port,
            "verbosity": "error",
            "enable_openapi": False,
            "CORS_origins": [],
        }
        config["apiserver"] = {"allow_custom_messages": True}
    return config


def secret_env(settings: Settings, environ: dict[str, str]) -> dict[str, str]:
    """Map the API credentials named in settings onto Freqtrade environment overrides."""
    names = {
        "FREQTRADE__API_SERVER__USERNAME": settings.api.username_env,
        "FREQTRADE__API_SERVER__PASSWORD": settings.api.password_env,
        "FREQTRADE__API_SERVER__JWT_SECRET_KEY": settings.api.jwt_secret_env,
    }
    required = list(names.values())
    if settings.swarm.enabled and settings.shadow is not None:
        required.append(settings.shadow.token_env)
    missing = [source for source in required if not environ.get(source)]
    if missing:
        raise MissingSecret(f"set environment variables: {', '.join(missing)}")
    return {target: environ[source] for target, source in names.items()}


def build_argv(command: str, extra: list[str], config_path: Path, userdir: str) -> list[str]:
    argv = ["freqtrade", command, "--config", str(config_path), "--userdir", userdir]
    if command in STRATEGY_COMMANDS:
        argv += ["--strategy", STRATEGY, "--strategy-path", str(ENGINE_ROOT / "strategies")]
    return argv + extra


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m engine.launch <freqtrade-command> [args...]", file=sys.stderr)
        return 2
    config_file = os.environ.get("TRADING_BOT_CONFIG", "config/config.yaml")
    userdir = os.environ.get("TRADING_BOT_USERDIR", "user_data")
    try:
        settings = load_settings(config_file)
        serve_api = argv[0] in API_COMMANDS
        overrides = secret_env(settings, dict(os.environ)) if serve_api else {}
    except (ConfigError, MissingSecret) as exc:
        print(f"trading-bot: refusing to start: {exc}", file=sys.stderr)
        return 2
    rendered = Path(userdir) / "trading-bot.freqtrade.json"
    rendered.parent.mkdir(parents=True, exist_ok=True)
    config = freqtrade_config(settings, serve_api)
    if serve_api:
        config["db_url"] = f"sqlite:///{(Path(userdir) / DRY_RUN_DB).resolve()}"
    rendered.write_text(json.dumps(config, indent=2), encoding="utf-8")
    command = build_argv(argv[0], argv[1:], rendered, userdir)
    os.execvpe(command[0], command, {**os.environ, **overrides})


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
