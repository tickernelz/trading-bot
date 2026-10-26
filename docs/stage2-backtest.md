# Stage 2e findings: 3-year rule-based strategy backtest

This document records the backtest of bot A's rule-based strategy (`SwingEmaRsi`, 1-hour candles) on public Indodax data, with fees and tax. The source of truth remains `docs/plan.md` revision 11 (sections 1 and 8). All numbers below are copied from the raw reports `report.json` and `report.md` attached to the backtest run; no number was typed by hand. This document does not conclude anything about future profit or loss.

## Summary

| Item | Status | Evidence |
| --- | --- | --- |
| 3 years of 1h history from Indodax via CCXT | Proven | `history.json`: 26,904 candles per pair, 2023-10-01 00:00 to 2026-10-25 23:00 UTC, 0 missing candles |
| Fee 0.2% and tax 0.21% per side | Applied | `--fee 0.0041` in Freqtrade, recorded in the log and in every trade (`fee_open`, `fee_close`) |
| Expectancy per trade, trade count, drawdown, distribution, in-sample and out-of-sample separated | Measured | Tables below |
| Stage 2 pass condition in plan section 8 (positive expectancy after fee and tax on out-of-sample) | Not met | Out-of-sample -0,832% per trade (limits_off) and -1,388% (as_configured), 95% CI entirely below zero |
| Parameters tuned | No | 1 strategy parameter set, matrix locked in commit `3d7a371` before the first result existed |

## Indodax history: correction to the stage 0a finding

Stage 0a recorded that Indodax 1h history was only about 649 candles (27 days). That was the limit of a single request, not the limit of the history. Indodax (`tradingview/history_v2`) returns only the most recent candles when the `from`-`to` range is long, and ccxt 4.5.84 fills `to` with the current time when `params.until` is not given, so an old `since` still yields the last 27 days. ccxt for Indodax reads `params.until` in seconds (not milliseconds as the ccxt convention has it).

`engine/history.py` fetches the history in windows of 500 candles (`since` and `until` per window) and then stores it as Freqtrade feather data. Result (`history.json`):

| Pair | Candles | First (UTC) | Last (UTC) | Missing before / inside / after | Zero-volume candles | Requests |
| --- | --- | --- | --- | --- | --- | --- |
| BTC/IDR | 26904 | 2023-10-01 00:00 | 2026-10-25 23:00 | 0 / 0 / 0 | 92 | 54 |
| ETH/IDR | 26904 | 2023-10-01 00:00 | 2026-10-25 23:00 | 0 / 0 / 0 | 99 | 54 |
| SOL/IDR | 26904 | 2023-10-01 00:00 | 2026-10-25 23:00 | 0 / 0 / 0 | 102 | 54 |

"Before" and "after" are counted against the requested range (`requested_since`, `requested_until`), "inside" between the first and last candle; all three come from `history.json` re-run at the review fix commit.

History older than 2023-10-01 was not requested. A separate probe with a 500-candle window returned full 1h BTC/IDR for 2023-10-22 and 2024-08-17, whereas without `until` every `since` (30 to 2000 days) yields the same 649 candles.

## Design (locked before the run)

