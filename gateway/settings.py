"""Schema of config/gateway.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

EnvName = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
LoopbackUrl = Annotated[str, Field(pattern=r"^http://(127\.0\.0\.1|\[::1\]|localhost):\d{2,5}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BotRef(Strict):
    id: Annotated[str, Field(pattern=r"^[A-Z]$")]
    label: str
    strategy: str
    api_url: LoopbackUrl
    config: str
    userdir: str
    shadow_url: LoopbackUrl | None = None
    decisions: str | None = None


class GatewaySettings(Strict):
    listen: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: Annotated[int, Field(ge=1024, le=65535)] = 8090
    state_dir: str
    password_env: EnvName = "GW_PASSWORD"
    ft_username_env: EnvName = "FT_API_USERNAME"
    ft_password_env: EnvName = "FT_API_PASSWORD"
    session_days: Annotated[int, Field(ge=1, le=90)] = 30
    heartbeat_lost_s: Annotated[int, Field(ge=30)] = 180
    exchange_probe_url: str | None = "https://indodax.com/api/server_time"
    models_yml: str = "~/.omp/agent/models.yml"
    bots: Annotated[list[BotRef], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_bots(self) -> GatewaySettings:
        ids = [bot.id for bot in self.bots]
        if len(set(ids)) != len(ids):
            raise ValueError("bot ids must be unique")
        return self

    def bot(self, bot_id: str | None) -> BotRef | None:
        if bot_id is None:
            return self.bots[0]
        return next((bot for bot in self.bots if bot.id == bot_id), None)


def load_gateway_settings(path: str | os.PathLike[str]) -> GatewaySettings:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return GatewaySettings.model_validate(raw)
