"""The analyst languages: one entry per language, keyed by its code and valued by the name the prompt uses."""

from __future__ import annotations

LANGUAGES: dict[str, str] = {"en": "English", "id": "Indonesian"}
DEFAULT_LANGUAGE = "en"


def language_name(code: str) -> str:
    try:
        return LANGUAGES[code]
    except KeyError:
        raise ValueError(f"unknown language {code!r}; expected one of {', '.join(LANGUAGES)}") from None
