import asyncio
import json
from collections import Counter

import pytest

from tb_swarm.config import SwarmSettings, VoterSpec
from tb_swarm.errors import ConfigError, ProviderError
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
from tb_swarm.providers.base import DecisionProvider
from tb_swarm.runner import SwarmRunner, VoterLog

OPTIONS = {"allow": "take", "shrink": "half", "skip": "pass"}


def request() -> DecisionRequest:
    return DecisionRequest(
        state="s",
        questions={
            "aligned": NoulQuestion(instructions="?"),
            "action": ChoiceQuestion(instructions="?", criteria=OPTIONS),
            "risk": ScoreQuestion(instructions="?", criteria=["low", "mid", "high"]),
        },
    )


class Fixed(DecisionProvider):
    def __init__(self, noul=0.6, choice="allow", score=1.0, delay=0.0, error=None, bogus=False):
        self.noul, self.choice_, self.score_, self.delay, self.error, self.bogus = (
            noul,
            choice,
            score,
            delay,
            error,
            bogus,
        )
        self.seen: list[DecisionRequest] = []

    async def decide(self, request):
        self.seen.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        choice = "nonexistent" if self.bogus else self.choice_
        return DecisionResponse(
            model="fixed",
            answers={
                "aligned": NoulAnswer(noul=self.noul),
                "action": ChoiceAnswer(choice=choice),
                "risk": ScoreAnswer(score=self.score_),
            },
        )


class FirstPresented(DecisionProvider):
    def __init__(self):
        self.calls = 0

    async def decide(self, request):
        self.calls += 1
        options = list(request.questions["action"].criteria)
        return DecisionResponse(
            model="bias",
            answers={
                "aligned": NoulAnswer(noul=0.5),
                "action": ChoiceAnswer(choice=options[0]),
                "risk": ScoreAnswer(score=0.0),
            },
        )


def build(providers: dict[str, DecisionProvider], *, min_answered=5, shuffle=True, max_spread=None, seed="t", log=None):
    voters = [VoterSpec(id=vid, adapter="llm_structured", provider="p", model="m", timeout_s=0.5) for vid in providers]
    settings = SwarmSettings(
        voters=voters, min_voters_answered=min_answered, shuffle_options=shuffle, max_spread=max_spread
    )
    return SwarmRunner(settings, providers, seed=seed, log=log)


def seven(**overrides: DecisionProvider) -> dict[str, DecisionProvider]:
    voters: dict[str, DecisionProvider] = {f"v{i}": Fixed() for i in range(1, 8)}
    voters.update(overrides)
    return voters


async def test_all_seven_answer():
    outcome = await build(seven()).decide(request())
    assert outcome.proceed and outcome.answered == 7
    assert outcome.aggregate.questions["action"].winner == "allow"
    assert outcome.aggregate.questions["aligned"].median == 0.6


async def test_exactly_quorum_proceeds():
    broken = {f"v{i}": Fixed(error=ProviderError("http", "boom")) for i in (6, 7)}
    outcome = await build(seven(**broken)).decide(request())
    assert outcome.proceed and outcome.answered == 5


async def test_one_below_quorum_skips_fail_closed():
    broken = {f"v{i}": Fixed(error=ProviderError("http", "boom")) for i in (5, 6, 7)}
    outcome = await build(seven(**broken)).decide(request())
    assert outcome.status == "skip" and outcome.reason == "quorum_not_met"
    assert outcome.answered == 4 and outcome.aggregate is None
    assert not outcome.proceed


async def test_every_voter_failing_skips():
    outcome = await build({f"v{i}": Fixed(error=ProviderError("network", "down")) for i in range(7)}).decide(request())
    assert outcome.status == "skip" and outcome.answered == 0


async def test_failed_voter_is_dropped_not_counted():
    voters = seven(v7=Fixed(noul=0.99, error=ProviderError("http", "boom")))
    outcome = await build(voters).decide(request())
    record = next(r for r in outcome.voters if r.voter_id == "v7")
    assert record.status == "failed" and record.error_kind == "http" and record.answers is None
    assert outcome.aggregate.voters == 6
    assert outcome.aggregate.questions["aligned"].spread.maximum == 0.6


async def test_slow_voter_is_dropped_by_timeout():
    outcome = await build(seven(v1=Fixed(delay=2.0))).decide(request())
    record = next(r for r in outcome.voters if r.voter_id == "v1")
    assert record.status == "timeout" and record.error_kind == "timeout"
    assert outcome.answered == 6 and outcome.proceed


async def test_slow_voters_alone_can_break_quorum():
    outcome = await build(seven(**{f"v{i}": Fixed(delay=2.0) for i in (1, 2, 3)})).decide(request())
    assert outcome.status == "skip" and outcome.answered == 4


async def test_provider_declared_timeout_counts_as_timeout():
    outcome = await build(seven(v1=Fixed(error=ProviderError("timeout", "slow")))).decide(request())
    assert next(r for r in outcome.voters if r.voter_id == "v1").status == "timeout"


async def test_invalid_answer_is_dropped():
    outcome = await build(seven(v1=Fixed(bogus=True))).decide(request())
    record = next(r for r in outcome.voters if r.voter_id == "v1")
    assert record.status == "invalid" and record.error_kind == "invalid"
    assert outcome.answered == 6


async def test_unexpected_exception_drops_voter_but_not_decision():
    outcome = await build(seven(v1=Fixed(error=RuntimeError("bug")))).decide(request())
    record = next(r for r in outcome.voters if r.voter_id == "v1")
    assert record.status == "failed" and record.error_kind == "internal"
    assert outcome.proceed


