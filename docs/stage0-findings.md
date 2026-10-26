# Stage 0b and 0c Findings

This document records what has been proven in Stage 0b and 0c, the measured numbers, and what remains unproven. The source of truth remains `docs/plan.md` revision 10.

The code is in `swarm/` (Python package `tb_swarm`, with its own `pyproject.toml` so it does not collide with the root `pyproject.toml` while Stage 0a work is in progress). The `vendor/freqtrade` vendor directory is untouched.

## Evidence summary

| Item | Status | Evidence |
| --- | --- | --- |
| 1. `DecisionProvider` interface, three primitives + three adapters | Proven | `swarm/tb_swarm/providers/`, 18 wire tests |
| 2. Voter registry, 5/7 quorum, option shuffling, median | Proven | `swarm/tb_swarm/{config,runner,shuffle,aggregate}.py`, 45 tests |
| 3. All adapters tested against a local stub server | Proven | `swarm/tb_swarm/stub_server.py`, no key and no network |
| 4. Live test of `nutaraline/deepseek-v4.1-flash-1017` | Proven: 20/20 valid in every cell, twice (default effort and `high`) | `swarm/bench/live_nutaraline.py`, section Item 4 |
| 5. deepagents 0.7.32 analyst agent + re-test of the earlier subagent tool-inheritance finding | Proven, including live latency and tokens | `swarm/tb_swarm/agents.py`, 21 tests, `bench/bench_voter_overhead.py` |
| 6. Kronos mini on CPU | Proven (time, memory, median across paths) | `swarm/bench/bench_kronos.py`, 10 configurations |
| 7. Findings and numbers in this document | This document | - |
| 8. Stage 0c: System One and OpenAI Decisions live at Experiential Labs, new `openai_decisions` adapter | Proven: 20/20 valid for `jev-latest`, `clef-flash`, `gpt-6-luna-decisions` | section "Stage 0c", `swarm/bench/live_voters.py` |
| 9. Stage 0c: seven `llm_structured` voters from seven providers and a real 5-of-7 quorum | Proven: 20/20 valid per selected voter; quorum passed on 18 of 20 and 20 of 20 decisions | section "Stage 0c", Items 3 and 4 |
| 10. Stage 0c: OpenRouter Decisions | Not proven (no key) | section "Stage 0c", Item 2 |

Suite: `170 passed` at Stage 0c (`cd swarm && .venv/bin/python -m pytest`, run via `heavy` on commit `8eeb4a6`, whose code tree is identical to the final commit; only documents changed afterwards), no network, no key; 43.1 seconds, peak RSS 206 MB (`/usr/bin/time -v`). Stage 0b: `161 passed`, 28.5 seconds, RSS 203 MB. `tests/test_settings.py` at the root (21 tests, including validation of `config.example.yaml` by the engine schema) passes in the swarm venv.

## Item 1: decision interface

`DecisionProvider` (`swarm/tb_swarm/providers/base.py`) has one abstract method `decide(request) -> DecisionResponse` plus three thin primitives `noul()`, `choice()`, `score()` on top of it. Questions are typed with pydantic: `NoulQuestion` (probability 0..1), `ChoiceQuestion` (2 to 255 options, the 255 limit from the Jev documentation), `ScoreQuestion` (ordered rubric, at least 2 levels).

Three adapters in Stage 0b; Stage 0c adds `openai_decisions` (`POST {base_url}/v1/decisions`, see section "Stage 0c"):

- `llm_structured` for the API types `openai-completions`, `openai-responses`, and `anthropic-messages` via LangChain (`ChatOpenAI`, `ChatAnthropic`). These three types are actually used, not just interfaces: all three send requests over their respective wires and are tested against the stub (`/v1/chat/completions`, `/v1/responses`, `/v1/messages`).
- `systemone`: `POST {base_url}/v1/systemone`.
- `openrouter_decisions`: `POST {base_url}/api/alpha/decisions` with default `base_url` `https://openrouter.ai`.

Questions and answers are validated strictly (`swarm/tb_swarm/validate.py`): the answer name must be exactly the same as the question name, `noul` in [0, 1], `choice` must be one of the option keys, `score` in [0, N-1], probabilities must cover all options. A deviating answer counts as a failed voter, never guessed.

### Quoted wire

OpenRouter Decisions (alpha), `POST /api/alpha/decisions`, https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request :

```yaml
model: typesafe/jev-1.13
state: {customer_tier: enterprise, ticket: '...'}
questions:
  is_bug:  {type: noul,   instructions: '...', criteria: {'false': '...', 'true': '...'}}
  team:    {type: choice, instructions: '...', criteria: {account: '...', frontend: '...', payments: '...'}}
  urgency: {type: score,  instructions: '...', criteria: ['Can wait for the next release', '...']}
```

Answer in the official example:

```yaml
answers:
  is_bug:  {noul: 0.96, type: noul}
  team:    {choice: payments, confidence: 0.75, probabilities: {account: 0, frontend: 0.16, payments: 0.84}, type: choice}
  urgency: {score: 1.99, confidence: 0.99, legend: {'0': '...', '1': '...', '2': '...'}, probabilities: {'0': 0, '1': 0.01, '2': 0.99}, type: score}
id: gen-dec-1789738314-X5e5eKGQdvR9rblyX250
model: typesafe/jev-1.13-20260917
provider: TypeSafe
usage: {cost: 0.000019992, input_tokens: 476, output_tokens: 70}
```

