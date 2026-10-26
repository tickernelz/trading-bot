# Default strategy search

**Final result after five rounds (ZHA-3876): tier T4 (provisional until forward data); no configuration reached the win-rate target, and the default is unchanged.** The default stays `RuleStrategy` with rule `J-rsi14-1h-tp3-sl10`, which often wins but loses money net of costs. 186 configurations were tried over five rounds (budget 1,500). The win-rate target (60% net, stable across folds, windows and regimes) was met only by small-target, wide-stop rules with a negative expectancy (rounds 1 and 2); every family with a positive expectancy wins 20% to 53% of trades. Measured by Zhafron's later criterion, profit per month on Rp 2,000,000, the best results are round 5's F1 regime holds (hold every pair while BTC/IDR closes above its SMA, one equal share each). One bad SOL/IDR candle decides which: with it, the locked selection is `F1-regime-btc-sma50` at Rp 79,841 a month and 34.4% drawdown on the five selection pairs; with that one low corrected, `F1-regime-btc-sma100` comes first at Rp 82,892 a month and 19.0% drawdown (section "Round 5"). On six pairs nobody used for selection they make Rp 46,970 (SMA50, 33.9% drawdown) and Rp 48,360 (SMA100, 22.3%) a month, against Rp 52,864 and Rp 34,090 for equal-weight buy-and-hold of the same pairs at 61.4% and 53.0% drawdown. That is more than buy-and-hold at roughly half its drawdown or less, but these numbers use research sizing the bot cannot run (one equal share of equity per pair, no 10% drawdown stop), but it is not shown to be profitable: it misses the win-rate target, so by the locked tiers it is T4, and the cross-asset pairs move with the selection pairs over the same years, so it is not forward evidence. Section "Round 5" below; families tried and the next directions at the end of that section.

## Round 5: portfolio versions of the ZHA-3913 shortlist (the last round)

Locked in `4293a43` before the first round 5 run (plan.md, "Round 5"). Twelve configurations: Laras's F1 (hold every pair while the daily BTC/IDR close is above its SMA 50, 100 or 200) and F3 with a Donchian channel exit (enter above the n-day high, exit below the m-day low, stop 2 x ATR(14) daily), scored with an equal-weight account (99% / N of equity per pair) next to the risk-sized one. Ranking: tier, then equal-weight profit per month, then drawdown.

Five selection pairs, 2022-07-01 to 2026-04-26, taker costs, compounded on Rp 2,000,000. Worst month is the worst calendar month's loss as a share of the equity that month started with, times Rp 2,000,000 (corrected after review: the first version multiplied the compounded account's absolute loss by Rp 2,000,000, which at 6x to 8x equity read as most of the capital; rounds 3 and 4 kept equity near 1x, so their figures barely move). Numbers from the run `walk-forward-r5-month` at `d885add`, identical to the locked run except the worst month:

| Config | Trades | Win rate | Mean net (95% CI) | Profit/month equal weight | Max DD | Worst month | Largest loss |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F1-regime-btc-sma50 (selected) | 195 | 28.7% | +7.31% (+2.30% .. +13.62%) | Rp 79,841 | 34.4% | Rp -239,506 | -24.6% |
| F1-regime-btc-sma100 | 116 | 25.9% | +13.29% (+2.34% .. +27.76%) | Rp 73,517 | 27.6% | Rp -206,646 | -95.0% (bad candle, see below) |
| F1-regime-btc-sma100, bad SOL low corrected | 115 | 27.0% | +14.42% (+3.37% .. +29.06%) | Rp 82,892 | 19.0% | Rp -206,646 | -15.2% |
| F3L-don1d20-low10-nofilter-st2atr | 137 | 39.4% | +7.44% (+2.01% .. +14.35%) | Rp 61,337 | 17.0% | Rp -167,889 | -14.4% |
| F3L-don1d55-low20-btc100-st2atr | 61 | 47.5% | +16.10% (+4.20% .. +31.20%) | Rp 58,840 | 12.2% | Rp -85,386 | -12.7% |
| Equal-weight buy-and-hold of the same five pairs | - | - | - | Rp 52,864 | 61.4% | - | - |

The random-entry null for the selected configuration (its own exits and entry rate, 1,000 series): p95 +5.61%, beaten (+7.31%). The random-entry control with F1's exits made Rp 2,604 a month. Controls for all nine rule configurations: shifting signals one daily candle earlier raises every mean (selected +7.31% to +13.75%), truncation 0 of 200 failures and 0 live-window mismatches each.

Cross-asset on BNB, NEAR, HBAR, ADA, LTC and TRX (the first three eligible configurations by the ranking key, research mode):

| Config | Trades | Win rate | Mean net (95% CI) | Profit/month equal weight | Max DD | Worst month | Pairs with a positive mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F1-regime-btc-sma100 | 138 | 31.2% | +8.40% (+1.17% .. +17.70%) | Rp 48,360 | 22.3% | Rp -300,073 | 6 of 6 |
| F1-regime-btc-sma50 | 234 | 29.9% | +5.09% (+0.73% .. +10.97%) | Rp 46,970 | 33.9% | Rp -365,665 | 6 of 6 |
| F3L-don1d20-low10-nofilter-st2atr | 157 | 29.9% | +4.55% (-0.31% .. +10.89%) | Rp 29,759 | 26.3% | Rp -171,522 | 5 of 6 |
| Equal-weight buy-and-hold of the six pairs | - | - | - | Rp 34,090 | 53.0% | - | - |

All three beat the random-entry null on the unseen pairs; their Bonferroni lower bounds over 186 configurations are negative (-4.5% to -7.1%), so after correcting for every configuration tried none is significant. Generated: [strategy-research/round5/results.md](strategy-research/round5/results.md), [strategy-research/cross/cross-asset-r5.md](strategy-research/cross/cross-asset-r5.md).

