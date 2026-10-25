import pytest

from tb_swarm.errors import ProviderError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
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
