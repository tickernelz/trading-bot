# Operations and technical reference

Notes on running, testing, and understanding the limits of the engine. The project overview is in the [README](../README.md).

## Contents

- vendor/freqtrade: the Freqtrade engine as a git submodule, pinned at tag 2026.9
- engine/: launcher, config schema, risk layer, strategies
- engine/settings.py: the single schema for config/config.yaml, validated before the engine starts
- engine/risk.py: daily loss limit, drawdown limit, risk-based position sizing
- engine/news.py: fetcher for CoinDesk and Cointelegraph RSS headlines and alternative.me Fear and Greed for the chart layer (15-minute and 1-hour cache, fetched only on request)
- engine/strategies/gated.py: risk gate, startup check, heartbeat and shadow hooks shared by the strategies
- engine/strategies/rule_strategy.py: the default strategy, any rule from engine/rules.py set in config strategy.rule
- engine/strategies/swing_ema_rsi.py: 1h swing strategy (EMA 20/50 + RSI), selectable with strategy.name
- engine/strategy_search.py, engine/search_plan.py: the locked strategy search and its run ledger (docs/strategy-research.md)
- engine/launch.py: validates the config, renders the Freqtrade config (trade database in the userdir), execs Freqtrade
- engine/heartbeat.py: heartbeat file and start log per bot
- engine/shadow.py, engine/shadow_client.py: the shadow swarm service for bot B and the candidate sender from the strategy
- engine/decisions.py: SQLite store of swarm decisions and the link to trades
- gateway/: gateway between the PWA and the bots (docs/gateway-api.md section 12); configuration, provider, key, voter (section 17)
- scripts/stack.sh: runs bot A, bot B, the shadow service, the analyst service, the gateway, and the PWA as systemd user units
- scripts/measure_gateway.py: measures fill delay and gateway client load
- scripts/stack_report.py: summary of one engine run
- scripts/record_fixture.py: records Freqtrade responses and swarm decisions from a dry-run into tests/data for gateway tests (docs/gateway-api.md section 13)
- docker/Dockerfile, docker-compose.yml: image derived from vendor/freqtrade, host network
- docs/plan.md: final plan
- docs/gateway-api.md: gateway API contract and event feed for the PWA
- docs/research-swarm-pwa.md: research and sources
- pwa: read-only PWA panel for stage 1 and a mock gateway with sample data (see pwa/README.md)
- config/config.example.yaml: example configuration
- tests/: pytest tests for the schema, risk layer, strategy, launcher
- .env.example: environment variable names

## After cloning

    git clone --recurse-submodules <url>
    git config core.hooksPath .githooks

If you already cloned without --recurse-submodules: git submodule update --init

## Running a dry-run

Requires Docker on the same machine; tested on WSL2 with Docker Engine 29.9.2.

    cp .env.example .env
    mkdir -p user_data
    cp config/config.example.yaml config/config.yaml

