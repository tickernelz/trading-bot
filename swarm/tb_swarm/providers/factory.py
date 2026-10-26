from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from tb_swarm.config import ProviderSpec, VoterSpec
from tb_swarm.errors import ConfigError
from tb_swarm.providers.base import DecisionProvider
from tb_swarm.providers.llm_structured import LlmStructuredProvider
from tb_swarm.providers.openai_decisions import OpenAiDecisionsProvider
from tb_swarm.providers.openrouter_decisions import OpenRouterDecisionsProvider
from tb_swarm.providers.systemone import SystemOneProvider

AgentFactory = Callable[[BaseChatModel], Any]


def build_provider(
    voter: VoterSpec,
    provider: ProviderSpec,
    env: Mapping[str, str],
    agent_factory: AgentFactory | None = None,
) -> DecisionProvider:
    api_key = provider.resolve_api_key(env)
    base_url = provider.resolve_base_url(env)
    if voter.adapter == "openrouter_decisions":
        extra = {"base_url": base_url} if base_url else {}
        return OpenRouterDecisionsProvider(api_key=api_key, model=voter.model, timeout_s=voter.timeout_s, **extra)
    if base_url is None:
        raise ConfigError(f"provider {provider.id!r} has no resolvable base_url")
    if voter.adapter == "systemone":
        return SystemOneProvider(base_url=base_url, api_key=api_key, model=voter.model, timeout_s=voter.timeout_s)
    if voter.adapter == "openai_decisions":
        return OpenAiDecisionsProvider(base_url=base_url, api_key=api_key, model=voter.model, timeout_s=voter.timeout_s)
    return LlmStructuredProvider(
        api_type=provider.type,
        base_url=base_url,
        api_key=api_key,
        model=voter.model,
        timeout_s=voter.timeout_s,
        temperature=voter.temperature,
        structured_mode=voter.structured_mode,
        backend=voter.backend,
        extra_body=voter.extra_body,
        agent_factory=agent_factory,
    )
