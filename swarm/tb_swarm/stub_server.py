import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Policy = Callable[[str, dict[str, Any]], dict[str, Any]]

DECISION_PATHS = ("/v1/systemone", "/api/alpha/decisions")
CHAT_PATH = "/v1/chat/completions"
RESPONSES_PATH = "/v1/responses"
MESSAGES_PATH = "/v1/messages"


def first_option_policy(name: str, question: dict[str, Any]) -> dict[str, Any]:
    """Position-biased voter: always picks the first option as presented, mimicking order bias."""
    kind = question["type"]
    if kind == "noul":
        return {"type": "noul", "noul": 0.9}
    if kind == "choice":
        options = list(question["criteria"])
        return {"type": "choice", "choice": options[0]}
    return {"type": "score", "score": 0.0}


@dataclass
class Behavior:
    policy: Policy = first_option_policy
    delay_s: float = 0.0
    fail_status: int | None = None
    malformed: str | None = None
    reasoning_tokens: int = 0


@dataclass
class Recorded:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass
class StubState:
    api_key: str = "stub-key"
    default: Behavior = field(default_factory=Behavior)
    behaviors: dict[str, Behavior] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def behavior_for(self, model: str) -> Behavior:
        return self.behaviors.get(model, self.default)


def _llm_questions(body_text: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(body_text)
    questions: dict[str, dict[str, Any]] = {}
    for name, entry in payload["questions"].items():
        question = {"type": entry["type"], "instructions": entry["instructions"]}
        if entry["type"] == "choice":
            question["criteria"] = {item["key"]: item["description"] for item in entry["options"]}
        elif entry["type"] == "score":
            question["criteria"] = [item["description"] for item in entry["levels"]]
        elif "criteria" in entry:
            question["criteria"] = entry["criteria"]
        questions[name] = question
    return questions


def _user_text(path: str, body: dict[str, Any]) -> str:
    if path == CHAT_PATH:
        return next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")
    if path == RESPONSES_PATH:
        entries = body["input"]
        if isinstance(entries, str):
            return entries
        last = next(m for m in reversed(entries) if m.get("role") == "user")
        content = last["content"]
        return content if isinstance(content, str) else "".join(part.get("text", "") for part in content)
    last = next(m for m in reversed(body["messages"]) if m["role"] == "user")
    content = last["content"]
    return content if isinstance(content, str) else "".join(part.get("text", "") for part in content)


class _Handler(BaseHTTPRequestHandler):
    server: "StubServer"

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def _send(self, status: int, payload: Any, raw: bool = False) -> None:
        data = payload.encode() if raw else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        key = self.server.state.api_key
        bearer = self.headers.get("Authorization", "")
        return bearer == f"Bearer {key}" or self.headers.get("x-api-key") == key

    def do_POST(self) -> None:
        state = self.server.state
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        path = self.path.split("?")[0]
        with state.lock:
            state.requests.append(
                Recorded(path=path, headers={k.lower(): v for k, v in self.headers.items()}, body=body)
            )
        if not self._authorized():
            self._send(401, {"error": {"message": "invalid api key"}})
            return
        behavior = state.behavior_for(body.get("model", ""))
        if behavior.delay_s:
            time.sleep(behavior.delay_s)
        if behavior.fail_status is not None:
            self._send(behavior.fail_status, {"error": {"message": f"stub failure {behavior.fail_status}"}})
            return
        if path in DECISION_PATHS:
            self._decision(path, body, behavior)
        elif path in (CHAT_PATH, RESPONSES_PATH, MESSAGES_PATH):
            self._llm(path, body, behavior)
        else:
            self._send(404, {"error": {"message": "not found"}})

    def _decision(self, path: str, body: dict[str, Any], behavior: Behavior) -> None:
        if behavior.malformed is not None:
            self._send(200, behavior.malformed, raw=True)
            return
        answers = {name: behavior.policy(name, question) for name, question in body["questions"].items()}
        for name, answer in answers.items():
            if answer["type"] == "choice":
                options = list(body["questions"][name]["criteria"])
                answer.setdefault("probabilities", {o: 1.0 if o == answer["choice"] else 0.0 for o in options})
                answer.setdefault("confidence", 1.0)
        response: dict[str, Any] = {
            "model": body["model"],
            "answers": answers,
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }
        if path == "/api/alpha/decisions":
            response.update({"id": "gen-dec-stub", "provider": "Stub"})
            response["usage"]["cost"] = 0.00001
        self._send(200, response)

    def _llm(self, path: str, body: dict[str, Any], behavior: Behavior) -> None:
        if behavior.malformed is not None:
            text = behavior.malformed
        else:
            questions = _llm_questions(_user_text(path, body))
            answers = {name: behavior.policy(name, q) for name, q in questions.items()}
            trimmed = {name: {k: v for k, v in a.items() if k != "type"} for name, a in answers.items()}
            text = json.dumps({"answers": trimmed})
        model = body["model"]
        reasoning = behavior.reasoning_tokens
        if path == CHAT_PATH:
            self._send(
                200,
                {
                    "id": "chatcmpl-stub",
                    "object": "chat.completion",
                    "created": 1,
                    "model": model,
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 30 + reasoning,
                        "total_tokens": 150 + reasoning,
                        "completion_tokens_details": {"reasoning_tokens": reasoning},
                    },
                },
            )
        elif path == RESPONSES_PATH:
            self._send(
                200,
                {
                    "id": "resp_stub",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": model,
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_stub",
                            "status": "completed",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": text, "annotations": []}],
                        }
                    ],
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 30 + reasoning,
                        "total_tokens": 150 + reasoning,
                        "output_tokens_details": {"reasoning_tokens": reasoning},
                    },
                },
            )
        else:
            self._send(
                200,
                {
                    "id": "msg_stub",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 120, "output_tokens": 30},
                },
            )


class StubServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: StubState | None = None) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.state = state or StubState()
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> "StubServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)
