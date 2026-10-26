from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedModel(BaseChatModel):
    """Chat model that replays a fixed script and records the tool names offered on every call."""

    script: list[AIMessage] = []
    offered: list[Any] = []
    cursor: int = 0
    failure: str | None = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        names = sorted(t["name"] if isinstance(t, dict) else t.name for t in tools)
        return self.bind(_tool_names=names)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if self.failure is not None:
            raise RuntimeError(self.failure)
        self.offered.append(kwargs.get("_tool_names"))
        message = self.script[self.cursor] if self.cursor < len(self.script) else AIMessage(content="done")
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
