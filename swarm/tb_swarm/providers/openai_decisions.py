import json
from typing import Any

from tb_swarm.errors import ProviderError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, Question, ScoreQuestion, Usage
from tb_swarm.providers.http_wire import HttpDecisionProvider

DEFAULT_PATH = "/v1/decisions"


def _input_text(state: str | dict | list) -> str:
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)


def _question(name: str, question: Question) -> dict[str, Any]:
    if isinstance(question, NoulQuestion):
        instructions = question.instructions
        if question.criteria:
            instructions += f" True means: {question.criteria['true']} False means: {question.criteria['false']}"
        return {"type": "predicate", "name": name, "instructions": instructions}
    if isinstance(question, ChoiceQuestion):
        choices = [{"value": value, "description": text} for value, text in question.criteria.items()]
        return {"type": "choice", "name": name, "instructions": question.instructions, "choices": choices}
    assert isinstance(question, ScoreQuestion)
    return {
        "type": "score",
        "name": name,
        "instructions": question.instructions,
        "levels": [{"label": label} for label in question.criteria],
    }


def _probabilities(raw: Any, key: str) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ProviderError("invalid", "probabilities is not a list")
    result: dict[str, float] = {}
    for item in raw:
        if not isinstance(item, dict) or key not in item or "probability" not in item:
            raise ProviderError("invalid", "probability entry malformed")
        result[str(item[key])] = item["probability"]
    return result


def _answer(item: dict[str, Any]) -> dict[str, Any]:
    kind = item.get("type")
    if kind == "predicate":
        return {"type": "noul", "noul": item.get("probability")}
    converted: dict[str, Any] = {"type": kind, "confidence": item.get("confidence")}
    if kind == "choice":
        converted["choice"] = item.get("choice")
        converted["probabilities"] = _probabilities(item.get("probabilities"), "value")
    elif kind == "score":
        converted["score"] = item.get("score")
        converted["probabilities"] = _probabilities(item.get("probabilities"), "value")
    return converted


class OpenAiDecisionsProvider(HttpDecisionProvider):
    """OpenAI Decisions wire: POST {base_url}/v1/decisions with input and a list of typed questions."""

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

    def _payload(self, request: DecisionRequest) -> dict[str, Any]:
        return {
            "model": self._model,
            "input": _input_text(request.state),
            "questions": [_question(name, question) for name, question in request.questions.items()],
        }

    def _raw_answers(self, body: dict[str, Any]) -> Any:
        items = body.get("answers")
        if not isinstance(items, list):
            raise ProviderError("invalid", "answers is not a list")
        converted: dict[str, Any] = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ProviderError("invalid", "answer without a name")
            if item["name"] in converted:
                raise ProviderError("invalid", f"duplicate answer {item['name']!r}")
            converted[item["name"]] = _answer(item)
        return converted

    def _usage(self, body: dict[str, Any]) -> Usage:
        usage = super()._usage(body)
        raw = body.get("usage")
        details = raw.get("output_tokens_details") if isinstance(raw, dict) else None
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
        return usage.model_copy(update={"reasoning_tokens": int(reasoning or 0)})
