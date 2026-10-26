<p align="center"><img src="docs/media/banner.png" alt="Trading Bot: a spot crypto swing bot with a voter swarm, median aggregation and a PWA control panel" width="100%"></p>

<p align="center">
  <img alt="Mode" src="https://img.shields.io/badge/mode-dry--run-1c1f26">
  <img alt="Engine" src="https://img.shields.io/badge/engine-Freqtrade%202026.9-1c1f26">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12%2B-1c1f26">
  <img alt="PWA" src="https://img.shields.io/badge/panel-PWA%20(Svelte)-1c1f26">
  <img alt="License" src="https://img.shields.io/badge/license-GPL--3.0-1c1f26">
</p>

An always-on spot crypto swing bot that runs on your own PC, with a PWA control panel for phone and desktop. A rule-based strategy on 1-hour candles, chosen in config, proposes entries. A **swarm** of voters (many models, one typed question, answers combined with the **median**) may only filter them. Loss limits and position sizing are enforced by **code**, not by prompts.

> **Honest status.** This project has not been shown to make money. Everything runs in dry-run: no exchange account, no exchange keys, no real funds, and live mode is deliberately unable to start in this build. The default strategy wins often but loses money after costs: on Indodax data from 2022-07 to 2026-04, after the official taker fees and the 0.21% tax on sells, it won 77.1% of 519 trades with a **negative** expectancy of -0.599% per trade (95% CI -1.07% to -0.15%); on the untouched last six months it won 77.8% of 54 trades at -0.112% per trade (95% CI -1.47% to +1.11%). Configurations whose expectancy is positive with a 95% CI above zero (25 of 93, before correcting for testing 93) win only 34% to 57% of trades and are unstable from period to period; the few that win 60% to 68% with a positive mean have CIs that include zero. A second search round found a rule that meets the win-rate target on the 2022-2026 data at +0.08% per trade (95% CI -0.44% to +0.60%); it is not the default, because no forward data exists yet to judge it on (not enough data), and on eight other IDR pairs over the same years it lost -0.65% per trade (95% CI -1.09% to -0.22%). Details in [docs/strategy-research.md](docs/strategy-research.md). Not financial advice.

## Screens

The screens below come from the PWA running against a mock gateway with sample data (the panel shows a "sample data" badge), not from a live bot run.

<p align="center">
  <img src="docs/media/phone-summary.png" alt="Summary on a phone: state Safe, today's loss trace against the daily limit, open positions" width="30%">
  <img src="docs/media/phone-chart.png" alt="Candlestick chart per pair with entry markers and limits" width="30%">
  <img src="docs/media/phone-control.png" alt="Control: hold new entries, force exit, with two-step confirmation" width="30%">
</p>

<p align="center">
  <img src="docs/media/desk-summary.png" alt="Desktop, Summary" width="49%">
  <img src="docs/media/desk-chart.png" alt="Desktop, live chart" width="49%">
  <img src="docs/media/desk-swarm.png" alt="Desktop, per-voter swarm decision" width="49%">
  <img src="docs/media/desk-ab.png" alt="Desktop, equity curves of bot A versus bot B" width="49%">
  <img src="docs/media/desk-providers.png" alt="Desktop, providers and keys" width="49%">
  <img src="docs/media/desk-config.png" alt="Desktop, configuration editor with risk limits in rupiah" width="49%">
</p>

The visual direction is written down in [PRODUCT.md](PRODUCT.md) and [DESIGN.md](DESIGN.md): one large answer readable in two seconds (Safe, Held, Stopped), a warm signal colour reserved for risk, and gains and losses always marked with a sign and a direction rather than only red and green.

## How it works

```mermaid
flowchart LR
    S[1h rule strategy\nstrategy.name in config] --> C[Entry candidate]
    C --> R{Risk layer\ndeterministic code}
    R -- passes --> W[Voter swarm\nmedian + spread + quorum]
    W -- shadow: recorded only --> O[Dry-run order\nFreqtrade]
    R -- limit crossed --> X[New entries held]
    O --> G[Gateway]
    W --> G
    G --> P[PWA\nphone and desktop]
```

