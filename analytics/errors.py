"""Error type that carries the gateway error envelope fields."""


class AnalyticsError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after_ms: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after_ms = retry_after_ms
