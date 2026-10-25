import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tb_swarm.errors import ConfigError

ProviderType = Literal[
    "openai-completions", "openai-responses", "anthropic-messages", "systemone", "openrouter-decisions"
]
Adapter = Literal["llm_structured", "systemone", "openrouter_decisions"]

ADAPTER_PROVIDER_TYPES: dict[str, tuple[str, ...]] = {
    "llm_structured": ("openai-completions", "openai-responses", "anthropic-messages"),
    "systemone": ("systemone",),
    "openrouter_decisions": ("openrouter-decisions",),
}

UNRESOLVED_BASE_URL = "from_import"


class ProviderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: ProviderType
    base_url: str | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    models: list[str] = Field(default_factory=list)

    def resolve_base_url(self, env: Mapping[str, str]) -> str | None:
        if self.base_url_env and env.get(self.base_url_env):
            return env[self.base_url_env]
        if self.base_url and self.base_url != UNRESOLVED_BASE_URL:
            return self.base_url
        return None

    def resolve_api_key(self, env: Mapping[str, str]) -> str | None:
        if self.api_key_env and env.get(self.api_key_env):
            return env[self.api_key_env]
        return self.api_key or None


class VoterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    adapter: Adapter
    provider: str
    model: str
    variation: Literal["option_order", "none"] = "option_order"
    timeout_s: float = Field(default=30.0, gt=0)
    weight: float = Field(default=1.0, gt=0)
    enabled: bool = True
    temperature: float | None = None
    structured_mode: Literal["prompt", "json_object", "json_schema"] = "prompt"
    backend: Literal["direct", "deepagents"] = "direct"
    extra_body: dict[str, Any] | None = None


class SwarmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    mode: Literal["shadow", "veto"] = "shadow"
    shuffle_options: bool = True
    min_voters_answered: int = Field(default=5, ge=1)
    max_spread: float | None = Field(default=None, ge=0)
    voters: list[VoterSpec]
    log_path: str | None = None


class SwarmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderSpec]
    swarm: SwarmSettings

    @model_validator(mode="after")
    def _cross_checks(self) -> "SwarmConfig":
        seen: set[str] = set()
        for voter in self.swarm.voters:
            if voter.id in seen:
                raise ValueError(f"duplicate voter id {voter.id!r}")
            seen.add(voter.id)
            provider = self.providers.get(voter.provider)
            if provider is None:
                raise ValueError(f"voter {voter.id!r} references unknown provider {voter.provider!r}")
            if provider.type not in ADAPTER_PROVIDER_TYPES[voter.adapter]:
                raise ValueError(
                    f"voter {voter.id!r}: adapter {voter.adapter!r} cannot use provider type {provider.type!r}"
                )
            if provider.models and voter.model not in provider.models:
                raise ValueError(f"voter {voter.id!r}: model {voter.model!r} not listed for provider {provider.id!r}")
        enabled = sum(1 for voter in self.swarm.voters if voter.enabled)
        if self.swarm.enabled and enabled < self.swarm.min_voters_answered:
            raise ValueError(
                f"{enabled} enabled voters cannot reach min_voters_answered={self.swarm.min_voters_answered}"
            )
        return self


def parse_config(raw: Mapping[str, Any]) -> SwarmConfig:
    providers_raw = raw.get("providers") or []
    if isinstance(providers_raw, list):
        providers = {item["id"]: item for item in providers_raw if isinstance(item, dict) and "id" in item}
    elif isinstance(providers_raw, dict):
        providers = {key: {"id": key, **value} for key, value in providers_raw.items()}
    else:
        raise ConfigError("providers must be a list or mapping")
    try:
        return SwarmConfig.model_validate({"providers": providers, "swarm": raw.get("swarm") or {}})
    except ValidationError as exc:
        lines = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors(include_input=False, include_url=False, include_context=False)
        ]
        raise ConfigError("invalid swarm config:\n" + "\n".join(lines)) from None


def load_config(path: str | Path) -> SwarmConfig:
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return parse_config(raw)


def environment() -> Mapping[str, str]:
    return os.environ
