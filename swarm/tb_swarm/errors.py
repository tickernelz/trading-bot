from typing import Literal

ErrorKind = Literal["auth", "rate_limit", "http", "timeout", "network", "invalid", "config", "internal"]


class ConfigError(ValueError):
    """Raised when the swarm configuration is invalid."""


class ProviderError(Exception):
    """A voter call that produced no scorable answer, classified by kind."""

    def __init__(self, kind: ErrorKind, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
