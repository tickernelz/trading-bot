# Strategy search, round 1: locked plan (ZHA-3872)

This file and `engine/search_plan.py` are committed before the first backtest of round 1. Every run of the search appends a line to `docs/strategy-research/ledger.jsonl` with the git SHA, time, kind, configuration and period, failed runs included. Targets may be tightened after this commit, never loosened.

## Data

- Indodax public 1h candles (`engine.history`, `tradingview/history_v2`) for BTC/IDR, ETH/IDR, SOL/IDR, 2021-01-01 00:00 to 2026-10-25 23:00 UTC. SOL/IDR starts 2021-11-11 05:00 (listing). No gaps inside the range.
- 4h and 1d candles are aggregated from 1h in UTC, which matches the Indodax 1D and 240 candles (checked against the public endpoint on 2026-10-26). A higher-timeframe value becomes visible on the 1h candle that closes with it (`freqtrade.strategy.merge_informative_pair`), never earlier.
- Fear and Greed: alternative.me daily index since 2018-02-01, used only by the exploratory family I, shifted one day like any 1d feature.
- SHA-256 of every input file is written to each ledger line.

## Periods

| Name | From (UTC) | To (UTC) | Use |
| --- | --- | --- | --- |
| Warm-up | 2021-01-01 | 2022-07-01 | indicators only (SMA200 on 1d needs 200 days) |
| Walk-forward F1..F8 | 2022-07-01 | 2026-04-26 | six-month folds (F8 is 2026-01-01..2026-04-26); every configuration is scored on every fold |
| Holdout | 2026-04-26 | 2026-10-26 | one run, one configuration, then marked used in the ledger |

Rule strategies have no fitted parameters, so every fold is out-of-sample for a fixed rule. The only fitting is the choice among the locked grid; the multiple-testing guards below and the holdout exist for that choice. No hyperopt is run in round 1 (epochs: 0).

## Costs

- Primary: Indodax taker all-in, buy 0.20555%, sell 0.41555% (ZHA-3871 `candidate-research`, section 1). A trade is a win only when its profit_ratio after these costs is above zero.
- Sensitivity, always reported: 0.41% per side (the stage 2 stress level), no tax (0.20555% per side), +0.05% and +0.10% slippage per side on the primary costs.

## Execution model

Signal on a 1h candle close, fill at the next 1h open. One position per pair. Stop loss and fixed target are checked inside each candle against high and low: the stop is assumed first when both are touched; a stop gapped through fills at the open. Exit signals, ATR trailing, lock and time exits are decided on a close and filled at the next open. A trade still open at the end of a period closes at the last close. Sizing for drawdown uses the risk layer: 0.5% of equity lost at the stop, at most 3 open trades. The simulator is cross-checked against the stage 2 Freqtrade numbers for SwingEmaRsi (`validate` command).

## Locked matrix: 93 configurations

| Family | Configurations |
| --- | --- |
| A Donchian 1d breakout, Donchian-mid exit | 10 |
| B Donchian 1d with ADX and 1d SMA200 filter, mid or 3xATR trail | 8 |
| B Donchian 4h with 1d SMA200 filter | 4 |
| C time-series momentum 1d, 20 to 90 days | 8 |
| D EMA trend 4h and 1d with ADX and SMA200 filter | 10 |
| E breakout with volume confirmation, 4h and 1d | 4 |
| F trend entry with asymmetric exit (fixed target plus profit lock) | 10 |
| G RSI2 mean reversion above SMA200, 1d and 4h | 10 |
| H Bollinger range reversion with ADX below 20 | 8 |
| N trend-filtered dip with fixed target (high win rate family) | 12 |
| I Fear and Greed filter (exploratory, not deployable) | 4 |
| J high win rate controls (small target, wide stop, random entry) | 3 |
| K benchmarks: SwingEmaRsi, buy-and-hold | 2 |

The exact parameters are in `engine/search_plan.py`. The swarm is a shadow and is not part of the search.

## Target (Zhafron 2026-10-26)

(a) net win rate on the holdout at least 60%, at least 100 trades on at least 2 pairs (10 trades each), Wilson 95% lower bound at least 50%; (b) every walk-forward fold at least 50% and standard deviation of fold win rates at most 8 points; (c) minimum win rate of any rolling 30-trade window at least 40%; (d) win rate at least 50% in every BTC/IDR regime with at least 20 trades. Regime: daily BTC/IDR close above its SMA200 with the SMA200 rising over 20 days is bull, below with it falling is bear, otherwise range. (c) and (d) are checked on the walk-forward and on the holdout separately.

Reported next to win rate: net expectancy per trade with a 95% bootstrap CI (10,000 resamples, seed 3872), profit factor, payoff ratio, largest loss, mean of the 5 worst trades, max drawdown, trades per month, longest stretch without entries.

Tiers: T1 target met and net expectancy above 0 with CI lower bound above 0 and above the 95th percentile of the null; T2 target met and expectancy above 0 otherwise; T3 target met and expectancy at or below 0; T4 target not met.

## Selection and holdout

1. Walk-forward every configuration. Eligible: deployable, at least 100 walk-forward trades, at least 2 pairs with 10 trades.
2. Walk-forward tier: target (a) and (b) to (d) evaluated on the walk-forward trades.
3. Selected: best walk-forward tier, then highest net expectancy, then lowest drawdown.
4. Null for the selected configuration: 1,000 random-entry series at its own entry rate per pair and with its own exits, on the walk-forward and again on the holdout.
5. The selected configuration runs once on the holdout. The runner refuses a second holdout run for any configuration; a replay of the same configuration is allowed for review and is logged as `holdout_replay`.
6. The final tier uses the holdout for (a), the walk-forward folds for (b), and both for (c) and (d).

## Controls that must fail or pass

- Lookahead detection must fire: shifting every signal one 1h candle and one candle of the rule timeframe into the future must look much better than the honest rule.
- Truncation: at 40 seeded cut points the signals of the last 48 candles computed on data cut at t must equal those computed on the full data.
- Live window: entries computed on the last 649 candles of each timeframe (the stage 0a live window) must equal entries on full history at the same cuts.
- Freqtrade `lookahead-analysis` and `recursive-analysis` on the selected strategy class.
- Benchmarks on the same folds and holdout: buy-and-hold per pair, random entry, SwingEmaRsi.
