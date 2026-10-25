import pytest

from tb_swarm.config import SwarmSettings, VoterSpec, parse_config
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
from tb_swarm.providers.llm_structured import LlmStructuredProvider, classify_exception
from tb_swarm.redact import redact
from tb_swarm.runner import SwarmRunner
from tb_swarm.validate import parse_answers

OPTIONS = {"allow": "take", "shrink": "half", "skip": "pass"}
SECRET = "super-secret-key-value-123"


def request():
    return DecisionRequest(
        state="s",
        questions={
            "aligned": NoulQuestion(instructions="?"),
            "action": ChoiceQuestion(instructions="?", criteria=OPTIONS),
            "risk": ScoreQuestion(instructions="?", criteria=["low", "mid", "high"]),
        },
    )


class Pick(DecisionProvider):
    def __init__(self, choice, error=None, key=None):
        self.choice_, self.error, self.key = choice, error, key

    def secrets(self):
        return (self.key,) if self.key else ()

    async def decide(self, request):
        if self.error:
            raise self.error
        return DecisionResponse(
            model="m",
            answers={
                "aligned": NoulAnswer(noul=0.5),
                "action": ChoiceAnswer(choice=self.choice_),
                "risk": ScoreAnswer(score=1.0),
            },
        )


def runner(picks, min_answered=5, max_spread=None):
    providers = {f"v{i}": Pick(c) if not isinstance(c, Pick) else c for i, c in enumerate(picks)}
    voters = [
        VoterSpec(id=vid, adapter="llm_structured", provider="p", model="m", variation="none") for vid in providers
    ]
    settings = SwarmSettings(
        voters=voters, min_voters_answered=min_answered, max_spread=max_spread, shuffle_options=False
    )
    return SwarmRunner(settings, providers, seed="t")


@pytest.mark.parametrize(
    "picks",
    [
        ["allow", "skip", "skip", "shrink", "shrink"],
        ["allow", "allow", "shrink", "shrink", "skip", "skip", "skip"],
        ["allow", "allow", "allow", "skip", "skip", "skip"],
        ["allow", "skip"] * 3,
    ],
)
async def test_choice_without_a_majority_is_skipped(picks):
    outcome = await runner(picks).decide(request())
    assert outcome.status == "skip" and outcome.reason == "choice_tie:action"
    assert not outcome.proceed


async def test_clear_majority_still_proceeds_with_that_winner():
    outcome = await runner(["skip", "skip", "skip", "skip", "allow", "allow", "shrink"]).decide(request())
    assert outcome.proceed
    assert outcome.aggregate.questions["action"].winner == "skip"


async def test_four_three_split_proceeds_with_the_majority_winner():
    outcome = await runner(["shrink"] * 4 + ["allow"] * 3).decide(request())
    assert outcome.proceed and outcome.aggregate.questions["action"].winner == "shrink"


async def test_tie_skip_is_independent_of_option_declaration_order():
    reordered = {
        "skip": "pass",
        "shrink": "half",
        "allow": "take",
    }
    req = DecisionRequest(
        state="s",
        questions={"action": ChoiceQuestion(instructions="?", criteria=reordered)},
    )

    class Only(DecisionProvider):
        def __init__(self, choice):
            self.choice = choice

        async def decide(self, request):
            return DecisionResponse(model="m", answers={"action": ChoiceAnswer(choice=self.choice)})

    picks = ["allow", "skip", "skip", "shrink", "shrink"]
    providers = {f"v{i}": Only(c) for i, c in enumerate(picks)}
    voters = [VoterSpec(id=v, adapter="llm_structured", provider="p", model="m", variation="none") for v in providers]
    outcome = await SwarmRunner(SwarmSettings(voters=voters, min_voters_answered=5), providers, seed="t").decide(req)
    assert outcome.reason == "choice_tie:action"


