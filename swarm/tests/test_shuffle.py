import random

from tb_swarm.models import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)
from tb_swarm.shuffle import identity_order, plan_order


def request():
    return DecisionRequest(
        state="s",
        questions={
            "n": NoulQuestion(instructions="?", criteria={"true": "yes", "false": "no"}),
            "c": ChoiceQuestion(instructions="?", criteria={f"o{i}": str(i) for i in range(6)}),
            "s": ScoreQuestion(instructions="?", criteria=["l0", "l1", "l2", "l3"]),
        },
    )


def test_shuffle_keeps_the_same_option_set():
    original = request()
    rng = random.Random(1)
    presented = plan_order(original, rng).present(original, rng)
    assert set(presented.questions["c"].criteria) == set(original.questions["c"].criteria)
    assert presented.questions["c"].criteria == {
        k: original.questions["c"].criteria[k] for k in presented.questions["c"].criteria
    }


def test_different_seeds_give_different_orders():
    original = request()
    orders = set()
    for seed in range(20):
        rng = random.Random(seed)
        presented = plan_order(original, rng).present(original, rng)
        orders.add(tuple(presented.questions["c"].criteria))
    assert len(orders) > 5


def test_same_seed_is_reproducible():
    original = request()
    outcomes = []
    for _ in range(2):
        rng = random.Random("seed")
        presented = plan_order(original, rng).present(original, rng)
        outcomes.append(presented.model_dump())
    assert outcomes[0] == outcomes[1]


def test_identity_order_changes_nothing():
    original = request()
    assert identity_order().present(original, random.Random(0)) == original


def test_score_flip_reverses_levels_and_restores_answer():
    original = request()
    order = type(identity_order())(flipped_scores=frozenset({"s"}))
    presented = order.present(original, random.Random(0))
    assert presented.questions["s"].criteria == ["l3", "l2", "l1", "l0"]
    response = DecisionResponse(
        model="m",
        answers={"s": ScoreAnswer(score=0.5, probabilities={"0": 0.5, "1": 0.5, "2": 0.0, "3": 0.0})},
    )
    restored = order.restore(original, response).answers["s"]
    assert restored.score == 2.5
    assert restored.probabilities == {"3": 0.5, "2": 0.5, "1": 0.0, "0": 0.0}


def test_both_flip_outcomes_occur():
    original = request()
    flips = {plan_order(original, random.Random(seed)).flipped_scores for seed in range(30)}
    assert frozenset({"s"}) in flips and frozenset() in flips
