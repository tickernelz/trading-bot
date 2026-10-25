"""Fire-and-forget delivery of entry candidates to the shadow swarm service."""

from __future__ import annotations

import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)


class ShadowClient:
    def __init__(self, url: str, timeout_s: float = 3.0) -> None:
        self.url = url.rstrip("/") + "/candidates"
        self.timeout_s = timeout_s
        self.sent = 0
        self.failed = 0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shadow")

    def submit(self, candidate: dict[str, Any]) -> None:
        self._pool.submit(self._post, candidate)

    def _post(self, candidate: dict[str, Any]) -> None:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(candidate).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                response.read()
            self.sent += 1
        except Exception as exc:
            self.failed += 1
            logger.warning(
                "shadow candidate %s for %s not delivered: %s", candidate["decision_id"], candidate["pair"], exc
            )

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