1. **Engine**: Freqtrade 2026.9 as a git submodule in `vendor/freqtrade` (unmodified). Strategy, configuration and user data live outside the vendor tree.
2. **Risk layer** (`engine/risk.py`): risk per trade, daily loss limit, total drawdown limit, maximum open positions, kill switch. It never goes through an AI. Raising a limit or switching mode takes a two-step confirmation; lowering a limit applies immediately.
3. **Swarm** (`swarm/tb_swarm`): voters from several vendors answer the same typed question with the option order shuffled. Aggregation uses the median, the spread and a quorum; below quorum the entry fails closed. Adapters: the System One wire (`/v1/systemone`), the OpenRouter and OpenAI decisions APIs, and ordinary LLMs with structured output. Adding a voter is one block of configuration. `veto` mode is rejected by the schema until its adoption gate passes, so the swarm is **shadow only** today: it records what it would decide and never affects an order.
4. **Gateway** (`gateway/`): the only door between the PWA and the bot. Session auth, read endpoints, a WebSocket feed, two-step controls with an `Idempotency-Key` and an audit log, Web Push. The Freqtrade API is never exposed to the network.
5. **Analyst agent** (deepagents): a daily report and Q&A with read-only tools. No tool can place an order or change configuration.
6. **PWA** (`pwa/`, Svelte + Vite): a purpose-built panel, not FreqUI.

## Features

- A Safe, Held or Stopped state with meters for the daily loss and the total drawdown against their limits, a dry-run or live badge, and the age of the data.
- Live candlestick chart per pair with entry and exit markers, a real-time activity feed, positions and orders, engine and provider health.
- Per-voter swarm decisions (answer, median, spread, quorum) with the outcome afterwards: did an entry that would have been skipped turn out to lose?
- Bot A (rules only) against bot B (rules plus shadow swarm) with stacked equity curves.
- Controls: pause, hold new entries, force exit, pair locks, blacklist, each with a two-step confirmation that states the consequence in rupiah.
- A schema-validated configuration editor with a change log, provider and voter registry, and a connection test per provider. Keys can only be entered from the bot's own machine and are never returned in full.
- Analytics: configuration what-if, voter scoreboard, stress test, CSV export, backtest from the UI, portfolio view.
- Time machine (step back through past decisions), news and Fear and Greed layer, last view available offline, an optional Telegram channel.
- Web Push notifications: fills, limit crossed, kill switch, heartbeat lost, quorum failed, daily summary.
- Languages: English (default) and Indonesian, with more addable. See [docs/i18n.md](docs/i18n.md).

## Quick start

