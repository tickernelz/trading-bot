import math
from typing import Any

from pydantic import TypeAdapter, ValidationError

from tb_swarm.errors import ProviderError
from tb_swarm.models import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)

_ANSWER = TypeAdapter(Answer)


def parse_answers(request: DecisionRequest, raw: Any) -> dict[str, Answer]:
    """Validate raw answers against the request; any deviation raises ProviderError('invalid')."""
    if not isinstance(raw, dict):
        raise ProviderError("invalid", "answers is not an object")
    missing = set(request.questions) - set(raw)
    extra = set(raw) - set(request.questions)
    if missing or extra:
        raise ProviderError("invalid", f"answer names mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    parsed: dict[str, Answer] = {}
    for name, question in request.questions.items():
        item = raw[name]
        if isinstance(item, dict) and "type" not in item:
            item = {**item, "type": question.type}
        try:
            answer = _ANSWER.validate_python(item)
        except ValidationError as exc:
            raise ProviderError("invalid", f"{name}: {exc.errors()[0]['msg']}") from exc
        _check_against_question(name, question, answer)
        parsed[name] = answer
    return parsed


def _check_against_question(name: str, question: Any, answer: Answer) -> None:
    if isinstance(question, NoulQuestion):
        if not isinstance(answer, NoulAnswer):
            raise ProviderError("invalid", f"{name}: expected noul answer")
    elif isinstance(question, ChoiceQuestion):
        if not isinstance(answer, ChoiceAnswer):
            raise ProviderError("invalid", f"{name}: expected choice answer")
        if answer.choice not in question.criteria:
            raise ProviderError("invalid", f"{name}: choice {answer.choice!r} is not an option")
        if answer.probabilities is not None:
            _check_probabilities(name, answer.probabilities, set(question.criteria))
            if answer.probabilities[answer.choice] < max(answer.probabilities.values()) - 1e-9:
                raise ProviderError("invalid", f"{name}: choice {answer.choice!r} is not the most probable option")
        _check_confidence(name, answer.confidence)
    elif isinstance(question, ScoreQuestion):
        if not isinstance(answer, ScoreAnswer):
            raise ProviderError("invalid", f"{name}: expected score answer")
        top = len(question.criteria) - 1
        if not 0.0 <= answer.score <= top:
            raise ProviderError("invalid", f"{name}: score {answer.score} outside [0, {top}]")
        if answer.probabilities is not None:
            _check_probabilities(name, answer.probabilities, {str(i) for i in range(top + 1)})
        _check_confidence(name, answer.confidence)


PROBABILITY_SUM_TOLERANCE = 0.01


def _check_probabilities(name: str, probabilities: dict[str, float], keys: set[str]) -> None:
    if set(probabilities) != keys:
        raise ProviderError("invalid", f"{name}: probability keys do not match options")
    if any(not math.isfinite(p) or p < 0.0 or p > 1.000001 for p in probabilities.values()):
        raise ProviderError("invalid", f"{name}: probability outside [0, 1]")
    if abs(sum(probabilities.values()) - 1.0) > PROBABILITY_SUM_TOLERANCE:
        raise ProviderError("invalid", f"{name}: probabilities do not sum to 1")


def _check_confidence(name: str, confidence: float | None) -> None:
    if confidence is not None and (not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0):
        raise ProviderError("invalid", f"{name}: confidence outside [0, 1]")
