import json

import pytest

from tb_swarm.errors import ProviderError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.openai_decisions import OpenAiDecisionsProvider
from tb_swarm.providers.openrouter_decisions import OpenRouterDecisionsProvider
from tb_swarm.providers.systemone import SystemOneProvider
from tb_swarm.stub_server import Behavior
from tests.conftest import STUB_KEY


def request() -> DecisionRequest:
    return DecisionRequest(
        state={"pair": "BTC/IDR", "rsi": 41.2},
        questions={
            "aligned": NoulQuestion(instructions="Does the entry align with recent news?"),
            "action": ChoiceQuestion(
                instructions="Allow, shrink or skip?",
                criteria={"allow": "take it", "shrink": "half size", "skip": "pass"},
            ),
            "risk": ScoreQuestion(instructions="Event risk?", criteria=["low", "medium", "high"]),
        },
    )


def systemone(stub, key=STUB_KEY, model="jev-latest", timeout_s=5.0):
    return SystemOneProvider(base_url=stub.base_url, api_key=key, model=model, timeout_s=timeout_s)


def openrouter(stub, key=STUB_KEY, model="typesafe/jev-1.13", timeout_s=5.0):
    return OpenRouterDecisionsProvider(base_url=stub.base_url, api_key=key, model=model, timeout_s=timeout_s)


def openai_decisions(stub, key=STUB_KEY, model="gpt-6-luna-decisions", timeout_s=5.0):
    return OpenAiDecisionsProvider(base_url=stub.base_url, api_key=key, model=model, timeout_s=timeout_s)


REAL_OPENAI_ANSWERS = (
    '{"model": "gpt-6-luna-decisions", "answers": ['
    '{"type": "choice", "name": "action", "choice": "shrink", "probabilities": ['
    '{"value": "allow", "probability": 0.2}, {"value": "shrink", "probability": 0.7}, '
    '{"value": "skip", "probability": 0.1}], "confidence": 0.5}, '
    '{"type": "score", "name": "risk", "score": 1.8, "probabilities": ['
    '{"value": 0, "label": "low", "probability": 0.0}, {"value": 1, "label": "medium", "probability": 0.2}, '
    '{"value": 2, "label": "high", "probability": 0.8}], "confidence": 0.8}, '
    '{"type": "predicate", "name": "aligned", "probability": 0.53}], '
    '"usage": {"input_tokens": 173, "output_tokens": 4, "output_tokens_details": {"reasoning_tokens": 3}, '
    '"cost": 0.0001, "is_byok": false}, "provider": "openai"}'
)


async def test_openai_decisions_wire_shape_and_parse(stub):
    provider = openai_decisions(stub)
    response = await provider.decide(request())
    sent = stub.state.requests[-1]
    assert sent.path == "/v1/decisions"
    assert sent.headers["authorization"] == f"Bearer {STUB_KEY}"
    assert set(sent.body) == {"model", "input", "questions"}
    assert sent.body["model"] == "gpt-6-luna-decisions"
    assert sent.body["input"] == '{"pair": "BTC/IDR", "rsi": 41.2}'
    assert sent.body["questions"] == [
        {"type": "predicate", "name": "aligned", "instructions": "Does the entry align with recent news?"},
        {
            "type": "choice",
            "name": "action",
            "instructions": "Allow, shrink or skip?",
            "choices": [
                {"value": "allow", "description": "take it"},
                {"value": "shrink", "description": "half size"},
                {"value": "skip", "description": "pass"},
            ],
        },
        {
            "type": "score",
            "name": "risk",
            "instructions": "Event risk?",
            "levels": [{"label": "low"}, {"label": "medium"}, {"label": "high"}],
        },
    ]
    assert response.answers["aligned"].noul == 0.9
    assert response.answers["action"].choice == "allow"
    assert response.usage.input_tokens == 100
    await provider.aclose()