- Strategy: `engine/strategies/swing_ema_rsi.py` as is on main, including the risk layer (position size 0.5% risk per trade, daily loss limit 1%, total drawdown limit 10%, maximum 3 positions). Configuration `config/config.example.yaml`: capital Rp 2.000.000, compounding on, BTC/IDR, ETH/IDR, SOL/IDR.
- Strategy parameters: 13 (EMA 20 and 50, RSI 14, RSI entry 45-70, RSI exit 78, stoploss -3%, three-step ROI table 0 minutes 5%, 480 minutes 2.5%, 1440 minutes 1.2%). Risk parameters: 4 (0.5%, 1%, 10%, 3 positions). All were chosen in stage 0a before this data was downloaded; none was changed in this stage.
- Variations tried: 1 strategy parameter set. Matrix: 2 periods × (as_configured with fee and tax, limits_off with three cost levels) = 8 backtests. The matrix, periods, and bootstrap seed are in `engine/backtest_suite.py` at commit `3d7a371`, before the first backtest.
- Periods: in-sample 2023-10-26 to 2025-10-26 (2 years), out-of-sample 2025-10-26 to 2026-10-26 (1 year). Since there is no tuning, the in-sample here is the part that may be used if tuning ever happens; out-of-sample must not be touched for that.
- Cost per side: fee_and_tax 0.41% (fee 0.2% from the public API plus tax 0.21% from a secondary source, not yet verified against an official document), fee_only 0.2%, no_cost 0% (gross comparison).
- Risk mode: as_configured uses the limits as they are; once total drawdown breaches 10%, new entries stop until the end of the period (on_breach: stop_new_entries). limits_off raises the daily loss and total drawdown limits to 100% (position size stays at 0.5% risk), so that the expectancy of the rules is measured over the whole period, not only up to the kill switch.
- Distribution: per-trade quantiles and a 95% percentile bootstrap interval for the mean (10,000 resamples, seed 3778).

Four trial runs occurred: the first three stopped because of script defects (data directory not yet created, container without network so Freqtrade could not load market metadata, `backtest_end` date without a time zone). The third run did manage to finish in_sample-as_configured-fee_and_tax (104 trades, -7.85%, same as the fourth run) before failing at summarisation. No strategy parameter, matrix, or period changed in between; the results below are from the fourth run.

## Results

Expectancy per trade is the mean Freqtrade `profit_ratio`, which already has the costs of both sides deducted at that run's cost level. Max drawdown is computed from the balance after each closed trade and equals Freqtrade's `max_drawdown_account` in all eight runs. "Days without entry at the end" is the distance from the last entry to the end of the period.

| Run | Period | Cost per side | Risk mode | Trades | Expectancy per trade | 95% CI | Median | Win rate | Max drawdown | Total result | Days without entry at the end |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample-as_configured-fee_and_tax | in_sample | 0.41% | as_configured | 104 | -0.590% | -1.092% .. -0.092% | -1.447% | 44.2% | 10.06% | -7.85% | 545.6 |
| in_sample-limits_off-fee_and_tax | in_sample | 0.41% | limits_off | 447 | -0.818% | -1.044% .. -0.594% | -1.524% | 38.3% | 40.06% | -38.48% | 1.8 |
| in_sample-limits_off-fee_only | in_sample | 0.20% | limits_off | 447 | -0.428% | -0.643% .. -0.218% | -0.964% | 40.5% | 28.63% | -24.90% | 1.8 |
| in_sample-limits_off-no_cost | in_sample | 0.00% | limits_off | 447 | -0.058% | -0.263% .. +0.143% | -0.508% | 43.6% | 12.77% | -4.61% | 1.8 |
| out_of_sample-as_configured-fee_and_tax | out_of_sample | 0.41% | as_configured | 59 | -1.388% | -1.913% .. -0.868% | -1.758% | 28.8% | 10.27% | -10.27% | 250.8 |
| out_of_sample-limits_off-fee_and_tax | out_of_sample | 0.41% | limits_off | 221 | -0.832% | -1.098% .. -0.561% | -1.521% | 34.4% | 22.17% | -21.63% | 5.3 |
| out_of_sample-limits_off-fee_only | out_of_sample | 0.20% | limits_off | 221 | -0.451% | -0.707% .. -0.194% | -1.097% | 37.1% | 14.55% | -13.81% | 5.3 |
| out_of_sample-limits_off-no_cost | out_of_sample | 0.00% | limits_off | 221 | -0.077% | -0.317% .. +0.171% | -0.675% | 38.9% | 6.89% | -2.95% | 5.3 |

