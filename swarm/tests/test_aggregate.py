import pytest

from tb_swarm.aggregate import aggregate, weighted_quantile
from tb_swarm.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)


def test_median_of_odd_and_even_counts():
    assert weighted_quantile([1, 2, 3], [1, 1, 1], 0.5) == 2
    assert weighted_quantile([1, 2, 3, 4], [1, 1, 1, 1], 0.5) == 2.5


def test_weights_move_the_median():
    assert weighted_quantile([0.1, 0.5, 0.9], [1, 1, 1], 0.5) == 0.5
    assert weighted_quantile([0.1, 0.5, 0.9], [1, 1, 5], 0.5) == 0.9


def test_outlier_does_not_move_the_median():
    values = [0.50, 0.52, 0.51, 0.49, 0.99]
    assert weighted_quantile(values, [1] * 5, 0.5) == 0.51


def noul_request():
    return DecisionRequest(state="s", questions={"q": NoulQuestion(instructions="?")})


def test_noul_median_and_iqr():
    ballots = [(1.0, {"q": NoulAnswer(noul=v)}) for v in (0.2, 0.4, 0.5, 0.6, 0.9)]
    result = aggregate(noul_request(), ballots).questions["q"]
    assert result.median == 0.5
    assert result.spread.iqr == pytest.approx(0.2)
    assert (result.spread.minimum, result.spread.maximum) == (0.2, 0.9)


def test_choice_winner_votes_agreement():
    request = DecisionRequest(
        state="s", questions={"q": ChoiceQuestion(instructions="?", criteria={"a": "x", "b": "y", "c": "z"})}
    )
    picks = ["a", "a", "a", "b", "c"]
    ballots = [(1.0, {"q": ChoiceAnswer(choice=p)}) for p in picks]
    result = aggregate(request, ballots).questions["q"]
    assert result.winner == "a"
    assert result.votes == {"a": 3, "b": 1, "c": 1}
    assert result.agreement == pytest.approx(0.6)
    assert not result.tie


def test_choice_uses_probabilities_when_given():
    request = DecisionRequest(
        state="s", questions={"q": ChoiceQuestion(instructions="?", criteria={"a": "x", "b": "y"})}
    )
    ballots = [
        (1.0, {"q": ChoiceAnswer(choice="a", probabilities={"a": 0.51, "b": 0.49})}),
        (1.0, {"q": ChoiceAnswer(choice="b", probabilities={"a": 0.1, "b": 0.9})}),
        (1.0, {"q": ChoiceAnswer(choice="b", probabilities={"a": 0.2, "b": 0.8})}),
    ]
    result = aggregate(request, ballots).questions["q"]
    assert result.winner == "b"
    assert result.median_probabilities["b"] == 0.8


def test_choice_tie_is_flagged():
    request = DecisionRequest(
        state="s", questions={"q": ChoiceQuestion(instructions="?", criteria={"a": "x", "b": "y"})}
    )
    ballots = [(1.0, {"q": ChoiceAnswer(choice=c)}) for c in ("a", "b")]
    assert aggregate(request, ballots).questions["q"].tie


def test_score_median():
    request = DecisionRequest(state="s", questions={"q": ScoreQuestion(instructions="?", criteria=["l", "m", "h"])})
    ballots = [(1.0, {"q": ScoreAnswer(score=v)}) for v in (0.0, 1.0, 2.0)]
    assert aggregate(request, ballots).questions["q"].median == 1.0
