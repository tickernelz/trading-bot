import time
from typing import Any

import httpx

from tb_swarm.errors import ProviderError
from tb_swarm.models import DecisionRequest, DecisionResponse, Usage
from tb_swarm.providers.base import DecisionProvider
from tb_swarm.validate import parse_answers


def classify_status(status: int, body: str) -> ProviderError:
    snippet = body[:200].replace("\n", " ")
    if status in (401, 403):
        return ProviderError("auth", f"HTTP {status}: {snippet}", status)
    if status == 429:
        return ProviderError("rate_limit", f"HTTP 429: {snippet}", status)
    return ProviderError("http", f"HTTP {status}: {snippet}", status)


class HttpDecisionProvider(DecisionProvider):
    """Shared transport for providers that speak a decisions-style JSON wire over HTTP."""

    def __init__(self, *, url: str, api_key: str | None, model: str, timeout_s: float) -> None:
        self._url = url
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout_s)

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ProviderError("auth", "no API key configured")
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _payload(self, request: DecisionRequest) -> dict[str, Any]:
        return {
            "model": self._model,
            "state": request.state,
            "questions": {
                name: question.model_dump(mode="json", exclude_none=True)
                for name, question in request.questions.items()
            },
        }

    def _usage(self, body: dict[str, Any]) -> Usage:
        raw = body.get("usage")
        if not isinstance(raw, dict):
            return Usage()
        cost = raw.get("cost")
        return Usage(
            input_tokens=int(raw.get("input_tokens") or 0),
            output_tokens=int(raw.get("output_tokens") or 0),
            cost=float(cost) if isinstance(cost, (int, float)) else None,
        )

    async def decide(self, request: DecisionRequest) -> DecisionResponse:
        headers = self._headers()
        started = time.perf_counter()
        try:
            response = await self._client.post(self._url, json=self._payload(request), headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", f"request timed out: {exc!r}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network", f"transport error: {exc!r}") from exc
        latency = time.perf_counter() - started
        if response.status_code != 200:
            raise classify_status(response.status_code, response.text)
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError("invalid", "response is not JSON") from exc
        if not isinstance(body, dict):
            raise ProviderError("invalid", "response is not an object")
        answers = parse_answers(request, body.get("answers"))
        served = body.get("model")
        return DecisionResponse(
            model=served if isinstance(served, str) and served else self._model,
            answers=answers,
            usage=self._usage(body),
            latency_s=latency,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