| Run | p05 | p25 | p75 | p95 | Standard deviation | Min | Max | Median holding time (hours) | Risk gate rejections |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample-as_configured-fee_and_tax | -3.792% | -3.299% | +1.744% | +2.573% | 2.649% | -3.792% | +5.000% | 13.0 | daily_loss 2, total_drawdown 341 |
| in_sample-limits_off-fee_and_tax | -3.792% | -2.776% | +1.200% | +2.500% | 2.395% | -3.792% | +5.000% | 15.0 | 0 |
| in_sample-limits_off-fee_only | -3.387% | -2.251% | +1.200% | +2.500% | 2.285% | -3.387% | +5.000% | 14.0 | 0 |
| in_sample-limits_off-no_cost | -3.000% | -1.850% | +2.036% | +2.874% | 2.196% | -3.000% | +5.000% | 13.0 | 0 |
| out_of_sample-as_configured-fee_and_tax | -3.792% | -2.862% | +1.200% | +2.123% | 2.036% | -3.792% | +2.500% | 15.0 | total_drawdown 162 |
| out_of_sample-limits_off-fee_and_tax | -3.792% | -2.248% | +1.200% | +2.500% | 2.044% | -3.792% | +5.000% | 18.0 | 0 |
| out_of_sample-limits_off-fee_only | -3.387% | -1.837% | +1.200% | +2.500% | 1.953% | -3.387% | +5.000% | 17.0 | 0 |
| out_of_sample-limits_off-no_cost | -3.000% | -1.417% | +1.200% | +2.500% | 1.866% | -3.000% | +5.000% | 16.0 | 0 |

| Run | Pair | Trades | Expectancy per trade |
| --- | --- | --- | --- |
| in_sample-as_configured-fee_and_tax | BTC/IDR | 33 | -1.103% |
| in_sample-as_configured-fee_and_tax | ETH/IDR | 34 | -0.526% |
| in_sample-as_configured-fee_and_tax | SOL/IDR | 37 | -0.191% |
| in_sample-limits_off-fee_and_tax | BTC/IDR | 146 | -0.979% |
| in_sample-limits_off-fee_and_tax | ETH/IDR | 152 | -0.825% |
| in_sample-limits_off-fee_and_tax | SOL/IDR | 149 | -0.654% |
| in_sample-limits_off-fee_only | BTC/IDR | 146 | -0.565% |
| in_sample-limits_off-fee_only | ETH/IDR | 152 | -0.438% |
| in_sample-limits_off-fee_only | SOL/IDR | 149 | -0.284% |
| in_sample-limits_off-no_cost | BTC/IDR | 146 | -0.170% |
| in_sample-limits_off-no_cost | ETH/IDR | 152 | -0.066% |
| in_sample-limits_off-no_cost | SOL/IDR | 149 | +0.060% |
| out_of_sample-as_configured-fee_and_tax | BTC/IDR | 22 | -1.369% |
| out_of_sample-as_configured-fee_and_tax | ETH/IDR | 17 | -0.921% |
| out_of_sample-as_configured-fee_and_tax | SOL/IDR | 20 | -1.806% |
| out_of_sample-limits_off-fee_and_tax | BTC/IDR | 71 | -0.859% |
| out_of_sample-limits_off-fee_and_tax | ETH/IDR | 75 | -0.638% |
| out_of_sample-limits_off-fee_and_tax | SOL/IDR | 75 | -1.000% |
| out_of_sample-limits_off-fee_only | BTC/IDR | 71 | -0.453% |
| out_of_sample-limits_off-fee_only | ETH/IDR | 75 | -0.310% |
| out_of_sample-limits_off-fee_only | SOL/IDR | 75 | -0.591% |
| out_of_sample-limits_off-no_cost | BTC/IDR | 71 | -0.048% |
| out_of_sample-limits_off-no_cost | ETH/IDR | 75 | +0.034% |
| out_of_sample-limits_off-no_cost | SOL/IDR | 75 | -0.215% |