Data quality: the SOL/IDR 1h candle of 2023-05-13 08:00 UTC has a low of Rp 500 against Rp 312,000 to 314,000 before and after (one bad print in the Indodax history). A scan of all 11 pairs (low below half the body or the previous close, or high above twice) finds it is the only such candle inside the scoring period. Any open SOL position with a stop below that price filled there: F1 with SMA100 or SMA200 (a 95% hard stop) and the random control each record one -95.0% trade. The locked run keeps the data as fetched. A sensitivity run with that one low set to min(open, close) (`walk-forward-r5-clean` at `d885add`, in the ledger with its own SOL hash; [strategy-research/round5-clean/results.md](strategy-research/round5-clean/results.md)) changes the selection to `F1-regime-btc-sma100`: Rp 82,892 a month, 19.0% drawdown, +14.42% per trade, largest loss -15.2%, null p95 +10.68% beaten. `F1-regime-btc-sma200` rises to Rp 70,161 at 14.7%, the random control to Rp 10,425; `F1-regime-btc-sma50` and the F3 rules (no open SOL trade then) change by under Rp 300. The three configurations checked cross-asset are the same with or without the correction. A live bot on bot-side stops could take such a fill if the exchange prints it.

Sizing: the equal-weight numbers bypass the risk layer. The bot sizes a stake to lose 0.5% of equity at the stop (about 0.53% of equity per F1 position with its 95% stop) and stops entering for good at a 10% total drawdown; F1 drawdowns are 19% to 34%. A dry run of the bot would not reproduce these figures without a stake mode for equal weight, a looser loss limit, and a Freqtrade parity check of `regime`, `regime_off` and `donchian_low`, none of which exist yet.

## Five rounds: families tried and why they fell short

| Round | Families | Best result | Why it fell short |
| --- | --- | --- | --- |
| 1 (ZHA-3872) | Donchian, momentum, EMA trend, volume breakout, RSI2 and Bollinger reversion, small target with wide stop, Fear and Greed | `J-rsi14-1h-tp3-sl10`, 77% net win rate, -0.60% per trade | high win rates came only from small targets and wide stops, which lose money after costs |
| 2 | faster trend filters, ATR exits, two more pairs | `S-don1d20-sma50-tp5-lock3`, 66.8%, +0.08% (CI includes 0) | no forward data to judge it; on eight other pairs it lost -0.65% per trade |
| 3 | trend rules that let winners run (Donchian with ATR trail, momentum, EMA) | `M-tsmom-90-sma100`, 25.5%, +9.12% | win rates of 23% to 53%; profit per month far below buy-and-hold at 0.5% risk sizing |
| 4 | Donchian and momentum behind the BTC regime gate | `F3-tsmom-55-btcabove-sma100-sl20`, 24.1%, +5.95% | same as round 3 |
| 5 | portfolio versions: F1 regime hold, F3 Donchian channels, equal-weight sizing | `F1-regime-btc-sma50`, Rp 79,841 a month, 34.4% DD (with one bad SOL low corrected: `F1-regime-btc-sma100`, Rp 82,892, 19.0% DD) | beats buy-and-hold per month at about half its drawdown or less, but wins 26% to 29% of trades (target 60%), is not significant after 186 configurations, and uses sizing the bot cannot run |

The locked target asks for a high win rate; the evidence of five rounds is that on Indodax spot after 0.62% round-trip costs, a high win rate and a positive expectancy do not come together in these families. What does carry to unseen pairs is a low-win-rate trend or regime hold with a positive mean.

## Three next directions, with their data needs

1. Forward test of `F1-regime-btc-sma100` and `F1-regime-btc-sma50` (one bad candle decides between them, so both) plus `F3L-don1d55-low20-btc100-st2atr`, unchanged: 2 to 4 trades a month on five pairs for F1, so 100 forward trades take two to four years; a monthly check of the equity curve against buy-and-hold is possible sooner. Needs: an equal-weight stake mode in the bot, a total-drawdown limit above the 19% to 34% these rules have shown (or research mode in a dry run only), a Freqtrade parity check of the new `regime`, `regime_off` and `donchian_low` rules, and one dry-run bot per configuration; no new historical data.
2. Re-state the target around Zhafron's monthly-profit criterion (median monthly return above zero with a CI, beating buy-and-hold on Sharpe and drawdown, as in Laras's protocol) instead of a per-trade win rate, and judge rounds 3 to 5 against it. Needs: a decision by Wira; the round 5 equity curves already exist.
3. Maker entries and stop-fill realism: Laras's F3 used maker entries (0.42% round trip instead of 0.62%), and the bad SOL print shows stop fills need a sanity check (reject a fill more than a set multiple of ATR away from the previous close). Needs: an Indodax order-book or trade history to model limit fills, which the public candle endpoint does not give.

**Rounds 3 and 4 result (ZHA-3876): tier T4 (provisional); the default is unchanged.** Thirty-two trend configurations, six of them behind a BTC/IDR daily regime gate, won 23% to 53% of trades, so none reaches the 60% target. Zhafron's measure (profit per month on Rp 2,000,000) puts the best eligible one at Rp 7,144 a month, against Rp 52,864 for equal-weight buy-and-hold of the same pairs, at 2.5% drawdown against 61.4%. Ranked by tier first, the default stays. Sections "Round 4" and "Round 3" below.

**Round 2 result (ZHA-3876): not enough data; the default is unchanged.** The default stays round 1's `RuleStrategy` with rule `J-rsi14-1h-tp3-sl10` (often wins but loses money net of costs; section "Round 1"). Round 2's best configuration, `S-don1d20-sma50-tp5-lock3` (1d Donchian 20 breakout while the daily close is above its SMA50, take-profit 5%, profit lock at 3%, Donchian-mid exit, 8% stop) on BTC/IDR, ETH/IDR, SOL/IDR, XRP/IDR and DOGE/IDR, meets the locked win-rate target on the walk-forward (2022-07-01 to 2026-04-26): 382 trades, net win rate 66.8% (Wilson 95% lower bound 61.9%), net expectancy +0.076% per trade (95% CI -0.436% to +0.598%), walk-forward tier T2. The task accepts only the holdout or forward data for the final evaluation; the round 1 holdout is used and the forward data after 2026-10-26 holds 0 trades, so no target is reported as met and the configuration is not the default. A once-only check on untouched older data (2018-09-01 to 2021-01-01) is supporting evidence only: 189 trades on 4 pairs, net win rate 69.8% (Wilson 63.0%), net expectancy +0.739% per trade (95% CI -0.028% to +1.484%). At 0.41% per side or with +0.10% slippage per side the walk-forward mean is negative. Nothing here is shown to be profitable. Live mode stays locked (`LIVE_ENGINE_PROVEN = False`).