TypeSafe System One, `POST /v1/systemone`, https://docs.typesafe.ai/api/system-one :

```yaml
model: jev-latest
state: 'free text or any object'
questions:
  billing: {type: noul,   instructions: '...'}
  tone:    {type: choice, instructions: '...', criteria: {angry: '...', calm: '...'}}
  urgency: {type: score,  instructions: '...', criteria: ['Can wait', '...']}
```

Answer: `model`, `answers` (keys same as the question names), `usage: {input_tokens, output_tokens}`; `choice` and `score` carry `confidence` and `probabilities`, and `score` also `legend`.

What is not yet verified and is therefore flagged:

- OpenRouter authentication scheme: the documentation only mentions the `apiKey` scheme; the implementation sends `Authorization: Bearer <key>` (common OpenRouter behaviour) but it has not been tested live.
- The OpenRouter `base_url` in the documentation is written `https://openrouter.ai/api/v1` because that is the default OpenAPI server, while the endpoint path is `/api/alpha/decisions` (not `/api/v1/...`). The adapter uses base `https://openrouter.ai` + that path; not tested live.
- The headers `TypeSafe-Danger-Zone-Images` and `TypeSafe-Danger-Zone-Long-Context` are not used (outside the scope of Stage 0b).
- The naming of API types on provider items (`openai-responses`, `anthropic-messages`) follows the OpenRouter/models.yml convention mentioned in the plan, not an official vendor specification.

## Item 2: voter registry and aggregation

The configuration (`swarm/tb_swarm/config.py`) accepts `providers` (list or map) and `swarm.voters` (id, adapter, provider, model, variation, timeout_s, weight, enabled, temperature, structured_mode, backend, extra_body). Validated at load time: voter ids are unique, providers are known, the adapter matches the provider type, the model is in the provider's model list, and the number of enabled voters must be able to reach quorum. The `config/config.example.yaml` in the repo passes as is (7 voters, `min_voters_answered: 5`).

Decision rules (`swarm/tb_swarm/runner.py`):

- All enabled voters run concurrently, each with its own time limit (`asyncio.wait_for`). A voter that exceeds the limit, returns an HTTP error, has a wrong key, returns an invalid answer, or raises an unexpected exception is dropped from that decision and the reason is recorded (`timeout`, `failed`, `invalid`).
- Quorum: fewer than `min_voters_answered` (5) valid answers means a `skip` result with reason `quorum_not_met`. Fail-closed: there is no aggregate, so the consumer cannot take a decision.
- Option order is shuffled per voter per decision with a seeded RNG (`seed:decision_id:voter_id`), including reversing the `score` rubric; answers are restored to the original order before being combined. Voters still answer by key name, so shuffling only removes position bias.
- Aggregation: weighted median (voter weight) for `noul` and `score`, plus quartile spread (q25, q75, IQR, min, max); for `choice` the per-option median probability is used (normalised distribution; one-hot if the model gives no probabilities), the winner, the vote count, and the weighted agreement rate. A tie (two or more options with the same highest median, e.g. no majority on a one-hot ballot) means the voters disagree: a `skip` result with reason `choice_tie:<question>`, checked before the spread gate.
- Optional `max_spread`: if the IQR exceeds the threshold, a `skip` result with reason `spread_exceeded:<question>`. This threshold applies to `noul` and to the winning probability of `choice`; `score` is not checked because its unit is a rubric level, not a probability, so a single threshold cannot be fair to both.
- Every decision can be logged to JSONL (`swarm.log_path`): request, status, aggregate, and one line per voter (status, latency, model, usage, answer, presented option order, reversed rubric).

## Item 3: test against a local stub

`swarm/tb_swarm/stub_server.py` is a local HTTP server (random port) that imitates five wires: `/v1/systemone`, `/api/alpha/decisions`, `/v1/chat/completions`, `/v1/responses`, `/v1/messages`. Behavior per model is configurable: answer policy, delay, failure status, malformed output, number of reasoning tokens. The server rejects a wrong key with 401, so tests can prove the auth path. There is no outbound network and no key in the tests: the only key used is `stub-key-not-a-secret`.

Stub results are not evidence of model quality, only evidence of wire shape, parsing, error classification, and decision logic.

## Item 4: live test of nutaraline

Run on 2026-10-26 against `https://nutaraline.co.uk/v1`, model `deepseek-v4.1-flash-1017`, API type `openai-completions`. The key was taken from `NUTARALINE_API_KEY` in the worktree's gitignored `.env` (permission from the owner via the operator's approval); the `apiKey` value in `~/.omp/agent/models.yml` was not read. Checks: the key value is not in any git-tracked file, not in git history, and not in any output file.

`swarm/bench/live_nutaraline.py` sends 20 trading decision samples (one `choice` question, one `noul`, one `score` per sample), one provider per cell with one warm-up call that is not counted. Cells: `direct` backend x three modes (`prompt`, `json_object`, `json_schema`) and `deepagents` backend x `prompt`.

### Structured output support