async def test_openai_decisions_parses_real_answer_list(stub):
    stub.state.behaviors["gpt-6-luna-decisions"] = Behavior(malformed=REAL_OPENAI_ANSWERS)
    provider = openai_decisions(stub)
    response = await provider.decide(request())
    assert response.answers["aligned"].noul == pytest.approx(0.53)
    assert response.answers["action"].choice == "shrink"
    assert response.answers["action"].probabilities == {"allow": 0.2, "shrink": 0.7, "skip": 0.1}
    assert response.answers["risk"].score == pytest.approx(1.8)
    assert response.answers["risk"].probabilities == {"0": 0.0, "1": 0.2, "2": 0.8}
    assert response.usage.reasoning_tokens == 3
    assert response.usage.cost == pytest.approx(0.0001)
    await provider.aclose()


async def test_openai_decisions_noul_criteria_move_into_instructions(stub):
    provider = openai_decisions(stub)
    question = NoulQuestion(instructions="Take it?", criteria={"true": "enter", "false": "wait"})
    await provider.decide(DecisionRequest(state="s", questions={"take": question}))
    assert stub.state.requests[-1].body["questions"] == [
        {"type": "predicate", "name": "take", "instructions": "Take it? True means: enter False means: wait"}
    ]
    await provider.aclose()


def valid_openai_answers():
    return [
        {"type": "predicate", "name": "aligned", "probability": 0.5},
        {
            "type": "choice",
            "name": "action",
            "choice": "allow",
            "probabilities": [
                {"value": "allow", "probability": 0.6},
                {"value": "shrink", "probability": 0.3},
                {"value": "skip", "probability": 0.1},
            ],
            "confidence": 0.3,
        },
        {
            "type": "score",
            "name": "risk",
            "score": 1.0,
            "probabilities": [
                {"value": 0, "label": "low", "probability": 0.1},
                {"value": 1, "label": "medium", "probability": 0.8},
                {"value": 2, "label": "high", "probability": 0.1},
            ],
            "confidence": 0.8,
        },
    ]


def break_answers(mutate):
    answers = valid_openai_answers()
    mutate(answers)
    return json.dumps({"model": "m", "answers": answers})


MALFORMED_OPENAI = [
    (json.dumps({"model": "m", "answers": {"aligned": {"type": "noul", "noul": 0.5}}}), "answers is not a list"),
    (break_answers(lambda a: a[0].pop("name")), "answer without a name"),
    (break_answers(lambda a: a.append(dict(a[0]))), "duplicate answer 'aligned'"),
    (break_answers(lambda a: a[0].update(probability=1.5)), "noul must be in [0, 1]"),
    (break_answers(lambda a: a.pop(0)), "answer names mismatch"),
    (break_answers(lambda a: a[1].update(choice="bogus")), "choice 'bogus' is not an option"),
    (break_answers(lambda a: a[1].update(probabilities="x")), "probabilities is not a list"),
]


@pytest.mark.parametrize(("malformed", "fragment"), MALFORMED_OPENAI)
async def test_openai_decisions_malformed_is_invalid(stub, malformed, fragment):
    stub.state.behaviors["gpt-6-luna-decisions"] = Behavior(malformed=malformed)
    provider = openai_decisions(stub)
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == "invalid"
    assert fragment in str(caught.value)
    await provider.aclose()


async def test_openai_decisions_accepts_the_valid_baseline(stub):
    stub.state.behaviors["gpt-6-luna-decisions"] = Behavior(malformed=break_answers(lambda a: None))
    provider = openai_decisions(stub)
    response = await provider.decide(request())
    assert response.answers["action"].choice == "allow"
    await provider.aclose()


async def test_openai_decisions_rejects_the_systemone_wire(stub):
    provider = SystemOneProvider(base_url=stub.base_url, api_key=STUB_KEY, model="m", timeout_s=5.0)
    provider._url = stub.base_url + "/v1/decisions"
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == "http"
    assert caught.value.status == 400
    await provider.aclose()