Generated tables for round 2: [strategy-research/round2/results.md](strategy-research/round2/results.md) (every configuration, fold, control and the pre-sample run), `round2/walk-forward-summary.json` and `round2/presample.json`. Locked plan: [strategy-research/plan.md](strategy-research/plan.md), section "Round 2". Ledger: [strategy-research/ledger.jsonl](strategy-research/ledger.jsonl).

## Round 4: F3 variants behind a BTC regime gate (ZHA-3876, ZHA-3913 shortlist)

**Result: tier T4 (provisional until forward data) for every configuration; the default does not change.** Six configurations (locked in `9b0741c`, after the round 3 runs; review ZHA-3896 made them round 4, and the ledger lines from `9b0741c` and `5556612` say `round: 3`) put Laras's BTC/IDR daily regime gate (`btc_above_sma100_1d`) in front of Donchian or time-series momentum entries. Only `F3-don1d55-exit20-btc_above_sma100-sl20` is close to her F3 grid (with a 20% stop and taker entries instead of her 2 x ATR stop and maker entries). The walk-forward run at `9b0741c` scored the round 3 and round 4 configurations together; the selected configuration is the round 4 `F3-tsmom-55-btcabove-sma100-sl20`. The generated report [strategy-research/round4/results.md](strategy-research/round4/results.md) carries the round number the run recorded (3).

On the five selection pairs, compounded on one Rp 2,000,000 account with 3 slots:

| Config | Trades | Win rate | Mean net (95% CI) | Profit/month at 0.5% risk | at 2% risk | Max DD at 0.5% / 2% | Worst month | Largest loss |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F3-tsmom-55-btcabove-sma100-sl20 (selected) | 162 | 24.1% | +5.95% (-0.21% .. +14.00%) | Rp 7,144 | Rp 24,003 | 2.5% / 9.6% | Rp -16,796 | -20.5% |
| F3-don1d55-exit55-btc_above_sma100-sl20 | 57 | 49.1% | +15.31% (+2.89% .. +31.07%) | Rp 6,281 | Rp 23,059 | 1.5% / 5.7% | Rp -15,763 | -20.5% |
| F3-don1d55-exit20-btc_above_sma100-sl20 | 80 | 47.5% | +9.73% (+2.77% .. +18.18%) | Rp 5,720 | Rp 21,469 | 1.4% / 5.6% | Rp -15,089 | -19.3% |
| Equal-weight buy-and-hold of the same five pairs | - | - | - | Rp 52,864 | - | 61.4% | - | - |

The random-entry null was run for the selected configuration only (its own exits and entry rate): p95 +3.22%, beaten. Controls for all six round 4 configurations (run after review at `b13fb51`, which gave the live-window check the BTC candles the gate reads): shifting signals one rule candle earlier raises every mean (selected: +5.95% to +11.90%), truncation 0 of 200 failures and 0 live-window mismatches each.

Cross-asset, on BNB, NEAR, HBAR, ADA, LTC and TRX (taker costs, research mode), for the first three round 4 configurations by the ranking key, eligible or not (the choice rule was recorded after the run, see plan.md "Round 4"):

| Config | Trades | Win rate | Mean net (95% CI) | Profit/month 0.5% | at 2% | Max DD | Worst month | Pairs with a positive mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F3-don1d55-exit20-btc_above_sma100-sl20 | 94 | 37.2% | +5.29% (-0.26% .. +12.79%) | Rp 4,301 | Rp 15,066 | 1.9% | Rp -17,884 | 5 of 6 |
| F3-tsmom-55-btcabove-sma100-sl20 | 169 | 27.8% | +5.47% (-0.83% .. +13.98%) | Rp 2,610 | Rp 8,238 | 4.2% | Rp -18,850 | 5 of 6 |
| F3-don1d55-exit55-btc_above_sma100-sl20 | 61 | 39.3% | +12.79% (+1.38% .. +27.35%) | Rp 2,181 | Rp 7,926 | 1.6% | Rp -18,223 | 5 of 6 |
| Equal-weight buy-and-hold of the six pairs | - | - | - | Rp 34,090 | - | 53.0% | - | - |

Generated: [strategy-research/cross/cross-asset-r4.md](strategy-research/cross/cross-asset-r4.md). The three configurations checked kept 5 of 6 unseen pairs positive; the other three round 4 configurations were not run cross-asset.

## Round 3: trend entries that let winners run, ranked by profit per month (ZHA-3876)

**Result: tier T4 (provisional until forward data) for every configuration; the default does not change.** Twenty-six trend configurations (Donchian 1d with a mid exit or an ATR trail, time-series momentum, EMA trend; locked in `8081f68`), none with the BTC gate, won 23% to 53% of trades (deployable rules), so none reaches the 60% target. Selected by the ranking (tier, then profit per month, then drawdown): `M-tsmom-90-sma100`, 106 trades, 25.5%, +9.12% per trade (95% CI -1.07% to +22.39%), Rp 6,542 a month at 0.5% risk (Rp 20,205 at 2%), 2.4% drawdown. The highest monthly profit, `L-don1d-30-nofilter-trail4atr` at Rp 7,595, has 83 trades and is not eligible (under 100). Generated: [strategy-research/round3/results.md](strategy-research/round3/results.md) (replayed at `8081f68` with the same inputs after its output was overwritten; ledger lines 15:11 UTC).

Cross-asset at `8081f68` on eight pairs (BNB, NEAR, HBAR, ADA, LTC, TRX, LINK, DOT), the first three eligible configurations, research mode ([strategy-research/cross/cross-asset-r3.md](strategy-research/cross/cross-asset-r3.md)); superseded because ZHA-3913 later used LINK and DOT for its own test:

| Config | Trades | Win rate | Mean net (95% CI) | Max DD | Worst month | Pairs with a positive mean |
| --- | --- | --- | --- | --- | --- | --- |
| M-tsmom-90-sma100 | 146 | 32.9% | +7.79% (+0.88% .. +16.19%) | 5.8% | Rp -34,756 | 8 of 8 |
| M-tsmom-90-nofilter | 212 | 32.1% | +5.51% (+0.65% .. +11.45%) | 6.2% | Rp -35,732 | 8 of 8 |
| P-don1d-30-mid-sl20 | 162 | 38.9% | +4.98% (+0.83% .. +9.88%) | 2.9% | Rp -26,464 | 7 of 8 |

