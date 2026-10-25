import logging
import os
import sys

import uvicorn

from engine.settings import ConfigError
from gateway.app import Gateway, create_app
from gateway.settings import load_gateway_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    path = os.environ.get("GATEWAY_CONFIG", "config/gateway.yaml")
    try:
        settings = load_gateway_settings(path)
        gateway = Gateway(settings, dict(os.environ))
    except (OSError, ValueError, ConfigError) as exc:
        print(f"trading-bot gateway: refusing to start: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(
        create_app(gateway),
        host=settings.listen,
        port=settings.port,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=40,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
