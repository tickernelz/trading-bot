import random
from dataclasses import dataclass

from tb_swarm.models import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)


@dataclass(frozen=True)
class OptionOrder:
    """One voter's presentation of a request: shuffled option order and which score scales are flipped."""

    flipped_scores: frozenset[str]

    def present(self, request: DecisionRequest, rng: random.Random) -> DecisionRequest:
        questions = {}
        for name, question in request.questions.items():
            if isinstance(question, ChoiceQuestion):
                keys = list(question.criteria)
                rng.shuffle(keys)
                questions[name] = question.model_copy(
                    update={"criteria": {key: question.criteria[key] for key in keys}}
                )
            elif isinstance(question, NoulQuestion) and question.criteria:
                keys = list(question.criteria)
                rng.shuffle(keys)
                questions[name] = question.model_copy(
                    update={"criteria": {key: question.criteria[key] for key in keys}}
                )
            elif isinstance(question, ScoreQuestion) and name in self.flipped_scores:
                questions[name] = question.model_copy(update={"criteria": list(reversed(question.criteria))})
            else:
                questions[name] = question
        return request.model_copy(update={"questions": questions})

    def restore(self, original: DecisionRequest, response: DecisionResponse) -> DecisionResponse:
        answers = dict(response.answers)
        for name in self.flipped_scores:
            answer = answers[name]
            question = original.questions[name]
            if not isinstance(answer, ScoreAnswer) or not isinstance(question, ScoreQuestion):
                continue
            top = len(question.criteria) - 1
            probabilities = None
            if answer.probabilities is not None:
                probabilities = {str(top - int(level)): value for level, value in answer.probabilities.items()}
            answers[name] = answer.model_copy(update={"score": top - answer.score, "probabilities": probabilities})
        return response.model_copy(update={"answers": answers})


def plan_order(request: DecisionRequest, rng: random.Random) -> OptionOrder:
    flipped = frozenset(
        name
        for name, question in request.questions.items()
        if isinstance(question, ScoreQuestion) and rng.random() < 0.5
    )
    return OptionOrder(flipped_scores=flipped)


def identity_order() -> OptionOrder:
    return OptionOrder(flipped_scores=frozenset())