All three modes are accepted by the server and produce valid answers 20/20. `json_object` and `json_schema` (strict) are not rejected by the gateway. Note: this proves the request is accepted and the answer passes our validation; it does not yet prove that the server actually enforces the schema (`prompt` mode is also 20/20, so on these 20 samples there is no difference attributable to enforcement).

### Reasoning

Without extra parameters the model answers without reasoning (`reasoning_tokens` = 0 on all 80 calls). Reasoning only activates with `reasoning_effort: "high"` via `extra_body`: the response carries `reasoning_content` and `completion_tokens_details.reasoning_tokens`. For the stage 0 test, "reasoning enabled" means it must be selected through voter configuration (`extra_body`), not a model default.

### Results of 20 samples per cell

The raw report (JSON per cell and per case, including answers and tokens) is kept outside the repository as `live_default.json`, `live_high.json` and `live_nopace.json`; the tables below are computed from those files. The round reported here is the second re-run (2026-10-26) with `--interval 3`; the first round (similar numbers, file not saved) is not used as evidence.

Default effort (`live_default.json`, 0 retries on 429):

| Backend | Mode | Valid | Median latency | p90 | Max | Input tokens (median) | Output tokens (median) | Reasoning tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| direct | prompt | 20/20 | 1.36 s | 1.79 s | 6.14 s | 333 | 36 | 0 |
| direct | json_object | 20/20 | 1.40 s | 1.74 s | 2.10 s | 333 | 36 | 0 |
| direct | json_schema | 20/20 | 1.30 s | 1.50 s | 1.57 s | 654 | 36 | 0 |
| deepagents | prompt | 20/20 | 1.75 s | 3.48 s | 5.33 s | 333 | 36 | 0 |

`reasoning_effort: high` (`live_high.json`, 0 retries on 429):

| Backend | Mode | Valid | Median latency | p90 | Max | Input tokens (median) | Output tokens (median) | Reasoning tokens (median / total) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| direct | prompt | 20/20 | 4.38 s | 8.66 s | 10.28 s | 358 | 390 | 356 / 8,289 |
| direct | json_object | 20/20 | 5.26 s | 10.47 s | 10.51 s | 358 | 506 | 473 / 9,641 |
| direct | json_schema | 20/20 | 3.55 s | 5.20 s | 7.53 s | 679 | 267 | 234 / 5,607 |
| deepagents | prompt | 20/20 | 4.06 s | 7.47 s | 8.12 s | 358 | 375 | 345 / 8,545 |

Monetary cost was not measured: responses do not carry `usage.cost`.

### Operational findings

- `json_schema` mode nearly doubles input tokens (654 versus 333) because the schema is sent along; with no measurable quality difference on 20 samples.
- `high` reasoning raises median latency from about 1.36 s to 3.55 s through 5.26 s and output tokens from 36 to about 267 through 506. The longest single call at `high` effort was 10.51 s, and at default effort 6.14 s; the first round recorded one call of 27.6 s, so `timeout_s: 30` in `config.example.yaml` is tight for `high` effort.
- Per-key rate limiting occurs but is not deterministic. In the first round (four cells back to back with no pause) the last three cells hit HTTP 429 (`Laju request per key melebihi batas`), 19 of 20 cases failing per cell; the report file of that round was not saved, so this is only an observation note, not attached data. On a re-run with the same script with no pause and no retries (`--interval 0 --rate-limit-retries 0`, `live_nopace.json`) there was not a single 429 and all 80 calls were valid. So a limit exists, its trigger is not yet known (possibly dependent on gateway load or a time window), and seven parallel voters on one key have not been tested. The 5-of-7 quorum risk remains real but unmeasured.
- The live-test script now applies an `--interval` pause (default 3 seconds) after every call completes, success or failure, and retries only HTTP 429 (`--rate-limit-retries`, `--rate-limit-wait`).

How to re-run:

```sh
cd swarm
set -a && . ../.env && set +a
.venv/bin/python bench/live_nutaraline.py --base-url https://nutaraline.co.uk/v1 --interval 3 --out <output file>
.venv/bin/python bench/live_nutaraline.py --base-url https://nutaraline.co.uk/v1 --interval 3 \
  --extra-body '{"reasoning_effort":"high"}' --out <output file>
```

## Item 5: deepagents 0.7.32

Installed versions: `deepagents==0.7.32`, `langchain==1.4.7`, `langgraph==1.2.17`.

### Analyst agent

`swarm/tb_swarm/agents.py` builds the analyst with three read-only tools: `get_metrics`, `get_trade_history`, `get_voter_log`. There is no path argument: the files read are fixed (`metrics.json`, `trades.jsonl`, `voter_decisions.jsonl`) inside the data directory, lines are capped at 200, output is truncated at 20,000 characters. There is no order tool, no config-modification tool, and config files or `.env` are never opened.

This boundary is enforced in two layers by `ToolAllowlist`, an `AgentMiddleware`: the tool list sent to the model is filtered, and every tool call outside the list is rejected with `ToolMessage(status="error")` before execution. This applies to both the synchronous and asynchronous paths (two separate tests). The tests try `write_file`, `edit_file`, `delete`, `execute`, `task`, and one fake order tool: all six are rejected, no file changes, and the data directory remains byte-identical.

### Re-test of the earlier finding

The earlier finding (deepagents 0.7.13) recurs in 0.7.32 for two subagent shapes:

