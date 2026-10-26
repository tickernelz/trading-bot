# Trading bot PWA

Trading bot panel for phone and desktop. Stage 1: safe, held, or stopped state; today's profit and loss trace; risk meters; positions and orders; candle chart per pair; activity feed; swarm decisions; health; Web Push notifications. Stage 2: Control (kill switch, force exit, pair locks, blacklist, stop the bot, with a two-step confirmation from the gateway), Configuration (per-bot editor with schema validation, old and new values side by side, a second step when raising a limit or the capital, voters, change log), Providers and keys (remote session: status and connection test; `control` session from the bot PC: keys, add, edit, remove, roles, models.yml import), Swarm per decision with what followed, History and statistics, Bot A vs B, and Audit.

The mock gateway in `mock-gateway/` serves sample data, and the PWA labels it "sample data" while `/gw/v1/health` carries `gateway.sample_data: true`. Endpoints used: `docs/gateway-api.md` sections 5, 7, 11 (stage 1) and 15 (stage 2). Control and audit follow the ZHA-3774 contract (gateway section 14); configuration, providers, keys, voters, and roles follow the ZHA-3775 contract as written. Swarm per decision, history, and A vs B follow the 15.3 draft.

On a phone the tabs are Summary, Chart, Activity, Control, More; Control sits in the tab bar so the kill switch is one tap away. On desktop a rail groups the screens into Watch, Control, Records, System.

## Running

    cd pwa
    NODE_ENV=development npm ci --include=dev
    npm run mock-gateway
    npm run build && npm run preview

Open http://localhost:4173. The mock gateway password is `example` (override with `MOCK_GATEWAY_PASSWORD`). `npm run dev` uses port 5173. Vite forwards `/gw` (HTTP and WebSocket) to `GATEWAY_URL`, default `http://127.0.0.1:8090`; the mock gateway port is `MOCK_GATEWAY_PORT`.

The mock gateway has token-free test routes, for development only:

- `POST /gw/v1/dev/scenario` body `{"name": "safe" | "held" | "stopped"}` (`MOCK_SCENARIO` sets the starting one)
- `POST /gw/v1/dev/drop` body `{"seconds": 20}` closes every connection and refuses new ones for that long
- `POST /gw/v1/dev/upstream` body `{"seconds": 30}` mimics Freqtrade being down: `gw.error` every 5 seconds, `/health`, `/overview`, `/risk` answer 503
- `POST /gw/v1/dev/fail` body `{"path": "/gw/v1/decisions", "status": 404}` forces one endpoint to fail; `status: 0` restores it
- `POST /gw/v1/dev/push` body `{"kind": "fill" | "risk_breach" | "kill_switch" | "heartbeat_lost" | "quorum_failed" | "daily_summary"}`
- `POST /gw/v1/dev/remote` body `{"remote": true}` gives the next login (and existing sessions) the `read` scope, like a login through the tunnel; `false` restores `control`. `MOCK_REMOTE=1` starts in that state.

Tests: `npm test`. Stage 1: backoff, feed client, data freshness, safety state, core versus panel refresh, HTTP client, signed number formatting, feed text. Stage 2: `tests/settings.test.ts` (keys editable through PATCH, nested `changes` body, two-step rule matching 2b `raising_keys`, schema errors mapped to fields, validation matching `engine/settings.py`), `tests/control.test.ts` (two steps with the same idempotency key, `confirmation_expired` and `confirmation_invalid`), `tests/decisions.test.ts` (outcome after a decision, audit), and `tests/contract.test.ts`, which starts the mock gateway and drives it with the PWA client: 2a rules (scope, required `Idempotency-Key`, replay including a failed 502, malformed key audited as `rejected`, token for another target refused, exit-all, DELETE with confirm) and 2b (nested PATCH, frozen roots, two steps for limits and capital, schema errors, `read` session refused and audited as `admin.denied`, voters per route with quorum, roles, keys only through the key route with a marker value that appears in no response, import with a key only when ticked), plus paging of decisions, trades, and audit. Languages: `tests/i18n.test.ts`, `tests/format.test.ts`, `tests/push.test.ts` (see below).

## Languages

English is the default and the source of truth. Indonesian is the second language. The choice is stored in `localStorage` `tb.lang` and picked on the Login and System screens; changing it reloads the app. The order is: a stored code that is in the registry, otherwise English. The browser language is not read. An unknown stored code falls back to English.

