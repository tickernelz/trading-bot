import json
import re
import time
from collections.abc import Callable
from typing import Any, Literal

import anthropic
import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tb_swarm.errors import ConfigError, ProviderError
from tb_swarm.llm_prompt import SYSTEM_PROMPT
from tb_swarm.models import ChoiceQuestion, DecisionRequest, DecisionResponse, NoulQuestion, Usage
from tb_swarm.providers.base import DecisionProvider
from tb_swarm.providers.http_wire import classify_status
from tb_swarm.redact import redact
from tb_swarm.validate import parse_answers

ApiType = Literal["openai-completions", "openai-responses", "anthropic-messages"]
StructuredMode = Literal["prompt", "json_object", "json_schema"]
Backend = Literal["direct", "deepagents"]

API_TYPES: tuple[str, ...] = ("openai-completions", "openai-responses", "anthropic-messages")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def build_user_message(request: DecisionRequest) -> str:
    questions: dict[str, Any] = {}
    for name, question in request.questions.items():
        if isinstance(question, NoulQuestion):
            entry: dict[str, Any] = {"type": "noul", "instructions": question.instructions}
            if question.criteria:
                entry["criteria"] = dict(question.criteria)
        elif isinstance(question, ChoiceQuestion):
            entry = {
                "type": "choice",
                "instructions": question.instructions,
                "options": [{"key": key, "description": text} for key, text in question.criteria.items()],
            }
        else:
            entry = {
                "type": "score",
                "instructions": question.instructions,
                "levels": [{"level": index, "description": text} for index, text in enumerate(question.criteria)],
            }
        questions[name] = entry
    return json.dumps({"state": request.state, "questions": questions}, ensure_ascii=False)


def response_schema(request: DecisionRequest) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name, question in request.questions.items():
        if isinstance(question, NoulQuestion):
            properties[name] = {
                "type": "object",
                "properties": {"noul": {"type": "number", "minimum": 0, "maximum": 1}},
                "required": ["noul"],
                "additionalProperties": False,
            }
        elif isinstance(question, ChoiceQuestion):
            properties[name] = {
                "type": "object",
                "properties": {"choice": {"type": "string", "enum": list(question.criteria)}},
                "required": ["choice"],
                "additionalProperties": False,
            }
        else:
            properties[name] = {
                "type": "object",
                "properties": {"score": {"type": "number", "minimum": 0, "maximum": len(question.criteria) - 1}},
                "required": ["score"],
                "additionalProperties": False,
            }
    answers = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"answers": answers},
        "required": ["answers"],
        "additionalProperties": False,
    }


def extract_json(text: str) -> Any:
    stripped = _FENCE.sub("", text.strip()).strip()
    if not stripped:
        raise ProviderError("invalid", "empty model output")
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("invalid", "no JSON object in model output")
    try:
        return json.loads(stripped[start : end + 1])
    except ValueError as exc:
        raise ProviderError("invalid", "model output is not valid JSON") from exc


def classify_exception(exc: BaseException, secrets: tuple[str, ...] = ()) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, (TimeoutError, openai.APITimeoutError, anthropic.APITimeoutError)):
        return ProviderError("timeout", f"request timed out: {redact(repr(exc), secrets)}")
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return classify_status(status, str(getattr(exc, "message", exc)), secrets)
    if isinstance(exc, (openai.APIConnectionError, anthropic.APIConnectionError)):
        return ProviderError("network", f"transport error: {redact(repr(exc), secrets)}")
    return ProviderError("internal", redact(f"unexpected {type(exc).__name__}: {exc}", secrets))