| Subagent shape | Parent tools included? | Safety line in prompt? |
| --- | --- | --- |
| Default `general-purpose` (auto-created) | Yes, `place_order` included | No |
| `SubAgent` without a `tools` key | Yes, `place_order` included | No |
| `SubAgent` with `tools=[]` | No | Only if the subagent's own prompt contains it |

Conclusion: the safety boundary must not be placed in the parent prompt, and restriction must be explicit per subagent (`tools=[]` or a filtering middleware). The analyst in this repo uses a stricter path: `ToolAllowlist` also filters `task` from the parent, so subagents cannot be called at all (tested: the `task` call is rejected).

### Cost of deepagents compared to direct calls

`swarm/bench/bench_voter_overhead.py`, 30 samples per path, two identical voters (same model, same prompt) against the local stub, same CPU:

| Stub delay | Direct (median) | Via deepagents (median) | Difference |
| --- | --- | --- | --- |
| 0 ms | 4.0 ms (max 5.6) | 9.9 ms (max 19.5) | +5.9 ms |
| 500 ms | 504.0 ms | 508.8 ms | +4.8 ms |

The length of the submitted prompt is identical (0 characters difference on the stub, because the default deepagents profile adds no system prompt and `ToolAllowlist` empties the tool list). This means the deepagents overhead here is purely framework latency, around 5-10 ms per call, while real provider latency is in the range of hundreds to thousands of milliseconds. The real provider numbers are in the section "Live: deepagents versus direct call" below.

### Live: deepagents versus direct call

The same cell (`prompt`), nutaraline model, 20 samples, from the attached report:

| Effort | Path | Median latency | p90 | Input tokens | Output tokens |
| --- | --- | --- | --- | --- | --- |
| default | direct | 1.36 s | 1.79 s | 333 | 36 |
| default | deepagents | 1.75 s | 3.48 s | 333 | 36 |
| high | direct | 4.38 s | 8.66 s | 358 | 390 |
| high | deepagents | 4.06 s | 7.47 s | 358 | 375 |

Input tokens are identical on both paths (333 and 358): deepagents does not add to the prompt. Median latency at default effort: deepagents 1.75 s versus direct 1.36 s (p90 3.48 s versus 1.79 s); at `high` effort: 4.06 s versus 4.38 s (p90 7.47 s versus 8.66 s). The direction of the difference is not consistent across effort levels and across rounds (the first round showed deepagents equal at default effort, now it is slower), so a single round of 20 samples is not enough to conclude a latency gain or loss. The framework overhead measured on the stub (5-10 ms) is far below that noise.

Decision: the fast voter does not need deepagents (no measurable benefit, and one more layer whose boundaries must be maintained); deepagents is used for the analyst agent, which does need tools.

### Voter agent

`build_voter_agent` creates an agent with no tools at all (`tools=[]` plus `ToolAllowlist(())`) and with the same voter system prompt as the direct path, so the direct versus deepagents comparison is fair. Tests prove that no tool is offered to the model and that the resulting answer is identical to the direct path.

## Item 6: Kronos mini on CPU

Model: `NeoQuasar/Kronos-mini` (4,108,032 model parameters + 3,958,042 tokenizer parameters, MIT license, source commit `shiyu-coder/Kronos` 67b630e), tokenizer `NeoQuasar/Kronos-Tokenizer-2k`, `max_context` 2048, `torch==2.14.1+cu130` used on CPU, synthetic data of 512 1-hour candles (not real market data, because accuracy is not tested here).

Machine: Intel i5-12600K, 16 logical CPUs, all jobs go through the `heavy` queue (400% CPU quota, nice 19). `T=1.0`, `top_p=0.9`.

| Configuration | Prediction | Paths | Threads | Median | p90 | Peak RSS |
| --- | --- | --- | --- | --- | --- | --- |
| lookback 512 | 1 hour | 1 | 4 | 48 ms | 75 ms | 677 MB |
| lookback 512 | 1 hour | 4 | 4 | 185 ms | 223 ms | 704 MB |
| lookback 512 | 1 hour | 8 | 4 | 342 ms | 411 ms | 765 MB |
| lookback 512 | 1 hour | 16 | 4 | 718 ms | 804 ms | 851 MB |
| lookback 512 | 1 hour | 32 | 4 | 1,448 ms | 1,555 ms | 1,068 MB (up from 677 MB) |
| lookback 512 | 1 hour | 8 | 1 | 903 ms | 965 ms | 751 MB |
| lookback 512 | 1 hour | 8 | 2 | 517 ms | 545 ms | 758 MB |
| lookback 512 | 1 hour | 8 | 8 | 649 ms | 696 ms | 773 MB |
| lookback 512 | 24 hours | 8 | 4 | 4,000 ms | 4,439 ms | 786 MB |
| lookback 2048 | 1 hour | 8 | 4 | 1,684 ms | 1,703 ms | 1,065 MB |

Reading the numbers:

- Cost rises almost linearly with `sample_count` and with prediction length; 24 steps of 1 hour (around 3-4 seconds) is already at the practical limit for an hourly shadow voter on this CPU.
- 8 threads is slower than 4 threads because the job runs under the 400% CPU quota; the 4-thread figure is the relevant one for this box.
- Baseline memory is around 680 MB (the torch import is included) and rises around 12 MB per additional path at 32 paths.
- Weight load time is 1.1-1.3 seconds once the Hugging Face cache is populated (7.4 seconds on the first download).

