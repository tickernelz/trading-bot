"""Mask URL query tokens in uvicorn log records before any handler sees them."""

from __future__ import annotations

import logging
import re

TOKEN = re.compile(r"(token=)[^\s\"'&]+")
LOGGERS = ("uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    return TOKEN.sub(r"\1<redacted>", text)


class TokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = redact(message)
        if masked != message:
            record.msg = masked
            record.args = None
        return True


def install() -> None:
    for name in LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(item, TokenFilter) for item in logger.filters):
            logger.addFilter(TokenFilter())