- `src/lib/locales/en.ts` defines the `Messages` type and is bundled with the app.
- Every other catalogue is typed `Messages`, so a missing or misspelled key is a compile error, and is loaded lazily as its own chunk.
- `src/lib/locales/index.ts` is the registry: one row per language with `code`, `nativeName`, `htmlLang`, `intlLocale`, and `load`. The language switch, the language choice, `Intl` number and date formats, and `<html lang>` all read it.
- At runtime a key that a catalogue lacks or leaves empty shows the English text, never the raw key.
- Codes from the gateway stay language-neutral and are labelled through the catalogue in `src/lib/words.ts`: verdicts `allow`, `reduce`, `skip`, refusal reasons, and Fear & Greed classes.
- Push: `POST /gw/v1/push/subscriptions` carries `lang`, the active language code, so the gateway writes notification text in that language. After a language switch the app sends the subscription again once (`localStorage` `tb.push_lang` remembers the last one sent). The service worker's fallback text is English.

### Adding a language

1. Copy `src/lib/locales/id.ts` to `src/lib/locales/<code>.ts`, rename the export, and translate every value. Keep each `{placeholder}` as it is.
2. Add one row to `LANGUAGES` in `src/lib/locales/index.ts`, for example `{ code: "ms", nativeName: "Bahasa Melayu", htmlLang: "ms", intlLocale: "ms-MY", load: async () => (await import("./ms")).ms }`.
3. Run `npx svelte-check` (missing keys fail here) and `npm test`. The catalogue test checks every registered language for the same keys and placeholders as English and no empty values.

No other file changes. `tests/i18n.test.ts` proves this: it adds a third language through a registry row alone and checks that the switch offers it, a stored choice selects it, numbers use its locale, and a key it lacks shows English; without the row the same stored code falls back to English and the switch does not list it.

## Choices and reasons

- Framework: Svelte 5 with Vite 8, no component library. Rune reactivity fits a WebSocket event stream. Seven stage 2 screens plus Swarm and System are lazy-loaded. Vue and Nuxt UI are not used so that FreqUI's and Nuxt UI's default look does not carry over.
- Chart: TradingView Lightweight Charts 5.2.1 (Apache-2.0, attribution on the System screen). Canvas, candles, entry and exit markers, a price line for the stop loss, a second pane for RSI. Lazy-loaded on the Chart screen only. ECharts is not used because it is FreqUI's library. The daily trace and the voter spread are hand-drawn SVG.
- Typeface: Atkinson Hyperlegible Next. Proof of tabular figures and why Inter was rejected are in `DESIGN.md`, Typography. Only the latin and latin-ext subsets load (34 kB and 19 kB woff2).
- Hand-written service worker (`sw/sw.js`), no Workbox. A small plugin in `vite.config.ts` writes `dist/sw.js` with a cache name from the hash of the asset list and that list for precaching, so every build has its own cache and old caches are deleted on activate. `/gw/` is never cached, navigations are stored only for `ok` responses, push URLs are limited to the app's own origin, and a push always shows a visible notification. Registered in production builds only.

## Measured

Initial load, the entry script plus preloaded modules (`vite build`, `gzip -9`, 2026-10-26): 56,078 bytes on `main` 3ad1315 with Indonesian bundled and English lazy, 56,038 bytes with English bundled and Indonesian lazy (-40 bytes); the entry chunk went from 14,329 to 14,249 bytes. The Indonesian catalogue is a separate 12,077-byte chunk loaded only when Indonesian is chosen. The chart module (about 57 kB gzip) loads only on the Chart screen.

Earlier measurements (Chromium headless, mock gateway on localhost, 2026-10-26):

- Installable: `Page.getInstallabilityErrors` empty, manifest without errors, service worker `activated` and controlling the page.
- Web Push: an FCM subscription created through the button; six push kinds sent (`sent: 1` each), six notifications shown; `risk_breach`, `kill_switch`, `heartbeat_lost` with `requireInteraction`.
- Reconnect: gateway dropped for 25 seconds; attempts at 0, 1.0, 2.5, 6.6, 11.2, 23.4 seconds, reconnected at 44.1 seconds and the board went from stale back to "Safe". Backoff starts at 1 s and doubles up to 30 s with upper-half jitter, and resets only after 10 s connected. While `navigator.onLine` is false the client waits for the `online` event without spending attempts.
- Feed: from event arrival in the browser to the DOM, median 1.7 ms, max 2.1 ms (n = 8).
- Offline: a reload without network shows the cached shell with "This device is offline."; if no state was ever loaded, the top bar shows "Mode ?" (accessible label "Mode not known yet").
- Contrast: see `DESIGN.md`, Colors; every text pair is above 4.5:1 in both themes.
- Touch targets: every button, tab, and link is at least 44 px tall; the layer check boxes are 20 px inside 44 px labels. Stage 2 was measured again at 390 px on eight screens: no interactive element under 44 px.
- Stage 2, no sideways scroll at 360 px on 12 screens (`scrollWidth` = 360). Input borders 3.93:1 (light) and 3.29:1 (dark) against the background; placeholders 8.41:1 and 9.14:1. `prefers-reduced-motion: reduce`: the confirmation panel animation is 0 s.
- Stage 2, the PWA client (`createApi`, `send`, `patchBody`, `schemaErrors`, audit labels) was run against the real 2b gateway (`feat/stage-2b-config` b7a801d, which includes 2a dbc3b9f) in image `trading-bot/engine:test-zha3775` with the fake Freqtrade `CountingFreqtrade`: two-step control, exit-all, blacklist DELETE with a confirm body, another action's token `confirmation_invalid`, `read` session 403; nested PATCH (lowering a limit, raising the capital with step 2, `api` root 400, schema error mapped to `risk.max_open_trades`, `read` session 403), `settings/changes`, the `providers` shape, a connection test from a `read` session then `429` within 5 seconds, keys through `/key`, `api_key` in a provider body 400, `/state` route 404, voter PUT/DELETE, roles, preview and import (a command key 400); every real audit action and result has a PWA label; a literal key value never appears in a preview or audit.
- Stage 2 in Chromium against the mock gateway: two-step force exit (focus moves to the panel, the trade closes after step 2), one-step kill switch, a `read` session with every control button disabled and no key field, saving a configuration that raises a limit with step 2 and the entry appearing in the log, a provider key saved with only "ending ABCD" shown, and a 502 on seven endpoints shown per section with Retry.

