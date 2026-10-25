import json

import pytest

from tb_swarm.errors import ConfigError, ProviderError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.llm_structured import LlmStructuredProvider, extract_json, response_schema
from tb_swarm.stub_server import CHAT_PATH, MESSAGES_PATH, RESPONSES_PATH, Behavior
from tests.conftest import STUB_KEY

WIRES = [
    ("openai-completions", "/v1", CHAT_PATH),
    ("openai-responses", "/v1", RESPONSES_PATH),
    ("anthropic-messages", "", MESSAGES_PATH),
]


def request() -> DecisionRequest:
    return DecisionRequest(
        state="BTC/IDR 1h: RSI 41, EMA20 above EMA50",
        questions={
            "aligned": NoulQuestion(instructions="Does the entry align with news?"),
            "action": ChoiceQuestion(instructions="Allow, shrink or skip?", criteria={"allow": "a", "skip": "b"}),
            "risk": ScoreQuestion(instructions="Event risk?", criteria=["low", "medium", "high"]),
        },
    )


def provider(stub, api_type, suffix, **overrides):
    options = {
        "api_type": api_type,
        "base_url": stub.base_url + suffix,
        "api_key": STUB_KEY,
        "model": "voter-model",
        "timeout_s": 5.0,
    }
    options.update(overrides)
    return LlmStructuredProvider(**options)


@pytest.mark.parametrize(("api_type", "suffix", "path"), WIRES)
async def test_each_api_type_round_trips_against_stub(stub, api_type, suffix, path):
    voter = provider(stub, api_type, suffix)
    response = await voter.decide(request())
    sent = stub.state.requests[-1]
    assert sent.path == path
    assert response.answers["aligned"].noul == 0.9
    assert response.answers["action"].choice == "allow"
    assert response.answers["risk"].score == 0.0
    assert response.usage.input_tokens == 120
    assert response.model == "voter-model"


@pytest.mark.parametrize(("api_type", "suffix", "path"), WIRES)
async def test_state_and_options_reach_the_model(stub, api_type, suffix, path):
    await provider(stub, api_type, suffix).decide(request())
    sent = json.dumps(stub.state.requests[-1].body)
    assert "RSI 41" in sent
    assert "Allow, shrink or skip?" in sent


async def test_reasoning_tokens_are_reported(stub):
    stub.state.behaviors["voter-model"] = Behavior(reasoning_tokens=77)
    response = await provider(stub, "openai-completions", "/v1").decide(request())
    assert response.usage.reasoning_tokens == 77
    assert response.usage.output_tokens == 107


async def test_json_schema_mode_sends_response_format(stub):
    voter = provider(stub, "openai-completions", "/v1", structured_mode="json_schema")
    await voter.decide(request())
    format_sent = stub.state.requests[-1].body["response_format"]
    assert format_sent["type"] == "json_schema"
    schema = format_sent["json_schema"]["schema"]
    assert schema["properties"]["answers"]["properties"]["action"]["properties"]["choice"]["enum"] == ["allow", "skip"]


async def test_json_object_mode_sends_response_format(stub):
    voter = provider(stub, "openai-completions", "/v1", structured_mode="json_object")
    await voter.decide(request())
    assert stub.state.requests[-1].body["response_format"] == {"type": "json_object"}


async def test_prompt_mode_sends_no_response_format(stub):
    await provider(stub, "openai-completions", "/v1").decide(request())
    assert "response_format" not in stub.state.requests[-1].body


def test_structured_mode_rejected_for_other_api_types():
    with pytest.raises(ConfigError):
        LlmStructuredProvider(
            api_type="anthropic-messages",
            base_url="http://x",
            api_key="k",
            model="m",
            timeout_s=1,
            structured_mode="json_schema",
        )


def test_unknown_api_type_rejected():
    with pytest.raises(ConfigError):
        LlmStructuredProvider(api_type="bogus", base_url="http://x", api_key="k", model="m", timeout_s=1)


@pytest.mark.parametrize(
    "text",
    [
        "I think allow.",
        "",
        "{broken",
        '{"answers": []}',
        '{"answers": {"aligned": {"noul": 2}}}',
        '{"answers": {"aligned": {"noul": 0.4}, "action": {"choice": "maybe"}, "risk": {"score": 1}}}',
        '{"answers": {"aligned": {"noul": 0.4}, "action": {"choice": "allow"}, "risk": {"score": 3}}}',
    ],
)
async def test_unusable_output_is_invalid_not_guessed(stub, text):
    stub.state.behaviors["voter-model"] = Behavior(malformed=text)
    with pytest.raises(ProviderError) as caught:
        await provider(stub, "openai-completions", "/v1").decide(request())
    assert caught.value.kind == "invalid"


async def test_fenced_json_is_accepted(stub):
    body = '```json\n{"answers": {"aligned": {"noul": 0.4}, "action": {"choice": "skip"}, "risk": {"score": 2}}}\n```'
    stub.state.behaviors["voter-model"] = Behavior(malformed=body)
    response = await provider(stub, "openai-completions", "/v1").decide(request())
    assert response.answers["action"].choice == "skip"


async def test_bad_key_is_auth(stub):
    with pytest.raises(ProviderError) as caught:
        await provider(stub, "openai-completions", "/v1", api_key="wrong").decide(request())
    assert caught.value.kind == "auth"


async def test_missing_key_is_auth_without_request(stub):
    with pytest.raises(ProviderError) as caught:
        await provider(stub, "openai-completions", "/v1", api_key=None).decide(request())
    assert caught.value.kind == "auth"
    assert stub.state.requests == []


@pytest.mark.parametrize(("status", "kind"), [(429, "rate_limit"), (500, "http")])
async def test_http_errors_are_classified(stub, status, kind):
    stub.state.behaviors["voter-model"] = Behavior(fail_status=status)
    with pytest.raises(ProviderError) as caught:
        await provider(stub, "openai-completions", "/v1").decide(request())
    assert caught.value.kind == kind


async def test_slow_server_is_timeout(stub):
    stub.state.behaviors["voter-model"] = Behavior(delay_s=1.5)
    with pytest.raises(ProviderError) as caught:
        await provider(stub, "openai-completions", "/v1", timeout_s=0.3).decide(request())
    assert caught.value.kind == "timeout"


def test_extract_json_finds_object_in_prose():
    assert extract_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def test_response_schema_lists_every_question():
    schema = response_schema(request())
    assert set(schema["properties"]["answers"]["required"]) == {"aligned", "action", "risk"}
