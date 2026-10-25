import argparse
import asyncio
import json
import os
import statistics
import sys
from pathlib import Path

from tb_swarm.errors import ProviderError
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.providers.llm_structured import LlmStructuredProvider

MODEL = "deepseek-v4.1-flash-1017"
PROVIDER_KEY = "nutaraline"

CASES = [
    (
        "rsi-cool-uptrend",
        "BTC/IDR 1h. Close 1.002e9, EMA20 1.000e9, EMA50 9.9e8, RSI 41.",
        "price keeps rising",
        "normal",
    ),
    ("rsi-hot-uptrend", "BTC/IDR 1h. Close 1.01e9, EMA20 9.9e8, EMA50 9.7e8, RSI 79.", "price keeps rising", "late"),
    (
        "breakdown",
        "BTC/IDR 1h. Close 9.4e8, EMA20 9.8e8, EMA50 9.9e8, RSI 28, volume 3x average.",
        "price keeps falling",
        "heavy",
    ),
    ("flat-range", "BTC/IDR 1h. Close 1.0e9, EMA20 1.0002e9, EMA50 1.0001e9, RSI 50.", "range holds", "quiet"),
    (
        "news-shock",
        "BTC/IDR 1h. Exchange halted withdrawals 20 minutes ago; spread 4x normal.",
        "exchange stays solvent",
        "extreme",
    ),
    ("thin-book", "ETH/IDR 1h. Order book depth 0.1x the 7-day average, spread 0.9%.", "fill at quoted price", "thin"),
    ("dividend-rumor", "SOL/IDR 1h. Unconfirmed social rumor of a large unlock next week.", "rumor is true", "rumor"),
    ("gap-open", "ETH/IDR 1h. Price gapped 6% above yesterday's close with no news.", "gap fills today", "gap"),
    (
        "funding-crowded",
        "BTC/IDR 1h. Perp funding 0.15% per 8h, open interest at 90-day high.",
        "longs get squeezed",
        "crowded",
    ),
    (
        "series-of-red",
        "SOL/IDR 1h. Seven consecutive red candles, each smaller than the last.",
        "downside momentum continues",
        "weakening",
    ),
    ("volume-dry", "BTC/IDR 1h. Volume 0.2x average for 12 hours, price flat.", "a breakout is near", "dry"),
    ("weekend", "ETH/IDR 1h. Saturday, volume 0.4x weekday average.", "volatility expands in 4h", "weekend"),
    (
        "listing-news",
        "SOL/IDR 1h. A large exchange announced a new SOL pair 1 hour ago.",
        "news is already priced",
        "fresh",
    ),
    ("macro-day", "BTC/IDR 1h. US CPI release in 2 hours.", "volatility expands after the release", "macro"),
    (
        "whale-transfer",
        "ETH/IDR 1h. 40k ETH moved to an exchange wallet in the last hour.",
        "seller pressure follows",
        "flow",
    ),
    ("stablecoin-peg", "BTC/IDR 1h. The main IDR stablecoin trades at 0.97.", "peg recovers within a day", "depeg"),
    (
        "api-outage",
        "BTC/IDR 1h. The exchange API returned errors for 5 minutes.",
        "quotes are still reliable",
        "outage",
    ),
    (
        "double-top",
        "ETH/IDR 4h. Two failed attempts at 5.2e7 with falling volume.",
        "resistance holds next test",
        "pattern",
    ),
    (
        "funding-flip",
        "BTC/IDR 1h. Funding flipped from +0.05% to -0.03% while price held.",
        "shorts are crowding",
        "flip",
    ),
    ("week-open", "SOL/IDR 1h. Monday open with a 2% gap down and normal volume.", "gap closes this week", "open"),
]

QUESTIONS = {
    "direction": ChoiceQuestion(
        instructions="Which way is the entry most likely to resolve over the next hour?",
        criteria={"long": "price rises", "flat": "stays inside 0.5%", "short": "price falls"},
    ),
    "confidence_up": NoulQuestion(instructions="Is there a reason to take an entry at all right now?"),
    "risk": ScoreQuestion(instructions="How large is the event risk?", criteria=["low", "medium", "high"]),
}


def base_url_from_models_yml(path: Path, provider: str) -> str | None:
    """Reads only the provider's base URL; never touches or returns any key material."""
    import yaml

    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    providers = data.get("providers") or {}
    entries = providers.values() if isinstance(providers, dict) else providers
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == provider:
            for key in ("baseUrl", "base_url"):
                value = entry.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def load_case(item):
    name, state, _, mode = item
    return DecisionRequest(state=state, questions=QUESTIONS)


async def run_mode(arguments, key, base_url, mode):
    rows = []
    for item in CASES:
        provider = LlmStructuredProvider(
            api_type="openai-completions",
            base_url=base_url,
            api_key=key,
            model=MODEL,
            timeout_s=arguments.timeout,
            structured_mode=mode,
            extra_body=json.loads(arguments.extra_body) if arguments.extra_body else None,
        )
        request = load_case(item)
        row = {"case": item[0], "mode": mode}
        try:
            response = await provider.decide(request)
        except ProviderError as exc:
            row.update({"valid": False, "error_kind": exc.kind, "error": str(exc)[:200]})
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
    valid = [r for r in rows if r["valid"]]
    latencies = [r["latency_s"] for r in valid]
    return {
        "mode": mode,
        "cases": len(rows),
        "valid": len(valid),
        "valid_rate": round(len(valid) / len(rows), 3),
        "error_kinds": sorted({r.get("error_kind") for r in rows if not r["valid"]}),
        "latency_s": {
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p90": round(sorted(latencies)[int(0.9 * (len(latencies) - 1))], 3) if latencies else None,
        },
        "reasoning_tokens": {
            "median": int(statistics.median([r["reasoning_tokens"] for r in valid])) if valid else None,
            "total": sum(r["reasoning_tokens"] for r in valid),
        },
        "output_tokens_median": int(statistics.median([r["output_tokens"] for r in valid])) if valid else None,
        "served_models": sorted({r["model"] for r in valid}),
        "rows": rows,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("NUTARALINE_BASE_URL"))
    parser.add_argument("--models-yml", type=Path, default=Path.home() / ".omp/agent/models.yml")
    parser.add_argument("--key-env", default="NUTARALINE_API_KEY")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--extra-body", default=os.environ.get("NUTARALINE_EXTRA_BODY"))
    parser.add_argument("--modes", default="prompt,json_object,json_schema")
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()

    key = os.environ.get(arguments.key_env)
    if not key:
        print(json.dumps({"status": "not_run", "reason": f"{arguments.key_env} is not set"}, indent=2))
        return 3
    base_url = arguments.base_url or base_url_from_models_yml(arguments.models_yml, PROVIDER_KEY)
    if not base_url:
        print(json.dumps({"status": "not_run", "reason": "no base URL for nutaraline"}, indent=2))
        return 4
    report = {"status": "ran", "base_url": base_url, "model": MODEL, "cases": len(CASES), "results": []}
    for mode in [m.strip() for m in arguments.modes.split(",") if m.strip()]:
        report["results"].append(await run_mode(arguments, key, base_url, mode))
    text = json.dumps(report, indent=2)
    if arguments.out:
        arguments.out.write_text(text + "\n", encoding="utf-8")
    summary = [{k: v for k, v in result.items() if k != "rows"} for result in report["results"]]
    print(json.dumps({"status": "ran", "base_url": base_url, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