### Median across paths

The vendor function `auto_regressive_inference` averages all paths (`np.mean(preds, axis=1)`) before returning the result, so `predict()` never exposes individual paths. A median across paths is still possible without touching the vendor code: `swarm/bench/bench_kronos.py` replaces the name `np` inside the vendor module with a proxy that captures the 4-dimensional array right before the averaging, then restores it to the original price scale. Verification: the mean of the captured paths equals the output of `predict()` (`rtol=1e-4`, matching on 10 of 10 configurations), so what is captured really is the actual paths.

With 8 paths, the spread of results (close price change at the last step, percent, synthetic data):

| Horizon | p10 | median | p90 |
| --- | --- | --- | --- |
| 1 hour | -0.71% | -0.71% | -0.13% |
| 24 hours | -2.05% | +0.62% | +2.18% |

The median across paths can therefore be produced and makes sense as a shadow voter: for the 1-hour horizon the spread is very narrow (the median is practically equal to the mean), and it widens at the 24-hour horizon. This is not an accuracy claim; only time, memory, and the feasibility of aggregation were tested.

## Stage 0c: live test of decision and voters across providers

Run on 2026-10-26 from the host with `swarm/bench/live_voters.py` and `swarm/bench/probe_decision_wires.py`. Keys were read from `NUTARALINE_API_KEY` and its siblings in the git-ignored worktree `.env`; `~/.omp/agent/models.yml` was only read for the provider list, base URLs, and API types, not keys. Model ids were taken from `GET {base_url}/models` of each provider, not guessed. The client uses httpx and the header `User-Agent: curl/8.5.0` on raw probes. The raw reports (JSON per cell and per case, including answers, tokens, and latency) are kept outside the repository: `wire_probe.json`, `single_1.json`, `single_2.json`, `cand.json`, `cand2.json`, `quorum_1.json`, `quorum_1.voters.jsonl`, `quorum_2.json`, `quorum_2.voters.jsonl`, `burst_1.json`, `local_host.json`, `local_container_hostnet.json`, `local_container_bridge.json`. All tables in this section are computed from those files. The same twenty cases as Item 4 (`CASES`, three questions `choice`, `noul`, `score` per case), one warm-up call not counted, 3-second pause after each call.

### Item 1: Experiential Labs decision adapter

Adapter probe against `https://api.experientiallabs.ai` (`wire_probe.json`, payload built by the adapter, same question for every model):

| Path | jev-latest | clef | clef-flash | gpt-6-luna-decisions |
| --- | --- | --- | --- | --- |
| `POST /v1/systemone` (adapter `systemone`) | 200, 0.62 s, answer passes validation | 200, 1.08 s, passes | 200, 1.42 s, passes | 400 `unsupported_capability` |
| `POST /v1/decisions` (adapter `openai_decisions`) | 400 `unsupported_capability` | 400 `unsupported_capability` | 400 `unsupported_capability` | 200, 0.67 s, passes |
| `POST /v1/responses/decisions` | 404 | 404 | 404 | 404 |

One earlier probe recorded `clef` at 6.9 s on the first cold call; the next probe 1.08 s. The three System One models do not serve `/v1/decisions`, and `gpt-6-luna-decisions` does not serve `/v1/systemone`: the error message asks to resend to the matching path. `/v1/responses/decisions` does not exist.

**System One (`/v1/systemone`) matches the existing adapter.** The real request `{model, state, questions: {name: {type, instructions, criteria}}}` was accepted as is. Real answer:

```yaml
id: decision_cd6f41269b093975f160f63a9c5dcb73
model: jev-latest
answers:
  direction: {type: choice, choice: flat, confidence: 0.69, probabilities: {long: 0.04, flat: 0.79, short: 0.17}}
  entry_reason: {type: noul, noul: 0.4}
  risk: {type: score, score: 1.95, confidence: 0.94, legend: {'0': low, '1': medium, '2': high}, probabilities: {'0': 0.0, '1': 0.04, '2': 0.96}}
usage: {input_tokens: 409, output_tokens: 69, cost: 0.0, is_byok: false}
provider: typesafe
```

Unlike the document quoted in Item 1: the answer carries `id`, `provider`, `usage.cost`, `usage.is_byok`, and `legend` on `score`; `noul` does not carry `confidence`. All of it is safe to ignore by `parse_answers`. `clef` and `clef-flash` return fractional probabilities (for example `0.4576796777173158`) and `output_tokens: 0`; the one serving is `experiential_cloud`, not `typesafe`. Reported cost per call is 0.0 for `jev-latest`, `clef-flash`, and `gpt-6-luna-decisions`.

**OpenAI Decisions (`/v1/decisions`) uses a different wire, and the old adapter does not match.** The gateway's OpenAPI spec (`/openapi.json`) only mentions "Relay the OpenAI Decisions API wire" with no schema; the shape was found by probing, and the 400 `invalid_parameter` error mentions `predicate`, `choice (with choices)`, `score (with levels)`. The accepted (200) and rejected (400) shapes on `gpt-6-luna-decisions`:

