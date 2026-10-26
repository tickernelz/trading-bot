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


# Round 2: locked plan (ZHA-3876)

Locked in the commit that adds this section, before the first round 2 run. Everything above stays in force unless this section says otherwise; targets may be tightened, never loosened. Round 1's matrix stays in `engine/search_plan.py` as `round1_candidates()` and its holdout guard still refuses a second holdout run.

## What round 1 showed (walk-forward data, `walk-forward-summary.json`)

- Every configuration with a positive mean was a long-only trend rule behind the 1d SMA200 filter, and all of them failed (b) at least because F1 (2022-07..2023-01) or F8 (2026-01..2026-04-26) had no trade: the filter keeps them flat in BTC bear markets. Nearest misses: `F-don1d20-tp5-lock3` (184 trades, 67.9%, +0.353%, CI -0.36..+1.06, traded folds 52-72%, SD 7.7) and `F-don1d20-tp8-lock3` (160 trades, 64.4%, +0.835%, CI -0.04..+1.69, F2 34.8%).
- The high win rate families (J, N) win 60-90% in every fold and regime, but with fixed percentage targets and stops their payoff is 0.06 to 0.56 and the mean is negative in all of them.
- Trend rules made 28 to 272 trades in almost four years on three pairs, so their CIs are wide.

## Changes in round 2

| Change | Why |
| --- | --- |
| Pairs: BTC/IDR, ETH/IDR, SOL/IDR plus XRP/IDR and DOGE/IDR | more trades per fold and narrower CIs; XRP and DOGE are the most liquid IDR coins after them (Indodax ticker 2026-10-26: spread 0.4 and 7.1 bps) |
| Trend filters `above_sma50_1d` and `above_sma100_1d` | a faster filter can let trend entries trade in the rallies of bear folds that SMA200 blocks |
| `take_profit_atr` and `stop_atr`: target and stop in multiples of the rule timeframe's ATR(14) at the signal candle; the stop is never looser than `stoploss` | fixed targets ignore volatility; ZHA-3871 section 4.4 proposes exits at k x ATR. Freqtrade runs them with `custom_roi` and `custom_stoploss` |
| Multiple-testing correction | T1 on the walk-forward also needs the Bonferroni lower bound of the mean (normal, two-sided 5% family-wise over the cumulative trial count, 142 after this round) above zero, next to the bootstrap CI and the null p95 |
| Untouched pre-sample period | the round 1 holdout is used and there is no forward data after 2026-10-26 yet; see below |

## Data

- Walk-forward: Indodax 1h candles for the five pairs from 2021-01-01 to 2026-04-26 00:00 UTC (the round 1 files for BTC, ETH and SOL, cut at the holdout start; XRP and DOGE fetched for the same range). The runner never loads a candle after 2026-04-26.
- Pre-sample: Indodax 1h candles from 2018-01-01 to 2021-01-01 for BTC/IDR, ETH/IDR, XRP/IDR and DOGE/IDR (SOL/IDR was not listed). Scored from 2018-09-01, after the 220 days the 1d SMA200 and its 20-day slope need. No run in this repository and no probe in ZHA-3871 has scored a trade before 2021-01-01.

## Locked matrix: 49 configurations (cumulative 142 of 600)

| Family | Configurations |
| --- | --- |
| Q round 1 near misses on five pairs: `F-don1d20` tp 5% and 8% with lock 3%, `G-rsi2-1d-10-sl25`, `J-rsi14-1h-tp3-sl10` (the current default) | 4 |
| S Donchian 1d 10 and 20, filter SMA50, SMA100 or none, fixed target 5% or 8%, lock 3%, stop 8% | 12 |
| V Donchian 1d 20, filter SMA200 or SMA100, target 1, 1.5 or 2 ATR, stop 2 or 3 ATR (hard stop 15%) | 12 |
| V Donchian 4h 20, filter SMA200, target 1.5, 2.5 or 3.5 ATR(4h), stop 2 or 3 ATR (hard stop 10%) | 6 |
| W RSI2 < 10 on 4h above SMA50 or SMA100, target 1 or 1.5 ATR, stop 1.5 or 2.5 ATR, 72 h time stop | 8 |
| W RSI14 < 30 on 1h above SMA100, target 2 or 3 ATR(1h), stop 3 or 5 ATR, 168 h time stop | 4 |
| R random entries with the exits of `V-don1d20-sma200-tp1.5atr-st2atr` (control, not deployable) | 1 |
| K benchmarks: SwingEmaRsi, buy-and-hold | 2 |

