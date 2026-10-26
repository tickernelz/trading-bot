# Deep research: swarm and median, multi-vendor decision model, PWA (2026-10-25)

At the direction of the owner: the bot must be able to analyze using swarm estimates (many bots, then take the median), the decision model must support many models (not only Jev), the application must run on all OSes including Android and iOS (PWA for mobile), deep research first and then the final plan. All numbers below come from sources I read today; anything not yet verified is marked.

## 1. Summary of findings

1. There is no ready-to-use repo themed on swarm and median that is proven for trading. What exists: multi-agent social simulation (MiroFish, MiroShark), forecasting models that can generate many price paths (Kronos) or collections of models (time series foundation models, FreqAI), LLM ensembles for event prediction, and RL agent ensembles (FinRL).
2. Evidence for ensembles exists for event prediction (an ensemble of 12 LLMs is on par with a human crowd). I have not found evidence that ensembles raise trading profit. The surrounding evidence is cautious: most LLM agents do not beat buy-and-hold in StockBench; time series foundation models only slightly beat a random walk on stocks.
3. A swarm is still worth building, but as a filter measured through forward testing, not as an assumed source of profit.
4. Decision model: the ecosystem is multi-vendor (the awesome-system-one list contains 19 hosted and 24 open-weight). Make the /v1/systemone wire the standard shape, and Ollama and vLLM serve it locally. Supporting many models is easy to build.
5. A PWA suits Android, iOS, and desktop as a control panel and notifications, not as the place where the bot runs. The Freqtrade API must not be exposed directly to the internet.

## 2. Repos and swarm methods

| Name | Type | Facts I read | Role in this bot |
|---|---|---|---|
| MiroFish (666ghj) | social simulation of thousands of agents with memory, seeded with news or financial signals | 81,796 stars, AGPL-3.0 license. Requires an OpenAI-format LLM API (README suggests Qwen-plus) and Zep Cloud. README: "High consumption, try simulations with fewer than 40 rounds first". No benchmark against historical outcomes yet (LinkedIn article; crabtalk: "exploration tool, not a prediction engine" until there is a backtest) | Not core to v1. Optional for news scenario exploration |
| MiroShark | same, 100+ agents on Twitter, Reddit, prediction markets | 1,480 stars, AGPL-3.0. README claim: 1 dollar per simulation, under 10 minutes. I have not found accuracy evidence | Same as MiroFish |
| Kronos (shiyu-coder) | candlestick (K-line) foundation model | 43,706 stars, MIT, accepted at AAAI 2026. Open models: mini 4.1 million, small 24.7 million, base 102.3 million parameters (large 499 million is not open). The predict function has a sample_count parameter: the number of forecast paths generated and then averaged. Paper claim (self-reported): RankIC +93% over the best time series foundation model. I did not find an independent trading evaluation | One price-path voter in shadow mode. The median across paths is built separately (repeated calls with different seeds; [INFERENCE] not yet tested) |
| General time series foundation models (Chronos, TimesFM, Moirai, TimeGPT) | return forecasting | Independent paper arXiv 2606.27100 (daily returns of five US stocks): pretrained models won 8 of 10 task-level comparisons against neural baselines, but the advantage over a random walk is small and rare; the Diebold-Mariano test rejects only for Chronos on AMZN and Moirai-2.0 on GOOG. The paper's conclusion: useful as a practical prior, not a reliable alpha engine | Backup voter; do not expect it to produce alpha |
| FreqAI (Freqtrade) | per-pair ML model training (LightGBM, XGBoost, CatBoost, PyTorch in the docs) | Already integrated with the engine, has dry-run | Cheap ML voter |
| FinRL ensemble (AI4Finance) | ensemble of RL agents (PPO, A2C, DDPG) | Ensemble pattern from Yang et al. 2020. I have not read the results | Pattern reference, not used in v1 |
| TradingAgents | multi-agent LLM debate | README: for research, not trading advice (read in revision 1) | Research material |

## 3. Evidence: what is known and what is not

- Wisdom of the silicon crowd (Schoenegger et al., Science Advances 2024): an ensemble of 12 LLMs predicted 31 binary questions, compared with 925 human forecasters over 3 months; the LLM crowd beat the no-information benchmark and did not differ significantly from the human crowd; there is an acquiescence bias. This is events, not prices.
- Halawi et al. (NeurIPS 2024): an LM system with retrieval, aggregation using a trimmed mean, approaches competitive human forecasters. This is events, not prices.
- StockBench (arXiv 2510.02209): LLM agent stock trading over multiple months without data contamination; most models struggle to beat buy-and-hold, some show potential.
- Alpha Arena (Nof1), secondary reports: six models, each with 10,000 dollars on Hyperliquid, two profited and four lost 31-63%. I have not read the primary source; other sources say the public results ended in December 2025 (the naming of Season 1 and 1.5 differs between sources).
- Look-ahead bias (arXiv 2512.23847): LLMs are trained on past news, so backtesting LLM signals on old data leaks. That is why evidence comes only from forward testing.
- Principle: models whose errors are correlated repeat the same mistakes, so the median only helps if the voters are truly diverse (different vendors and model families).
- Not available: evidence that a swarm with a median raises net profit after fees for crypto spot with small capital.

