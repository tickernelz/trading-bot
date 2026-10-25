import argparse
import asyncio
import json
import statistics

from tb_swarm.agents import build_voter_agent
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.llm_structured import LlmStructuredProvider
from tb_swarm.stub_server import Behavior, StubServer, StubState

STUB_KEY = "stub-key-not-a-secret"

REQUEST = DecisionRequest(
    state={"pair": "BTC/IDR", "timeframe": "1h", "rsi": 41.2, "ema20": 100_120_000, "ema50": 99_800_000},
    questions={
        "aligned": NoulQuestion(instructions="Does this entry align with the recent news tone?"),
        "action": ChoiceQuestion(
            instructions="Allow, shrink or skip this entry?",
            criteria={"allow": "take the planned size", "shrink": "half size", "skip": "no entry"},
        ),
        "risk": ScoreQuestion(instructions="How large is the event risk?", criteria=["low", "medium", "high"]),
    },
)


async def measure(backend, stub, samples, delay_s):
    options = {
        "api_type": "openai-completions",
        "base_url": stub.base_url + "/v1",
        "api_key": STUB_KEY,
        "model": "voter-model",
        "timeout_s": 30.0,
        "backend": backend,
    }
    if backend == "deepagents":
        options["agent_factory"] = build_voter_agent
    voter = LlmStructuredProvider(**options)
    stub.state.behaviors["voter-model"] = Behavior(delay_s=delay_s)
    await voter.decide(REQUEST)
    latencies, prompts, completions = [], [], []
    before = len(stub.state.requests)
    for _ in range(samples):
        response = await voter.decide(REQUEST)
        latencies.append(response.latency_s)
        prompts.append(response.usage.input_tokens)
        completions.append(response.usage.output_tokens)
    bodies = [len(json.dumps(r.body["messages"])) for r in stub.state.requests[before:]]
    calls = [1] * samples
    return {
        "backend": backend,
        "stub_delay_s": delay_s,
        "samples": samples,
        "latency_ms": {
            "median": round(statistics.median(latencies) * 1000, 1),
            "mean": round(statistics.mean(latencies) * 1000, 1),
            "max": round(max(latencies) * 1000, 1),
        },
        "input_tokens": int(statistics.median(prompts)),
        "output_tokens": int(statistics.median(completions)),
        "prompt_chars": int(statistics.median(bodies)),
        "model_calls_per_decision": int(statistics.median(calls)),
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()
    stub = StubServer(StubState(api_key=STUB_KEY)).start()
    try:
        direct = await measure("direct", stub, args.samples, args.delay)
        wrapped = await measure("deepagents", stub, args.samples, args.delay)
    finally:
        stub.stop()
    overhead = wrapped["latency_ms"]["median"] - direct["latency_ms"]["median"]
    delta_chars = wrapped["prompt_chars"] - direct["prompt_chars"]
    print(
        json.dumps(
            {
                "direct": direct,
                "deepagents": wrapped,
                "framework_overhead_ms_median": round(overhead, 1),
                "prompt_chars_delta": delta_chars,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