| Run | Exit reason |
| --- | --- |
| in_sample-as_configured-fee_and_tax | ema_cross_down_or_rsi 47, roi 33, stop_loss 24 |
| in_sample-limits_off-fee_and_tax | ema_cross_down_or_rsi 218, force_exit 1, roi 147, stop_loss 81 |
| in_sample-limits_off-fee_only | ema_cross_down_or_rsi 210, force_exit 1, roi 160, stop_loss 76 |
| in_sample-limits_off-no_cost | ema_cross_down_or_rsi 193, force_exit 1, roi 179, stop_loss 74 |
| out_of_sample-as_configured-fee_and_tax | ema_cross_down_or_rsi 31, roi 15, stop_loss 13 |
| out_of_sample-limits_off-fee_and_tax | ema_cross_down_or_rsi 136, roi 63, stop_loss 22 |
| out_of_sample-limits_off-fee_only | ema_cross_down_or_rsi 129, roi 70, stop_loss 22 |
| out_of_sample-limits_off-no_cost | ema_cross_down_or_rsi 126, roi 75, stop_loss 20 |

## Reading

- After fees and tax, expectancy per trade is negative in both periods: in-sample -0,818% (447 trades) and out-of-sample -0,832% (221 trades) under limits_off; the 95% CI upper bounds are -0,594% and -0,561% respectively.
- Without costs (no_cost) expectancy is -0,058% in-sample and -0,077% out-of-sample, with 95% CIs that include zero: this data shows no edge in the rules before costs. The 0.41% per-side cost lowers expectancy by about 0.76 percentage points per trade (in-sample -0,818 versus -0,058; out-of-sample -0,832 versus -0,077); median holding time is 13 to 18 hours.
- With the configuration as is, the 10% total drawdown limit is reached and halts entries: last entry 2024-04-28 in-sample (545.6 days without entries, 341 total_drawdown rejections) and 2026-02-17 out-of-sample (250.8 days, 162 rejections). The risk gate works as designed and caps losses at around 10%, but it also means bot A with this strategy stops opening positions for several months.
- The stage 2 pass criteria in plan section 8 are not met by this strategy. No tuning was done to change that.

## Not proven and limitations

- The 0.21% per-side tax comes from a secondary source (plan section 1). The plan states one cycle at 0.61-0.82%; the backtest uses the 0.82% upper bound. The 0.61% scenario (tax on one side only) was not run; fee_only (0.4% per cycle) is its lower bound.
- Freqtrade fill model: orders fill at the next candle's open price or at the stoploss/ROI price, with no spread, slippage, order book depth, or unfilled limit orders. Indodax spread has not been measured.
- Market metadata (precision, minimum order) was fetched from Indodax at run time (2026-10-26) and applied to the entire history.
- The bootstrap interval assumes trades are independent. Trades across the three pairs often overlap and are correlated, so the true interval is likely wider.
- One historical path and one parameter set; no walk-forward. A 4-hour timeframe strategy or other parameters were not tested (every additional variation raises overfit risk and must be recorded).
- Data comes from the Indodax TradingView endpoint, which is not officially documented; completeness was checked (0 missing candles), price correctness was not compared against a second source.
- The swarm, news signals, and bot B are not included; the plan specifies evaluating them through a forward test.

## Re-running

    docker compose --profile build build freqtrade-base
    docker build -f docker/Dockerfile --target engine --build-context freqtrade-base=docker-image://trading-bot/freqtrade:2026.9 -t trading-bot/engine:stage2 .
    IMAGE=trading-bot/engine:stage2 scripts/stage2_backtest.sh user_data/stage2

The script downloads the history if `history.json` does not exist yet, then runs the eight backtests and writes `plan.json`, `report.json`, `report.md`, and the Freqtrade results per run in `runs/<run>/`. The eight backtests take 54 seconds (including container start) on the owner's PC. The download uses the network; the backtests also use the network for market metadata, without a key.
