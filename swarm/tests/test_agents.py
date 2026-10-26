import json

import pytest
from deepagents import SubAgent, create_deep_agent
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from tb_swarm.agents import (
    ANALYST_TOOL_NAMES,
    MAX_ROWS,
    build_analyst,
    build_voter_agent,
    read_only_tools,
)
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.llm_structured import LlmStructuredProvider
from tests.conftest import STUB_KEY
from tests.recorder import RecorderModel, tool_call

SAFETY = "SAFETY: never place orders."


@tool
def place_order(symbol: str) -> str:
    """Place an order."""
    return "ORDER PLACED"


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"win_rate": 0.41, "drawdown_pct": 2.5}))
    (tmp_path / "trades.jsonl").write_text("\n".join(json.dumps({"id": i, "pnl": i}) for i in range(300)) + "\n")
    voter_rows = [{"decision_id": f"d{i}", "status": "ok" if i % 2 else "skip"} for i in range(10)]
    (tmp_path / "voter_decisions.jsonl").write_text("\n".join(json.dumps(r) for r in voter_rows) + "\n")
    (tmp_path / "config.yaml").write_text("api_key: SECRET-VALUE")
    (tmp_path / ".env").write_text("NUTARALINE_API_KEY=SECRET-VALUE")
    return tmp_path


def tools_by_name(data_dir):
    return {t.name: t for t in read_only_tools(data_dir)}


def test_analyst_exposes_exactly_the_read_tools(data_dir):
    assert set(tools_by_name(data_dir)) == ANALYST_TOOL_NAMES


def test_tools_take_no_path_argument(data_dir):
    for item in tools_by_name(data_dir).values():
        assert set(item.args) <= {"name", "limit", "decision_id", "day", "pair"}


def test_metrics_tool(data_dir):
    tools = tools_by_name(data_dir)
    assert json.loads(tools["get_metrics"].invoke({})) == {"win_rate": 0.41, "drawdown_pct": 2.5}
    assert json.loads(tools["get_metrics"].invoke({"name": "win_rate"})) == {"win_rate": 0.41}
    assert "no metric named" in tools["get_metrics"].invoke({"name": "nope"})


def test_trade_history_is_newest_last_and_capped(data_dir):
    note, *rows = tools_by_name(data_dir)["get_trade_history"].invoke({"limit": 5}).splitlines()
    assert [json.loads(r)["id"] for r in rows] == [295, 296, 297, 298, 299]
    assert "newest 5 of 300" in note
    note, *capped = tools_by_name(data_dir)["get_trade_history"].invoke({"limit": 10_000}).splitlines()
    assert len(capped) == MAX_ROWS and f"newest {MAX_ROWS} of 300" in note
    assert "[showing" not in tools_by_name(data_dir)["get_trade_history"].invoke({"limit": 500, "day": "2020-01-01"})


def test_voter_log_filters_by_decision(data_dir):
    rows = tools_by_name(data_dir)["get_voter_log"].invoke({"decision_id": "d3"}).splitlines()
    assert [json.loads(r)["decision_id"] for r in rows] == ["d3"]


def test_missing_files_are_reported_not_raised(tmp_path):
    tools = tools_by_name(tmp_path)
    assert tools["get_metrics"].invoke({}) == "no metrics recorded"
    assert tools["get_trade_history"].invoke({}) == "no trades recorded"
    assert tools["get_voter_log"].invoke({}) == "no voter decisions recorded"


def test_tools_never_reach_config_or_env_files(data_dir):
    outputs = [t.invoke({}) for t in tools_by_name(data_dir).values()]
    assert not any("SECRET-VALUE" in out for out in outputs)