def build_chat_model(
    api_type: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout_s: float,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    extra_body: dict[str, Any] | None = None,
) -> BaseChatModel:
    if api_type in ("openai-completions", "openai-responses"):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "timeout": timeout_s,
            "max_retries": 0,
            "use_responses_api": api_type == "openai-responses",
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            kwargs["max_completion_tokens"] = max_output_tokens
        if extra_body:
            kwargs["extra_body"] = extra_body
        return ChatOpenAI(**kwargs)
    if api_type == "anthropic-messages":
        from langchain_anthropic import ChatAnthropic

        kwargs = {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "timeout": timeout_s,
            "max_retries": 0,
            "max_tokens": max_output_tokens or 4096,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if extra_body:
            kwargs["extra_body"] = extra_body
        return ChatAnthropic(**kwargs)
    raise ConfigError(f"unknown api type {api_type!r}")


def usage_from_message(message: AIMessage) -> Usage:
    meta = message.usage_metadata or {}
    details = meta.get("output_token_details") or {}
    return Usage(
        input_tokens=int(meta.get("input_tokens") or 0),
        output_tokens=int(meta.get("output_tokens") or 0),
        reasoning_tokens=int(details.get("reasoning") or 0),
    )


def served_model(message: AIMessage, fallback: str) -> str:
    meta = message.response_metadata or {}
    value = meta.get("model_name") or meta.get("model")
    return value if isinstance(value, str) and value else fallback


class LlmStructuredProvider(DecisionProvider):
    """Asks a chat model for JSON answers and validates them; invalid output is a failed voter, never a guess."""

    def __init__(
        self,
        *,
        api_type: ApiType,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_s: float,
        temperature: float | None = None,
        structured_mode: StructuredMode = "prompt",
        backend: Backend = "direct",
        max_output_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
        agent_factory: Callable[[BaseChatModel], Any] | None = None,
    ) -> None:
        if api_type not in API_TYPES:
            raise ConfigError(f"unknown api type {api_type!r}")
        if structured_mode != "prompt" and api_type != "openai-completions":
            raise ConfigError(f"structured_mode {structured_mode!r} is only supported for openai-completions")
        if backend == "deepagents" and agent_factory is None:
            raise ConfigError("backend 'deepagents' needs an agent_factory")
        if backend == "deepagents" and structured_mode != "prompt":
            raise ConfigError(f"structured_mode {structured_mode!r} is not supported by the deepagents backend")
        self._api_type = api_type
        self._base_url = base_url
        self._api_key = api_key
        self._model_name = model
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._structured_mode = structured_mode
        self._backend = backend
        self._max_output_tokens = max_output_tokens
        self._extra_body = extra_body
        self._agent_factory = agent_factory
        self._chat: BaseChatModel | None = None
        self._agent: Any = None

    def secrets(self) -> tuple[str, ...]:
        return (self._api_key,) if self._api_key else ()

    def _model(self) -> BaseChatModel:
        if self._chat is None:
            if not self._api_key:
                raise ProviderError("auth", "no API key configured")
            self._chat = build_chat_model(
                self._api_type,
                model=self._model_name,
                base_url=self._base_url,
                api_key=self._api_key,
                timeout_s=self._timeout_s,
                temperature=self._temperature,
                max_output_tokens=self._max_output_tokens,
                extra_body=self._extra_body,
            )
        return self._chat

    def _bound(self, request: DecisionRequest) -> Any:
        chat = self._model()
        if self._structured_mode == "json_object":
            return chat.bind(response_format={"type": "json_object"})
        if self._structured_mode == "json_schema":
            schema = {"name": "decision_answers", "schema": response_schema(request), "strict": True}
            return chat.bind(response_format={"type": "json_schema", "json_schema": schema})
        return chat

    async def _invoke(self, request: DecisionRequest) -> tuple[str, Usage, str]:
        if self._backend == "deepagents":
            if self._agent is None:
                self._agent = self._agent_factory(self._model())
            result = await self._agent.ainvoke({"messages": [HumanMessage(content=build_user_message(request))]})
            ai = [m for m in result["messages"] if isinstance(m, AIMessage)]
            if not ai:
                raise ProviderError("invalid", "agent returned no assistant message")
            total = Usage()
            for item in ai:
                part = usage_from_message(item)
                total = Usage(
                    input_tokens=total.input_tokens + part.input_tokens,
                    output_tokens=total.output_tokens + part.output_tokens,
                    reasoning_tokens=total.reasoning_tokens + part.reasoning_tokens,
                )
            return ai[-1].text, total, served_model(ai[-1], self._model_name)
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=build_user_message(request))]
        message = await self._bound(request).ainvoke(messages)
        return message.text, usage_from_message(message), served_model(message, self._model_name)

    async def decide(self, request: DecisionRequest) -> DecisionResponse:
        started = time.perf_counter()
        try:
            text, usage, served = await self._invoke(request)
        except ProviderError:
            raise
        except Exception as exc:
            raise classify_exception(exc, self.secrets()) from exc
        latency = time.perf_counter() - started
        payload = extract_json(text)
        if not isinstance(payload, dict):
            raise ProviderError("invalid", "model output is not a JSON object")
        answers = parse_answers(request, payload.get("answers"))
        return DecisionResponse(model=served, answers=answers, usage=usage, latency_s=latency)
