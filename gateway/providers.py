"""Provider registry operations: views, edits, models.yml import and the connection test."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from engine.settings import Provider, Settings
from gateway.redact import key_last4, redact
from gateway.upstream import ApiError

API_TYPES = ("openai-completions", "openai-responses", "anthropic-messages")
RESERVED_IDS = frozenset({"import"})
KEY_PATTERN = re.compile(r"^\S{8,1024}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
TEST_PROMPT = "Reply with the single word: ok"
TEST_MAX_TOKENS = 16
TEST_TIMEOUT_S = 30.0
TEST_COOLDOWN_S = 5.0
DETAIL_LIMIT = 160
USER_AGENT = "trading-bot-gateway/0.1 (provider-test)"


def default_env_name(provider_id: str) -> str:
    return provider_id.upper().replace("-", "_") + "_API_KEY"


def host_of(base_url: str) -> str | None:
    if base_url == "from_import":
        return None
    parts = urlsplit(base_url)
    if not parts.hostname:
        return None
    return f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname


def key_state(provider: Provider, env: Mapping[str, str]) -> dict[str, Any]:
    if provider.api_key is not None:
        return {
            "source": "config",
            "configured": True,
            "last4": key_last4(provider.api_key.get_secret_value()),
            "env_name": None,
            "env_set": None,
        }
    if provider.api_key_env:
        present = bool(env.get(provider.api_key_env))
        return {
            "source": "env",
            "configured": present,
            "last4": None,
            "env_name": provider.api_key_env,
            "env_set": present,
        }
    return {"source": "none", "configured": False, "last4": None, "env_name": None, "env_set": None}


def active_models(settings: Settings, provider_id: str) -> list[str]:
    used = {voter.model for voter in settings.swarm.voters if voter.enabled and voter.provider == provider_id}
    analyst_provider, analyst_model = settings.llm.analyst_model.split(":", 1)
    if analyst_provider == provider_id:
        used.add(analyst_model)
    return sorted(used)


def provider_view(
    provider: Provider, settings: Settings, env: Mapping[str, str], last_test: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "id": provider.id,
        "type": provider.type,
        "base_url": provider.base_url,
        "host": host_of(provider.base_url),
        "models": provider.models,
        "active_models": active_models(settings, provider.id),
        "key": key_state(provider, env),
        "last_test": last_test,
    }


def find_provider(raw: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    return next((item for item in raw.get("providers") or [] if item.get("id") == provider_id), None)


def require_provider(raw: dict[str, Any], provider_id: str) -> dict[str, Any]:
    entry = find_provider(raw, provider_id)
    if entry is None:
        raise ApiError(404, "not_found", f"unknown provider {provider_id}")
    return entry


def check_provider_id(provider_id: str) -> None:
    if provider_id in RESERVED_IDS or not PROVIDER_ID.match(provider_id):
        raise ApiError(400, "invalid_request", f"invalid provider id {provider_id!r}")


def upsert_provider(raw: dict[str, Any], provider_id: str, type_: str, base_url: str, models: list[str]) -> None:
    check_provider_id(provider_id)
    parts = urlsplit(base_url)
    if parts.username or parts.password:
        raise ApiError(400, "invalid_request", "base_url must not carry credentials")
    entry = find_provider(raw, provider_id)
    if entry is None:
        raw.setdefault("providers", []).append(
            {
                "id": provider_id,
                "type": type_,
                "base_url": base_url,
                "api_key_env": default_env_name(provider_id),
                "api_key": None,
                "models": models,
            }
        )
        return
    entry.update(type=type_, base_url=base_url, models=models)


def delete_provider(raw: dict[str, Any], provider_id: str) -> None:
    require_provider(raw, provider_id)
    raw["providers"] = [item for item in raw["providers"] if item.get("id") != provider_id]


def set_key(raw: dict[str, Any], provider_id: str, api_key: str | None, api_key_env: str | None) -> None:
    entry = require_provider(raw, provider_id)
    if (api_key is None) == (api_key_env is None):
        raise ApiError(400, "invalid_request", "send exactly one of api_key and api_key_env")
    if api_key is not None:
        if not KEY_PATTERN.match(api_key):
            raise ApiError(400, "invalid_request", "api_key must be 8 to 1024 characters without whitespace")
        entry.update(api_key=api_key, api_key_env=None)
        return
    if not ENV_NAME.match(api_key_env or ""):
        raise ApiError(400, "invalid_request", "api_key_env must be an upper-case variable name")
    entry.update(api_key=None, api_key_env=api_key_env)


def clear_key(raw: dict[str, Any], provider_id: str) -> None:
    require_provider(raw, provider_id).update(api_key=None, api_key_env=None)


def read_models_yml(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ApiError(404, "not_found", "models.yml was not found on this machine") from exc
    except yaml.YAMLError as exc:
        raise ApiError(400, "invalid_request", "models.yml is not valid YAML") from exc
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        raise ApiError(400, "invalid_request", "models.yml has no providers mapping")
    return {str(name): entry for name, entry in providers.items() if isinstance(entry, dict)}


def key_source(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "none"
    if value.startswith("!"):
        return "command"
    return "env" if ENV_NAME.match(value) else "literal"


def model_ids(entry: dict[str, Any]) -> list[str]:
    models = entry.get("models")
    if not isinstance(models, list):
        return []
    ids = [item["id"] if isinstance(item, dict) else item for item in models]
    return [str(item) for item in ids if isinstance(item, (str, int)) and str(item)]


def import_candidate(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    base_url = entry.get("baseUrl")
    return {
        "name": name,
        "id": name.lower(),
        "type": entry.get("api"),
        "base_url": base_url if isinstance(base_url, str) else None,
        "host": host_of(base_url) if isinstance(base_url, str) else None,
        "models": model_ids(entry),
        "key_source": key_source(entry.get("apiKey")),
    }


def import_blocker(candidate: dict[str, Any]) -> str | None:
    if candidate["type"] not in API_TYPES:
        return f"unsupported api type {candidate['type']!r}"
    base_url = candidate["base_url"]
    if not base_url or not re.match(r"^https?://\S+$", base_url):
        return "base url is missing or not http(s)"
    if not candidate["models"]:
        return "no models"
    if not PROVIDER_ID.match(candidate["id"]) or candidate["id"] in RESERVED_IDS:
        return "name cannot be used as a provider id"
    return None


def apply_import(
    raw: dict[str, Any], source: dict[str, dict[str, Any]], wanted: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for item in wanted:
        name = item["name"]
        entry = source.get(name)
        if entry is None:
            results.append({"name": name, "result": "skipped", "reason": "not in models.yml"})
            continue
        candidate = import_candidate(name, entry)
        blocker = import_blocker(candidate)
        if blocker:
            results.append({"name": name, "result": "skipped", "reason": blocker})
            continue
        models = candidate["models"]
        if item.get("models") is not None:
            unknown = sorted(set(item["models"]) - set(models))
            if unknown or not item["models"]:
                raise ApiError(
                    400, "invalid_request", f"{name}: models must be a non-empty subset of the file's models"
                )
            models = item["models"]
        provider_id = candidate["id"]
        exists = find_provider(raw, provider_id) is not None
        if exists and not item.get("replace"):
            results.append({"name": name, "result": "skipped", "reason": "provider already exists"})
            continue
        upsert_provider(raw, provider_id, candidate["type"], candidate["base_url"], models)
        if item.get("with_key"):
            source_kind = candidate["key_source"]
            if source_kind == "command":
                raise ApiError(400, "invalid_request", f"{name}: the key is a shell command and is not imported")
            if source_kind == "none":
                raise ApiError(400, "invalid_request", f"{name}: models.yml holds no key for this provider")
            value = entry["apiKey"]
            if source_kind == "env":
                set_key(raw, provider_id, None, value)
            else:
                set_key(raw, provider_id, value, None)
        results.append(
            {
                "name": name,
                "id": provider_id,
                "result": "updated" if exists else "created",
                "with_key": bool(item.get("with_key")),
            }
        )
    return results


def build_test_request(provider: Provider, model: str, key: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    base = provider.base_url.rstrip("/")
    prompt = [{"role": "user", "content": TEST_PROMPT}]
    if provider.type == "openai-completions":
        return (
            f"{base}/chat/completions",
            {"authorization": f"Bearer {key}"},
            {"model": model, "messages": prompt, "max_tokens": TEST_MAX_TOKENS},
        )
    if provider.type == "openai-responses":
        return (
            f"{base}/responses",
            {"authorization": f"Bearer {key}"},
            {"model": model, "input": TEST_PROMPT, "max_output_tokens": TEST_MAX_TOKENS},
        )
    url = f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"
    return (
        url,
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        {"model": model, "max_tokens": TEST_MAX_TOKENS, "messages": prompt},
    )


def error_class(status: int) -> str:
    if status in (401, 403):
        return "unauthorized"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "upstream_error"
    return "rejected"


def error_detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        text = response.text
    else:
        error = body.get("error") if isinstance(body, dict) else None
        text = error.get("message") if isinstance(error, dict) else error
        if not isinstance(text, str):
            text = body.get("message") if isinstance(body, dict) else None
        if not isinstance(text, str):
            return None
    return redact(text)[:DETAIL_LIMIT] or None


class ProviderTester:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout_s: float = TEST_TIMEOUT_S) -> None:
        self.transport = transport
        self.timeout_s = timeout_s

    async def run(self, provider: Provider, model: str, key: str | None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "model": model,
            "ok": False,
            "status": None,
            "latency_ms": None,
            "error": None,
            "detail": None,
        }
        if provider.base_url == "from_import":
            result["error"] = "base_url_unresolved"
            return result
        if not key:
            result["error"] = "no_key"
            return result
        url, headers, body = build_test_request(provider, model, key)
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_s,
                follow_redirects=False,
                headers={"user-agent": USER_AGENT},
            ) as client:
                response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            result["latency_ms"] = round((time.perf_counter() - started) * 1000)
            result["error"] = "timeout"
            return result
        except httpx.HTTPError:
            result["latency_ms"] = round((time.perf_counter() - started) * 1000)
            result["error"] = "connect_error"
            return result
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["status"] = response.status_code
        if response.status_code // 100 == 2:
            try:
                response.json()
            except ValueError:
                result["error"] = "invalid_response"
                return result
            result["ok"] = True
            return result
        result["error"] = error_class(response.status_code)
        result["detail"] = error_detail(response)
        return result