def test_config_error_never_contains_the_misspelled_key_value():
    raw = {
        "providers": [{"id": "p", "type": "openai-completions", "base_url": "http://x/v1", "apikey": SECRET}],
        "swarm": {
            "min_voters_answered": 1,
            "voters": [{"id": "a", "adapter": "llm_structured", "provider": "p", "model": "m"}],
        },
    }
    with pytest.raises(ConfigError) as caught:
        parse_config(raw)
    message = str(caught.value)
    assert SECRET not in message
    assert "apikey" in message


@pytest.mark.parametrize(
    "text",
    [
        f"HTTP 401: bad key {SECRET}",
        "HTTP 401: Bearer abcdefgh12345678",
        "HTTP 401: incorrect key sk-abcdef123456",
        '{"api_key": "zzzzzz9999"}',
    ],
)
def test_redact_removes_credentials(text):
    cleaned = redact(text, [SECRET])
    for leaked in (SECRET, "abcdefgh12345678", "sk-abcdef123456", "zzzzzz9999"):
        assert leaked not in cleaned
    assert "[redacted]" in cleaned


def test_redact_leaves_plain_text_alone():
    assert redact("HTTP 500: upstream exploded", [SECRET]) == "HTTP 500: upstream exploded"


async def test_voter_log_error_text_has_the_key_removed():
    leaking = Pick("allow", error=ProviderError("auth", f"HTTP 401: key {SECRET} rejected"), key=SECRET)
    outcome = await runner(["allow"] * 6 + [leaking]).decide(request())
    record = next(r for r in outcome.voters if r.voter_id == "v6")
    assert record.status == "failed" and SECRET not in record.error and "[redacted]" in record.error


async def test_wire_error_text_passes_through_redaction(stub):
    from tb_swarm.providers.systemone import SystemOneProvider
    from tb_swarm.stub_server import Behavior

    stub.state.behaviors["jev-latest"] = Behavior(fail_status=500)
    provider = SystemOneProvider(
        base_url=stub.base_url, api_key="stub-key-not-a-secret", model="jev-latest", timeout_s=5
    )
    assert provider.secrets() == ("stub-key-not-a-secret",)


@pytest.mark.parametrize(
    "probabilities",
    [
        {"allow": 0.0, "shrink": 0.0, "skip": 1.0},
        {"allow": 0.0, "shrink": 0.0, "skip": 0.0},
        {"allow": 1.0, "shrink": 1.0, "skip": 0.0},
        {"allow": 0.4, "shrink": 0.4, "skip": 0.4},
    ],
)
def test_contradictory_choice_probabilities_are_invalid(probabilities):
    raw = {
        "aligned": {"noul": 0.5},
        "action": {"choice": "allow", "probabilities": probabilities},
        "risk": {"score": 1},
    }
    with pytest.raises(ProviderError) as caught:
        parse_answers(request(), raw)
    assert caught.value.kind == "invalid"


def test_consistent_choice_probabilities_are_accepted():
    raw = {
        "aligned": {"noul": 0.5},
        "action": {"choice": "allow", "probabilities": {"allow": 0.6, "shrink": 0.3, "skip": 0.1}},
        "risk": {"score": 1},
    }
    assert parse_answers(request(), raw)["action"].choice == "allow"


def test_unknown_exception_is_internal_not_network():
    assert classify_exception(ValueError("our bug")).kind == "internal"
    assert classify_exception(ConnectionError("x")).kind == "internal"


async def test_internal_error_from_a_provider_is_reported_as_internal(stub):
    voter = LlmStructuredProvider(
        api_type="openai-completions",
        base_url=stub.base_url + "/v1",
        api_key="stub-key-not-a-secret",
        model="voter-model",
        timeout_s=5,
    )

    async def boom(_request):
        raise ValueError("our bug")

    voter._invoke = boom
    with pytest.raises(ProviderError) as caught:
        await voter.decide(request())
    assert caught.value.kind == "internal"