## Nice-to-have N2 (ZHA-3781)

- Time machine (Chart screen, "Open time machine"): a slider and arrow buttons step through the swarm decisions for that pair; the selected decision shows above the chart (result, quorum, median, spread, a dot per voter, each voter's answer) and is marked on its candle. Data from `/gw/v1/decisions?pair=&limit=200` (`docs/gateway-api.md` 12.1), loaded only when the time machine opens. Decisions older than the 300 loaded candles are counted and named, not shown.
- News and sentiment layer (check boxes under Layers, off by default): CoinDesk and Cointelegraph RSS headlines that mention the pair's asset are marked per hour on the chart and listed with source, fetch time, and per-source error; alternative.me Fear & Greed as a daily line in the lower pane with attribution and link. Data from `/gw/v1/news` and `/gw/v1/sentiment` (12.2, 12.3); the real fetcher is `engine/news.py`. The layer is display only and does not change bot decisions.
- Last view while offline: every successful core refresh stores the state (core, positions, equity, decisions, up to 300 candles per pair, news, sentiment) in `localStorage` `tb.lastView`. Offline without a session, the login screen offers "Open last view", which shows every screen read-only with the save time and a "read-only" label. Signing out deletes it. The manifest is cached too, so there is no network error offline.
- App icon badge: the service worker sets `setAppBadge(n)` to the number of notifications still shown when no app window is visible, and `clearAppBadge()` when a window becomes visible, a notification is clicked, or the last one is closed. The page also clears the badge when opened or shown again.
- Real news fetcher: cold feed 0.28 s (two RSS feeds), from cache 0.1 ms, Fear & Greed cold 1.04 s.

## Not proven

- iOS 16.4 or later on a real device: add to Home Screen, push permission through the button, notifications shown. The System screen shows the Home Screen hint when opened from plain Safari, but that flow has not been tested on an iPhone.
- Android and desktop: the install dialog from Chrome or Edge has not been clicked by a person; only the installability requirements are proven.
- PWA screens in a browser against the real gateway: the PWA client was tested against the real 2b gateway with a fake Freqtrade, the screens in Chromium only against the mock gateway; a real Freqtrade dry-run has not been used for the stage 2 screens.
- Section 15.3 is still a draft: decision `outcome`, `status` and `bot` on `/gw/v1/decisions`, `offset` and `state=closed` for trades, `window=total` for equity, `overview.state` per bot.
- Enabling or disabling a provider remotely is not built (2b limits a `read` session to reading and testing); the decision is in ZHA-3796.
- Screen readers: ARIA and focus order were checked in code, not with VoiceOver or TalkBack.
- Badge permission and display on iOS 16.4 or later and the badge on Android and desktop as seen by a person; `/gw/v1/news`, `/gw/v1/sentiment`, and the `pair`/`before` parameters on the real gateway; the quality of each translation as judged by a native speaker.

## Stage 2 technical audit (impeccable audit, 2026-10-26)

| # | Dimension | Score | Main finding |
| --- | --- | --- | --- |
| 1 | Accessibility | 3 | Every input labelled, buttons named, 2 px focus; screen readers not tested |
| 2 | Performance | 4 | Seven new screens plus Swarm and System lazy-loaded |
| 3 | Responsive | 3 | No sideways scroll at 360 px on 12 screens; Configuration is long on a phone |
| 4 | Theme | 4 | Every colour from a token; dark and light measured |
| 5 | Anti-patterns | 4 | Detector `[]` with a negative control |
| **Total** | | **18/20** | P0 0, P1 0 |
