import pytest

from tb_swarm.agents import build_voter_agent
from tb_swarm.config import SwarmSettings, VoterSpec, parse_config
from tb_swarm.errors import ConfigError, ProviderError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.base import DecisionProvider
from tb_swarm.providers.http_wire import classify_status
from tb_swarm.providers.llm_structured import LlmStructuredProvider, classify_exception
from tb_swarm.providers.systemone import SystemOneProvider
from tb_swarm.runner import SwarmRunner
from tb_swarm.stub_server import Behavior
from tests.conftest import STUB_KEY

KEY = "plain-key-without-known-prefix-9f8e7d6c5b4a"


def request():
    return DecisionRequest(
        state="s",
        questions={
            "aligned": NoulQuestion(instructions="?"),
            "action": ChoiceQuestion(instructions="?", criteria={"allow": "a", "skip": "b"}),
            "risk": ScoreQuestion(instructions="?", criteria=["low", "high"]),
        },
    )


def voter(**extra):
    return {"id": "a", "adapter": "llm_structured", "provider": "p", "model": "m", **extra}


def config(voters, provider_type="openai-completions"):
    return {
        "providers": [{"id": "p", "type": provider_type, "base_url": "http://x/v1", "models": ["m"]}],
        "swarm": {"min_voters_answered": 1, "voters": voters},
    }


@pytest.mark.parametrize("mode", ["json_object", "json_schema"])
async def test_deepagents_backend_rejects_structured_mode_in_the_provider(stub, mode):
    with pytest.raises(ConfigError):
        LlmStructuredProvider(
            api_type="openai-completions",
            base_url=stub.base_url + "/v1",
            api_key=STUB_KEY,
            model="m",
            timeout_s=5,
            structured_mode=mode,
            backend="deepagents",
            agent_factory=build_voter_agent,
        )


@pytest.mark.parametrize("mode", ["json_object", "json_schema"])
def test_deepagents_backend_rejects_structured_mode_at_config_load(mode):
    with pytest.raises(ConfigError):
        parse_config(config([voter(backend="deepagents", structured_mode=mode)]))


def test_deepagents_with_prompt_mode_and_direct_with_structured_mode_load():
    parse_config(config([voter(backend="deepagents")]))
    parse_config(config([voter(id="b", structured_mode="json_schema")]))


def test_structured_mode_on_a_non_openai_provider_is_rejected_at_load():
    with pytest.raises(ConfigError):
        parse_config(config([voter(structured_mode="json_schema")], provider_type="anthropic-messages"))


@pytest.mark.parametrize(
    "option",
    [{"temperature": 0.2}, {"structured_mode": "json_object"}, {"backend": "deepagents"}, {"extra_body": {"a": 1}}],
)
def test_options_a_wire_adapter_would_ignore_are_rejected_at_load(option):
    raw = {
        "providers": [{"id": "p", "type": "systemone", "base_url": "http://x"}],
        "swarm": {
            "min_voters_answered": 1,
            "voters": [{"id": "a", "adapter": "systemone", "provider": "p", "model": "m", **option}],
        },
    }
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_status_body_is_redacted_before_it_is_cut():
    padded = "x" * 185 + KEY + "y" * 50
    error = classify_status(401, padded, (KEY,))
    assert KEY[:8] not in str(error)
    assert "[redacted]" in str(error)


def test_status_body_without_redaction_would_leak_the_prefix():
    padded = "x" * 185 + KEY + "y" * 50
    assert KEY[:8] in str(classify_status(401, padded))


def test_sdk_error_message_is_redacted_before_it_is_cut():
    class FakeSdkError(Exception):
        status_code = 401
        message = "z" * 190 + KEY

    error = classify_exception(FakeSdkError(), (KEY,))
    assert KEY[:8] not in str(error)
    assert KEY[:8] in str(classify_exception(FakeSdkError()))


def test_internal_error_text_is_redacted():
    error = classify_exception(ValueError(f"boom {KEY}"), (KEY,))
    assert error.kind == "internal" and KEY not in str(error)


class Leaky(DecisionProvider):
    def __init__(self, message):
        self.message = message

    def secrets(self):
        return (KEY,)

    async def decide(self, request):
        raise ProviderError("http", self.message)


@pytest.mark.parametrize("offset", [0, 185, 280, 295])
async def test_voter_record_never_keeps_a_key_prefix(offset):
    message = "x" * offset + KEY + "tail"
    providers = {"a": Leaky(message)}
    spec = VoterSpec(id="a", adapter="llm_structured", provider="p", model="m", variation="none")
    runner = SwarmRunner(SwarmSettings(voters=[spec], min_voters_answered=1), providers, seed="t")
    outcome = await runner.decide(request())
    record = outcome.voters[0]
    assert KEY[:8] not in record.error
    assert len(record.error) <= 300


async def test_wire_provider_redacts_a_key_echoed_by_the_gateway(stub):
    body = '{"error": "' + "p" * 150 + " key " + STUB_KEY + '"}'
    stub.state.behaviors["jev-latest"] = Behavior(fail_status=401, fail_body=body)
    provider = SystemOneProvider(base_url=stub.base_url, api_key=STUB_KEY, model="jev-latest", timeout_s=5)
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert STUB_KEY[:8] not in str(caught.value)
    assert caught.value.kind == "auth"
