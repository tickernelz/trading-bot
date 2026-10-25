import re
from collections.abc import Iterable

REDACTED = "[redacted]"

_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|x-api-key)([\"'\s:=]+)[^\s\"',}]{6,}"),
)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Removes configured secret values and credential-shaped substrings from text before it is stored."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS[:2]:
        text = pattern.sub(REDACTED, text)
    return _PATTERNS[2].sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
