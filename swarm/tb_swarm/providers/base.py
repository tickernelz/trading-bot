from abc import ABC, abstractmethod

from tb_swarm.errors import ProviderError
from tb_swarm.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)

_QUESTION = "q"


class DecisionProvider(ABC):
    """Answers a set of typed questions about a state; raises ProviderError when no scorable answer exists."""

    @abstractmethod
    async def decide(self, request: DecisionRequest) -> DecisionResponse: ...

    async def noul(self, state: str | dict | list, instructions: str) -> NoulAnswer:
        request = DecisionRequest(state=state, questions={_QUESTION: NoulQuestion(instructions=instructions)})
        answer = (await self.decide(request)).answers[_QUESTION]
        if not isinstance(answer, NoulAnswer):
            raise ProviderError("invalid", "expected noul answer")
        return answer

    async def choice(self, state: str | dict | list, instructions: str, criteria: dict[str, str]) -> ChoiceAnswer:
        question = ChoiceQuestion(instructions=instructions, criteria=criteria)
        answer = (await self.decide(DecisionRequest(state=state, questions={_QUESTION: question}))).answers[_QUESTION]
        if not isinstance(answer, ChoiceAnswer):
            raise ProviderError("invalid", "expected choice answer")
        return answer

    async def score(self, state: str | dict | list, instructions: str, criteria: list[str]) -> ScoreAnswer:
        question = ScoreQuestion(instructions=instructions, criteria=criteria)
        answer = (await self.decide(DecisionRequest(state=state, questions={_QUESTION: question}))).answers[_QUESTION]
        if not isinstance(answer, ScoreAnswer):
            raise ProviderError("invalid", "expected score answer")
        return answer

    async def aclose(self) -> None:
        return None
