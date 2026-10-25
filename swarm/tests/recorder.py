from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class RecorderModel(BaseChatModel):
    """Scripted chat model that records the tool names and system prompt of every model call."""

    script: list[AIMessage] = []
    calls: list[dict[str, Any]] = []
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "recorder"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        names = sorted(t["name"] if isinstance(t, dict) else t.name for t in tools)
        return self.bind(_tool_names=names)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        system = str(messages[0].content) if messages and messages[0].type == "system" else ""
        self.calls.append({"tools": kwargs.get("_tool_names"), "system": system})
        if self.cursor < len(self.script):
            message = self.script[self.cursor]
            self.cursor += 1
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