## Rounds 3 and 4: what this says

- Zhafron's measure (profit per month) leaves the same verdict as the win rate: buy-and-hold of the same pairs made six to twelve times the monthly profit of the best rule over the same years, at 53% to 61% drawdown against 1.4% to 6.2%. Per unit of drawdown the trend rules are far better; in absolute rupiah they are not close.
- The trend families carry their positive mean to unseen pairs: every configuration checked cross-asset in rounds 3 and 4 had a positive mean on at least 5 of 6 (or 7 of 8) unseen pairs. The tier stays T4 only because the target asks for a 60% win rate, which these rules never reach.
- Loss limits were never reached on the round 3 or 4 trades (0 refusals in the account model), so research mode and the bot's limits give the same numbers here; the one-off measurement on the round 1 default stands at 592 to 367 walk-forward trades and 23.2% to 10.8% drawdown.
- The "2% risk" columns are research sizing: the bot refuses `risk.risk_per_trade_pct` above `risk.max_daily_loss_pct` (1% in the example config), so 2% per trade needs a daily limit of at least 2% or research mode.
- Configurations: 26 in round 3 (168 cumulative of 1,500) and 6 in round 4 (174). One round is left.

Not shown, and the subject of the last round: Laras's F1, F2, F4 and F6 are portfolio strategies (equal weight across pairs, rotation, ensemble), not per-pair rules; her numbers (3.29% a month for F1, 2.91% for F6) need a portfolio engine in this runner to check.

## Cross-asset check of the round 1 and 2 candidates (ZHA-3876, direction of 2026-10-26 12:28 UTC)

**Result: tier T4 (provisional until forward data) for all four configurations checked; the default is unchanged.** On eight IDR pairs never used for selection (BNB, NEAR, HBAR, ADA, LTC, TRX, LINK, DOT; 2022-07-01 to 2026-04-26, taker costs), the round 2 candidate `S-don1d20-sma50-tp5-lock3` made 621 trades at a net win rate of 59.7% (Wilson 55.8%) and lost -0.646% per trade (95% CI -1.09% to -0.22%); it lost money on six of the eight pairs. The default `Q-J-rsi14-1h-tp3-sl10` won 77.9% of 1,353 trades and lost -0.374% per trade (95% CI -0.67% to -0.08%); it misses the target only on (c), a rolling 30-trade minimum of 26.7%, and is "often wins but loses money net of costs" by its expectancy. `Q-F-don1d20-tp5-lock3`: 429 trades, 59.2%, -0.695%. `Q-G-rsi2-1d-10-sl25`: 199 trades, 55.3%, -0.515%. The round 2 walk-forward edge does not carry over to other coins over the same years, which points to selection luck on the five pairs rather than a general effect. Generated tables: [strategy-research/cross/cross-asset-r12.md](strategy-research/cross/cross-asset-r12.md) (generated at ae2fc04); raw output `cross/cross-asset-r12.json`; protocol: plan.md, section "Round 3 and later" (locked in `51a82d1` before the run).

Risk next to the win rate (cross-asset, taker costs, one Rp 2,000,000 account with 0.5% risk per trade and 3 slots): largest loss -10.24% (`S`), -11.45% (default), -25.46% (`Q-G`, 25% stop); mean of the 5 worst trades -9.50%, -11.15%, -25.46%; max drawdown 20.0%, 20.8%, 3.6%; worst calendar month Rp -41,727, Rp -63,916, Rp -19,214.

Research mode against the loss limits, measured once on the same trades ("one account" table): the simulator never modelled the 1% daily and 10% total loss limits, so rounds 1 and 2 ran in research mode. With the limits, the default takes 367 instead of 592 walk-forward trades (341 entries refused by the limits, the account stops for good at the 10% drawdown), its drawdown falls from 23.2% to 10.8% and its win rate rises from 75.2% to 77.1% with the mean still negative (-0.595%). `S` on the cross-asset pairs: 315 instead of 493 trades, drawdown 10.1% instead of 20.0%. On the walk-forward `S`, `Q-F` and `Q-G` never reach a limit (0 refusals).

Round 3 searches new families from the ZHA-3902 shortlist under this protocol: selection on the five walk-forward pairs, tier from the walk-forward folds plus the eight cross-asset pairs, written provisional until forward data.

## Round 2: why these changes

Round 1's data (section "Round 1" below) showed three failure modes: every positive-expectancy trend rule failed target (b) because its 1d SMA200 filter left fold F1 (2022-H2) or F8 (2026-01..04) without a trade; the high win rate families had a payoff of 0.06 to 0.56 from fixed percentage targets; and trend rules made too few trades for narrow CIs. Round 2 added two liquid pairs (XRP/IDR, DOGE/IDR), faster trend filters (SMA50, SMA100 on 1d), ATR-scaled targets and stops (ZHA-3871 section 4.4), a Bonferroni bound over the cumulative number of configurations, and a once-only check on untouched pre-2021 data, because the round 1 holdout is used and no forward data after 2026-10-26 exists yet. After review (ZHA-3896) that check is supporting evidence only; the final evaluation needs forward data (plan.md, "Correction after review"). 49 configurations, 142 over both rounds (budget 600), locked in `4642bd8` before the first run.

## Round 2: locked before the first run

| Item | Value |
| --- | --- |
| Lock commit | `4642bd8` (plan, 49-configuration matrix, pre-sample rule) |
| Walk-forward data | Indodax 1h, 2021-01-01 to 2026-04-26 for the five pairs (BTC, ETH, SOL: the round 1 files, same SHA-256; XRP and DOGE fetched 2026-10-26, 0 gaps); nothing after 2026-04-26 is loaded |
| Pre-sample data | Indodax 1h, 2018-01-01 to 2021-01-01 for BTC, ETH, XRP (0 gaps) and DOGE (listed 2018-07-25, 0 gaps after); scored from 2018-09-01; no earlier run or probe scored a trade before 2021 |
| Pre-sample rule | one run, one configuration, only for a walk-forward T1 or T2; refused afterwards (`presample_started`); supporting evidence, not the final evaluation (correction after review) |
| Costs, folds, targets, seeds | as in round 1 |

## Round 2: ledger

