"""Configuration schema for config/config.yaml; the single source of validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

LLM_PROVIDER_TYPES = ("openai-completions", "openai-responses", "anthropic-messages")
Percent = Annotated[float, Field(gt=0, le=100)]
EnvName = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Capital(Strict):
    initial_idr: Annotated[float, Field(gt=0)]
    compounding: bool


class RiskSettings(Strict):
    max_daily_loss_pct: Percent
    max_total_drawdown_pct: Percent
    risk_per_trade_pct: Percent
    max_open_trades: Annotated[int, Field(ge=1, le=20)]
    leverage: Literal["none"]
    on_breach: Literal["stop_new_entries"]
    daily_reset_timezone: str = "Asia/Jakarta"

    @field_validator("daily_reset_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _ordered_limits(self) -> RiskSettings:
        if self.risk_per_trade_pct > self.max_daily_loss_pct:
            raise ValueError("risk_per_trade_pct must not exceed max_daily_loss_pct")
        if self.max_daily_loss_pct > self.max_total_drawdown_pct:
            raise ValueError("max_daily_loss_pct must not exceed max_total_drawdown_pct")
        return self


class Exchange(Strict):
    name: Annotated[str, Field(pattern=r"^[a-z0-9]+$")]
    pairs: Annotated[list[Annotated[str, Field(pattern=r"^[A-Z0-9]+/[A-Z0-9]+$")]], Field(min_length=1)]
    timeframe: Literal["1h"]
    fee_pct: Annotated[float, Field(ge=0, lt=5)]

    @field_validator("pairs")
    @classmethod
    def _unique_idr_pairs(cls, pairs: list[str]) -> list[str]:
        if len(set(pairs)) != len(pairs):
            raise ValueError("pairs must be unique")
        quotes = {pair.split("/")[1] for pair in pairs}
        if quotes != {"IDR"}:
            raise ValueError(f"every pair must be quoted in IDR to match capital.initial_idr, got {sorted(quotes)}")
        return pairs

    @property
    def stake_currency(self) -> str:
        return "IDR"


class Provider(Strict):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    type: Literal[
        "openai-completions",
        "openai-responses",
        "anthropic-messages",
        "systemone",
        "openai-decisions",
        "openrouter-decisions",
    ]
    base_url: Annotated[str, Field(pattern=r"^(from_import|https?://\S+)$")]
    api_key_env: EnvName | None = None
    api_key: SecretStr | None = None
    models: Annotated[list[str], Field(min_length=1)]


class Voter(Strict):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    adapter: Literal["llm_structured", "systemone", "openrouter_decisions", "openai_decisions"]
    provider: str
    model: str
    variation: Literal["option_order", "temperature", "prompt_variant"]
    timeout_s: Annotated[float, Field(gt=0, le=600)]
    weight: Annotated[float, Field(gt=0)]
    enabled: bool


class Swarm(Strict):
    enabled: bool
    mode: Literal["shadow", "veto"]
    shuffle_options: bool
    min_voters_answered: Annotated[int, Field(ge=1)]
    max_spread: Annotated[float, Field(gt=0)] | None
    voters: list[Voter]


class Llm(Strict):
    backend: Literal["deepagents"]
    analyst_model: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*:\S+$")]


class Compute(Strict):
    max_cost_idr_per_day: Literal[False] | Annotated[float, Field(gt=0)]
    on_exceed: Literal["skip_new_entries"]
    log_cost: bool


class Data(Strict):
    news_rss: list[Literal["coindesk", "cointelegraph"]]
    fear_greed: bool
    social: bool


class Telegram(Strict):
    enabled: bool = False
    token_env: EnvName = "TELEGRAM_BOT_TOKEN"
    chat_id: Annotated[str, Field(pattern=r"^-?[0-9]+$")] | None = None
    authorized_users: list[Annotated[str, Field(pattern=r"^[0-9]+$")]] = []

    @model_validator(mode="after")
    def _addressed_when_enabled(self) -> Telegram:
        if self.enabled and self.chat_id is None:
            raise ValueError("notify.telegram.chat_id is required when telegram is enabled")
        if self.enabled and not self.authorized_users:
            raise ValueError("notify.telegram.authorized_users must name at least one user when telegram is enabled")
        return self


class Notify(Strict):
    web_push: bool
    telegram: Telegram = Telegram()


class Api(Strict):
    listen: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: Annotated[int, Field(ge=1024, le=65535)] = 8080
    username_env: EnvName = "FT_API_USERNAME"
    password_env: EnvName = "FT_API_PASSWORD"
    jwt_secret_env: EnvName = "FT_API_JWT_SECRET"
    ws_token_env: EnvName = "FT_API_WS_TOKEN"
    force_entry: bool = False


class Scoreboard(Strict):
    enabled: bool = True
    auto_disable: bool = True
    min_samples: Annotated[int, Field(ge=5)] = 30
    max_ece: Annotated[float, Field(gt=0, lt=1)] = 0.25
    brier_margin: Annotated[float, Field(ge=0, lt=1)] = 0.05
    accuracy_margin: Annotated[float, Field(ge=0, lt=0.5)] = 0.05
    bins: Annotated[int, Field(ge=2, le=20)] = 5
    interval_s: Annotated[int, Field(ge=60)] = 3600


class Stress(Strict):
    drop_pct: Percent = 10.0


class Tax(Strict):
    pph22_final_pct: Annotated[float, Field(ge=0, le=100)] = 0.21


class Portfolio(Strict):
    max_pair_share_pct: Percent = 50.0


class Analytics(Strict):
    scoreboard: Scoreboard = Scoreboard()
    stress: Stress = Stress()
    tax: Tax = Tax()
    portfolio: Portfolio = Portfolio()


class Settings(Strict):
    mode: Literal["dry_run"]
    capital: Capital
    risk: RiskSettings
    exchange: Exchange
    providers: list[Provider]
    swarm: Swarm
    llm: Llm
    compute: Compute
    data: Data
    notify: Notify
    api: Api = Api()
    analytics: Analytics = Analytics()

    @model_validator(mode="after")
    def _references_resolve(self) -> Settings:
        providers = {provider.id: provider for provider in self.providers}
        if len(providers) != len(self.providers):
            raise ValueError("provider ids must be unique")
        voter_ids = [voter.id for voter in self.swarm.voters]
        if len(set(voter_ids)) != len(voter_ids):
            raise ValueError("voter ids must be unique")
        for voter in self.swarm.voters:
            provider = providers.get(voter.provider)
            if provider is None:
                raise ValueError(f"voter {voter.id} references unknown provider {voter.provider!r}")
            if voter.model not in provider.models:
                raise ValueError(f"voter {voter.id} model {voter.model!r} is not listed by provider {provider.id}")
        enabled = sum(1 for voter in self.swarm.voters if voter.enabled)
        if self.swarm.enabled and self.swarm.min_voters_answered > enabled:
            raise ValueError(f"min_voters_answered {self.swarm.min_voters_answered} exceeds {enabled} enabled voters")
        analyst_provider, analyst_model = self.llm.analyst_model.split(":", 1)
        if analyst_provider not in providers:
            raise ValueError(f"llm.analyst_model references unknown provider {analyst_provider!r}")
        if providers[analyst_provider].type not in LLM_PROVIDER_TYPES:
            raise ValueError(f"llm.analyst_model provider {analyst_provider!r} is not a chat provider")
        if analyst_model not in providers[analyst_provider].models:
            raise ValueError(f"llm.analyst_model {analyst_model!r} is not listed by provider {analyst_provider}")
        return self


class ConfigError(Exception):
    """Raised when the configuration file is missing, unreadable, or invalid."""


def load_settings(path: str | os.PathLike[str]) -> Settings:
    """Read and validate a YAML configuration file."""
    file = Path(path)
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{file}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{file}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{file}: top level must be a mapping")
    try:
        return Settings.model_validate(raw)
    except ValueError as exc:
        raise ConfigError(f"{file}: {exc}") from exc