Download the archive for your system from the [releases page](https://github.com/tickernelz/trading-bot/releases), check it against `SHA256SUMS`, unpack it and start it:

```bash
tar -xzf trading-bot-<version>-linux-x64.tar.gz
cd trading-bot-<version>-linux-x64
./trading-bot run
```

On Windows unzip the archive and run `trading-bot.exe run`. The first start creates the data folder, prints the password of the web panel and starts bot A, bot B, the shadow swarm, the analyst and the gateway as one application. Open http://127.0.0.1:8090 and sign in. Stop everything with Ctrl+C.

| System | Archive | Data folder |
| --- | --- | --- |
| Linux | `linux-x64`, `linux-arm64` (`.tar.gz`) | `~/.local/share/trading-bot` |
| Windows | `win-x64`, `win-arm64` (`.zip`) | `%LOCALAPPDATA%\TradingBot` |
| macOS | `mac-x64` (Intel), `mac-arm64` (Apple silicon) (`.tar.gz`) | `~/Library/Application Support/TradingBot` |

On Windows on ARM the bundle is native too. `pyarrow` has no wheel there and its source package needs a prebuilt Arrow C++ library, so it is left out: downloaded candles are stored as `jsongz` instead of `feather`. `cryptography` and `python-rapidjson` are built from source on the release runner.

The data folder holds `config/` (one YAML file per bot and for the gateway), `secrets/` (generated passwords and the files for provider keys), `run/` (databases) and `logs/`. Options: `--home <folder>` uses another data folder, `--port-base <n>` sets the first of the local ports (default 8080; the panel is on n+10) when the folder is created, `--version` prints the versions of the bundled libraries. Provider keys for the swarm and the analyst go into `secrets/swarm.env` and `secrets/analyst.env` as `NAME=value` lines, or into the panel's configuration editor; without a key the analyst refuses to start (the log in `logs/` says why) and the voters of the shadow swarm cannot answer, while the bots and the panel keep running. A component that crashes, or a bot that cannot load the exchange markets because the exchange is unreachable or rate limiting, is restarted with a growing delay; only a configuration refusal (exit code 78) is not retried.

### First open without code signing

The archives are not signed, because signing needs a paid developer account. The operating system warns about that:

- **Windows**: SmartScreen shows "Windows protected your PC". Right-click the zip, open Properties and tick Unblock before unpacking, or run `Get-ChildItem -Recurse trading-bot-* | Unblock-File` in PowerShell. If the warning still appears, choose More info, then Run anyway.
- **macOS**: Gatekeeper blocks files that came from a browser. After unpacking run `xattr -dr com.apple.quarantine trading-bot-<version>-mac-arm64`, or open System Settings, Privacy & Security and choose Open Anyway after the first blocked start.
- **Linux**: nothing to unblock; the executable bit is kept by the archive.

The checksum of each archive is in `SHA256SUMS` on the release page (`sha256sum -c SHA256SUMS`, `shasum -a 256 -c SHA256SUMS` on macOS, `Get-FileHash` on Windows).

### From source

With [uv](https://docs.astral.sh/uv/) and Node 24:

```bash
git clone --recurse-submodules https://github.com/tickernelz/trading-bot.git
cd trading-bot
uv venv --python 3.13
uv pip install -c swarm/constraints.txt -r vendor/freqtrade/requirements.txt ./swarm pyyaml==6.0.3 pywebpush==2.5.0 http_ece==1.2.1 py-vapid==1.9.6 pytest==9.1.1
uv pip install --no-deps ./vendor/freqtrade ./vendor/freqtrade/ft_client
(cd pwa && NODE_ENV=development npm ci --include=dev && npm run build)
python -m tbapp run
```

Where a dependency has no wheel for your system (for example `bottleneck`, which Freqtrade does not need, on Windows ARM) remove that line from the requirements first.

To try only the panel against the mock gateway:

```bash
cd pwa
NODE_ENV=development npm ci --include=dev
npm run mock-gateway &
npm run build && npm run preview
```

Open http://127.0.0.1:4173. The mock gateway password is `example`. The full two-bot layout, the shadow swarm and the gateway are described in [docs/operations.md](docs/operations.md).

## Releasing

1. Merge the change to `main`.
2. Tag the commit: `v1.2.3`, or `v1.2.3-rc.1` for a release candidate (a tag ending in `-rc` or `-rc.<n>` becomes a prerelease).
3. Push the tag to GitHub. The tag must name a commit that exists on GitHub: when the public history is rewritten from a private one, create the tag on the rewritten head and push it without force.
4. The `release` workflow runs on the tag: it builds the panel, then builds the six bundles on native runners (`ubuntu-24.04`, `ubuntu-24.04-arm`, `windows-latest`, `windows-11-arm`, `macos-15-intel`, `macos-15`), unpacks each archive and starts it on random ports, checks the panel, sign-in and `/gw/v1/health`, and only then uploads the archives and `SHA256SUMS` to the release. A target that fails is left out of the release, and the other targets still ship.
5. A manual run of the same workflow (Actions, release, Run workflow) builds and tests without creating a release.

Building locally: `uv run --python 3.13 --no-project packaging/build.py --target linux-x64` after `npm run build` in `pwa`.

## Configuration

One YAML file, validated against a schema at start. A bad configuration means the bot refuses to start instead of running on guesses. A full example is in [config/config.example.yaml](config/config.example.yaml). Defaults, all changeable:

| Setting | Default |
| --- | --- |
| Starting capital | Rp 2,000,000, profits compounded |
| Maximum daily loss | 1.0% |
| Maximum total drawdown | 10.0% |
| Risk per trade | 0.5% |
| Maximum open positions | 3, spot only, no leverage |
| Swarm mode | shadow |
| LLM compute cost | recorded, not limited |

API keys come from environment variables (`api_key_env`) or are written directly into `config/config.yaml`. Both are git-ignored. A key in the config file is stored as plain text on disk, so treat it as leaked if that file ever leaves the machine.

## Limits you should know about

- Indodax is not officially supported by Freqtrade 2026.9. OHLCV data works, but the live order path has never been run. For that reason live mode cannot start in this build, and the stop loss runs on the bot side, so the PC must stay on.
- The strategy research ([docs/strategy-research.md](docs/strategy-research.md)) uses the official Indodax all-in fee table and PMK 50/2025: taker 0.20555% on a buy and 0.41555% on a sell, the 0.21% tax applying to sells only. The dry-run bot charges `exchange.fee_pct` on both sides; the example's 0.31055% is the mean of those two costs, so a round trip costs the same 0.6211% as in the research. The research assumes taker fills and no slippage; +0.10% slippage per side lowers the default's expectancy by about 0.2 points per trade.
- The default strategy (`RuleStrategy`, RSI 14 below 30 on 1h, 3% take-profit, 10% stop) gets its high win rate from a small target and a wide stop: each stop costs about 10.6% of the stake, as much as four to five wins of about 2.4%. Random entries with the same exits win as often. `SwingEmaRsi` can still be selected with `strategy.name`.
- The swarm is built as a filter that gets measured, not as an assumed source of profit. Evidence that ensembles raise trading profit has not been found; what exists is for event forecasting, not prices ([docs/research-swarm-pwa.md](docs/research-swarm-pwa.md)).
- During testing every voter used the same model, so their errors are correlated. The swarm's value can only be measured with voters from several vendors in a forward test.
- A 7-day non-stop engine test on the complete application is in progress; there are no results yet.

## Layout

| Path | Contents |
| --- | --- |
| `engine/` | launcher, configuration schema, risk layer, strategy, shadow service, decision store |
| `swarm/` | the `tb_swarm` package: voters, adapters, aggregation, analyst agent |
| `gateway/`, `analytics/` | the PWA gateway and the analytics routes |
| `pwa/` | the PWA panel and the mock gateway |
| `scripts/` | run the whole stack as systemd units, measure, record fixtures, backtest |
| `tbapp/`, `packaging/` | the single launcher and the native bundle build |
| `docker/`, `docker-compose.yml` | container files used by the server stack scripts |
| `docs/` | [plan](docs/plan.md), [gateway contract](docs/gateway-api.md), [operations](docs/operations.md), [research](docs/research-swarm-pwa.md), [languages](docs/i18n.md), per-stage findings |
| `vendor/freqtrade` | the Freqtrade submodule, pinned to tag 2026.9 |

## Tests

```bash
PYTHONPATH=. python -m pytest
cd pwa && npm test
```

Run the engine tests in the environment from the source instructions so the Freqtrade, ccxt and pandas versions match the bundle. The git hooks (`git config core.hooksPath .githooks`) reject comments in our code and commits that are not Conventional Commits.

## License

[GPL-3.0](LICENSE), the same as Freqtrade: the strategy and launcher import Freqtrade and every bundle contains it. Each archive carries `LICENSE` and `SOURCE.txt` with the link to this source. The software is provided as is, and trading risks losing all of your capital.
