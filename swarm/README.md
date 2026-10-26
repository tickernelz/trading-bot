# swarm

Stage 0b decision layer: `DecisionProvider` adapters, voter registry, read-only analyst agent, and measurement tools. Details of the numbers and the status of each item are in `../docs/stage0-findings.md`.

## Install

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python pytest pytest-asyncio ruff
```

## Use from code

```python
from tb_swarm.config import load_config
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.runner import SwarmRunner, VoterLog

config = load_config("../config/config.yaml")
runner = SwarmRunner.from_config(config, os.environ, log=VoterLog("../logs/voter_decisions.jsonl"))
outcome = await runner.decide(
    DecisionRequest(
        state={"pair": "BTC/IDR", "rsi": 41, "ema20": 100_000_000, "ema50": 99_000_000},
        questions={
            "take": NoulQuestion(instructions="Is there a reason to take an entry now?"),
            "size": ChoiceQuestion(instructions="Size?", criteria={"full": "...", "half": "...", "skip": "..."}),
            "risk": ScoreQuestion(instructions="Event risk?", criteria=["low", "medium", "high"]),
        },
    )
)
if outcome.proceed:
    ...
```

`outcome.proceed` is true only when the number of valid voters reaches `swarm.min_voters_answered` and the spread does not exceed `swarm.max_spread`. Otherwise the result is `skip` with a reason that can be logged, and the consumer must not enter.

## Adapters

| Adapter | Provider type | Wire |
| --- | --- | --- |
| `llm_structured` | `openai-completions`, `openai-responses`, `anthropic-messages` | chat model + validated JSON |
| `systemone` | `systemone` | `POST {base_url}/v1/systemone` |
| `openai_decisions` | `openai-decisions` | `POST {base_url}/v1/decisions` |
| `openrouter_decisions` | `openrouter-decisions` | `POST {base_url}/api/alpha/decisions` |

API keys are taken from environment variables (`api_key_env`) or from `api_key` in the local gitignored config. A missing key makes that voter fail with error kind `auth`, and the quorum decides whether the decision may still proceed.

## Analyst agent

`build_analyst(model, data_dir)` creates a deepagents agent with three read tools (`get_metrics`, `get_trade_history`, `get_voter_log`). `ToolAllowlist` filters the tool list sent to the model and rejects calls to any other tool, including `task`, `write_file`, `edit_file`, `delete`, and `execute`. `get_trade_history` and `get_voter_log` accept `day` (YYYY-MM-DD in the risk timezone) and `pair` filters, add `ts_local` to each row, and end truncated output with a "showing the newest N of M" line.

Stage 3a adds three modules on top of it:

- `tb_swarm/analyst.py`: `AnalystRunner.daily_report(day)` produces a `DailyReport` (summary, anomalies, suggestions; each finding carries `evidence` and `grounded`, which the code computes from tool output) and `AnalystRunner.ask(question, history)` answers questions; `ReportStore` stores one JSON file per day; `build_runner(raw_config, env, data_dir)` picks the model from `llm.analyst_model` in `config.yaml`.
- `tb_swarm/snapshot.py`: `write_snapshot` writes the three files the tools read, each atomically, with the swarm daily summary (`swarm_by_day`) in `metrics.json` so busy days do not need to be read row by row.
- `bench/live_analyst.py`: live test against a real provider with synthetic or empty data; needs a provider key in the environment and `--base-url`.

In the app, the analyst runs as its own process (`engine/analyst_service.py`); see the README at the repo root, Stage 3a section.

## Running tests and measurement tools

```sh
.venv/bin/python -m pytest
.venv/bin/python bench/bench_voter_overhead.py --samples 30
.venv/bin/python bench/live_nutaraline.py --base-url <base URL ending in /v1> --out /tmp/nutaraline-live.json
```

`bench/live_nutaraline.py` needs `NUTARALINE_API_KEY` and `--base-url`; without them the script stops with status `not_run` and does not contact the network.
