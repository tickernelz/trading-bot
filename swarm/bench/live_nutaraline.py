import argparse
import asyncio
import json
import os
import statistics
import sys
from pathlib import Path

from tb_swarm.agents import build_voter_agent
from tb_swarm.errors import ProviderError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.llm_structured import LlmStructuredProvider
from tb_swarm.redact import redact

MODEL = "deepseek-v4.1-flash-1017"

CASES = [
    ("rsi-cool-uptrend", "BTC/IDR 1h. Close 1.002e9, EMA20 1.000e9, EMA50 9.9e8, RSI 41."),
    ("rsi-hot-uptrend", "BTC/IDR 1h. Close 1.01e9, EMA20 9.9e8, EMA50 9.7e8, RSI 79."),
    ("breakdown", "BTC/IDR 1h. Close 9.4e8, EMA20 9.8e8, EMA50 9.9e8, RSI 28, volume 3x average."),
    ("flat-range", "BTC/IDR 1h. Close 1.0e9, EMA20 1.0002e9, EMA50 1.0001e9, RSI 50."),
    ("news-shock", "BTC/IDR 1h. Exchange halted withdrawals 20 minutes ago; spread 4x normal."),
    ("thin-book", "ETH/IDR 1h. Order book depth 0.1x the 7-day average, spread 0.9%."),
    ("unlock-rumor", "SOL/IDR 1h. Unconfirmed social rumor of a large token unlock next week."),
    ("gap-open", "ETH/IDR 1h. Price gapped 6% above yesterday's close with no news."),
    ("funding-crowded", "BTC/IDR 1h. Perp funding 0.15% per 8h, open interest at 90-day high."),
    ("series-of-red", "SOL/IDR 1h. Seven consecutive red candles, each smaller than the last."),
    ("volume-dry", "BTC/IDR 1h. Volume 0.2x average for 12 hours, price flat."),
    ("weekend", "ETH/IDR 1h. Saturday, volume 0.4x weekday average."),
    ("listing-news", "SOL/IDR 1h. A large exchange announced a new SOL pair 1 hour ago."),
    ("macro-day", "BTC/IDR 1h. US CPI release in 2 hours."),
    ("whale-transfer", "ETH/IDR 1h. 40k ETH moved to an exchange wallet in the last hour."),
    ("stablecoin-peg", "BTC/IDR 1h. The main IDR stablecoin trades at 0.97."),
    ("api-outage", "BTC/IDR 1h. The exchange API returned errors for 5 minutes."),
    ("double-top", "ETH/IDR 4h. Two failed attempts at 5.2e7 with falling volume."),
    ("funding-flip", "BTC/IDR 1h. Funding flipped from +0.05% to -0.03% while price held."),
    ("week-open", "SOL/IDR 1h. Monday open with a 2% gap down and normal volume."),
]

QUESTIONS = {
    "direction": ChoiceQuestion(
        instructions="Which way is the entry most likely to resolve over the next hour?",
        criteria={"long": "price rises", "flat": "stays inside 0.5%", "short": "price falls"},
    ),
    "entry_reason": NoulQuestion(instructions="Is there a reason to take an entry at all right now?"),
    "risk": ScoreQuestion(instructions="How large is the event risk?", criteria=["low", "medium", "high"]),
}


def build_voter(arguments, key, mode, backend):
    options = {
        "api_type": "openai-completions",
        "base_url": arguments.base_url,
        "api_key": key,
        "model": MODEL,
        "timeout_s": arguments.timeout,
        "structured_mode": mode,
        "backend": backend,
        "extra_body": json.loads(arguments.extra_body) if arguments.extra_body else None,
    }
    if backend == "deepagents":
        options["agent_factory"] = build_voter_agent
    return LlmStructuredProvider(**options)


def percentile(values, share):
    ordered = sorted(values)
    return ordered[int(share * (len(ordered) - 1))]


async def run_cell(arguments, key, mode, backend):
    voter = build_voter(arguments, key, mode, backend)
    warmup_error = None
    try:
        await voter.decide(DecisionRequest(state=CASES[0][1], questions=QUESTIONS))
    except ProviderError as exc:
        warmup_error = redact(f"{exc.kind}: {exc}", voter.secrets())[:200]
    rows = []
    for name, state in CASES:
        row = {"case": name, "mode": mode, "backend": backend}
        try:
            response = await voter.decide(DecisionRequest(state=state, questions=QUESTIONS))
        except ProviderError as exc:
            row.update(
                {
                    "valid": False,
                    "error_kind": exc.kind,
                    "error": redact(str(exc), voter.secrets())[:200],
                }
            )
        else:
            row.update(
                {
                    "valid": True,
                    "latency_s": round(response.latency_s, 3),
                    "model": response.model,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "reasoning_tokens": response.usage.reasoning_tokens,
                    "answers": {k: v.model_dump(exclude_none=True) for k, v in response.answers.items()},
                }
            )
        rows.append(row)
    await voter.aclose()
    valid = [r for r in rows if r["valid"]]
    latencies = [r["latency_s"] for r in valid]
    return {
        "mode": mode,
        "backend": backend,
        "cases": len(rows),
        "valid": len(valid),
        "valid_rate": round(len(valid) / len(rows), 3),
        "warmup_error": warmup_error,
        "error_kinds": sorted({r.get("error_kind") for r in rows if not r["valid"]}),
        "latency_s": {
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p90": round(percentile(latencies, 0.9), 3) if latencies else None,
        },
        "input_tokens_median": int(statistics.median([r["input_tokens"] for r in valid])) if valid else None,
        "output_tokens_median": int(statistics.median([r["output_tokens"] for r in valid])) if valid else None,
        "reasoning_tokens": {
            "median": int(statistics.median([r["reasoning_tokens"] for r in valid])) if valid else None,
            "total": sum(r["reasoning_tokens"] for r in valid),
        },
        "served_models": sorted({r["model"] for r in valid}),
        "rows": rows,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("NUTARALINE_BASE_URL"))
    parser.add_argument("--key-env", default="NUTARALINE_API_KEY")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--extra-body", default=os.environ.get("NUTARALINE_EXTRA_BODY"))
    parser.add_argument("--modes", default="prompt,json_object,json_schema")
    parser.add_argument("--backends", default="direct,deepagents")
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()

    key = os.environ.get(arguments.key_env)
    if not key:
        print(json.dumps({"status": "not_run", "reason": f"{arguments.key_env} is not set"}, indent=2))
        return 3
    if not arguments.base_url:
        print(json.dumps({"status": "not_run", "reason": "pass --base-url or set NUTARALINE_BASE_URL"}, indent=2))
        return 4
    modes = [m.strip() for m in arguments.modes.split(",") if m.strip()]
    backends = [b.strip() for b in arguments.backends.split(",") if b.strip()]
    report = {"status": "ran", "base_url": arguments.base_url, "model": MODEL, "cases": len(CASES), "results": []}
    for backend in backends:
        for mode in modes if backend == "direct" else ["prompt"]:
            report["results"].append(await run_cell(arguments, key, mode, backend))
    if arguments.out:
        arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = [{k: v for k, v in result.items() if k != "rows"} for result in report["results"]]
    print(json.dumps({"status": "ran", "base_url": arguments.base_url, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