async def test_disabled_voter_is_not_called():
    providers = seven()
    voters = [
        VoterSpec(id=vid, adapter="llm_structured", provider="p", model="m", enabled=vid != "v7") for vid in providers
    ]
    runner = SwarmRunner(SwarmSettings(voters=voters, min_voters_answered=5), providers, seed="t")
    outcome = await runner.decide(request())
    assert outcome.answered == 6 and providers["v7"].seen == []


async def test_disabled_swarm_skips_without_calling():
    providers = seven()
    settings = SwarmSettings(
        enabled=False, voters=[VoterSpec(id=v, adapter="llm_structured", provider="p", model="m") for v in providers]
    )
    outcome = await SwarmRunner(settings, providers).decide(request())
    assert outcome.status == "skip" and outcome.reason == "swarm_disabled"
    assert all(p.seen == [] for p in providers.values())


def test_missing_provider_instance_is_config_error():
    voters = [VoterSpec(id="v1", adapter="llm_structured", provider="p", model="m")]
    with pytest.raises(ConfigError):
        SwarmRunner(SwarmSettings(voters=voters, min_voters_answered=1), {})


async def test_shuffle_defeats_position_bias():
    runs = 40
    counts: Counter[str] = Counter()
    for index in range(runs):
        providers = {f"v{i}": FirstPresented() for i in range(1, 8)}
        outcome = await build(providers, seed="bias").decide(request(), decision_id=f"d{index}")
        for record in outcome.voters:
            counts[record.answers["action"].choice] += 1
    assert set(counts) == set(OPTIONS)
    assert min(counts.values()) > 0.15 * sum(counts.values())


async def test_negative_control_without_shuffle_bias_is_total():
    counts: Counter[str] = Counter()
    for index in range(10):
        providers = {f"v{i}": FirstPresented() for i in range(1, 8)}
        outcome = await build(providers, shuffle=False).decide(request(), decision_id=f"d{index}")
        for record in outcome.voters:
            counts[record.answers["action"].choice] += 1
    assert set(counts) == {"allow"}


async def test_voters_see_different_orders_in_one_decision():
    providers = {f"v{i}": Fixed() for i in range(1, 8)}
    await build(providers, seed="x").decide(request(), decision_id="d")
    orders = {tuple(p.seen[0].questions["action"].criteria) for p in providers.values()}
    assert len(orders) > 1


async def test_same_seed_and_decision_reproduce_orders():
    first = {f"v{i}": Fixed() for i in range(1, 8)}
    second = {f"v{i}": Fixed() for i in range(1, 8)}
    await build(first, seed="x").decide(request(), decision_id="d")
    await build(second, seed="x").decide(request(), decision_id="d")
    assert [p.seen[0] for p in first.values()] == [p.seen[0] for p in second.values()]


async def test_score_flip_is_undone_before_aggregation():
    providers = {f"v{i}": FirstPresented() for i in range(1, 8)}
    outcome = await build(providers, seed="flip").decide(request(), decision_id="d")
    flips = [bool(r.flipped_scores) for r in outcome.voters]
    assert any(flips) and not all(flips)
    scores = {r.answers["risk"].score for r in outcome.voters}
    assert scores == {0.0, 2.0}


async def test_original_request_is_not_mutated():
    original = request()
    snapshot = original.model_dump()
    await build(seven()).decide(original)
    assert original.model_dump() == snapshot


async def test_weights_decide_the_median():
    voters = {f"v{i}": Fixed(noul=0.1) for i in range(1, 6)}
    voters["v6"] = Fixed(noul=0.9)
    voters["v7"] = Fixed(noul=0.9)
    specs = [
        VoterSpec(
            id=v, adapter="llm_structured", provider="p", model="m", weight=1.0 if v not in ("v6", "v7") else 10.0
        )
        for v in voters
    ]
    runner = SwarmRunner(SwarmSettings(voters=specs, min_voters_answered=5), voters, seed="t")
    outcome = await runner.decide(request())
    assert outcome.aggregate.questions["aligned"].median == 0.9


async def test_max_spread_skips_disagreement():
    voters = {f"v{i}": Fixed(noul=0.05 if i <= 3 else 0.95) for i in range(1, 8)}
    outcome = await build(voters, max_spread=0.2).decide(request())
    assert outcome.status == "skip" and outcome.reason == "spread_exceeded:aligned"
    agreeing = await build(seven(), max_spread=0.2).decide(request())
    assert agreeing.proceed


async def test_log_records_every_decision(tmp_path):
    log = VoterLog(tmp_path / "logs" / "voters.jsonl")
    runner = build(seven(v1=Fixed(error=ProviderError("http", "boom"))), log=log)
    await runner.decide(request(), decision_id="a")
    broken = build({f"v{i}": Fixed(error=ProviderError("http", "x")) for i in range(7)}, log=log)
    await broken.decide(request(), decision_id="b")
    lines = [json.loads(line) for line in (tmp_path / "logs" / "voters.jsonl").read_text().splitlines()]
    assert [line["decision_id"] for line in lines] == ["a", "b"]
    assert lines[0]["status"] == "ok" and lines[1]["reason"] == "quorum_not_met"
    assert {v["voter_id"]: v["status"] for v in lines[0]["voters"]}["v1"] == "failed"
    assert lines[0]["aggregate"]["questions"]["action"]["winner"] == "allow"