## Selection, final evaluation and default

1. Walk-forward, eligibility, ranking, null and controls as in round 1, on the five pairs.
2. The pre-sample run is allowed once, for one configuration, and only when the selected configuration meets the target with a positive mean on the walk-forward (walk-forward tier T1 or T2). A T3 is not spent on it: the pre-sample is the only untouched data left for later rounds. The runner refuses a second run (`presample_started` in the ledger).
3. Final tier of that configuration: (a) on the pre-sample trades, (b) on the walk-forward folds, (c) and (d) on both; expectancy, CI and null on the pre-sample.
4. When the selected configuration is not T1 or T2 on the walk-forward, the pre-sample stays untouched, the round reports its walk-forward tier only, and the default does not change.
5. The default changes only to a configuration whose final tier is higher than the current default's (T4 on the round 1 holdout, T3 on the walk-forward), with a Freqtrade backtest of `RuleStrategy` that reproduces the simulator's trades.

### Correction after review (ZHA-3896, 2026-10-26, after the round 2 runs)

Points 2, 3 and 5 loosened the task's rule, which accepts only the holdout or forward data for target (a) and the final tier, and requires "not enough data" with fewer than 100 forward trades. They are replaced, which tightens the plan and changes no run:

- The final evaluation of round 2, and of every later round, uses forward data only: Indodax candles after 2026-10-26 or a dry run started after the configuration was locked, with no parameter tuned on them. Below 100 forward trades on at least 2 pairs the round's result is "not enough data", no target is reported as met, and the default does not change.
- The pre-sample run stays a once-only, locked out-of-sample check and is reported as supporting evidence next to the walk-forward, never as the final tier.
- At 2026-10-26 the forward data holds 0 trades, so round 2's result is "not enough data" and the default stays `J-rsi14-1h-tp3-sl10`.

# Round 3 and later: research mode and cross-asset validation (ZHA-3876, direction of 2026-10-26 12:28 UTC)

Zhafron's direction replaces the decision to pause rounds 3 to 5 until forward data exists. Everything above stays in force unless this section says otherwise. Locked in the commit that adds this section, before any cross-asset run.

## Research mode

