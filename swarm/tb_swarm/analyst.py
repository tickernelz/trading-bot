import asyncio
import json
import os
import re
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tb_swarm.agents import DEFAULT_TIMEZONE, build_analyst
from tb_swarm.config import ProviderSpec
from tb_swarm.errors import ConfigError, ProviderError
from tb_swarm.languages import DEFAULT_LANGUAGE, LANGUAGES, language_name
from tb_swarm.models import Usage
from tb_swarm.providers.llm_structured import (
    build_chat_model,
    classify_exception,
    extract_json,
    served_model,
    usage_from_message,
)
from tb_swarm.redact import redact

Language = Literal[*LANGUAGES]

DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_QUESTION_CHARS = 2_000
MAX_HISTORY_TURNS = 20
MAX_TURN_CHARS = 4_000
RECURSION_LIMIT = 40
CONCURRENT_RUNS = 2

REPORT_PROMPT = (
    'Write the daily report for {day} (timezone {timezone}). Call get_metrics with day="{day}" first: it holds '
    "the swarm totals and the list of skipped decisions for that day. Then call get_trade_history and "
    "get_voter_log with "
    'day="{day}" for the rows behind anything you report. Answer with one JSON object and nothing else, shaped as '
    '{{"summary": str, "anomalies": [{{"title": str, "detail": str, "evidence": [str]}}], '
    '"suggestions": [{{"title": str, "detail": str, "evidence": [str]}}]}}. '
    "Every evidence entry is an exact id or value copied from a tool result (a trade_id, a decision_id, a metric "
    "name). Anomalies are things that look wrong or unusual; suggestions are advice the owner may consider and "
    "that you cannot apply. Write the text in {language}. If the tools return no data for the day, say so in the "
    "summary and return empty lists."
)

CHAT_CONTEXT = (
    "Current time: {now} (timezone {timezone}). Answer in {language}. Use the read tools to look at the recorded "
    "data before you answer, and name the rows you relied on.\n\n"
)

REPAIR_PROMPT = (
    "Your last answer could not be used: {problem}. Reply again with only the JSON object in the requested shape."
)


class ToolUse(BaseModel):
    name: str
    args: dict[str, Any]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=2_000)
    evidence: list[str] = Field(default_factory=list, max_length=20)


class ModelReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4_000)
    anomalies: list[Finding] = Field(default_factory=list, max_length=20)
    suggestions: list[Finding] = Field(default_factory=list, max_length=20)


class GroundedFinding(Finding):
    grounded: bool


class DailyReport(BaseModel):
    day: str
    generated_at: str
    model: str
    language: Language
    summary: str
    anomalies: list[GroundedFinding]
    suggestions: list[GroundedFinding]
    tools_used: list[ToolUse]
    usage: Usage
    latency_s: float


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_TURN_CHARS)


class ChatAnswer(BaseModel):
    answer: str
    model: str
    tools_used: list[ToolUse]
    usage: Usage
    latency_s: float


def check_day(day: str) -> str:
    if not DAY_PATTERN.match(day):
        raise ValueError("day must be YYYY-MM-DD")
    date.fromisoformat(day)
    return day


def message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
    )


def _scalars(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(str(key))
            _scalars(item, out)
    elif isinstance(value, list):
        for item in value:
            _scalars(item, out)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, float):
        out.add(repr(value))
        if value.is_integer():
            out.add(str(int(value)))
    else:
        out.add(str(value))


def tool_values(messages: Iterable[BaseMessage]) -> set[str]:
    """Every key and scalar value in the JSON the read tools returned, as the strings evidence must equal."""
    found: set[str] = set()
    for message in messages:
        for line in message_text(message).splitlines():
            try:
                _scalars(json.loads(line), found)
            except ValueError:
                continue
    return found


