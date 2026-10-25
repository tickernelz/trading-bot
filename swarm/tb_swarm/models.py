import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_CHOICE_OPTIONS = 255


class NoulQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["noul"] = "noul"
    instructions: str
    criteria: dict[Literal["true", "false"], str] | None = None


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str]

    @field_validator("criteria")
    @classmethod
    def _option_count(cls, value: dict[str, str]) -> dict[str, str]:
        if not 2 <= len(value) <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"choice needs 2 to {MAX_CHOICE_OPTIONS} options")
        return value


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str]

    @field_validator("criteria")
    @classmethod
    def _level_count(cls, value: list[str]) -> list[str]:
        if len(value) < 2:
            raise ValueError("score needs at least 2 levels")
        return value


Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str | dict[str, Any] | list[Any]
    questions: dict[str, Question] = Field(min_length=1)


class NoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    noul: float

    @field_validator("noul")
    @classmethod
    def _unit(cls, value: float) -> float:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("noul must be in [0, 1]")
        return value


class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    confidence: float | None = None
    probabilities: dict[str, float] | None = None


class ScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    score: float
    confidence: float | None = None
    probabilities: dict[str, float] | None = None

    @field_validator("score")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float | None = None

    @model_validator(mode="after")
    def _non_negative(self) -> "Usage":
        if min(self.input_tokens, self.output_tokens, self.reasoning_tokens) < 0:
            raise ValueError("token counts must be non-negative")
        return self


class DecisionResponse(BaseModel):
    model: str
    answers: dict[str, Answer]
    usage: Usage = Field(default_factory=Usage)
    latency_s: float = 0.0