| Run | Commit | Tree | Outcome |
| --- | --- | --- | --- |
| walk-forward, 49 configurations | 4642bd8 | clean | ok, selected `S-don1d20-sma50-tp5-lock3` (walk-forward T2) |
| validation (stage 2 period, SwingEmaRsi) | fea68c3 | clean | ok, 447 trades, -0.818%, 38.3%, equal to stage 2 |
| controls, every configuration | fea68c3 | clean | ok |
| pre-sample, `S-don1d20-sma50-tp5-lock3` | fea68c3 | clean | ok (the runner labels it T2; supporting evidence only) |

Every run first writes a `<kind>_started` line, so a killed run leaves a trace. `fea68c3` differs from `4642bd8` only in `engine/search_report.py` (report headings), which no run imports.

## Round 2: results

Walk-forward, net of taker costs, the selected configuration and the nearest alternatives (all 49 rows: round2/results.md):

| Config | Tier | Trades | Net win rate | Mean net per trade | 95% CI | Fold WR % F1..F8 | Fold SD | Payoff | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-don1d20-sma50-tp5-lock3 (best, not the default) | T2 | 382 | 66.8% | +0.076% | -0.44% .. +0.60% | 51 62 70 69 69 72 73 61 | 7.4 | 0.51 | 5.4% |
| S-don1d20-nofilter-tp5-lock3 | T2 | 418 | 65.8% | +0.039% | -0.47% .. +0.56% | 51 61 68 69 71 71 71 55 | 7.9 | 0.53 | |
| Q-J-rsi14-1h-tp3-sl10 (the default) | T3 | 875 | 75.8% | -0.767% | -1.14% .. -0.39% | 75 81 83 76 74 70 80 71 | 4.6 | 0.22 | |
| Q-F-don1d20-tp5-lock3 | T4 | 280 | 68.2% | +0.353% | -0.27% .. +0.98% | 57 60 71 68 70 74 69 - | 6.1 | 0.54 | |
| Q-F-don1d20-tp8-lock3 | T4 | 250 | 63.6% | +0.750% | -0.01% .. +1.52% | 57 45 64 68 67 71 66 - | 8.7 | 0.77 | |
| V-don1d20-sma200-tp2atr-st3atr | T4 | 212 | 59.0% | +0.912% | -0.25% .. +2.08% | 33 43 70 64 67 47 50 - | 13.7 | 0.88 | |

- The faster SMA50 filter is what moved the near miss over target (b): it trades in F1 (51%) and F8 (61%), where the SMA200 version took no trade even on five pairs. It pays for that with a lower mean (+0.08% against +0.35%).
- ATR exits (family V) raised the mean of trend entries (up to +0.91%) but not the win rate: their folds range from 33% to 79% and none meets (b). ATR exits on pullbacks (family W) lost in every configuration (-0.53% to -0.72%).
- `S-don1d20-sma50-tp5-lock3` on the walk-forward: profit factor 1.03, payoff 0.51, largest loss -8.57%, mean of the 5 worst trades -8.57% (the 8% stop plus costs), max drawdown 5.9% at 0.5% risk per trade (5.4% in the generated tables, see below), 8.3 trades per month, rolling 30-trade minimum 50.0%, regimes bear 57.3% (75 trades), range 73.3% (30), bull 68.6% (277). Cost sensitivity of the mean: 0.41% per side -0.122%, no tax +0.287%, +0.05% slippage -0.024%, +0.10% slippage -0.124%.
- Multiple testing: Bonferroni lower bound of the walk-forward mean over 142 configurations -0.890%. Null (1,000 random-entry series with the same exits and entry rate): mean p95 -0.370%, beaten.
- Positions: the simulator scores each pair independently, so up to 4 trades of this rule were open at once, and the Freqtrade parity run allowed 5. With the example's `max_open_trades: 3`, taking entries in time order (ties by pair), 37 of 382 walk-forward trades would be skipped (the remaining 345: win rate 67.8%, +0.218% per trade) and 11 of 189 pre-sample trades (178: 70.2%, +0.742%).
- Drawdown: the drawdown model let an entry refused for lack of slots hold a slot until its exit; fixed in this round. The generated tables of rounds 1 and 2 were computed before the fix; with the fix this rule's walk-forward drawdown is 5.89% (tables 5.41%) and its pre-sample drawdown 2.28% (unchanged).
- Selection walked forward (pick the best earlier mean before each fold) chose four different configurations over seven folds; the walk-forward is not evidence that the S rule would have been picked in advance.

Pre-sample 2018-09-01 to 2021-01-01, `S-don1d20-sma50-tp5-lock3`, taker costs: 189 trades (BTC 55, ETH 58, XRP 42, DOGE 34), net win rate 69.8% (Wilson 63.0%), mean +0.739% (95% CI -0.028% to +1.484%), profit factor 1.37, payoff 0.59, largest loss -8.57%, mean of the 5 worst trades -8.57%, max drawdown 2.3%, 6.7 trades per month, rolling 30-trade minimum 56.7% (walk-forward 50.0%), regimes bear 67.7% (31 trades), range 66.1% (62), bull 72.9% (96). Null p95 -0.100%, beaten. Mean at 0.41% per side +0.539%, with +0.10% slippage +0.537%. Comparators on the same period: SwingEmaRsi 970 trades, -0.935% per trade; buy-and-hold BTC +292%, ETH +149%, XRP -38%, DOGE -5%. On these trades (a) to (d) pass and the mean is above zero with a CI that includes zero, but this period is not holdout or forward data, so it yields no tier.

## Round 2: controls

- Lookahead detection fires for all 47 rule configurations (moving signals one candle earlier raises the mean by 0.35 to 3+ points). For `S-don1d20-sma50-tp5-lock3`, honest +0.076%, shift 1h +1.91%, shift 1d +3.12%, peek at the fill candle +0.54%.
- Truncation (40 seeded cuts, 5 pairs): 0 of 200 comparisons failed for every configuration; live window (649 candles per timeframe): 0 entry mismatches.
- Freqtrade 2026.9 backtest of `RuleStrategy` with rule `S-don1d20-sma50-tp5-lock3` on the five pairs over the whole walk-forward at 0.41% per side, one position per pair: 382 trades with the same pair, entry and exit times as the simulator (382 of 382), win rate 64.40% in both, mean -0.1230% (Freqtrade) against -0.1223% (simulator).
- Freqtrade `lookahead-analysis` on rule `S-don1d20-sma50-tp5-lock3`, 2024: `has_bias: No` (20 signals, 0 biased entries or exits). `recursive-analysis`: indicator differences at most 0.002% with 199 startup candles, 0.000% at the strategy's 400.