| Element | Accepted | Rejected |
| --- | --- | --- |
| Body | `{model, input, questions}` | `state`, `questions` as a map of names to objects |
| `input` | text, or a list of user messages with an `input_text` part | JSON object |
| `noul` question | `{type: predicate, name, instructions}` | `criteria`, `true`, `false` |
| `choice` question | `{type: choice, name, instructions, choices: [{value, description?}]}` | `choices` as a list of strings, `{id}`, `{label}`, `{name}`, a map, `criteria` |
| `score` question | `{type: score, name, instructions, levels: [{label, description?}]}` | `levels` as a list of strings, `{value}`, `{name}`, `{description}` only |
| `name` | optional, unique | duplicate |

The real answer is a named list, not a map:

```yaml
model: gpt-6-luna-decisions
answers:
  - {type: choice, name: d, choice: long, probabilities: [{value: long, probability: 0.94}, {value: short, probability: 0.06}], confidence: 0.88}
  - {type: score, name: r, score: 0.95, probabilities: [{value: 0, label: low, probability: 0.05}, {value: 1, label: high, probability: 0.95}], confidence: 0.9}
  - {type: predicate, name: p, probability: 0.53}
usage: {input_tokens: 124, input_tokens_details: {cached_tokens: 0, cache_write_tokens: 0}, output_tokens: 0, output_tokens_details: {reasoning_tokens: 0}, total_tokens: 124, cost: 0.0, is_byok: false}
provider: openai
```

Fix: new adapter `openai_decisions` (`swarm/tb_swarm/providers/openai_decisions.py`, provider type `openai-decisions`, `POST {base_url}/v1/decisions`). Mapping: `noul` to `predicate` (the `true`/`false` criteria are moved into the instruction text because the wire does not accept them), `choice.criteria` to `choices`, `score.criteria` to `levels[].label`, object-shaped state serialized to JSON text, list answers mapped back to a name map, list probabilities to a map, `reasoning_tokens` read from `output_tokens_details`. The stub (`swarm/tb_swarm/stub_server.py`) was corrected to match reality: the `/v1/decisions` route rejects with 400 exactly like the real message when the body shape deviates, and the System One response now carries `id`, `provider`, `usage.cost`, `usage.is_byok`, and `legend`. New tests in `swarm/tests/test_wire_adapters.py` and `test_config.py` use the real answer above as a fixture. `engine/settings.py` also accepts the provider types `systemone`, `openai-decisions`, and `openrouter-decisions` so the same `config/config.example.yaml` is validated by both the engine and the swarm.

Result of 20 cases per decision voter (rows d1 through d3 in the Item 3 table): 20/20 valid, no 429, reported cost 0.0 for all three.

### Item 2: OpenRouter Decisions

There is no OpenRouter key in `models.yml` or `.env`, so the `openrouter_decisions` adapter is still not proven live: the auth scheme and the `/api/alpha/decisions` path come only from documentation. Only the stub tests the wire shape and parsing. The OpenRouter wire (state and questions keyed by name) is the same as System One, which is now proven, but that is not evidence for OpenRouter.

### Item 3: `llm_structured` voters across families and providers

Seven voters, seven model families, seven providers with seven different keys (`config/config.example.yaml`), plus three decision voters from one provider (same key, run sequentially). Each voter alone, 20 cases, `--interval 3`, no 429 retries used (`single_1.json`, `single_2.json`):

| Voter | Provider | Model | Valid | Median latency | p90 | Max | Tokens in / out (median) | Reasoning tokens (total) | 429 | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v1 | nutaraline | deepseek-v4.1-flash-1017 | 20/20 | 1.47 s | 1.94 s | 2.19 s | 333 / 36 | 0 | 0 | - |
| v2 | modelrouter | glm-5.3-flash:mr | 20/20 | 1.69 s | 2.66 s | 5.55 s | 338 / 43 | 238 | 0 | - |
| v3 | xai-hm | cx/gpt-6-luna | 20/20 | 2.84 s | 3.54 s | 4.31 s | 348 / 105 | 1423 | 0 | - |
| v4 | sub2api-claude | claude-haiku-5-5 | 20/20 | 2.54 s | 3.77 s | 4.20 s | 972 / 305 | 4966 | 0 | - |
| v5 | omniroute | agy/gemini-3.8-flash-medium | 20/20 | 6.79 s | 8.36 s | 11.69 s | 401 / 518 | 10487 | 0 | - |
| d1 | experientiallabs-systemone | jev-latest | 20/20 | 0.43 s | 0.98 s | 1.97 s | 416 / 69 | 0 | 0 | - |
| d2 | experientiallabs-systemone | clef-flash | 20/20 | 0.81 s | 2.25 s | 5.85 s | 350 / 0 | 0 | 0 | - |
| d3 | experientiallabs-decisions | gpt-6-luna-decisions | 20/20 | 1.02 s | 2.55 s | 4.48 s | 419 / 0 | 0 | 0 | - |
| v6 | experientiallabs | llama-4-maverick | 20/20 | 2.21 s | 3.97 s | 5.64 s | 343 / 41 | 0 | 0 | - |
| v7 | sub2api-agy | gpt-oss-120b-medium | 20/20 | 2.21 s | 4.66 s | 6.49 s | 0 / 0 | 0 | 0 | - |

