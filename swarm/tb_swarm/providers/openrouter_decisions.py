from tb_swarm.providers.http_wire import HttpDecisionProvider

DEFAULT_BASE_URL = "https://openrouter.ai"
PATH = "/api/alpha/decisions"


class OpenRouterDecisionsProvider(HttpDecisionProvider):
    """OpenRouter Decisions API (alpha): POST {base_url}/api/alpha/decisions with model, state, questions."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout_s: float,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        super().__init__(url=base_url.rstrip("/") + PATH, api_key=api_key, model=model, timeout_s=timeout_s)