## Round 2: what the code now does

- `config.example.yaml` keeps the round 1 default and its three pairs; `exchange.fee_pct` is 0.31055, the mean of the taker buy and sell costs, so a dry-run round trip costs the same 0.6211% as the research (it was 0.2% per side).
- `strategy.rule` accepts `trend_filter` `above_sma50_1d` and `above_sma100_1d`, and `take_profit_atr` and `stop_atr` (multiples of the rule timeframe's ATR(14) at the signal candle; Freqtrade `custom_roi` and `custom_stoploss`; the ATR stop never loosens `stoploss`). Nothing in the example config uses them.
- The drawdown model no longer counts an entry refused for lack of slots as an open slot.
- The analytics backtest routes read the strategy name from the backtest result instead of assuming the configured default.

## Round 2: reproduce

```sh
run=$HOME/trading-bot-search2
docker build -f docker/Dockerfile --build-context freqtrade-base=docker-image://trading-bot/freqtrade:2026.9 --target test -t trading-bot/engine:search .
# walk-forward data in $run/data/indodax (five pairs, 2021-01-01 .. 2026-04-26), pre-sample data in $run/pre/indodax (2018-01-01 .. 2021-01-01), both with engine.history
IMAGE=trading-bot/engine:search scripts/strategy_search.sh $run walk-forward
IMAGE=trading-bot/engine:search scripts/strategy_search.sh $run controls
IMAGE=trading-bot/engine:search scripts/strategy_search.sh $run presample --datadir /run-dir/pre/indodax --wf-datadir /run-dir/data/indodax --candidate S-don1d20-sma50-tp5-lock3 --replay
```

The later `--datadir` replaces the script's walk-forward one. The candle files must match the SHA-256 values in the ledger. A replay is logged as `presample_replay`.

## Round 2: not shown

- A positive expectancy: both CIs include zero, the walk-forward mean is +0.08% and turns negative at 0.41% per side or with +0.10% slippage, and the pre-sample (a long bull run for BTC and ETH) is the only period where the mean is clearly above the costs.
- That the win-rate target holds on data the search never saw: the forward data holds 0 trades. Round 2, and every later round, can only be judged on forward data (a dry run of the locked configuration that keeps adding trades, or Indodax candles after 2026-10-26); at about 8 trades per month on five pairs, 100 forward trades take about a year. Until then the result is "not enough data".
- The pre-sample is now used and cannot serve as a check for later rounds.
- Stops run on the bot side, as in round 1; a gap or an offline PC can lose more than 8%.

## Round 1 (ZHA-3872), whose selection is still the default

**Result tier: T3 on the walk-forward, T4 on the holdout.** The new default `RuleStrategy` with rule `J-rsi14-1h-tp3-sl10` often wins but loses money net of costs: walk-forward 2022-07-01 to 2026-04-26, 519 trades, net win rate 77.1% (Wilson 95% lower bound 73.3%), net expectancy -0.599% per trade (95% CI -1.07% to -0.15%). On the untouched holdout (2026-04-26 to 2026-10-26) it made 54 trades, net win rate 77.8%, expectancy -0.112% per trade (95% CI -1.47% to +1.11%); the win-rate target fails there because 54 is below the required 100 trades. Nothing in this round is shown to be profitable. Live mode stays locked (`LIVE_ENGINE_PROVEN = False`).

All tables with every configuration, fold, pair, regime, control and cost level are generated into [strategy-research/results.md](strategy-research/results.md) by `python -m engine.search_report`. The locked plan is [strategy-research/plan.md](strategy-research/plan.md). The run ledger is [strategy-research/ledger.jsonl](strategy-research/ledger.jsonl). The stage 2 baseline is in [stage2-backtest.md](stage2-backtest.md).

### What was asked and how it was read

Zhafron asked for a default strategy with a high and stable win rate (2026-10-26). The locked definitions: a trade wins only when its profit after Indodax costs is above zero; the target is (a) holdout net win rate at least 60% with at least 100 trades on at least 2 pairs and a Wilson lower bound of at least 50%, (b) every walk-forward fold at least 50% with a fold standard deviation of at most 8 points, (c) every rolling 30-trade window at least 40%, (d) at least 50% in every BTC/IDR regime with 20 or more trades. Tiers: T1 target met with positive expectancy and a CI above zero (and above the random-entry null); T2 target met with positive point expectancy; T3 target met with expectancy at or below zero; T4 target not met. Wira's reading is kept next to it: a win rate says nothing about money unless expectancy per trade, which is win rate times average win minus loss rate times average loss minus costs, is reported beside it.

### Locked before the first result

| Item | Value |
| --- | --- |
| Lock commit | `daaeda1` (plan, 93-configuration matrix, folds, costs, targets, tiers, seeds), committed before any backtest |
| Data | Indodax public 1h candles, BTC/IDR and ETH/IDR from 2021-01-01, SOL/IDR from 2021-11-11 (listing), to 2026-10-25 23:00 UTC; 0 gaps; SHA-256 of each file in every ledger line |
| Costs | primary: taker all-in, buy 0.20555%, sell 0.41555% (ZHA-3871, Indodax help center table 2026-10-25 and PMK 50/2025 tax on the sell side only); sensitivity: 0.41% per side, no tax, +0.05% and +0.10% slippage per side |
| Folds | F1..F8, six months each from 2022-07-01, F8 ends 2026-04-26 |
| Holdout | 2026-04-26 .. 2026-10-26, one run for one configuration |
| Configurations | 93 of the 300 allowed in round 1 (600 over all rounds); hyperopt epochs: 0 |
| Seeds | bootstrap 10,000 resamples, null 1,000 shuffles, seed 3872 |

The simulator (`engine/simulate.py`) reproduces Freqtrade: on the stage 2 in-sample period it gives SwingEmaRsi 447 trades, -0.818% per trade, win rate 38.3%, exactly the stage 2 Freqtrade report. For the selected rule, a Freqtrade 2026.9 backtest of `RuleStrategy` over the whole walk-forward at 0.41% per side produced the same 519 trades with the same entry and exit times (519 of 519), win rate 77.07% in both, mean -0.797% (Freqtrade) against -0.796% (simulator).

### Ledger

| Run | Commit | Tree | Outcome |
| --- | --- | --- | --- |
| validation (stage 2 period, SwingEmaRsi) | daaeda1 | runner script not yet committed | ok |
| walk-forward, 93 configurations | 37090ca | clean | ok, selected `J-rsi14-1h-tp3-sl10` |
| controls | 0eb4fd5 | clean | ok (shift and truncation controls) |
| controls with the added peek control | 09f73d0 | clean | ok |
| holdout, `J-rsi14-1h-tp3-sl10` | 09f73d0 | clean | ok, tier T4; `holdout_started` line written before data was read |

Two attempts left no ledger line: a controls launch at 09:39 UTC that never started its container (the log directory did not exist yet), and a controls run at about 09:47 UTC on an uncommitted tree that was stopped by hand so the run could be repeated on a commit. Neither touched the holdout. Between the lock and the runs, `engine/search_plan.py`, `engine/search_metrics.py`, `engine/signals.py` and `engine/simulate.py` changed only in formatting (identical syntax trees at every run commit, checked with `ast.dump`); `engine/rules.py` gained `RuleSpec.freqtrade_roi`, which the search does not use; `engine/strategy_search.py` kept its syntax tree up to `0eb4fd5` and gained the peek control (`peeked` and the `peek_next_close` variant, 12 lines) in `09f73d0`, the commit of the second controls run and the holdout run. The walk-forward, holdout, null and tier code did not change.

**The holdout of round 1 is used.** `python -m engine.strategy_search holdout` refuses any further holdout run except a `--replay` of the same configuration. Later rounds (ZHA-3876) must be judged on data after 2026-10-26.

### Results

Walk-forward, net of taker costs, selected rows (all 93 rows: results.md):

| Config | Family | Tier | Trades | Net win rate | Mean net per trade | 95% CI | Profit factor | Payoff | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| J-rsi14-1h-tp1.5-sl15 | small target, wide stop | T3 | 564 | 90.1% | -0.755% | -1.16% .. -0.35% | 0.51 | 0.06 | 14.1% |
| J-rsi14-1h-tp3-sl10 (default) | small target, wide stop | T3 | 519 | 77.1% | -0.599% | -1.07% .. -0.15% | 0.75 | 0.22 | 16.0% |
| J-random-tp1.5-sl15 | random entries, same exits | T3 | 309 | 90.6% | -0.575% | -1.11% .. -0.08% | 0.58 | 0.06 | 6.0% |
| N-rsi14-1h-tp2-sl10 | trend-filtered dip, fixed target | T4 | 335 | 75.2% | -0.782% | -1.24% .. -0.36% | 0.57 | 0.19 | 11.9% |
| F-don1d20-tp5-lock3 | trend entry, asymmetric exit | T4 | 184 | 67.9% | +0.353% | -0.36% .. +1.06% | 1.18 | 0.56 | 2.1% |
| G-rsi2-1d-5-sl10 | RSI2 above SMA200 | T4 | 60 | 68.3% | +0.908% | -0.41% .. +2.22% | 1.56 | 0.72 | 1.2% |
| B-don1d-20-adx20-mid | Donchian 1d, regime filter | T4 | 52 | 51.9% | +5.080% | +0.66% .. +10.47% | 2.67 | 2.47 | 0.9% |
| C-tsmom-30-sl15 | time-series momentum | T4 | 152 | 34.9% | +4.912% | +0.93% .. +10.50% | 2.80 | 5.22 | 3.0% |
| A-don1d-20-sl10 | Donchian 1d | T4 | 104 | 37.5% | +3.803% | +0.73% .. +7.24% | 2.16 | 3.60 | 3.7% |
| K-SwingEmaRsi (old default) | benchmark | T4 | 795 | 38.5% | -0.616% | -0.77% .. -0.46% | 0.55 | 0.88 | 50.4% |

Max DD is the realised-equity drawdown with the risk layer's sizing (0.5% of equity lost at the stop, at most 3 positions), so a wide stop means a small stake.

The trade-off is the whole story of this round:

- Only three configurations met the win-rate target on the walk-forward, all with a small take-profit and a stop 3 to 10 times wider. Their payoff ratio is 0.06 to 0.22: one stop wipes out about 4 to 17 average wins. A random-entry control with the same exits reaches the same 90% win rate, and the null for the default (1,000 random-entry series at its entry rate) has a median mean of -0.628% and a 95th percentile of -0.393%, better than the default's -0.599%. The RSI entry adds nothing over random entries; the win rate comes from the exit geometry.
- 25 of 93 configurations have a positive mean with a CI above zero, before any correction for testing 93 configurations. All are trend followers (Donchian, time-series momentum, EMA trend, volume breakout) with net win rates of 34% to 57%, 28 to 272 trades in almost four years, and fold win rates that move a lot (fold standard deviation 5 to 28 points). None meets the win-rate target, so by the locked rule none can be the default in this round. Their null distributions were not run; only the selected configuration gets one.
- Five configurations win 60% to 68% of walk-forward trades with a positive mean, all with a CI that includes zero: `G-rsi2-1d-5-sl10` (68.3%, +0.908%, 60 trades), `F-don1d20-tp5-lock3` (67.9%, +0.353%, 184 trades, fold SD 7.7 points), `G-rsi2-1d-5-sl25` (67.8%, +1.191%, 59 trades), `F-don1d20-tp8-lock3` (64.4%, +0.835%, 160 trades) and `G-rsi2-1d-10-sl25` (60.2%, +0.099%, 108 trades). They are T4, and all five fail (b) at least because their 1d SMA200 filter took no trade in F1 (2022-07 to 2023-01) or F8 (2026-01 to 2026-04-26). Beyond that: `G-rsi2-1d-5-sl10` and `G-rsi2-1d-5-sl25` have fewer than 100 trades (a) and a fold SD of 13.3 and 14.3 points; `F-don1d20-tp8-lock3` won 34.8% in F2, has a fold SD of 14.3 points and a rolling 30-trade minimum of 36.7% (c); `G-rsi2-1d-10-sl25` passes (a), (c) and (d), with traded folds from 51.9% to 72.2% but a fold SD of 9.2 points; `F-don1d20-tp5-lock3` passes (a), (c) and (d), with traded folds from 52.0% to 72.2% and a fold SD of 7.7 points. `F-don1d20-tp5-lock3` and `G-rsi2-1d-10-sl25` are the nearest misses and the starting points for round 2 (ZHA-3876).
- The walk-forward selection process itself (pick the best mean on the folds before, score it on the next fold) chose a different trend configuration in most folds and was negative in 4 of 7 folds; a positive full-period mean is not the same as a rule you could have picked in advance.
- SwingEmaRsi stays negative under every cost level, as in stage 2.

Holdout for the default (`J-rsi14-1h-tp3-sl10`, taker costs): 54 trades, 77.8% net win rate (Wilson lower bound 65.1%), mean -0.112% (95% CI -1.47% to +1.11%), profit factor 0.94, payoff 0.27, largest loss -10.56%, mean of the 5 worst trades -10.56%, max drawdown 2.2%, 9.0 trades per month. Per pair: BTC/IDR 11 trades, ETH/IDR 19, SOL/IDR 24. The null's 95th percentile on the holdout is -0.053%; the default does not beat it. Holdout tier: T4, because the holdout has fewer than 100 trades; checks (b) to (d) pass. At 0.41% per side the holdout mean is -0.310%. Comparators on the same holdout: SwingEmaRsi 124 trades, 33.9% win rate, -0.583% per trade; buy-and-hold BTC/IDR +7.9%, ETH/IDR +4.8%, SOL/IDR +22.9%.

### Why this configuration is the default

The locked rule makes the default the highest tier reached, then the highest net expectancy, then the lowest drawdown, among deployable configurations with at least 100 walk-forward trades on at least 2 pairs (61 of 93). T3 beats T4, so `J-rsi14-1h-tp3-sl10` wins over every positive-expectancy trend configuration. Against the old default it trades less (11.3 instead of 17.3 trades per month on the walk-forward), loses a little less per trade (-0.60% against -0.62%) and has a far lower sized drawdown (16.0% against 50.4%). Its tail risk is explicit: each stop costs about 10.6% of the stake, and five of them in a row would cost about 2.5% of equity under the 0.5% risk rule.

Alternative not taken: making a trend configuration (for example `B-don1d-20-adx20-mid`) the default. Its walk-forward mean is positive, but its win rate is 52%, it made 52 trades in almost four years, and the locked rule ranks it below every T3 configuration.

### Controls

- Lookahead detection fires. Moving every signal one rule candle earlier makes trend rules look far better (`A-don1d-20-sl10` +3.80% to +14.40% per trade). For dip-buying rules an earlier signal buys before the dip and looks worse, so a second control was added before the holdout: keep an entry only when its fill candle closes green. For the default this moves the mean from -0.599% to -0.082% and the win rate from 77.1% to 81.1%; the median uplift over all configurations is +0.56 points.
- Truncation: at 40 seeded cut points, the signals of the last 48 candles computed on data cut at the point equal those computed on full data, for all 91 configurations except buy-and-hold and the random-entry control (0 of 120 comparisons failed per configuration).
- Live window: entries computed from the last 649 candles of each timeframe (what a live start gets from Indodax) equal entries from full history at the same cuts, for all configurations.
- Freqtrade 2026.9 on `RuleStrategy` with the default rule, 2024: `lookahead-analysis` reports `has_bias: No` (20 signals, 0 biased entries or exits); `recursive-analysis` shows indicator differences of at most 0.002% with 199 startup candles and 0.000% at the strategy's 400.

### What the code now does

- `config.strategy.name` selects `RuleStrategy` (default in `config/config.example.yaml`) or `SwingEmaRsi`; `strategy.rule` holds the rule (`engine/rules.py`), validated by the schema, so an unknown name, a missing or extra rule, a positive stop, or an unknown field stops the bot before it starts.
- `engine/strategies/rule_strategy.py` runs any rule from the searched families through the same signal code as the simulator (`engine/signals.py`), with 4h and 1d candles taken from the exchange as informative pairs and merged with `merge_informative_pair`. The take-profit is converted into Freqtrade's fee-inclusive ROI so it fills at the gross target price.
- Both strategies inherit the risk layer, startup check, heartbeat and shadow swarm hooks from `engine/strategies/gated.py`. The swarm stays a shadow and was not part of the search. The chart columns (EMA 20/50, RSI 14) are still computed for the PWA chart and the shadow candidate.
- The analytics backtest and signal routes use the configured strategy name.

### Reproduce

Run these at commit `09f73d0`: from round 2 on, `walk-forward` and `controls` run the round 2 matrix and the example config lists five pairs. The `holdout --replay` command still replays round 1 at later commits.

```sh
docker build -f docker/Dockerfile --build-context freqtrade-base=docker-image://trading-bot/freqtrade:2026.9 --target test -t trading-bot/engine:search .
run=$HOME/trading-bot-search
docker run --rm --network host -v $run:/run-out -v $PWD/config/config.example.yaml:/opt/trading-bot/config/config.yaml:ro \
  --entrypoint python trading-bot/engine:search -m engine.history --since 2021-01-01 --until 2026-10-26 \
  --datadir /run-out/data/indodax --manifest /run-out/history.json
curl -s "https://api.alternative.me/fng/?limit=0&format=json" -o $run/data/fear_greed.json
IMAGE=trading-bot/engine:search scripts/strategy_search.sh $run validate
IMAGE=trading-bot/engine:search scripts/strategy_search.sh $run walk-forward
IMAGE=trading-bot/engine:search scripts/strategy_search.sh $run controls
IMAGE=trading-bot/engine:search scripts/strategy_search.sh $run holdout --candidate J-rsi14-1h-tp3-sl10 --replay
```

The candle files must match the SHA-256 values in the ledger; Indodax can revise recent candles, and the Fear and Greed file grows daily (only the exploratory family I reads it). A replay is logged as `holdout_replay`.

### Not shown

- No configuration is shown to be profitable after costs on data it was not chosen on.
- A high and stable win rate with positive expectancy was not found in this matrix; no source reviewed in ZHA-3871 reports one for spot crypto after these costs.
- Maker-only entries (0.4211% round trip) were not simulated; Freqtrade cannot send Indodax post-only orders without an exchange subclass.
- Fear and Greed filters (family I) were exploratory and not deployable; none reached the target.
- The stop runs on the bot side (Indodax has no stop order in the API), so a gap or an offline PC can lose more than the backtest stop.