Families: deepseek (nutaraline), glm (modelrouter), openai gpt-6 (xai-hm, type `openai-responses`), anthropic (sub2api-claude, type `anthropic-messages`, base URL without `/v1` because the SDK appends it), gemini (omniroute), llama (experientiallabs), gpt-oss (sub2api-agy). The last two providers are local hosts. Row v7 reports 0 tokens because sub2api-agy does not carry `usage` for this model; monetary cost is not reported by any LLM provider (only the three decision voters carry `usage.cost`).

Model choices that failed testing and were replaced (`single_1.json` for the first two rows, `cand.json` and `cand2.json` for the rest; the voter ids in those files are `c1` through `c8`, `e1`, `e2`):

| Voter | Provider | Model | Valid | Median latency | p90 | Max | Tokens in / out (median) | Reasoning tokens (total) | 429 | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v6 | experientiallabs | kimi-k2.6 | 15/20 | 25.51 s | 27.29 s | 28.37 s | 335 / 1835 | 28683 | 0 | timeout |
| v7 | sub2api-mimo | mimo-v2.6-flash | 0/20 | - | - | - | - / - | 0 | 0 | http |
| c1 | experientiallabs | llama-4-maverick | 3/3 | 1.54 s | 1.54 s | 1.70 s | 365 / 41 | 0 | 0 | - |
| c2 | experientiallabs | grok-4.20-non-reasoning | 3/3 | 2.86 s | 2.86 s | 3.22 s | 524 / 34 | 0 | 0 | - |
| c3 | experientiallabs | gpt-oss-120b | 2/3 | 20.67 s | 14.78 s | 26.55 s | 416 / 314 | 565 | 0 | invalid |
| c8 | experientiallabs | deepseek-v4-flash | 3/3 | 2.21 s | 2.21 s | 3.72 s | 349 / 36 | 0 | 0 | - |
| c4 | lucif | lucif | 2/3 | 29.87 s | 5.65 s | 54.09 s | 393 / 858 | 0 | 0 | timeout |
| c5 | tiprouter | gemini-3.8-flash | 0/3 | - | - | - | - / - | 0 | 0 | http |
| c6 | sub2api-mimo | mimo-v2.5 | 0/3 | - | - | - | - / - | 0 | 0 | http |
| c7 | sub2api-codex | glm-5.2 | 0/3 | - | - | - | - / - | 0 | 12 | rate_limit |
| e1 | sub2api-agy | gpt-oss-120b-medium | 6/6 | 2.17 s | 2.25 s | 2.40 s | 0 / 0 | 0 | 0 | - |
| e2 | sub2api-agy | tab_flash_lite_preview | 0/6 | - | - | - | - / - | 0 | 0 | invalid |

Reasons for replacement: `kimi-k2.6` is a reasoning model (28,683 reasoning tokens, median 25.5 s, 5 of 20 exceeded `timeout_s: 30`); `mimo-v2.6-flash` and `mimo-v2.5` on sub2api-mimo answered 502 "Upstream authentication failed" then 503; tiprouter 503 `platform_unavailable` (also `GET /models`); sub2api-codex 429 "Upstream rate limit exceeded" on `glm-5.2` (12 occurrences of 429 including retries, never succeeded); lucif had one of three calls time out (54 s); `gpt-oss-120b` on experientiallabs is slow and once returned `noul` instead of a number; `tab_flash_lite_preview` does not produce JSON. On these rows there are only 3 or 6 cases, so they only show viable or not viable, not a validity rate.

### Item 4: real quorum

Real aggregator (`SwarmRunner`, weighted median, quartile spread, quorum 5 of 7, option order shuffled) with real voters, 20 decisions, 3-second interval between decisions, all active voters run concurrently and each voter is on its own key (`quorum_1.json`, `quorum_2.json`, per-voter logs `*.voters.jsonl`).

| Round | Voters | Decisions passed | Voters dropped | Decision latency (median / p90) |
| --- | --- | --- | --- | --- |
| 1: seven `llm_structured` voters from seven providers | v1 through v7 | 18 of 20 | 1 answer (v3 on case `api-outage`: "model output is not valid JSON"); that decision still passed with 6 of 7 | 6.91 s / 9.21 s |
| 2: three decision voters + four `llm_structured` | d1, d2, d3, v1, v2, v4, v5 | 20 of 20 | 0 | 6.69 s / 10.13 s |

Two decisions in round 1 had status `skip` with reason `choice_tie:direction` (cases `funding-flip` and `week-open`): all seven voters answered, but the votes split 3/2/2 and the median of the one-hot ballots does not yield a single winner. That is the aggregator behavior designed in Item 2 (fail-closed), not a voter failure. In round 2 there were no ties because the decision voters send probabilities, so the per-option medians differ. Decision latency is determined by the slowest voter: v5 (gemini via omniroute, median 6.7 s to 6.8 s).

### Measured intervals and rate limits

- One voter per key with a 3-second interval after each call: 0 occurrences of 429 across 7 voters and 3 decision voters, 20 cases each (the only 429 in the whole test came from sub2api-codex `glm-5.2`, which was rejected upstream anyway).
- Seven voters from seven keys concurrently every 3 seconds for 20 decisions: 0 occurrences of 429 (`quorum_1.json`, `quorum_2.json`).
- Load test of seven parallel calls on one key, three rounds, 5-second interval between rounds (`burst_1.json`):