def test_analyst_model_is_offered_only_the_read_tools(data_dir):
    model = RecorderModel(script=[], calls=[])
    build_analyst(model, data_dir).invoke({"messages": [("user", "summarize")]})
    assert {tuple(call["tools"]) for call in model.calls} == {tuple(sorted(ANALYST_TOOL_NAMES))}


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("write_file", {"file_path": "/pwn.txt", "content": "x"}),
        ("edit_file", {"file_path": "/a", "old_string": "a", "new_string": "b"}),
        ("delete", {"file_path": "/a"}),
        ("execute", {"command": "id"}),
        ("task", {"description": "do anything", "subagent_type": "general-purpose"}),
        ("place_order", {"symbol": "BTC/IDR"}),
    ],
)
def test_analyst_refuses_forbidden_tool_calls(data_dir, name, args):
    before = {p.name: p.read_bytes() for p in data_dir.iterdir()}
    model = RecorderModel(script=[tool_call(name, args, "c1")], calls=[])
    result = build_analyst(model, data_dir).invoke({"messages": [("user", "go")]})
    refusals = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(refusals) == 1 and refusals[0].status == "error" and "not permitted" in refusals[0].content
    assert not result.get("files")
    assert {p.name: p.read_bytes() for p in data_dir.iterdir()} == before
    assert len(model.calls) == 2


def test_analyst_can_use_an_allowed_tool(data_dir):
    model = RecorderModel(script=[tool_call("get_metrics", {}, "c1")], calls=[])
    result = build_analyst(model, data_dir).invoke({"messages": [("user", "go")]})
    outputs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert outputs[0].status != "error" and "win_rate" in outputs[0].content


async def test_analyst_async_path_enforces_the_same_boundary(data_dir):
    model = RecorderModel(script=[tool_call("write_file", {"file_path": "/x", "content": "y"}, "c1")], calls=[])
    result = await build_analyst(model, data_dir).ainvoke({"messages": [("user", "go")]})
    refusals = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert refusals[0].status == "error"
    assert {tuple(call["tools"]) for call in model.calls} == {tuple(sorted(ANALYST_TOOL_NAMES))}


def run_subagent(subagents, kind):
    model = RecorderModel(script=[tool_call("task", {"description": "go", "subagent_type": kind}, "t1")], calls=[])
    agent = create_deep_agent(model=model, tools=[place_order], system_prompt=SAFETY, subagents=subagents)
    agent.invoke({"messages": [("user", "go")]})
    return model.calls


def test_zha3610_default_subagent_inherits_parent_tools_and_loses_safety_prompt():
    calls = run_subagent(None, "general-purpose")
    parent, child = calls[0], calls[1]
    assert "place_order" in parent["tools"] and SAFETY in parent["system"]
    assert "place_order" in child["tools"]
    assert "never place orders" not in child["system"]


def test_zha3610_subagent_without_tools_key_inherits_parent_tools():
    spec = SubAgent(name="helper", description="helps", system_prompt="You help.")
    child = run_subagent([spec], "helper")[1]
    assert "place_order" in child["tools"]


def test_zha3610_explicit_empty_tools_stops_the_inheritance():
    spec = SubAgent(name="helper", description="helps", system_prompt=f"You help. {SAFETY}", tools=[])
    child = run_subagent([spec], "helper")[1]
    assert "place_order" not in child["tools"]


def test_voter_agent_has_no_tools(tmp_path):
    model = RecorderModel(script=[], calls=[])
    build_voter_agent(model).invoke({"messages": [("user", "vote")]})
    assert all(not call["tools"] for call in model.calls)


async def test_deepagents_backend_matches_direct_backend(stub):
    request = DecisionRequest(
        state="BTC/IDR 1h",
        questions={
            "aligned": NoulQuestion(instructions="Aligned?"),
            "action": ChoiceQuestion(instructions="Allow?", criteria={"allow": "y", "skip": "n"}),
            "risk": ScoreQuestion(instructions="Risk?", criteria=["low", "mid", "high"]),
        },
    )
    common = {
        "api_type": "openai-completions",
        "base_url": stub.base_url + "/v1",
        "api_key": STUB_KEY,
        "model": "voter-model",
        "timeout_s": 10.0,
    }
    direct = await LlmStructuredProvider(**common).decide(request)
    agent_voter = LlmStructuredProvider(**common, backend="deepagents", agent_factory=build_voter_agent)
    wrapped = await agent_voter.decide(request)
    assert direct.answers == wrapped.answers
    sent = stub.state.requests[-1].body
    assert not sent.get("tools")
    assert wrapped.usage.input_tokens > 0