Fill in FT_API_USERNAME, FT_API_PASSWORD, FT_API_JWT_SECRET (at least 32 characters) in .env (do not commit it). Only trade and webserver open the API and need all three; download-data, backtesting, and show-config run without an API server. The example config enables the shadow swarm, so trade and webserver also need SHADOW_TOKEN (at least 32 characters, the same as the shadow service's); for a rules-only bot set `swarm.enabled: false` and remove the `shadow` section. Freqtrade's `ws_token` is deliberately not used: the gateway connects to the WebSocket with a 15-minute JWT (docs/gateway-api.md section 8). Then:

    docker compose build bot
    docker compose up -d bot
    docker compose logs -f bot

The bot listens on 127.0.0.1:8080 (api.listen and api.port in the config). If the configuration is invalid, the container stops with exit code 2 and a refusing to start message; no orders are created.

Other Freqtrade commands use the same launcher, so validation still applies. Run them directly from the already built image (docker compose run would rebuild the base image, which takes over ten minutes):

    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev download-data --days 120 --timeframes 1h
    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev backtesting --timerange 20250601-
    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev show-config

Network: network_mode host is used so the bot can reach LLM providers that only listen on the host's 127.0.0.1 (verified on WSL2: 127.0.0.1:62173 and 127.0.0.1:20128 answered 401 from inside the container, while host.docker.internal with host-gateway only produced 000). The Docker Desktop path on Windows has not been tested. api.listen is restricted by the schema to 127.0.0.1 or ::1, so REST is never exposed to the LAN; for Docker Desktop the plan is a bridge network with publish 127.0.0.1:8080:8080, still untested.

## Stage 1: two bots, shadow swarm, gateway

Four processes, one image (`trading-bot/engine`), all listening only on 127.0.0.1:

| Component | Port | Contents |
| --- | --- | --- |
| bot-a | 8080 | Freqtrade, rules only (`swarm.enabled: false`) |
| bot-b | 8081 | Freqtrade, same rules; each entry that passes the risk layer is sent to the shadow service without waiting for an answer |
| shadow-b | 8091 | `POST /candidates` only with an `X-Shadow-Token` header equal to SHADOW_TOKEN. Real swarm voters; records answers, median, spread, quorum, and the verdict that WOULD be taken into `bot-b/swarm_decisions.sqlite`. Never affects orders |
| gateway | 8090 | Sessions, read endpoints, feed, health, cost and tokens, audit |

The example voter lineup follows stage 0c (seven active voters on seven different providers, docs/stage0-findings.md). The reason for not putting many voters on a single key was measured on 2026-10-26 02:0x UTC via `ShadowService` with real voters, the same BTC/IDR candidate each round and a 2 s gap between rounds (raw output per decision and per voter attached to the measurement task):

| Lineup | Rounds | Voter calls | Decisions |
| --- | --- | --- | --- |
| 7 voters on one nutaraline key | 5 | 18 valid, 17 HTTP 429 "Request rate per key exceeded the limit" | quorum 5 failed 3 of 5 |
| 4 nutaraline + 3 experientiallabs | 8 | 56 of 56 valid | 7 of 7 answered in 8 of 8; 5 `ok`, 3 `choice_tie` |
| 3 nutaraline + 2 tiprouter + 2 experientiallabs | 5 | tiprouter 0 of 10 (6 HTTP 503, 4 timeouts at 30 s) | quorum 5 reached thanks to the 5 other voters |

Latency of valid answers in the 4+3 split: nutaraline median 1.6 s max 2.7 s; experientiallabs median 6.4 s max 26.9 s. The experientiallabs max is close to `timeout_s` 30, so timeouts of that voter need to be monitored. `choice_tie` is a tie between voter answers (an aggregation rule), not a provider error.

`swarm.mode: veto` is rejected by the schema until the gate is built. A shadowed trade carries the custom data `shadow_decision_id`, so `DecisionStore.outcomes(<tradesv3.dryrun.sqlite>)` can calculate whether an entry that would have been skipped turned out to lose.

Each bot writes `heartbeat.json` every loop and appends one line to `starts.jsonl` at each start. After start, the bot rejects all entries until the start check passes: open positions are priced and the daily loss limit and drawdown are evaluated; the result is sent as a `strategy_msg` `startup_check`. All of this, plus sending candidates to the shadow service, only runs in the `dry_run` and `live` runmodes: Freqtrade also calls `bot_start`, `bot_loop_start`, `confirm_trade_entry`, and `order_filled` during backtest, hyperopt, and webserver, and there the strategy touches neither the live bot's files nor the voters. The launcher only renders the shadow service address and requires SHADOW_TOKEN for the `trade` command.

Run directory (outside the repo), for example `~/Projects/trading-bot-runs/machine-test`:

    config/bot-a.yaml config/bot-b.yaml config/gateway.yaml
    secrets/ft.env        FT_API_USERNAME, FT_API_PASSWORD, FT_API_JWT_SECRET (bot-a, bot-b)
    secrets/shadow.env    SHADOW_TOKEN, at least 32 characters (bot-b, shadow-b)
    secrets/swarm.env     voter provider keys, e.g. NUTARALINE_API_KEY, EXPERIENTIALLABS_API_KEY (shadow-b)
    secrets/gateway.env   GW_PASSWORD (at least 12 characters), FT_API_USERNAME, FT_API_PASSWORD, ANALYST_TOKEN (gateway)
    secrets/analyst.env   analyst provider key, ANALYST_TOKEN at least 32 characters (analyst-b)

Each process receives only the secret files it uses: the gateway does not hold the Freqtrade JWT secret, the bot does not hold provider keys, the shadow service does not hold Freqtrade credentials. Containers mount only `config/` (read-only) and their component's data directory; `secrets/` never enters a container (`--env-file` is read on the host).
    bot-a/ bot-b/ gateway/

The PWA has no data directory: the PWA unit serves the build output from the repo checkout (`pwa/`).

`config/bot-*.yaml` derives from `config/config.example.yaml` with different `bot_id`, `api.port`, and `swarm.enabled`; `config/gateway.yaml` derives from `config/gateway.example.yaml` with paths under `/opt/trading-bot/run`. Then:

    docker build -f docker/Dockerfile --build-context freqtrade-base=docker-image://trading-bot/freqtrade:2026.9 --target engine -t trading-bot/engine:<sha> .
    RUN_DIR=~/Projects/trading-bot-runs/machine-test IMAGE=trading-bot/engine:<sha> scripts/stack.sh start
    RUN_DIR=... IMAGE=... scripts/stack.sh status
    RUN_DIR=... scripts/stack.sh stop bot-b

Run summary (uptime from the `Bot heartbeat` lines in journald with gaps above 180 seconds counted as down, restarts, orders by status, ERROR lines, swarm decisions, bot B hours since the first real voter answer, tokens, results of shadowed trades, fill delay):

    PYTHONPATH=. python3 scripts/stack_report.py --run-dir ~/Projects/trading-bot-runs/machine-test --unit-prefix trading-bot-stack

Record gateway test data from a running run (needs `secrets/ft.env` and `RUN_STARTED_AT` in the run directory; for `show_config` only the fields the gateway uses are saved):

    docker run --rm --network host -v $PWD:/src:ro -v <run-dir>:/run-dir:ro -v <out>:/out -w /src -e PYTHONPATH=/src --entrypoint python trading-bot/engine:<sha> scripts/record_fixture.py --run-dir /run-dir --out /out

Transient systemd user units (`Restart=always`) survive terminal sessions or other servers being restarted; restarts are counted from `starts.jsonl`. Logs: `journalctl --user -u trading-bot-stack-bot-a`.

Impact on the machine is bounded: each container carries `--cpus` (bot 1.0; shadow service, analyst, and gateway 0.5) and `--memory`; the PWA unit runs on the host without a container with `Nice=10`, `CPUQuota=50%`, and `MemoryMax=512M`. `stack.sh start pwa` runs `npm ci --include=dev` if `pwa/node_modules` does not exist or `package-lock.json` is newer than it, then `npm run build`, then `npm run preview` serves `http://127.0.0.1:4173` and forwards `/gw` to `GATEWAY_URL`.

## Stage 2b: configuration, providers, keys, voters

The gateway writes bot configuration through `PATCH /gw/v1/settings` (schema validation in `engine/settings.py`, change record in the audit, two-step raise of risk limits), manages providers and keys (`/gw/v1/providers`, keys only from 127.0.0.1, display of the last 4 characters, import from omp models.yml, connection test), and the voter registry (`/gw/v1/voters`, `/gw/v1/roles`). Contract and what is not yet proven: docs/gateway-api.md section 17. Changes require an engine restart; the gateway does not restart anything.

## Telegram channel (disabled by default)

The control channel uses Freqtrade's built-in Telegram (commands /status, /profit, /balance, /daily, /stopentry, /start, /stop, /forceexit, /reload_config, /help, and others). It is off by default. To enable it, fill in config/config.yaml:

    notify:
      telegram:
        enabled: true
        token_env: TELEGRAM_BOT_TOKEN
        chat_id: "<chat id>"
        authorized_users: ["<Telegram user id>"]

then fill in TELEGRAM_BOT_TOKEN in .env. The token travels only through the environment variable (FREQTRADE__TELEGRAM__TOKEN) and is never written to the rendered Freqtrade config. The launcher refuses to start if the channel is enabled without chat_id, without authorized_users, or without a token. Only the trade command loads this channel.

Risk accepted when enabling it: Telegram commands are executed by Freqtrade directly, without two-step confirmation and without the gateway audit log (docs/gateway-api.md section 3). /forcelong remains rejected as long as api.force_entry is false. Messages from other chats or users are ignored by Freqtrade.

Evidence: tests/test_telegram_channel.py runs the real Freqtrade Telegram module against a local fake Bot API (the owner's chat gets replies to /status, /stopentry, /help; /stopentry from another chat does not change state). Not yet proven with a real Telegram bot because there is no token yet.

## Tests

    docker compose --profile test build tests
    docker compose --profile test run --rm tests

Tests run inside an image derived from Freqtrade, so the Freqtrade, ccxt, and pandas versions match production. Negative control: disable the limit checks in engine/risk.py (change both limit ifs to if False:) then run the tests; the limit tests must fail.

## Analytics

The analytics/ package provides a what-if preview of risk limits and replay of voter answers, a voter scoreboard, a 10 percent drop stress test, CSV export and tax summary as information, per-pair portfolio, and strategy signals and backtest through a Freqtrade instance in webserver mode. The endpoint shapes are in section 13 of docs/gateway-api.md; thresholds and rates are set in the analytics section of the config. The routes are attached to the gateway through `gateway/analytics_context.py`; `analysis_url` in the gateway config points to the webserver instance (port 8092 in the example) whose config uses `api.port: 8092`.

Signals and backtest need a webserver-mode instance with OHLCV data in its userdir (a trade-mode bot answers 503 for /pair_history and /backtest):

    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev download-data --days 25 --timeframes 1h
    docker run -d --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev webserver

Additional pairs only need to be written in exchange.pairs (and risk.max_open_trades raised); each pair adds a voter call per entry candidate.

## Measured Indodax limitations

- Freqtrade 2026.9 prints a warning that indodax is not officially supported and uses the generic exchange class, but 1h OHLCV for BTC/IDR, ETH/IDR, SOL/IDR is fetched.
- ccxt 4.5.84 reports the Indodax taker fee 0.2 as a ratio (not 0.2%), so Freqtrade would use a 20% fee if not overridden. Therefore exchange.fee_pct: 0.2 is mandatory in the config and is rendered as fee: 0.002.
- ccxt reports fetchMyTrades and watchOHLCV as unavailable (reported by Freqtrade as missing opt).
- A single OHLCV request with a long range returns only the latest candles (1h: 649 candles, 27 days), so Freqtrade's download-data stops at 27 days. The 1h history itself is available from at least 2023-10-01: engine/history.py fetches it in windows of 500 candles (docs/stage2-backtest.md).

## Stage 2 backtest

    IMAGE=trading-bot/engine:dev scripts/stage2_backtest.sh user_data/stage2

Downloads 1h history of three pairs since 2023-10-01, then runs eight backtests whose matrix is locked in engine/backtest_suite.py (in-sample and out-of-sample, fee 0.2% and tax 0.21% per side, fee-only and no-cost comparisons, risk limits as is and disabled). Results: report.json and report.md in the output directory. Findings: docs/stage2-backtest.md.

## Updating Freqtrade

    git -C vendor/freqtrade fetch --depth 1 origin tag <tag>
    git -C vendor/freqtrade checkout <tag>
    git add vendor/freqtrade
    git commit -m "build(vendor): bump freqtrade to <tag>"

Strategies and user data live outside vendor/freqtrade (--strategy-path and --userdir), so the vendor contents are not modified. If you ever need to modify the engine, fork Freqtrade and point the url in .gitmodules to the fork.

## Secrets

API keys may go through environment variables (copy .env.example to .env) or directly in config/config.yaml. Both files are in .gitignore and must not be committed. The Freqtrade config rendered by the launcher never contains secrets: API credentials enter only through the FREQTRADE__API_SERVER__* environment variables at exec time.

## Repo rules

- Commits use English Conventional Commits, subject under 72 characters, with no Co-Authored-By trailer.
- There are no comments in our code. The contents of vendor/freqtrade are third-party code and are not modified.
- There is no remote yet and no LICENSE file (Freqtrade is licensed under GPL-3.0).


## Stage 3a: analyst agent and live-mode control

One new process, `analyst-b` (port 8092, loopback), and two groups of gateway endpoints; the contract is in `docs/gateway-api.md` section 16, the figures and evidence limits in `docs/stage3a-findings.md`.

| Component | Contents |
| --- | --- |
| analyst-b | `python -m engine.analyst_service`. Holds the analyst model key (`secrets/analyst.env`: provider key and `ANALYST_TOKEN` of at least 32 characters). Runs a deepagents agent with three read tools (metrics, trade history, voter log) over a snapshot written by the gateway; no order tool, no config-change tool, no access to config or `.env` |
| gateway | Writes the snapshot, forwards it to analyst-b (`ANALYST_TOKEN` is added to `secrets/gateway.env`, the provider key is not), records the daily report after `analyst.report_at`, serves `/gw/v1/analyst/*` and `/gw/v1/mode` |

The daily report contains a summary, anomalies, and suggestions; each finding carries a list of evidence and a `grounded` flag, computed by code: true only if every piece of evidence appears verbatim in the tool output. Asking the analyst (`POST /gw/v1/analyst/ask`) uses the same tools.

Live-mode control: `POST /gw/v1/control/mode` in two steps, only from the bot's own machine, fail-closed. Live is rejected if the engine has no exchange key on record (`INDODAX_API_KEY`, `INDODAX_API_SECRET` in the bot environment, never at the gateway) and while `engine.modectl.LIVE_ENGINE_PROVEN` is false. That value is false in this build because the Indodax live order path has not been proven, so live cannot be enabled from this code. The engine refuses to start if `mode.json` in the bot userdir records live.