| Voter | Provider | Round 1 | Round 2 | Round 3 |
| --- | --- | --- | --- | --- |
| d1 | experientiallabs-systemone | 7 ok, 3.64 s | 7 ok, 1.77 s | 7 ok, 1.05 s |
| d3 | experientiallabs-decisions | 7 ok, 1.54 s | 7 ok, 2.73 s | 7 ok, 1.54 s |
| v6 | experientiallabs (`llama-4-maverick`) | 7 ok, 3.47 s | 6 ok 1 invalid, 4.59 s | 7 ok, 2.79 s |
| v2 | modelrouter | 7 ok, 3.66 s | 7 ok, 3.81 s | 7 ok, 3.40 s |
| v1 | nutaraline | 7 ok, 7.00 s | 7 ok, 3.05 s | 4 ok 3 `rate_limit`, 4.00 s |

Only nutaraline returned 429, in round 3 after 14 requests had completed in about 20 seconds. The exact threshold has not been determined; two rounds of seven parallel requests were accepted. Operational conclusion: do not run more than one voter on a nutaraline key per decision, and if several voters per key are needed, use a provider other than nutaraline or a 3-second delay. One llama answer was invalid in round 2 of the v6 load test (the reason was not stored in the load report).

### Item 5: localhost providers from the host and from a container

`GET /v1/models` five times and one small call (`max_tokens: 16`) five times per provider with urllib (`local_host.json`, `local_container_hostnet.json`, `local_container_bridge.json`); the container uses the image `trading-bot/engine:dev` with a 512 MB memory limit:

| Provider | From host (median POST) | Container `--network host`, 127.0.0.1 | Container bridge, `host.docker.internal` (host-gateway) |
| --- | --- | --- | --- |
| sub2api-claude :62173 | 5/5 ok, 1.49 s | 5/5 ok, 1.61 s | 0/5, URLError |
| sub2api-agy :62173 | 5/5 ok, 0.90 s | 5/5 ok, 0.48 s | 0/5, URLError |
| omniroute :20128 | 5/5 ok, 2.26 s | 5/5 ok, 2.54 s | 0/5, URLError |

The difference between host and container `--network host` is within the range of upstream variation (the first call per provider is slower, for example 4.76 s on sub2api-agy from the container). The bridge path with `host.docker.internal` does not reach services that only listen on the host's 127.0.0.1, same as the README note; so the bot in Docker uses `network_mode: host`. The Docker Desktop path on Windows remains untested.

### Example configuration

`config/config.example.yaml` now contains nine providers and ten voters: seven active `llm_structured` voters (v1 to v7, seven providers and seven model families, quorum 5 of 7) and three inactive decision voters (d1 `jev-latest`, d2 `clef-flash`, d3 `gpt-6-luna-decisions`) that can be selected via `enabled: true` or `--voters`. Base URLs are written directly (no longer `from_import`) because all of them have been measured; `timeout_s: 30` is sufficient for all active voters (measured maximum 11.7 s, v5). Reasoning models such as `kimi-k2.6` need a much larger `timeout_s` and are not used.

### How to re-run Stage 0c

```sh
cd swarm
.venv/bin/python bench/probe_decision_wires.py --out /tmp/wire_probe.json
.venv/bin/python bench/live_voters.py single --voters v1,v2,v3,v4,v5,v6,v7,d1,d2,d3 --interval 3 --out /tmp/single.json
.venv/bin/python bench/live_voters.py quorum --cases 20 --interval 3 --log /tmp/quorum.voters.jsonl --out /tmp/quorum.json
.venv/bin/python bench/live_voters.py quorum --voters d1,d2,d3,v1,v2,v4,v5 --min-voters 5 --out /tmp/quorum_decisions.json
.venv/bin/python bench/live_voters.py burst --voters d1,d3,v1,v2,v6 --parallel 7 --rounds 3 --interval 5 --out /tmp/burst.json
```

`.env` at the repo root is read automatically; the script does not print keys.

## Not yet proven

1. That `json_object` and `json_schema` are enforced on the server side: on 20 samples the `prompt` mode was also 20/20 valid, so no difference can be attributed to enforcement.
2. The exact per-key rate limit threshold on the nutaraline gateway. Stage 0c measured that seven parallel calls on one nutaraline key were accepted for two rounds and then produced 3 of 7 responses with 429 in the third round; the threshold figure (requests per second or per minute) remains unknown.
3. Decision quality of the model: 20/20 valid means the answer shape is correct, not that the answer is right. There are no ground-truth labels.
4. The authentication scheme and path of OpenRouter Decisions: only from documentation, not tested live (no OpenRouter key). System One and OpenAI Decisions are proven live on Experiential Labs in Stage 0c (Bearer, `/v1/systemone`, `/v1/decisions`); neither has been tested directly against TypeSafe.
5. Kronos accuracy: deliberately not concluded, and the data is synthetic.
6. Daily swarm cost: nutaraline responses do not carry `usage.cost`, so there is no monetary figure yet.

## How to re-run

```sh
cd swarm
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . --group dev
.venv/bin/python -m pytest
.venv/bin/python bench/bench_voter_overhead.py --samples 30
heavy --kind other --label <label> -- <venv kronos>/bin/python bench/bench_kronos.py \
  --kronos-src <checkout Kronos> --sample-count 8 --repeats 10
```
