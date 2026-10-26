"""Voter records and the quorum, tie and spread rules that turn them into a decision outcome."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from tb_swarm.aggregate import Aggregate, ChoiceResult, NoulResult, aggregate
from tb_swarm.models import Answer, DecisionRequest, Usage

VoterStatus = Literal["ok", "timeout", "failed", "invalid"]
OutcomeStatus = Literal["ok", "skip"]


class VoterRecord(BaseModel):
    voter_id: str
    status: VoterStatus
    latency_s: float
    error_kind: str | None = None
    error: str | None = None
    model: str | None = None
    usage: Usage = Usage()
    answers: dict[str, Answer] | None = None
    presented_options: dict[str, list[str]] = {}
    flipped_scores: list[str] = []


@dataclass(frozen=True)
class DecisionOutcome:
    decision_id: str
    status: OutcomeStatus
    reason: str | None
    required: int
    answered: int
    aggregate: Aggregate | None
    voters: list[VoterRecord] = field(default_factory=list)

    @property
    def proceed(self) -> bool:
        return self.status == "ok"


def settle(
    request: DecisionRequest,
    decision_id: str,
    records: Sequence[VoterRecord],
    weights: Mapping[str, float],
    required: int,
    max_spread: float | None,
) -> DecisionOutcome:
    """Apply quorum, tie and spread rules to recorded voter answers."""
    voters = list(records)
    ballots = [(weights[r.voter_id], r.answers) for r in voters if r.status == "ok" and r.answers is not None]
    if len(ballots) < required:
        return DecisionOutcome(decision_id, "skip", "quorum_not_met", required, len(ballots), None, voters)
    merged = aggregate(request, ballots)
    for name, result in merged.questions.items():
        if isinstance(result, ChoiceResult) and result.tie:
            return DecisionOutcome(decision_id, "skip", f"choice_tie:{name}", required, len(ballots), merged, voters)
    if max_spread is not None:
        for name, result in merged.questions.items():
            if isinstance(result, (NoulResult, ChoiceResult)) and result.spread.iqr > max_spread:
                return DecisionOutcome(
                    decision_id, "skip", f"spread_exceeded:{name}", required, len(ballots), merged, voters
                )
    return DecisionOutcome(decision_id, "ok", None, required, len(ballots), merged, voters)