- The simulator has never modelled the risk layer's loss limits: every number in rounds 1 and 2 is a per-pair trade list with no daily-loss or drawdown stop, and drawdowns come from an account model that only applied the 0.5% risk per trade and the 3-slot cap. Ledger lines of every command except \`cross-asset\` record \`research_mode: true\` for that reason.
- \`cross-asset\` runs an account model in two modes on the same trades and reports both: research mode (no loss limits) and loss limits (\`risk.max_daily_loss_pct\` 1% from the Asia/Jakarta day-start equity and \`risk.max_total_drawdown_pct\` 10% from the realised peak, open trades marked at the signal candle's close, entries refused on a breach, as the bot does). The tier uses the mode named by \`--research-mode\`; the ledger records it. Bot, dry-run and live configuration do not change.

## Cross-asset validation

- Selection and every parameter choice stay on the five walk-forward pairs (BTC, ETH, SOL, XRP, DOGE against IDR).
- Cross-asset pairs: from 20 established coins checked on 2026-10-26 (BNB, NEAR, HBAR, LSK, ADA, LTC, TRX, LINK, DOT, BCH, XLM, ETC, ATOM, POL, UNI, AVAX, SHIB, VET, EOS, XAUT; not a scan of all 420 IDR pairs, which Indodax rate-limited), the IDR pairs with 1h candles on 2021-12-01, 24 h volume at least 0.05 bn IDR, a bid-ask spread at most 100 bps (ticker snapshot about 11:40 UTC) and no gold token: BNB, NEAR, HBAR, ADA, LTC, TRX, LINK, DOT, BCH. A pair whose candles have a gap longer than 24 hours inside the period is dropped before the first run and the drop is written here.
- Dropped before the first run: BCH/IDR. Its 46,584 candles from 2021-01-01 to 2026-04-26 all have zero volume, so no entry can fire (rules require volume above zero). The other eight have no gaps; zero-volume candles: BNB 204, NEAR 7,475 (listed 2021-10-07), HBAR 1,560 (listed 2021-02-10), ADA 211, LTC 255, TRX 208, LINK 4,350, DOT 1,016. Cross-asset pairs: BNB, NEAR, HBAR, ADA, LTC, TRX, LINK, DOT. Period: the walk-forward period 2022-07-01 to 2026-04-26 (warm-up from 2021-01-01 or the listing).
- The cost model is the same taker cost; a sensitivity adds half the snapshot spread per side for each pair (\`CROSS_SPREAD_BPS\`).
- Only configurations named before the run are evaluated: in each round the walk-forward selection, plus in this first run the round 1 and 2 near misses \`Q-F-don1d20-tp5-lock3\`, \`Q-G-rsi2-1d-10-sl25\`, \`S-don1d20-sma50-tp5-lock3\` and the current default \`Q-J-rsi14-1h-tp3-sl10\` as a comparator. Nothing is tuned on cross-asset results; every run is in the ledger.
- Tier: (a) on the cross-asset trades, (b) on the walk-forward folds, (c) and (d) on both; expectancy, bootstrap CI, null p95 (1,000 random-entry series on the cross-asset pairs) and the Bonferroni bound over the cumulative trial count on the cross-asset trades. T1 needs both lower bounds above zero and the null beaten. Every tier from this protocol is written "provisional until forward data": the cross-asset pairs move with BTC and the selection pairs over the same years, so they are correlated with the selection data and are not forward evidence. Monthly forward monitoring stays the final gate before any decision about live trading.
- Ranking (Zhafron): tier, then higher net win rate, then lower drawdown. Reported next to the win rate: largest loss, mean of the 5 worst trades, max drawdown, and the worst calendar-month realised loss in rupiah on Rp 2,000,000 capital with the 0.5% risk sizing.
- The default changes to the best-ranked configuration when its provisional tier is higher than the current default's.

## Budget

The total over all rounds is raised from 600 to 1,500 configurations (Zhafron). The multiple-testing correction keeps using the cumulative count.

## Ranking (Zhafron, 2026-10-26 13:39 UTC)

"The research is free as long as the monthly profit is as high as possible." From round 3 on, both the walk-forward selection and the cross-asset ranking order configurations by tier, then compounded net profit per month on one Rp 2,000,000 account (3 slots, sized to lose 0.5% of equity at the stop, the bot's setting), then lower drawdown. Reported next to it: the same account sized at 2% risk with its drawdown and worst month, largest loss, mean of the 5 worst trades, max drawdown, worst calendar month in rupiah, and the equal-weight buy-and-hold of the same pairs over the same period as rupiah per month. Tiers, targets and the wording rules do not change; the default still changes only with a higher tier.

## Round 3 matrix: 26 configurations (cumulative 168 of 1,500)

Locked in the commit that adds this section, before the first round 3 run. The ZHA-3913 shortlist (Agent Laras) was not out at lock time; it goes into round 4. Evidence: the only configurations with a positive mean and a bootstrap CI above zero in round 1 (25 of 93) were trend rules that let winners run (Donchian, time-series momentum, EMA trend), all with low win rates; for profit per month, the right tail matters more than the win rate.

| Family | Configurations |
| --- | --- |
| P round 1 positive Donchian 1d rules on the five pairs: lookback 30, 60, 90, Donchian-mid exit, 20% stop | 3 |
| L Donchian 1d breakout, lookback 30, 55, 90, filter SMA100 or none, exit on a close 3 or 4 ATR(1d) below the highest close, 20% stop | 12 |
| M time-series momentum 1d, 30, 60, 90 days, filter SMA100 or none, exit when the return turns negative, 20% stop | 6 |
| E EMA trend 1d, 20/100 and 50/200, exit on the cross or a 3 ATR trail, 20% stop | 2 |
| R random entries with the exits of \`L-don1d-55-nofilter-trail4atr\` (control, not deployable) | 1 |
| K benchmarks: SwingEmaRsi, buy-and-hold | 2 |

Runs: walk-forward on the five pairs, controls, then \`cross-asset\` in research mode for the first three configurations of the walk-forward ranking (named by the ranking, not by hand). Tiers from cross-asset are provisional until forward data.
