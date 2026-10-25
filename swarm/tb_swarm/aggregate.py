from dataclasses import dataclass, field

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

_EPS = 1e-12


def weighted_quantile(values: list[float], weights: list[float], q: float) -> float:
    """Smallest value whose cumulative weight passes q of the total; midpoint when it lands exactly on q."""
    pairs = sorted(zip(values, weights, strict=True))
    target = q * sum(weight for _, weight in pairs)
    cumulative = 0.0
    for index, (value, weight) in enumerate(pairs):
        cumulative += weight
        if cumulative > target + _EPS:
            return value
        if abs(cumulative - target) <= _EPS and index + 1 < len(pairs):
            return (value + pairs[index + 1][0]) / 2
    return pairs[-1][0]


@dataclass(frozen=True)
class Spread:
    q25: float
    q75: float
    iqr: float
    minimum: float
    maximum: float


def spread_of(values: list[float], weights: list[float]) -> Spread:
    q25 = weighted_quantile(values, weights, 0.25)
    q75 = weighted_quantile(values, weights, 0.75)
    return Spread(q25=q25, q75=q75, iqr=q75 - q25, minimum=min(values), maximum=max(values))


@dataclass(frozen=True)
class NoulResult:
    median: float
    spread: Spread


@dataclass(frozen=True)
class ChoiceResult:
    winner: str
    tie: bool
    median_probabilities: dict[str, float]
    agreement: float
    votes: dict[str, int]
    spread: Spread


@dataclass(frozen=True)
class ScoreResult:
    median: float
    spread: Spread


QuestionResult = NoulResult | ChoiceResult | ScoreResult


@dataclass(frozen=True)
class Aggregate:
    questions: dict[str, QuestionResult] = field(default_factory=dict)
    voters: int = 0


def _distribution(answer: ChoiceAnswer, options: list[str]) -> list[float]:
    if answer.probabilities is not None:
        raw = [answer.probabilities.get(option, 0.0) for option in options]
        total = sum(raw)
        if total > 0:
            return [value / total for value in raw]
    return [1.0 if option == answer.choice else 0.0 for option in options]


def aggregate(request: DecisionRequest, ballots: list[tuple[float, dict[str, Answer]]]) -> Aggregate:
    weights = [weight for weight, _ in ballots]
    results: dict[str, QuestionResult] = {}
    for name, question in request.questions.items():
        answers = [ballot[name] for _, ballot in ballots]
        if isinstance(question, NoulQuestion):
            values = [a.noul for a in answers if isinstance(a, NoulAnswer)]
            results[name] = NoulResult(
                median=weighted_quantile(values, weights, 0.5), spread=spread_of(values, weights)
            )
        elif isinstance(question, ScoreQuestion):
            values = [a.score for a in answers if isinstance(a, ScoreAnswer)]
            results[name] = ScoreResult(
                median=weighted_quantile(values, weights, 0.5), spread=spread_of(values, weights)
            )
        elif isinstance(question, ChoiceQuestion):
            options = list(question.criteria)
            choices = [a for a in answers if isinstance(a, ChoiceAnswer)]
            rows = [_distribution(a, options) for a in choices]
            medians = {
                option: weighted_quantile([row[i] for row in rows], weights, 0.5) for i, option in enumerate(options)
            }
            best = max(medians.values())
            leaders = [option for option in options if abs(medians[option] - best) <= _EPS]
            winner = leaders[0]
            index = options.index(winner)
            agreeing = sum(weight for weight, row in zip(weights, rows, strict=True) if row.index(max(row)) == index)
            results[name] = ChoiceResult(
                winner=winner,
                tie=len(leaders) > 1,
                median_probabilities=medians,
                agreement=agreeing / sum(weights),
                votes={option: sum(1 for a in choices if a.choice == option) for option in options},
                spread=spread_of([row[index] for row in rows], weights),
            )
    return Aggregate(questions=results, voters=len(ballots))