class Run:
    """What one agent invocation produced: final text, tool trace, tool output and usage."""

    def __init__(self, messages: Sequence[BaseMessage], fallback_model: str, started: float) -> None:
        self.messages = list(messages)
        assistants = [m for m in self.messages if isinstance(m, AIMessage)]
        self.final = message_text(assistants[-1]) if assistants else ""
        self.model = served_model(assistants[-1], fallback_model) if assistants else fallback_model
        self.tools_used = [
            ToolUse(name=call["name"], args=call.get("args") or {}) for m in assistants for call in m.tool_calls
        ]
        self.values = tool_values(m for m in self.messages if isinstance(m, ToolMessage) and m.status != "error")
        total = Usage()
        for message in assistants:
            used = usage_from_message(message)
            total = Usage(
                input_tokens=total.input_tokens + used.input_tokens,
                output_tokens=total.output_tokens + used.output_tokens,
                reasoning_tokens=total.reasoning_tokens + used.reasoning_tokens,
            )
        self.usage = total
        self.latency_s = round(time.monotonic() - started, 3)


class AnalystRunner:
    def __init__(
        self,
        agent: Any,
        *,
        model_id: str,
        timezone: str = DEFAULT_TIMEZONE,
        language: Language = DEFAULT_LANGUAGE,
        secrets: Sequence[str] = (),
        timeout_s: float = 300.0,
    ) -> None:
        self._agent = agent
        self._model_id = model_id
        self._zone = ZoneInfo(timezone)
        self._timezone = timezone
        self._language = language
        self._language_name = language_name(language)
        self._secrets = tuple(secrets)
        self._timeout_s = timeout_s
        self._slots = asyncio.Semaphore(CONCURRENT_RUNS)

    async def _invoke(self, messages: Sequence[BaseMessage], deadline: float) -> Run:
        started = time.monotonic()

        async def run() -> Any:
            async with self._slots:
                return await self._agent.ainvoke(
                    {"messages": list(messages)}, config={"recursion_limit": RECURSION_LIMIT}
                )

        try:
            result = await asyncio.wait_for(run(), timeout=max(0.0, deadline - started))
        except Exception as exc:
            raise classify_exception(exc, self._secrets) from None
        return Run(result["messages"], self._model_id, started)

    def _deadline(self, timeout_s: float | None) -> float:
        return time.monotonic() + (timeout_s or self._timeout_s)

    async def daily_report(self, day: str, timeout_s: float | None = None) -> DailyReport:
        check_day(day)
        prompt = REPORT_PROMPT.format(day=day, timezone=self._timezone, language=self._language_name)
        deadline = self._deadline(timeout_s)
        run = await self._invoke([HumanMessage(prompt)], deadline)
        parsed, problem = _parse_report(run.final)
        if parsed is None:
            retry = await self._invoke([*run.messages, HumanMessage(REPAIR_PROMPT.format(problem=problem))], deadline)
            retry.latency_s = round(retry.latency_s + run.latency_s, 3)
            run = retry
            parsed, problem = _parse_report(run.final)
            if parsed is None:
                raise ProviderError("invalid", redact(f"analyst report unusable: {problem}", self._secrets))
        values = run.values
        return DailyReport(
            day=day,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            model=run.model,
            language=self._language,
            summary=redact(parsed.summary, self._secrets),
            anomalies=[_ground(item, values, self._secrets) for item in parsed.anomalies],
            suggestions=[_ground(item, values, self._secrets) for item in parsed.suggestions],
            tools_used=run.tools_used,
            usage=run.usage,
            latency_s=run.latency_s,
        )

    async def ask(self, question: str, history: Sequence[ChatTurn] = (), timeout_s: float | None = None) -> ChatAnswer:
        text = question.strip()
        if not text:
            raise ValueError("question is empty")
        if len(text) > MAX_QUESTION_CHARS:
            raise ValueError(f"question is longer than {MAX_QUESTION_CHARS} characters")
        if len(history) > MAX_HISTORY_TURNS:
            raise ValueError(f"history is longer than {MAX_HISTORY_TURNS} turns")
        context = CHAT_CONTEXT.format(
            now=datetime.now(self._zone).isoformat(timespec="minutes"),
            timezone=self._timezone,
            language=self._language_name,
        )
        messages: list[BaseMessage] = [
            HumanMessage(turn.content) if turn.role == "user" else AIMessage(turn.content) for turn in history
        ]
        messages.append(HumanMessage(context + text))
        run = await self._invoke(messages, self._deadline(timeout_s))
        answer = redact(run.final.strip(), self._secrets)
        if not answer:
            raise ProviderError("invalid", "analyst returned an empty answer")
        return ChatAnswer(
            answer=answer, model=run.model, tools_used=run.tools_used, usage=run.usage, latency_s=run.latency_s
        )


