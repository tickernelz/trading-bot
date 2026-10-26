"""Removes credentials from text and log records before they are stored or shown."""

from __future__ import annotations

import logging
import re
import traceback

REDACTED = "[redacted]"
MIN_SECRET_LENGTH = 6
LAST_CHARS = 4
MIN_KEY_LENGTH_FOR_TAIL = 12

_PATTERNS = (
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+|basic\s+)?[^\s,\"';}]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{6,}"), r"\1" + REDACTED),
    (
        re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|key|password|secret)=)[^&\s\"']+"),
        r"\1" + REDACTED,
    ),
    (
        re.compile(
            r"(?i)((?:x-api-key|api[_-]?key|jwt_secret_key|ws_token|password|secret)[\"']?\s*[:=]\s*[\"']?)"
            r"[^\s,\"';}]{4,}"
        ),
        r"\1" + REDACTED,
    ),
    (re.compile(r"(?i)\b(token=)[^\s\"'&]+"), r"\1" + REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), REDACTED),
)


class SecretRegistry:
    """Exact secret values the process knows about, replaced wherever they appear."""

    def __init__(self) -> None:
        self._ordered: tuple[str, ...] = ()

    def add(self, *values: str | None) -> None:
        known = set(self._ordered)
        known.update(value for value in values if value and len(value) >= MIN_SECRET_LENGTH)
        self._ordered = tuple(sorted(known, key=len, reverse=True))

    def redact(self, text: str) -> str:
        for value in self._ordered:
            text = text.replace(value, REDACTED)
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
        return text


registry = SecretRegistry()


def redact(text: str) -> str:
    return registry.redact(text)


def key_last4(key: str | None) -> str | None:
    """Last four characters of a key long enough that they reveal little, else None."""
    if not key or len(key) < MIN_KEY_LENGTH_FOR_TAIL:
        return None
    return key[-LAST_CHARS:]


_installed = False


def install_log_redaction() -> None:
    """Makes every log record in the process pass through the registry and patterns."""
    global _installed
    if _installed:
        return
    factory = logging.getLogRecordFactory()

    def make(*args, **kwargs) -> logging.LogRecord:
        record = factory(*args, **kwargs)
        try:
            record.msg = registry.redact(record.getMessage())
        except Exception:
            record.msg = registry.redact(str(record.msg))
        record.args = None
        if record.exc_info and record.exc_info[0] is not None:
            record.exc_text = registry.redact("".join(traceback.format_exception(*record.exc_info)))
        return record

    logging.setLogRecordFactory(make)
    _installed = True
