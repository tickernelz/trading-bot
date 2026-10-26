from pathlib import Path

import pytest

from tb_swarm.config import ProviderSpec, load_config, parse_config
from tb_swarm.errors import ConfigError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.factory import build_provider
from tb_swarm.runner import SwarmRunner
from tests.conftest import STUB_KEY

EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "config.example.yaml"


def voter(vid, **extra):
    return {"id": vid, "adapter": "llm_structured", "provider": "p", "model": "m", **extra}


def raw(voters=None, providers=None, **swarm):
    return {
        "providers": providers
        or [{"id": "p", "type": "openai-completions", "base_url": "http://x/v1", "models": ["m"]}],
        "swarm": {"min_voters_answered": 2, "voters": voters or [voter("a"), voter("b"), voter("c")], **swarm},
    }


def test_repository_example_config_parses():
    config = load_config(EXAMPLE)
    enabled = [v for v in config.swarm.voters if v.enabled]
    assert len(enabled) == 7
    assert config.swarm.min_voters_answered == 5
    assert len({v.provider for v in enabled}) == 7
    assert len({v.model for v in enabled}) == 7
    assert {v.adapter for v in config.swarm.voters if not v.enabled} == {"systemone", "openai_decisions"}
    assert all(spec.resolve_base_url({}) for spec in config.providers.values())


def test_unresolved_base_url_fails_build_loudly():
    config = load_config(EXAMPLE)
    spec = config.providers["nutaraline"].model_copy(update={"base_url": "from_import"})
    assert spec.resolve_base_url({}) is None
    with pytest.raises(ConfigError):
        build_provider(config.swarm.voters[0], spec, {})


def test_base_url_env_overrides_placeholder():
    spec = ProviderSpec(id="p", type="openai-completions", base_url="from_import", base_url_env="P_URL")
    assert spec.resolve_base_url({"P_URL": "http://h/v1"}) == "http://h/v1"


def test_api_key_never_appears_in_repr():
    spec = ProviderSpec(id="p", type="systemone", api_key="literal-secret-value")
    assert "literal-secret-value" not in repr(spec)
    assert spec.resolve_api_key({}) == "literal-secret-value"


def test_api_key_prefers_env_then_literal():
    spec = ProviderSpec(id="p", type="systemone", api_key_env="K", api_key="literal")
    assert spec.resolve_api_key({"K": "from-env"}) == "from-env"
    assert spec.resolve_api_key({}) == "literal"
    assert ProviderSpec(id="p", type="systemone").resolve_api_key({}) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["swarm"]["voters"].append(voter("a")),
        lambda r: r["swarm"]["voters"].append(voter("z", provider="ghost")),
        lambda r: r["swarm"]["voters"].append(voter("z", model="not-listed")),
        lambda r: r["swarm"]["voters"].append(voter("z", adapter="systemone")),
        lambda r: r["swarm"].update(min_voters_answered=4),
        lambda r: r["swarm"]["voters"].append(voter("z", timeout_s=0)),
        lambda r: r["swarm"]["voters"].append(voter("z", weight=-1)),
        lambda r: r["swarm"]["voters"].append(voter("z", variation="temperature")),
        lambda r: r["swarm"]["voters"].append(voter("z", surprise=True)),
        lambda r: r["swarm"].update(mode="live"),
    ],
)
def test_invalid_configs_are_rejected(mutate):
    config = raw()
    mutate(config)
    with pytest.raises(ConfigError):
        parse_config(config)


def test_disabled_voters_do_not_count_toward_quorum_capacity():
    config = raw(voters=[voter("a"), voter("b", enabled=False), voter("c", enabled=False)])
    with pytest.raises(ConfigError):
        parse_config(config)


def test_providers_accept_mapping_form():
    config = parse_config(
        {
            "providers": {"p": {"type": "systemone", "base_url": "http://x"}},
            "swarm": {"min_voters_answered": 1, "voters": [voter("a", adapter="systemone")]},
        }
    )
    assert config.providers["p"].id == "p"


async def test_four_adapters_answer_the_same_question_end_to_end(stub):
    config = parse_config(
        {
            "providers": [
                {"id": "llm", "type": "openai-completions", "base_url": stub.base_url + "/v1", "api_key_env": "K"},
                {"id": "s1", "type": "systemone", "base_url": stub.base_url, "api_key_env": "K"},
                {"id": "or", "type": "openrouter-decisions", "base_url": stub.base_url, "api_key_env": "K"},
                {"id": "od", "type": "openai-decisions", "base_url": stub.base_url, "api_key_env": "K"},
            ],
            "swarm": {
                "min_voters_answered": 4,
                "voters": [
                    voter("llm", provider="llm", model="deepseek-test"),
                    voter("s1", adapter="systemone", provider="s1", model="jev-latest"),
                    voter("or", adapter="openrouter_decisions", provider="or", model="typesafe/jev-1.13"),
                    voter("od", adapter="openai_decisions", provider="od", model="gpt-6-luna-decisions"),
                ],
            },
        }
    )
    runner = SwarmRunner.from_config(config, {"K": STUB_KEY}, seed="e2e")
    request = DecisionRequest(
        state={"pair": "ETH/IDR"},
        questions={
            "aligned": NoulQuestion(instructions="Aligned with news?"),
            "action": ChoiceQuestion(instructions="Allow?", criteria={"allow": "yes", "skip": "no"}),
            "risk": ScoreQuestion(instructions="Risk?", criteria=["low", "high"]),
        },
    )
    outcome = await runner.decide(request)
    assert outcome.proceed and outcome.answered == 4
    assert {r.voter_id: r.status for r in outcome.voters} == {"llm": "ok", "s1": "ok", "or": "ok", "od": "ok"}
    assert {req.path for req in stub.state.requests} == {
        "/v1/chat/completions",
        "/v1/systemone",
        "/v1/decisions",
        "/api/alpha/decisions",
    }
    await runner.aclose()