def _parse_report(text: str) -> tuple[ModelReport | None, str]:
    try:
        return ModelReport.model_validate(extract_json(text)), ""
    except ProviderError as exc:
        return None, str(exc)
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_url=False, include_context=False)[0]
        return None, f"{'.'.join(str(part) for part in first['loc'])}: {first['msg']}"


def _ground(finding: Finding, values: set[str], secrets: Sequence[str]) -> GroundedFinding:
    evidence = [redact(item, secrets) for item in finding.evidence]
    grounded = bool(finding.evidence) and all(item in values for item in finding.evidence)
    return GroundedFinding(
        title=redact(finding.title, secrets),
        detail=redact(finding.detail, secrets),
        evidence=evidence,
        grounded=grounded,
    )


class ReportStore:
    """One JSON file per reporting day; a newer report for the same day replaces the older one."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._dir = Path(directory)

    def _path(self, day: str) -> Path:
        return self._dir / f"{check_day(day)}.json"

    def save(self, report: DailyReport) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._path(report.day)
        handle, name = tempfile.mkstemp(dir=self._dir, prefix=".report-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(report.model_dump_json(indent=2))
            os.replace(name, target)
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise

    def load(self, day: str) -> DailyReport | None:
        path = self._path(day)
        if not path.is_file():
            return None
        return DailyReport.model_validate_json(path.read_text(encoding="utf-8"))

    def days(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted((p.stem for p in self._dir.glob("*.json") if DAY_PATTERN.match(p.stem)), reverse=True)


def analyst_provider(raw: Mapping[str, Any], env: Mapping[str, str]) -> tuple[ProviderSpec, str, str, str]:
    """Resolve llm.analyst_model ("provider:model") against the providers list into (spec, model, url, key)."""
    reference = ((raw.get("llm") or {}).get("analyst_model")) or ""
    provider_id, separator, model = str(reference).partition(":")
    if not separator or not provider_id or not model:
        raise ConfigError("llm.analyst_model must look like provider:model")
    entries = [item for item in raw.get("providers") or [] if isinstance(item, dict) and item.get("id") == provider_id]
    if not entries:
        raise ConfigError(f"llm.analyst_model references unknown provider {provider_id!r}")
    try:
        spec = ProviderSpec.model_validate(entries[0])
    except ValidationError as exc:
        raise ConfigError(f"provider {provider_id!r} is invalid: {len(exc.errors())} problem(s)") from None
    if spec.models and model not in spec.models:
        raise ConfigError(f"model {model!r} is not listed for provider {provider_id!r}")
    base_url = spec.resolve_base_url(env)
    if base_url is None:
        raise ConfigError(f"provider {provider_id!r} has no resolvable base_url")
    api_key = spec.resolve_api_key(env)
    if not api_key:
        raise ConfigError(f"provider {provider_id!r} has no API key; set {spec.api_key_env or 'api_key'}")
    return spec, model, base_url, api_key


def build_runner(
    raw: Mapping[str, Any],
    env: Mapping[str, str],
    data_dir: str | os.PathLike[str],
    *,
    language: Language = DEFAULT_LANGUAGE,
    timeout_s: float = 300.0,
    model: BaseChatModel | None = None,
) -> AnalystRunner:
    """Build the analyst from a parsed config.yaml; pass model to replace the chat model (tests)."""
    timezone = ((raw.get("risk") or {}).get("daily_reset_timezone")) or DEFAULT_TIMEZONE
    spec, model_id, base_url, api_key = analyst_provider(raw, env)
    chat = model or build_chat_model(
        spec.type, model=model_id, base_url=base_url, api_key=api_key, timeout_s=min(timeout_s, 120.0)
    )
    return AnalystRunner(
        build_analyst(chat, data_dir, timezone),
        model_id=model_id,
        timezone=timezone,
        language=language,
        secrets=(api_key,),
        timeout_s=timeout_s,
    )
