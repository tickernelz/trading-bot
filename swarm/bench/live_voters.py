import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from live_nutaraline import CASES, QUESTIONS, percentile, script_revision

from tb_swarm.config import SwarmConfig, VoterSpec, load_config
from tb_swarm.errors import ProviderError
from tb_swarm.models import DecisionRequest
from tb_swarm.providers.factory import build_provider
from tb_swarm.redact import redact
from tb_swarm.runner import SwarmRunner, VoterLog

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "config.example.yaml"
DEFAULT_ENV = Path(__file__).resolve().parents[2] / ".env"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def select_voters(config: SwarmConfig, ids: list[str] | None) -> list[VoterSpec]:
    voters = config.swarm.voters
    if ids is None:
        return [voter for voter in voters if voter.enabled]
    known = {voter.id: voter for voter in voters}
    unknown = [vid for vid in ids if vid not in known]
    if unknown:
        raise SystemExit(f"unknown voter ids: {unknown}")
    return [known[vid] for vid in ids]


async def decide_paced(provider, request, arguments, counters):
    retries = 0
    while True:
        try:
            response = await provider.decide(request)
        except ProviderError as exc:
            if exc.kind == "rate_limit":
                counters["rate_limit_events"] += 1
                if retries < arguments.rate_limit_retries:
                    retries += 1
                    await asyncio.sleep(arguments.rate_limit_wait * retries * random.uniform(0.8, 1.2))
                    continue
            await asyncio.sleep(arguments.interval)
            raise
        await asyncio.sleep(arguments.interval)
        return response, retries


def summarize(voter, rows, warmup_error):
    valid = [row for row in rows if row["valid"]]
    latencies = [row["latency_s"] for row in valid]

    def median_of(key):
        return int(statistics.median([row[key] for row in valid])) if valid else None

    costs = [row["cost"] for row in valid if row["cost"] is not None]
    return {
        "voter": voter.id,
        "adapter": voter.adapter,
        "provider": voter.provider,
        "model": voter.model,
        "cases": len(rows),
        "valid": len(valid),
        "valid_rate": round(len(valid) / len(rows), 3) if rows else None,
        "warmup_error": warmup_error,
        "rate_limit_events": sum(row["rate_limit_events"] for row in rows),
        "error_kinds": sorted({row["error_kind"] for row in rows if not row["valid"]}),
        "latency_s": {
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p90": round(percentile(latencies, 0.9), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
        },
        "input_tokens_median": median_of("input_tokens"),
        "output_tokens_median": median_of("output_tokens"),
        "reasoning_tokens_total": sum(row["reasoning_tokens"] for row in valid),
        "cost_total": round(sum(costs), 8) if costs else None,
        "served_models": sorted({row["model"] for row in valid}),
        "rows": rows,
    }


async def run_voter(voter, config, arguments):
    provider = build_provider(voter, config.providers[voter.provider], os.environ)
    warmup_error = None
    try:
        await decide_paced(
            provider, DecisionRequest(state=CASES[0][1], questions=QUESTIONS), arguments, defaultdict(int)
        )
    except ProviderError as exc:
        warmup_error = redact(f"{exc.kind}: {exc}", provider.secrets())[:200]
    rows = []
    for name, state in CASES[: arguments.cases]:
        counters = defaultdict(int)
        row = {"case": name}
        try:
            response, retries = await decide_paced(
                provider, DecisionRequest(state=state, questions=QUESTIONS), arguments, counters
            )
        except ProviderError as exc:
            row.update(
                {
                    "valid": False,
                    "error_kind": exc.kind,
                    "status": exc.status,
                    "error": redact(str(exc), provider.secrets())[:200],
                }
            )
        else:
            row.update(
                {
                    "valid": True,
                    "retries": retries,
                    "latency_s": round(response.latency_s, 3),
                    "model": response.model,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "reasoning_tokens": response.usage.reasoning_tokens,
                    "cost": response.usage.cost,
                    "answers": {k: v.model_dump(exclude_none=True) for k, v in response.answers.items()},
                }
            )
        row["rate_limit_events"] = counters["rate_limit_events"]
        rows.append(row)
    await provider.aclose()
    return summarize(voter, rows, warmup_error)


async def run_group(voters, config, arguments):
    return [await run_voter(voter, config, arguments) for voter in voters]


async def single(config, arguments):
    groups = defaultdict(list)
    for voter in select_voters(config, arguments.voters):
        groups[config.providers[voter.provider].resolve_api_key(os.environ) or voter.provider].append(voter)
    started = time.perf_counter()
    batches = await asyncio.gather(*(run_group(group, config, arguments) for group in groups.values()))
    return {
        "wall_s": round(time.perf_counter() - started, 1),
        "results": [result for batch in batches for result in batch],
    }