async def test_systemone_wire_shape_and_parse(stub):
    provider = systemone(stub)
    response = await provider.decide(request())
    sent = stub.state.requests[-1]
    assert sent.path == "/v1/systemone"
    assert sent.headers["authorization"] == f"Bearer {STUB_KEY}"
    assert set(sent.body) == {"model", "state", "questions"}
    assert sent.body["model"] == "jev-latest"
    assert sent.body["questions"]["action"] == {
        "type": "choice",
        "instructions": "Allow, shrink or skip?",
        "criteria": {"allow": "take it", "shrink": "half size", "skip": "pass"},
    }
    assert sent.body["questions"]["risk"]["criteria"] == ["low", "medium", "high"]
    assert "criteria" not in sent.body["questions"]["aligned"]
    assert response.answers["aligned"].noul == 0.9
    assert response.answers["action"].choice == "allow"
    assert response.usage.input_tokens == 100
    assert response.model == "jev-latest"
    await provider.aclose()


async def test_openrouter_wire_path_and_cost(stub):
    provider = openrouter(stub)
    response = await provider.decide(request())
    assert stub.state.requests[-1].path == "/api/alpha/decisions"
    assert response.usage.cost == pytest.approx(0.00001)
    await provider.aclose()


async def test_primitives_noul_choice_score(stub):
    provider = systemone(stub)
    assert (await provider.noul("state", "Is it true?")).noul == 0.9
    assert (await provider.choice("state", "Pick", {"a": "first", "b": "second"})).choice == "a"
    assert (await provider.score("state", "Rate", ["lo", "hi"])).score == 0.0
    await provider.aclose()


async def test_bad_key_is_auth_error(stub):
    provider = systemone(stub, key="wrong")
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == "auth"
    await provider.aclose()


async def test_missing_key_never_sends_request(stub):
    provider = systemone(stub, key=None)
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == "auth"
    assert stub.state.requests == []
    await provider.aclose()


@pytest.mark.parametrize(("status", "kind"), [(429, "rate_limit"), (500, "http"), (403, "auth")])
async def test_http_failures_are_classified(stub, status, kind):
    stub.state.behaviors["jev-latest"] = Behavior(fail_status=status)
    provider = systemone(stub)
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == kind
    assert caught.value.status == status
    await provider.aclose()


@pytest.mark.parametrize(
    "malformed",
    [
        "not json",
        "[]",
        '{"model": "m"}',
        '{"model": "m", "answers": {"aligned": {"type": "noul", "noul": 1.5}}}',
        '{"model": "m", "answers": {"aligned": {"type": "noul", "noul": 0.5}}}',
        '{"model": "m", "answers": {"aligned": {"type": "noul", "noul": 0.5}, "action": {"type": "choice", '
        '"choice": "bogus"}, "risk": {"type": "score", "score": 1}}}',
        '{"model": "m", "answers": {"aligned": {"type": "noul", "noul": 0.5}, "action": {"type": "choice", '
        '"choice": "allow"}, "risk": {"type": "score", "score": 7}}}',
    ],
)
async def test_malformed_responses_are_invalid(stub, malformed):
    stub.state.behaviors["jev-latest"] = Behavior(malformed=malformed)
    provider = systemone(stub)
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == "invalid"
    await provider.aclose()


async def test_valid_response_without_type_field_is_accepted(stub):
    body = '{"model": "m", "answers": {"aligned": {"noul": 0.5}, "action": {"choice": "allow"}, "risk": {"score": 1}}}'
    stub.state.behaviors["jev-latest"] = Behavior(malformed=body)
    provider = systemone(stub)
    response = await provider.decide(request())
    assert response.answers["risk"].score == 1
    await provider.aclose()


async def test_client_timeout_is_timeout_kind(stub):
    stub.state.behaviors["jev-latest"] = Behavior(delay_s=1.0)
    provider = systemone(stub, timeout_s=0.2)
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == "timeout"
    await provider.aclose()


async def test_unreachable_host_is_network_error():
    provider = SystemOneProvider(base_url="http://127.0.0.1:9", api_key="k", model="m", timeout_s=2.0)
    with pytest.raises(ProviderError) as caught:
        await provider.decide(request())
    assert caught.value.kind == "network"
    await provider.aclose()
