# Final plan for a 24-hour autonomous trading bot (revision 10)

Drafted 2026-10-25 after in-depth research (the research-swarm-pwa document). Directives from the owner that are fulfilled: capital of Rp 2 million; profit goes back into capital; analysis uses news and social; demo first; decision model (System One) as a fast aid for the LLM and must support many models, not only Jev; analysis with a swarm and median; runs on all OSes, mobile via PWA. No code, accounts, or money have been touched yet.

## Revision history

Changes in revision 4 (the owner's directive 2026-10-25): (1) all settings are made configurable; (2) the LLM backend uses deepagents so any provider can be used; (3) the default loss limits follow the operator's proposal and remain configurable; (4) the plan PDF along with mockups is done by the team first, before the stage 0 and 1 tasks.

Changes in revision 5 (the owner 2026-10-25): LLM compute cost is not a constraint because the owner has many AI providers; the priority is the bot's maximum capability. The cost limit remains available in configuration but is off by default.

Changes in revision 6 (the owner 2026-10-25): the AI providers used are those active in omp models.yml; the list and findings are in section 4.3.

Changes in revision 7 (the owner 2026-10-25): (a) the bot runs on the owner's own PC; (b) test model: deepseek-v4.1-flash-1017 on the nutaraline provider for all LLM roles during testing; (c) there is a provider and key setup UI, and the operator arranges key storage to be secure (section 4.5); (d) the UI/UX must be unique, not AI slop, using the impeccable skill (section 12); (e) the project is stored in ~/Projects with git (section 11).

Changes in revision 8 (the owner 2026-10-25): the application is built full-featured, including live charts, live actions, and live preview; the must-have and nice-to-have feature list follows the operator's suggestions (section 13).

Changes in revision 9 (the owner 2026-10-25): (a) secrets do not need to go too deep: the API key may come from an environment variable or directly in the config; the keyring is dropped (section 4.5); (b) Freqtrade is vendored via a git submodule so modification is easy and flexible (section 11); (c) the person using the application is the owner on their own PC, and the visual theme follows the operator's decision; (d) full-autonomy mode: after the plan is finished, the work runs to completion without waiting for approval at each step, with the owner correcting along the way (24-hour autonomy window).

Changes in revision 10 (the owner 2026-10-25): (a) destructive actions are permitted ("full autonomy destructive true"); real money and pushes to the remote remain outside what the operator does on their own; (b) the visual direction is decided by the operator and written in PRODUCT.md and DESIGN.md (section 12); (c) the stage 0 and 1 tasks are created (section 8).

## 1. Honest statement about results

- Profit every day cannot be guaranteed. What is guaranteed is the limit: the bot stops opening new positions if the daily loss exceeds the limit.
- Rp 100 thousand per day requires 5% per day on Rp 2 million: not realistic. 0.1% per day = Rp 2,000, 0.3% = Rp 6,000 (compounding 0.1% per day over a year = +44%, already ambitious). The goal of the early stage is to prove the system, not to earn income.
- The swarm and median are a measured filter, not an assumed source of profit. I have not found evidence that an ensemble raises trading profit; the evidence that exists is for event prediction, not prices (details in the research document).
- Indodax costs: 0.2% fee (public API 2026-10-25) and 0.21% tax (secondary source), so one buy-sell cycle costs 0.61-0.82%. The strategy must be profitable on average above that per trade, so swing 1-4 hours, not scalping.

## 2. Architecture

One machine, four layers, one control panel:

1. Engine: Freqtrade (Python) runs on the owner's PC (native Windows, Docker, or WSL2; the choice is discussed in sections 4.5 and 10). A 1-4 hour swing rule strategy produces entry candidates. Profit becomes capital again via stake_amount "unlimited" with tradable_balance_ratio 0.99 (verified in the Freqtrade documentation).
2. Swarm (filter only): a set of diverse voters answers questions of the same type; the results are combined with the median. It may only cancel or reduce entries. It never adds risk and never touches exits and stop loss.
3. Deterministic risk layer: risk per trade, daily and total loss limits, kill switch, position sizing. It does not pass through AI.
4. Orders and exits: deterministic. The stop loss runs on the bot's side (Indodax is not documented as supporting stoploss on exchange), so the PC must always be on and a tight loss limit matters more.
5. System 2: a large LLM acting as the operator is used only for daily review and strategy research outside the order loop.
6. Control panel: PWA (section 6).

## 3. Swarm and median

Two groups of voters, two tasks:

A. Decision model voters (typed questions on the state: indicators, tagged news, Fear and Greed):
- noul: whether this entry is aligned with the latest news; whether there is risk news (regulation, exchange hack, macro).
- score: news sentiment on an ordinal scale.
- choice: allow, reduce, or skip.
B. Price path voters (shadow first): Kronos (MIT; mini, small, base are open), one general time series foundation model, and a FreqAI (LightGBM) model. Each gives a return forecast for the entry horizon.

Aggregation (initial proposed values, to be re-determined from shadow data, not tuning results):
- Each voter A is run with the option order shuffled (option order has been shown to change results in a single-model report: 72% vs 21%).
- Combine with the median probability and measure the spread (interquartile range). A large spread means the voters disagree: skip.
- Quorum: at least 5 of 7 voter A must answer; fewer than that, the new entry is skipped (fail-closed).
- Voter B: an entry passes only if the median return forecast is above the cost threshold (0.82% + margin) and the majority point the same direction.
- The initial weights are equal for all voters. Weights are not tuned from small data (overfitting risk). A voter whose calibration is poor in forward testing is removed, not given a new weight.
- Diversity: different vendors and model families, because voters whose errors are correlated repeat the same mistakes.

## 4. Support for many decision models (not only Jev)

A DecisionProvider interface with adapters:
1. System One wire (/v1/systemone): Jev (TypeSafe), Solar Decide, Hanzo Kai, and all servers that imitate that wire. Ollama (native since 0.35.0) and vLLM serve it locally for open-weight models (Clef, d1, Tev1, pplx-decider, and others).
2. OpenRouter Decisions API (POST /api/alpha/decisions, alpha): one OpenRouter API key, one account bill.
3. OpenAI Decisions API (its own shape).
4. Fallback regular LLM with structured output (103 cheap structured models on OpenRouter, 11 free) via an adapter that imitates choice, noul, score; AnyJev (Nokia, Apache 2.0) as a reference for how to turn an LLM into a decision model.

The voter registry is a configuration file: model, adapter, price, timeout, health status. A voter that fails or is slow is dropped for that decision; the quorum determines the result. Adding a new model means adding one line of configuration, not code. The decision model catalog on OpenRouter is fetched in stage 0 using the API key.

### 4.1 LLM backend: deepagents

Verified today: deepagents (langchain-ai/deepagents) MIT license, PyPI version 0.7.32 (uploaded 2026-10-23), Python 3.11 or later. Models are written in provider:model format, for example openai:gpt-5.4 or anthropic:claude-sonnet-4-6 (examples from the documentation); all LangChain models that support tool calling can be used, including OpenRouter and Ollama (deepagents documentation). So the provider is swapped via a single configuration string.

Division of roles:
- System 2 analyst agent (daily review, strategy research, decision explanations): deepagents with the model from configuration. Its tools are read-only (metrics, trade history, voter logs). No tool can create an order or change configuration.
- Fast voters: via the DecisionProvider adapter. The fallback LLM adapter uses the same provider:model string via LangChain with structured output.
- There is no figure yet on whether the deepagents harness (planning, filesystem, context) adds latency and tokens per voter decision. It is measured in stage 0. If the difference is small, everything goes through deepagents; if large, fast voters use direct calls and deepagents is only for the analyst agent. The decision comes once the figures are out, and both remain purely a configuration setting.

Security note from an earlier review (deepagents 0.7.13, not re-tested on 0.7.32): a sub-agent with no tool list inherits all of its parent's tools, and safety rules that exist only in the parent's system prompt do not reach the sub-agent. Therefore the risk limits must not depend on the prompt: they are enforced in code (strategy, gateway), and the LLM agent is not given any tool that can place orders. Re-test in stage 0 before the analyst agent is installed.

### 4.2 Everything configurable

A single YAML configuration file. The API key may come via an environment variable (api_key_env) or directly in config/config.yaml (api_key); config.yaml and .env are in .gitignore and do not enter the repo. The file is schema-validated at start; a wrong configuration means the bot does not start, rather than running on guessed values. The values below are the operator's proposed defaults, all of which the owner can change.

```yaml
mode: dry_run                     # live requires two-step confirmation
capital:
  initial_idr: 2000000
  compounding: true               # stake_amount unlimited, tradable_balance_ratio 0.99
risk:
  max_daily_loss_pct: 1.0         # Rp 20.000 on capital of Rp 2 million
  max_total_drawdown_pct: 10.0    # Rp 200.000
  risk_per_trade_pct: 0.5         # Rp 10.000
  max_open_trades: 3
  leverage: none                  # spot only
  on_breach: stop_new_entries     # kill switch
exchange:
  name: indodax                   # Freqtrade support not yet proven, tested in stage 0
  pairs: [BTC/IDR, ETH/IDR, SOL/IDR]
  timeframe: 1h
providers:
  - id: nutaraline
    type: openai-completions       # openai-completions, openai-responses, anthropic-messages
    base_url: from_import          # taken from omp models.yml, ends with /v1
    api_key_env: NUTARALINE_API_KEY   # environment variable name; or fill in api_key below
    api_key: null                  # may be filled in directly in the local config.yaml (not committed)
    models: [deepseek-v4.1-flash-1017]
swarm:
  enabled: true
  mode: shadow                    # shadow or veto; veto only after the adoption criteria pass
  shuffle_options: true
  min_voters_answered: 5
  max_spread: tbd                 # set from shadow data in stage 0
  voters:
    - id: v1
      adapter: llm_structured      # systemone, openrouter_decisions, openai_decisions, llm_structured
      provider: nutaraline
      model: deepseek-v4.1-flash-1017
      variation: option_order     # option_order, temperature, prompt_variant
      timeout_s: 30               # initial number, measured in stage 0
      weight: 1.0
      enabled: true
llm:
  backend: deepagents
  analyst_model: nutaraline:deepseek-v4.1-flash-1017   # bot provider id : model; test model
compute:
  max_cost_idr_per_day: off       # off by default; fill in a number to set a limit
  on_exceed: skip_new_entries     # applies only when a limit is set
  log_cost: true                  # cost and tokens are recorded as information
data:
  news_rss: [coindesk, cointelegraph]
  fear_greed: true
  social: off                     # enabled after Reddit access is verified
notify:
  web_push: true
```

Configuration change rules:
1. Every change is logged: who, when, old and new value.
2. From the PWA, lowering a risk limit takes effect immediately. Raising a risk limit or switching to live mode requires two-step confirmation. The decision to raise a limit stays with the owner.
3. Adding or replacing voters and LLM backends only changes configuration, not code.
4. Switching the swarm mode from shadow to veto happens only after the adoption criteria in section 8 are met or the owner decides otherwise.
5. Freqtrade's built-in Protections have not been confirmed from the documentation, so the daily loss limit is implemented and tested by ourselves in stage 0.
6. Position sizing based on risk_per_trade_pct is applied through custom_stake_amount in the strategy (this callback is mentioned in the Freqtrade documentation); the detailed design is in stage 0.

### 4.3 AI providers the owner already has (from omp models.yml)

Read on 2026-10-25 from ~/.omp/agent/models.yml. Only the provider name, API type, host, and model ids were taken. API keys are not copied into this document; keys are supplied through environment variables or local config (section 4.5).

| Provider | API type | Host | Number of model ids |
|---|---|---|---|
| sub2api-codex | openai-responses | localhost:62173 | 18 |
| sub2api-agy | openai-completions | localhost:62173 | 21 |
| sub2api-claude, sub2api-claude-kaitech, sub2api-claude-all | anthropic-messages | localhost:62173 | 7 each |
| sub2api-mimo | openai-completions | localhost:62173 | 8 |
| omniroute | openai-completions | localhost:20128 | 20 |
| xai-hm | openai-responses | gateway.example.com | 17 |
| modelrouter | openai-completions | modelrouter.id | 23 |
| tiprouter | openai-completions | tiprouter.my.id | 18 |
| nutaraline | openai-completions | nutaraline.co.uk | 23 |
| lucif | anthropic-messages | lucif.ai | 2 |
| experientiallabs | openai-completions | api.experientiallabs.ai | 272 |

Total 13 providers and 443 model ids (some of the same ids appear on several gateways).

Findings:
1. Model families are diverse by id (number of providers that list them): Claude 8, Gemini 6, GPT 5, DeepSeek 5, GLM 5, Nemotron 5, Mimo 5, MiniMax 4, Hunyuan 4, Kimi 3, Step 3, Solar 3, Longcat 3, Qwen 2, plus Mistral, Llama, Grok, and Cohere on one provider each. Swarm voters are chosen per model family, not per gateway: the same id on two gateways is not necessarily a different model, and it is not two independent voters ([INFERENCE]).
2. Decision models already exist on the owner's providers by model id: jev-1.13 on modelrouter; jev-latest, clef, clef-flash, and gpt-6-luna-decisions on experientiallabs. It is not proven that these gateways serve a decisions endpoint or /v1/systemone rather than only chat completions; this is tested in stage 0 with a key supplied by the owner. The ids mercury-2 and mercury-3 on experientiallabs are probably ordinary chat models, not Mercury Decide; not yet verified.
3. models.yml does not include OpenRouter. So an OpenRouter API key is no longer mandatory; the OpenRouter Decisions adapter is still supported as an option.
4. Three API types appear: openai-completions, openai-responses, anthropic-messages. The llm_structured adapter must support all three. Custom base URL support for all three through LangChain and deepagents has not been verified from the documents I read; tested in stage 0 ([INFERENCE]: the OpenAI and Anthropic chat classes accept a custom base URL).
5. 7 of the 13 providers are addressed at localhost (sub2api-*, omniroute): reachable only from the owner's PC. The bot runs on the owner's PC (decided 2026-10-25), so localhost providers are reachable. If the bot is ever moved to a VPS, voters on localhost providers will not be reachable unless there is a tunnel. The other 6 providers have public addresses (xai-hm, modelrouter, tiprouter, nutaraline, lucif, experientiallabs).
6. Some gateways appear to be third-party; I do not know each gateway's availability and policies. The quorum design and discarding failed voters (section 3) exist for exactly this reason. Voters are spread across more than one gateway so that one gateway going down does not break the quorum.
7. The voter registry stores the environment variable name for the key (api_key_env), or its value in a local config.yaml that is not committed.

### 4.4 Test model (decided by the owner 2026-10-25)

During testing all LLM roles (the analyst agent and all voters) use deepseek-v4.1-flash-1017 on the nutaraline provider. From models.yml (non-secret fields only): name "DeepSeek V4.1 Flash 1017 LoRA (nutaraline)", API openai-completions, base URL ending in /v1, auth apiKey, reasoning enabled, contextWindow 1,048,576, maxTokens 384,000.

- Because reasoning is enabled, latency and tokens per decision may be larger than with a non-reasoning model. The initial voter timeout of 30 seconds is a proposed figure, measured in stage 0.
- Structured output support for this model is not yet proven. Tested in stage 0. If it is absent, the llm_structured adapter uses JSON output validated against a schema, and invalid answers are counted as a failed voter (quorum).
- One model for all voters means voter errors are correlated. In the testing phase the swarm only tests the engine and adapters, not the value of the swarm. Diverse voters are enabled after the engine passes.
- The provider:model format in the configuration uses the bot's own provider id (nutaraline). The backend translates it to the LangChain integration: openai-completions becomes the OpenAI chat class with a custom base_url ([INFERENCE], tested in stage 0).

### 4.5 Provider and key setup (UI) and storage

The owner (revision 9): secrets do not need to be handled too deeply; env or directly in config is fine. The earlier decision (keyring and Credential Locker) is cancelled; as a result, the choice of native Windows or Docker no longer depends on key storage.

UI (Provider screen):
- Provider list: name, API type, host, last test status, active model.
- Add or edit provider: API type, base URL, model list.
- Key field: written to config/config.yaml (api_key) or, if a variable name is entered, read from the environment (api_key_env). After saving, the display shows only the last 4 characters.
- Test connection button: one small call, shows latency and result.
- Choose provider and model per role (analyst agent, each voter).
- Import from omp models.yml: read locally by the app on the PC (name, API type, base URL, models; key only if ticked per provider).

Simple rules that still hold:
1. config/config.yaml and .env are in .gitignore; secret scanning of the staged diff runs before commit.
2. No endpoint returns a full key; keys are not written to logs (logs filter Authorization and token patterns).
3. The LLM agent (deepagents) is not given any tool that reads config or .env.
4. Entering or replacing a key is done only from the PC (localhost), not from the remote PWA; the remote PWA only shows status, active or inactive, and connection test.

Consequence accepted by the owner: the key in config.yaml is stored as plain text on the PC's disk. This is sufficient for a personal bot on one's own PC; if the repo or that file is ever copied out, the key must be considered leaked and replaced. The operator's recommendation: use env if comfortable, config if practical.

How to run on the PC: the Freqtrade documentation recommends Docker for Windows (easier and safer), then WSL2; native via setup.ps1 (Python 3.12 or newer, 64 bit) if really needed. The operator's current recommendation: Docker, because the reason for choosing native (keyring) no longer applies. One thing tested in stage 0: localhost providers (sub2api, omniroute) from inside the container must go through host.docker.internal or the host network ([INFERENCE], not yet tested). If that is troublesome, native Windows or WSL2 becomes the option.

## 5. Data sources

- News: RSS CoinDesk (25 items) and Cointelegraph (30 items), read 2026-10-25; no historical archive.
- Fear and Greed Index (alternative.me): 3,185 daily values since 2018-02-01, free, attribution of the source required.
- Social (Reddit, X): access and cost not yet verified; Reddit is tried first in stage 0.
- Prices: public exchange data via Freqtrade; dry-run needs no API key or account.

## 6. All OS and mobile (PWA)

- The engine runs on the owner's own PC (decided 2026-10-25). The bot is not run on a phone (phones restrict background processes; [INFERENCE]). Consequence of the PC: the stop loss lives on the bot side, so if the PC is off, asleep, restarted (for example by Windows Update), or the internet drops, open positions are unprotected. Proposed mitigations: dry-run first (no risk); live only after the PC is set to no sleep and no automatic restart; a heartbeat from the bot to a monitor outside the PC that sends a notification if the heartbeat stops (monitor service not yet chosen); on restart, the bot checks open positions and the loss limit first before opening new positions.
- The Freqtrade API stays on localhost and is not exposed to the internet (documentation warning). Between the PWA and the engine there is a small self-built gateway: authentication, read endpoints, kill switch, Web Push sender. The gateway is accessed through an HTTPS tunnel (proposed Cloudflare Tunnel with Access, or a private network), not an open port. The owner already has a Cloudflare named tunnel for a subdomain of a personal domain (internal skill notes), so the gateway can use it once approved; not done now.
- PWA: dashboard (profit, open positions, daily loss meter, each voter's vote, median, spread) and notifications. FreqUI is not a PWA (no manifest and service worker), so the PWA is built ourselves. Android and desktop: installed from the Chrome or Edge browser (desktop installation not yet verified). iOS: iOS 16.4 or newer, must be added to the Home Screen, push permission is requested via a button tap, notifications must be visible.
- Dangerous actions from the phone (live mode, raising limits) require two-step confirmation. The first version of the panel is read-only plus notifications; controls follow after the gateway is tested.
- Windows: three ways to run Freqtrade: Docker (recommended by the documentation), WSL2, or native via setup.ps1. Current recommendation Docker (section 4.5).

## 7. Compute cost (not a constraint)

The owner's direction: LLM cost need not be worried about too much because there are many AI providers; what matters is that the bot can be maximal.

- compute.max_cost_idr_per_day remains in the configuration, off by default. If it is filled in someday and exceeded, behavior follows compute.on_exceed (default: skip new entries).
- Cost and tokens are still recorded as information in the log and PWA. Recording does not limit anything.
- Consequence: voters may use larger models and the number of voters may exceed 7 (the voter list is only configuration). The practical limit shifts from money to latency and each provider's rate limit. For a 1-4 hour strategy, latency of a few seconds per decision is probably still acceptable ([INFERENCE]); measured in stage 0.
- A larger or more expensive model is not automatically more accurate. Vendor diversity and voter calibration are still tested in the forward test before the swarm may cancel entries (adoption criteria in section 8).
- The earlier estimate (7 cheap voters, about Rp 380 per day at a price of 0.04 dollars per million tokens) is only a comparison; cost with large models has not been measured.

## 8. Stages and pass criteria

| Stage | Content | Pass criteria (proposed) |
|---|---|---|
| 0. Setup (1-2 days) | Freqtrade dry-run (Docker or VPS), test Indodax via CCXT, spike the DecisionProvider adapters (the owner's gateway: jev and clef on modelrouter and experientiallabs, one plain chat model through llm_structured; local Ollama and OpenRouter optional), test the test model deepseek-v4.1-flash-1017 on nutaraline (structured output, latency, reasoning tokens), test running the Freqtrade submodule in Docker and native Windows (including reaching the localhost provider from the container), fetch the decision model catalogue, test Kronos mini on CPU, set the default loss limits through configuration, measure voter latency and tokens through deepagents compared with direct calls | Dry-run runs with Indodax data without errors; at least 3 adapters answer the same question |
| 1. Week 1 demo | Dry-run for 7 days non-stop. Bot A rules only; bot B rules plus swarm in shadow mode (logging only). The read-only PWA shell and notifications are built in parallel | Engine stable for 24 hours, no failed orders, costs and tokens recorded. This is an engine test, not proof of profit |
| 2. Weeks 2-4 | Backtest the rule strategy over 2-3 years (without news signals), dry-run continues, swarm evaluated in forward test | Positive expectancy after fees and tax on out-of-sample data; swarm adoption criteria below |
| 3. Small live, at least 4 weeks | Proposed initial allocation Rp 500 thousand (25%), because fees and minimum orders make a 5-10% allocation too small to measure | No breach of the loss limits; difference from dry-run is reasonable |
| 4. Scale up gradually | Add capital in steps, monthly review | monthly review |

Swarm adoption criteria as a gate (after at least 4 weeks in shadow and at least 30 veto decisions; final numbers set in stage 0): (a) trades that would be cancelled are on average more losing than those allowed; (b) net profit or drawdown of bot B is better than bot A after fees and tax; (c) compute cost is recorded as information, not a requirement (the owner's directive). If not met, the swarm remains a report only.

During testing all voters use the same test model (deepseek-v4.1-flash-1017), so the swarm in that phase only tests the engine and adapters, not the value of the swarm: errors from the same model are correlated. Diverse voters are enabled after the engine passes.

One week of demo only tests the engine; a 1-4 hour strategy produces few trades per week (the number is measured in backtest), so it is not yet enough to judge profit and loss. Real money is proposed after at least 4 weeks of dry-run.

## 9. What is not used and why

- MiroFish and MiroShark: social simulation wastes tokens, AGPL-3.0 license, no public accuracy benchmark that I found. Not core; may be tried later for news scenario exploration.
- Scalping, tight grids, and leverage: costs of 0.61-0.82% per cycle eat the margin; leverage increases risk.
- A large LLM swarm inside the order loop is no longer excluded because of cost (the owner's directive). The only condition is passing the latency and calibration tests in stage 0 and the forward test. The LLM does not hold exit, stop loss, and risk limits.

## 10. Decisions

Already decided by the owner: the bot runs on his own PC; test model deepseek-v4.1-flash-1017 on nutaraline; provider and key setup UI with secure storage arranged by the operator; UI/UX must be unique (not AI slop) using impeccable; project in ~/Projects with git; LLM compute cost is not a constraint (default cost limit off); capital Rp 2 million; profit is reinvested as capital; demo first; everything configurable; LLM backend deepagents; default loss limits as proposed (1% per day, 10% total, still configurable); the PDF plan along with mockups is made first by the team.

Still needed from the owner: nothing blocks the work. Full-autonomy mode (revision 9): the operator decides on his own and the owner corrects along the way. Decisions the operator has taken that can be corrected:
1. The stage 0 and 1 tasks are created after this plan (previously waiting for approval; now covered by full autonomy).
2. The theme and visual direction are decided by the operator (section 12), not the result of an interview.
3. How to run on the PC: Docker first (section 4.5), tested in stage 0.
4. The repo stays local with no remote and no LICENSE until the owner decides (push and license are not part of the autonomous window).
5. Exchange for the live stage: not needed for the demo; live does not start without the owner's explicit approval (real money is outside the autonomous window).

## 11. Project and git

- Location: ~/Projects/trading-bot (working name, easy to change). Branch main. Commit identity follows ~/.gitconfig (the owner), without Co-Authored-By.
- Freqtrade as a git submodule at vendor/freqtrade (the owner's directive, revision 9): url https://github.com/freqtrade/freqtrade.git, branch stable, shallow, pinned at commit 1f394eae which is tag 2026.9 (commit 568b46b). Strategy, configuration, and user data live outside vendor via --strategy-path and --userdir (Freqtrade docs), so the contents of vendor are not modified. If the engine ever needs modification: fork Freqtrade and change the url in .gitmodules to the fork. Updating the version: fetch the new tag in the submodule, checkout, commit its gitlink (steps are in the README).
- Size: the shallow submodule is about 58 MB of working files and 41 MB of git data (measured when installed).
- Already in the repo: README, .gitignore, .gitattributes, .editorconfig, .env.example, git hooks, example configuration without comments, copies of the plan and research in docs/. PRODUCT.md and DESIGN.md (seed) from impeccable. The impeccable skill link in .agents/skills is not committed.
- Created in stage 0, not yet present: Freqtrade strategy, gateway, DecisionProvider adapters and voters, deepagents analyst agent, PWA, docker-compose.
- Commits: Conventional Commits in English, subject under 72 characters. The commit-msg hook rejects wrong formats and Co-Authored-By trailers. The pre-commit hook runs the comment gate on our code (the owner's rule: no comments); the contents of vendor/freqtrade are third-party code and are not checked.
- Branches: main and feature branches (feat/..., fix/...). Worktrees via ~/Projects/.worktrees.
- Tests: the repo has no CI, so the full suite runs locally at most once per final SHA before push; during development only the related tests (the owner's rule).
- Tools: Python 3.12 or newer with uv; deepagents; the PWA framework is chosen in the design stage.
- Secrets: config/config.yaml, .env, user_data, databases, and logs are not in the repo (.gitignore).
- Remote and license: no remote yet and no LICENSE yet. Freqtrade is licensed GPL-3.0; a strategy that imports Freqtrade is likely bound as well ([INFERENCE], needs legal assessment if the repo will be opened). Recommendation: private repo, no LICENSE, until the owner decides.

## 12. Unique UI/UX with impeccable

The owner: UI/UX must be unique and must not look like AI slop; the impeccable skill is prepared.

Status (2026-10-25, full-autonomy mode): PRODUCT.md and DESIGN.md (seed) have been written in ~/Projects/trading-bot and committed (54ed647). The owner delegated the theme to the operator and did not answer the interview; so the contents of both are the operator's decisions, corrected by the owner along the way. The impeccable skill is linked to the project (.agents/skills, not committed); context.mjs now reads PRODUCT.md.

Register: product. User: the owner only, on the PC (configuration, analysis) and on the phone (glance, notifications, in harsh daylight and at midnight).

Visual direction decided (details in DESIGN.md):
- Creative North Star: a station information board meets a seismograph paper strip. One big answer readable from afar (safe, held, stopped) and one trace line about what just happened.
- Theme: light as the default (highest contrast under the sun), dark following the system setting for the night; both are designed.
- Color: Restrained strategy. One warm signal color (seed seed-041 from palette.mjs for the key trading-bot, oklch(0.673 0.217 38.6)) only for loss, limits, warnings, and the kill switch. Profit uses dark blue. The blue and orange pairing is chosen because it stays distinguishable for red-green color blindness; every number also carries a plus or minus sign and a direction. The primary button uses ink. No cream or sand band.
- Typography: one technical sans family with mandatory tabular figures; the concrete family is chosen at implementation after confirming it supports tabular figures. Fixed scale.
- Flat, no wide shadows; motion of 150 to 250 ms only for state changes.
- Forbidden: Binance or Robinhood style, gamification, hero-metric template, generic AI dashboard, default FreqUI and Nuxt UI look.
- Quick test: if the screen is immediately guessed to be a "trading dashboard" from color and shape alone, the direction has failed.

Anti-slop rules from the skill that apply to this project:
- No hero-metric template (big number, small label, supporting stats, gradient accent): a profit dashboard is usually exactly that, so it must be avoided.
- No repeated grid of identical cards, nested cards, glassmorphism, gradient text, small capital eyebrow on every section, 01/02/03 numbering as scaffolding, 1px border together with wide shadow, card radius above 12-16px, sketch SVG illustrations, diagonal line backgrounds.
- Dark or light theme is not a default: one sentence of physical scene (who, where, what light) is written before choosing. Colors in OKLCH, text contrast at least 4.5:1.
- Product: one font family is enough, fixed type scale (not fluid), every component has default, hover, focus, active, disabled, loading, error states; skeleton instead of spinner; teaching empty states; modal is not the first choice; motion of 150-250 ms only to convey state; prefers-reduced-motion mandatory.
- Two-level category-reflex test: level one, the easily guessed trading dashboard is a dark theme with neon green and red plus candlestick charts; level two, terminal-native dark mode. The chosen direction must pass both.

Color and profit-and-loss semantics: not just red and green (color blindness). Add plus and minus signs, arrow direction, position, and text. The primary button uses ink, and the signal color is only for risk, so that it does not clash with profit and loss semantics. The color seed has been taken: palette.mjs --from trading-bot gave seed-041, used as the risk signal color.

Screens designed: Dashboard, Live chart, Live actions, Preview, Swarm, Configuration, Providers and keys, Kill switch and two-step confirmation, notifications, install the PWA on iOS. The Providers and keys screen follows section 4.5; in the remote PWA the key field is absent, only status, active or inactive, and connection test.

Process: impeccable shape then craft for each screen; critique and audit before release; detect.mjs (the skill's built-in pattern detector, runs locally) is read before committing UI; results are viewed via screenshots at phone and desktop sizes.

## 13. Full features (must-have and nice-to-have)

The owner: full-featured app (live chart, live actions, live preview), following the operator's suggestion. The basis of each feature was checked against the Freqtrade docs on 2026-10-25: REST API (/status, /trades, /balance, /profit, /daily, /weekly, /monthly, /exits, /entries, /mix_tags, /stats, /performance, /pair_candles, /pair_history, /plot_config, /health, /sysinfo, /logs, /pause, /start, /stopbuy, /stop, /forceexit, /locks, /blacklist) and WebSocket messages at /api/v1/message/ws (subscribe whitelist, analyzed_df, plus fill messages). Features marked custom are built in the gateway and PWA ourselves.

The operator's interpretation of "live preview" (correct if the owner means otherwise): (1) preview of entry candidates together with voter answers before an order is sent, and in shadow mode showing what would happen; (2) what-if preview of configuration before it is applied; (3) preview of strategy signals on the chart.

### Must-have

| Feature | Basis | Stage |
|---|---|---|
| Live chart per pair: candlesticks, entry and exit markers, indicator overlays | /pair_candles, WebSocket analyzed_df, /plot_config | 1 |
| Live positions and orders, running profit and loss, balance | /status, /trades, /balance, /profit | 1 |
| Live actions (real-time feed): fills, voter answers, median, spread, quorum, veto or reduce, risk gate, errors, heartbeat | Freqtrade WebSocket messages and custom gateway events | 1 |
| Preview of entry candidates together with voter answers before order | custom | 1 |
| Risk meter: daily and total loss against limits, dry or live mode indicator | custom, /profit | 1 |
| Push notifications: fills, loss limit exceeded, kill switch, heartbeat lost, quorum failed, daily summary | Web Push (iOS 16.4 or newer, Home Screen) | 1 |
| Health: bot loop, system load, status and latency of each provider, heartbeat, logs | /health, /sysinfo, /logs, custom | 1 |
| Bot A vs bot B: stacked equity curves during dry-run | two instances, custom | 1 to 2 |
| Controls: pause, resume, stop entries, force exit one or all positions, lock pairs, blacklist; risky ones need two-step confirmation | /pause, /start, /stopbuy, /forceexit, /locks, /blacklist | 2 |
| Providers and keys screen, voter registry, configuration editor with schema validation and change notes | custom, section 4.5 | 2 |
| Swarm view per decision and the outcome afterwards (whether a skipped entry turned out to be a loss) | custom | 2 |
| Trade history and statistics: daily, weekly, monthly, per exit reason, per entry tag | /trades, /daily, /weekly, /monthly, /exits, /entries, /mix_tags, /stats, /performance | 2 |
| Audit log: configuration changes, keys (without values), mode, controls | custom | 2 |
| Daily report from the analyst agent: summary, anomalies, suggestions | deepagents, custom | 3 |

### Nice-to-have

| Feature | Basis |
|---|---|
| What-if config preview: effect of limits in rupiah, and replay of recorded voter answers with a new quorum or spread threshold without new LLM calls | custom |
| Strategy signal preview on the chart for a time range | /pair_history |
| Time machine: scrub to past decisions with voter answers shown above the chart | custom |
| Backtest and its results from the UI | backtest endpoint not yet verified by me |
| Voter scoreboard: calibration and accuracy, auto-disabled when drifting | custom |
| News and sentiment layer on the chart (RSS, Fear and Greed) | custom |
| Ask the analyst agent (chat, read-only tools), for example why BTC was skipped at a certain hour | deepagents |
| Stress test: 10 percent drop scenario against open positions | custom |
| App icon badge and last view when offline (read-only) | PWA; Apple mentions badging permission in iOS 16.4 |
| CSV export of trade history and tax summary as information, not tax advice | custom, PMK 50/2025 |
| Two languages: Indonesian (default) and English | custom |
| Telegram control channel | built-in Freqtrade Telegram commands |
| More than 3 pairs and a portfolio view | configuration |

### Deliberately not built

- Copy trading and public leaderboards.
- Leverage and futures.
- Withdraw-funds button and all-in button.
- Features that raise risk automatically.
- Keys that can be viewed again.

### Live transport and performance

- The gateway keeps one WebSocket connection to Freqtrade (/api/v1/message/ws with a 15-minute JWT from /token/login, not ws_token, because the Freqtrade log records the WebSocket URL along with its query; subscribe) and pushes deltas to the PWA over its own WebSocket. Candle data is fetched only while a client is connected, so the bot on the PC is not burdened.
- iOS: the WebSocket is only alive while the app is open in the foreground; in the background, updates arrive via Web Push. Safari does not support silent push, so notifications must be shown (Apple documentation).
- Connection dropped: reconnect with backoff and the display marks data as stale.
- Metrics measured in stage 1: delay from a fill in Freqtrade to appearing in the PWA, and gateway CPU load while a client is connected. No numbers yet.
- FreqUI uses Vue and Nuxt UI (FreqUI README) and ECharts (package.json). Reusing it contradicts the request for a unique UI, so the PWA is built from scratch. The chart library is chosen in the design stage.

### Delivery order

Stage 1 (demo): all stage 1 features, read-only. Stage 2: controls, configuration, providers and keys, swarm, history, audit. Stage 3: daily report and live-mode controls. Nice-to-have follows, in an order driven by usage data. Full features means a large scope; there is no time estimate because it has not been measured, and this order keeps the bot testable first.

## Sources

Full evidence and links are in the research-swarm-pwa document on this issue. The sources of revisions 1 and 2 (AI-Trader, Hummingbot, NautilusTrader, TradingAgents, claude-trading-skills, Freqtrade, Indodax API, alternative.me, OpenRouter Jev) remain valid.
