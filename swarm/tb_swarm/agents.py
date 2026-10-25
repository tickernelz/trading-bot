import json
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool

from tb_swarm.llm_prompt import SYSTEM_PROMPT

METRICS_FILE = "metrics.json"
TRADES_FILE = "trades.jsonl"
VOTER_LOG_FILE = "voter_decisions.jsonl"

MAX_TOOL_CHARS = 20_000
MAX_ROWS = 200

ANALYST_PROMPT = (
    "You are the read-only analyst of a trading bot. You review metrics, trade history and voter decisions and "
    "explain what happened. You cannot place orders, change configuration or read secrets: you only have the read "
    "tools you were given. Cite the rows you rely on and say plainly when the data does not answer the question."
)

ANALYST_TOOL_NAMES = frozenset({"get_metrics", "get_trade_history", "get_voter_log"})


class ToolAllowlist(AgentMiddleware):
    """Keeps every tool outside the allowlist away from the model and rejects any call to one."""

    def __init__(self, allowed: Iterable[str]) -> None:
        super().__init__()
        self._allowed = frozenset(allowed)

    @staticmethod
    def _name(item: Any) -> str | None:
        return item.get("name") if isinstance(item, dict) else getattr(item, "name", None)

    def _filtered(self, request: Any) -> Any:
        return request.override(tools=[item for item in request.tools if self._name(item) in self._allowed])

    def _refusal(self, request: Any) -> ToolMessage:
        call = request.tool_call
        return ToolMessage(
            content=f"tool {call['name']!r} is not permitted",
            tool_call_id=call["id"],
            name=call["name"],
            status="error",
        )

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(self._filtered(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(self._filtered(request))

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        if request.tool_call["name"] not in self._allowed:
            return self._refusal(request)
        return handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        if request.tool_call["name"] not in self._allowed:
            return self._refusal(request)
        return await handler(request)


def _clip(text: str) -> str:
    if len(text) <= MAX_TOOL_CHARS:
        return text
    return text[:MAX_TOOL_CHARS] + f"\n[truncated at {MAX_TOOL_CHARS} characters]"


def _tail(path: Path, limit: int, keep: Callable[[dict[str, Any]], bool] | None = None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=max(1, min(limit, MAX_ROWS)))
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if keep is None or keep(row):
                rows.append(row)
    return list(rows)


def read_only_tools(data_dir: str | Path) -> list[BaseTool]:
    """The analyst's only tools: fixed files inside data_dir, no path argument, nothing writable."""
    root = Path(data_dir).resolve()

    @tool
    def get_metrics(name: str = "") -> str:
        """Return the bot metrics as JSON; pass a metric name to return only that entry."""
        path = root / METRICS_FILE
        if not path.is_file():
            return "no metrics recorded"
        data = json.loads(path.read_text(encoding="utf-8"))
        if name:
            if not isinstance(data, dict) or name not in data:
                return f"no metric named {name!r}"
            data = {name: data[name]}
        return _clip(json.dumps(data, ensure_ascii=False))

    @tool
    def get_trade_history(limit: int = 50) -> str:
        """Return the most recent trades as JSON lines, newest last; limit is capped at 200."""
        rows = _tail(root / TRADES_FILE, limit)
        return _clip("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)) or "no trades recorded"

    @tool
    def get_voter_log(limit: int = 20, decision_id: str = "") -> str:
        """Return recent swarm decisions with every voter's status and answers; filter by decision_id."""
        rows = _tail(
            root / VOTER_LOG_FILE, limit, (lambda row: row.get("decision_id") == decision_id) if decision_id else None
        )
        return _clip("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)) or "no voter decisions recorded"

    return [get_metrics, get_trade_history, get_voter_log]


def build_analyst(model: BaseChatModel | str, data_dir: str | Path) -> Any:
    return create_deep_agent(
        model=model,
        tools=read_only_tools(data_dir),
        system_prompt=ANALYST_PROMPT,
        middleware=[ToolAllowlist(ANALYST_TOOL_NAMES)],
    )


def build_voter_agent(model: BaseChatModel | str) -> Any:
    return create_deep_agent(model=model, tools=[], system_prompt=SYSTEM_PROMPT, middleware=[ToolAllowlist(())])
