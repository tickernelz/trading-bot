import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from live_nutaraline import CASES, QUESTIONS
from live_voters import DEFAULT_ENV, load_env

from tb_swarm.errors import ProviderError
from tb_swarm.models import DecisionRequest
from tb_swarm.providers.openai_decisions import OpenAiDecisionsProvider
from tb_swarm.providers.systemone import SystemOneProvider
from tb_swarm.validate import parse_answers

MODELS = ("jev-latest", "clef", "clef-flash", "gpt-6-luna-decisions")


async def probe(provider, url, model, request, key):
    payload = provider._payload(request)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {key}", "User-Agent": "curl/8.5.0", "Content-Type": "application/json"},
        )
    latency = round(time.perf_counter() - started, 3)
    row = {
        "model": model,
        "url": url,
        "status": response.status_code,
        "latency_s": latency,
        "body": response.text[:1500],
    }
    if response.status_code == 200:
        try:
            parse_answers(request, provider._raw_answers(response.json()))
            row["adapter_parse"] = "ok"
        except (ProviderError, ValueError) as exc:
            row["adapter_parse"] = f"invalid: {exc}"
    return row


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://api.experientiallabs.ai")
    parser.add_argument("--key-env", default="EXPERIENTIALLABS_API_KEY")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    load_env(arguments.env_file)
    key = os.environ[arguments.key_env]
    request = DecisionRequest(state=CASES[0][1], questions=QUESTIONS)
    rows = []
    for model in MODELS:
        system_one = SystemOneProvider(base_url=arguments.base_url, api_key=key, model=model, timeout_s=90)
        decisions = OpenAiDecisionsProvider(base_url=arguments.base_url, api_key=key, model=model, timeout_s=90)
        for name, provider, path in (
            ("systemone", system_one, "/v1/systemone"),
            ("openai_decisions", decisions, "/v1/decisions"),
            ("systemone_wire_on_responses_decisions", system_one, "/v1/responses/decisions"),
        ):
            row = await probe(provider, arguments.base_url + path, model, request, key)
            row["adapter"] = name
            rows.append(row)
            await provider.aclose()
    report = {"base_url": arguments.base_url, "state": CASES[0][1], "rows": rows}
    if arguments.out:
        arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        print(row["adapter"], row["model"], row["status"], row["latency_s"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