## 4. Multi-vendor decision model

List: github.com/andyrewlee/awesome-system-one (read 2026-10-25).
- Hosted (19 names): Celeris-1, Decider (Perplexity), Decider 1, GLiDE, Hanzo Kai, Instinct, Jev, Jev Router, kettei, Snowflake Decision, Mercury Decide, Microsoft-Decision-1, OpenAI Decisions API, Sage, Solar Decide, Span-01, SPX-CD, SubQ Snap, wity-1.
- Open-weight (24 names): basal-omni, Clef, Chon, CLM, Cua-S1, d1, Decisio, GEV-26B-Decide, GLiNER2.5-Decide, H2O-Lightning-4B, Intern-Decision, Jeva, Jev-Omni, Laya, mammoth/elephant, NeuDecide, OneJev, Quyet, StartLux-Decision, Strands Decider, Surogate Rune, Torchcast Decision, Vela, xor.
- Standard wire: the TypeSafe request shape /v1/systemone. Ollama serves it natively since 0.35.0 (pull Nimble 9B, Tev1, d1, Clef, Clef-Flash, pplx-decider). Upstream vLLM serves /v1/systemone for decision models. There is also AnyJev (Nokia, Apache 2.0), which turns any LLM into a decision model without training, and several other open-source servers.
- The OpenAI Decisions API has its own shape (the llm-openai-decisions plugin shows predicate, choice, score).
- Hosted gateways: OpenRouter (Decisions API, alpha), Vercel AI Gateway, Cloudflare Workers AI, LLMGateway (according to the Jev entry README). In OpenRouter's /api/v1/models only typesafe/jev-router appears; other decision models go through the Decisions endpoint, and I have not found their live catalog.
- Listed prices: Jev 0.042 dollars per million input tokens, output free; Clef-flash 0.038 dollars per million input on Workers AI; Celeris-1 and Decider 1 0.04 dollars per million input.
- Warning: one open-weight model in the list reports 72% vs 21% accuracy on the same questions just because the option order was reversed. Option order must be shuffled per voter and the results combined.
- Fallback without a decision model: a regular LLM with structured output. On OpenRouter (467 models, fetched 2026-10-25) there are 103 structured models with input prices up to 0.2 dollars per million, and 11 free structured models.

## 5. PWA, all OSes, and remote access

- iOS: web push for Home Screen web apps is available on iOS 16.4 or later; permission is requested through a user gesture (tapping a button) and subscribe is called directly from that gesture handler; Safari does not support invisible push; the Apple Developer Program is not required (Apple documentation).
- Requirements for a PWA to be installable: HTTPS, or localhost and 127.0.0.1 during development (MDN).
- Freqtrade REST API: by default only localhost; the docs strongly advise against exposing the API to the internet; FreqUI does not support built-in HTTPS. In Docker, the API must listen for incoming connections and the port is mapped to 127.0.0.1:8080.
- FreqUI is not a PWA: in the frequi repo tree (321 files) there is no manifest or service worker, and package.json has no PWA dependency. A separate PWA is needed.
- Integration points: the Freqtrade REST API, the message websocket (/api/v1/message/ws), and webhooks (entry, exit, and others).
- The bot is not run on the phone; [INFERENCE] iOS and Android restrict background processes. The engine runs on a VPS or PC via Docker (the Freqtrade docs recommend Docker for Windows), and mobile becomes the control panel and notifications.
- PWA installation on desktop Chrome and Edge was not verified in this run.

## 6. Not yet verified

- Kronos on a small CPU VPS (README does not mention GPU requirements; not tested) and its inference speed.
- The live catalog of decision models on OpenRouter.
- Reddit and X access and cost.
- Freqtrade support for Indodax.
- Alpha Arena from the primary source; FinRL ensemble results.
- Evidence that swarm median raises net trading profit.

## 7. Sources

- https://github.com/666ghj/MiroFish
- https://github.com/MiroShark/MiroShark
- https://crabtalk.ai/blog/mirofish-swarm-prediction
- https://github.com/shiyu-coder/Kronos and https://arxiv.org/abs/2508.02739
- https://arxiv.org/html/2606.27100
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11800985/
- https://arxiv.org/html/2402.18563v1
- https://arxiv.org/html/2510.02209
- https://arxiv.org/html/2512.23847v1
- https://syntheticalpha.beehiiv.com/p/the-receipts-are-in-ai-lost-synthetic-alpha-issue-5 and https://www.traderank.ai/llm-trading-benchmark
- https://github.com/AI4Finance-Foundation/FinRL
- https://github.com/andyrewlee/awesome-system-one
- https://openrouter.ai/docs/guides/community/jev
- https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers
- https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable
- Freqtrade docs: rest-api.md, webhook-config.md, freqai.md; repo freqtrade/frequi
