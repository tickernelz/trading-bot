import logging
import os
import sys
from pathlib import Path

import uvicorn

from engine.exitcodes import REFUSED
from engine.settings import ConfigError
from gateway.app import Gateway, create_app
from gateway.redact import install_log_redaction
from gateway.settings import load_gateway_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install_log_redaction()
    path = os.environ.get("GATEWAY_CONFIG", "config/gateway.yaml")
    try:
        settings = load_gateway_settings(path)
        gateway = Gateway(settings, dict(os.environ))
    except (OSError, ValueError, ConfigError) as exc:
        print(f"trading-bot gateway: refusing to start: {exc}", file=sys.stderr)
        return REFUSED
    pwa_dir = os.environ.get("TRADING_BOT_PWA_DIR")
    uvicorn.run(
        create_app(gateway, pwa_dir=Path(pwa_dir) if pwa_dir else None),
        host=settings.listen,
        port=settings.port,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=40,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