def outcome_row(case, outcome, wall_s):
    return {
        "case": case,
        "status": outcome.status,
        "reason": outcome.reason,
        "answered": outcome.answered,
        "required": outcome.required,
        "wall_s": round(wall_s, 3),
        "aggregate": asdict(outcome.aggregate) if outcome.aggregate else None,
        "voters": [
            {
                "voter": record.voter_id,
                "status": record.status,
                "latency_s": round(record.latency_s, 3),
                "error_kind": record.error_kind,
                "error": record.error,
                "model": record.model,
            }
            for record in outcome.voters
        ],
    }


async def quorum(config, arguments):
    log = VoterLog(arguments.log) if arguments.log else None
    runner = SwarmRunner.from_config(config, os.environ, seed="live-quorum", log=log)
    rows = []
    for name, state in CASES[: arguments.cases]:
        started = time.perf_counter()
        outcome = await runner.decide(DecisionRequest(state=state, questions=QUESTIONS))
        rows.append(outcome_row(name, outcome, time.perf_counter() - started))
        await asyncio.sleep(arguments.interval)
    await runner.aclose()
    per_voter = defaultdict(lambda: defaultdict(int))
    latencies = defaultdict(list)
    for row in rows:
        for record in row["voters"]:
            per_voter[record["voter"]][record["status"]] += 1
            if record["status"] == "ok":
                latencies[record["voter"]].append(record["latency_s"])
    return {
        "decisions": len(rows),
        "proceeded": sum(1 for row in rows if row["status"] == "ok"),
        "wall_s": {
            "median": round(statistics.median(row["wall_s"] for row in rows), 3),
            "p90": round(percentile([row["wall_s"] for row in rows], 0.9), 3),
        },
        "voters": {
            vid: {
                "statuses": dict(statuses),
                "latency_median_s": round(statistics.median(latencies[vid]), 3) if latencies[vid] else None,
            }
            for vid, statuses in per_voter.items()
        },
        "rows": rows,
    }


def restrict(config, ids, minimum):
    if ids is None:
        return config
    voters = [voter.model_copy(update={"enabled": voter.id in ids}) for voter in config.swarm.voters]
    update = {"voters": voters}
    if minimum is not None:
        update["min_voters_answered"] = minimum
    return config.model_copy(update={"swarm": config.swarm.model_copy(update=update)})


async def burst(config, arguments):
    results = []
    for voter in select_voters(config, arguments.voters):
        provider = build_provider(voter, config.providers[voter.provider], os.environ)
        request = DecisionRequest(state=CASES[0][1], questions=QUESTIONS)
        rounds = []
        for _ in range(arguments.rounds):
            started = time.perf_counter()
            outcomes = await asyncio.gather(
                *(provider.decide(request) for _ in range(arguments.parallel)), return_exceptions=True
            )
            kinds = defaultdict(int)
            for outcome in outcomes:
                kinds["ok" if not isinstance(outcome, Exception) else getattr(outcome, "kind", "error")] += 1
            rounds.append({"wall_s": round(time.perf_counter() - started, 3), "outcomes": dict(kinds)})
            await asyncio.sleep(arguments.interval)
        await provider.aclose()
        results.append(
            {"voter": voter.id, "provider": voter.provider, "parallel": arguments.parallel, "rounds": rounds}
        )
    return {"results": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["single", "quorum", "burst"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--voters", type=lambda text: [item for item in text.split(",") if item])
    parser.add_argument("--cases", type=int, default=len(CASES))
    parser.add_argument("--min-voters", type=int)
    parser.add_argument("--parallel", type=int, default=7)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--rate-limit-retries", type=int, default=3)
    parser.add_argument("--rate-limit-wait", type=float, default=15.0)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    load_env(arguments.env_file)
    config = load_config(arguments.config)
    if arguments.mode == "quorum":
        config = restrict(config, arguments.voters, arguments.min_voters)
    result = asyncio.run({"single": single, "quorum": quorum, "burst": burst}[arguments.mode](config, arguments))
    report = {
        "mode": arguments.mode,
        "script_revision": script_revision(),
        "cases": min(arguments.cases, len(CASES)),
        "interval_s": arguments.interval,
        "rate_limit_retries": arguments.rate_limit_retries,
        "rate_limit_wait_s": arguments.rate_limit_wait,
        **result,
    }
    if arguments.out:
        arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if arguments.mode == "single":
        summary = [{k: v for k, v in item.items() if k != "rows"} for item in report["results"]]
    elif arguments.mode == "burst":
        summary = report
    else:
        summary = {k: v for k, v in report.items() if k != "rows"}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
