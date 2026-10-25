from tb_swarm.providers.http_wire import HttpDecisionProvider

DEFAULT_PATH = "/v1/systemone"


class SystemOneProvider(HttpDecisionProvider):
    """TypeSafe System One wire: POST {base_url}{path} with model, state, questions."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_s: float,
        path: str = DEFAULT_PATH,
    ) -> None:
        super().__init__(url=base_url.rstrip("/") + path, api_key=api_key, model=model, timeout_s=timeout_s)
