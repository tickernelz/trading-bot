# API gateway contract and event feed

Contract for the PWA task (stage 1) and the stage 2 gateway. Derived from section 13 of revised plan 10 and from the Freqtrade 2026.9 REST/WebSocket that actually exists in `vendor/freqtrade`. The `/gw/...` paths are our contract, not Freqtrade paths; Freqtrade paths are in section 8.

Every JSON example carries one of two labels:

- `tangkapan Freqtrade 2026.9`: taken from the Indodax dry-run bot running on this PC on 2026-10-25 (REST, WebSocket `/api/v1/message/ws`, and the risk rejection `strategy_msg`). Values may be trimmed; field names and shapes are not changed.
- `draft`: shapes owned by the gateway, written before the gateway existed (session, confirmation, error envelope, summary, `gw.*` events). The stage 1 gateway (`gateway/`) has already built the read side, session, envelope, and feed; what was built, what differs, and what does not exist yet is recorded in section 12. Controls (sections 3 and 6) and `PATCH /gw/v1/settings` have not been built.

## 1. Topology and trust boundaries

```text
PWA (browser) --HTTPS/WebSocket--> gateway --HTTP/WebSocket 127.0.0.1:8080--> Freqtrade REST/WS
```

- Freqtrade REST/WS only listens on loopback (`api.listen: 127.0.0.1`, `api.port: 8080` in `config/config.yaml`). The gateway is the only client.
- The gateway holds the Freqtrade credentials (`FT_API_USERNAME`, `FT_API_PASSWORD`) and never sends them to the browser. `FT_API_JWT_SECRET` is held only by the bot. Freqtrade's `ws_token` is not used (section 8).
- The gateway maintains one WebSocket connection to Freqtrade, not one per PWA tab.
- The PWA must not call Freqtrade directly, including for candles. Everything goes through the gateway so that one place enforces auth, audit, and bandwidth savings.
- The gateway is for a single owner only (single owner). There is no multi-tenancy in this plan.
- Sensitive zones (changing API keys, changing config, enabling live mode) are only reachable from `127.0.0.1` on the bot machine, not through a tunnel. This follows plan section 4.5.

## 2. Gateway authentication

- `POST /gw/v1/session` with body `{"password": "..."}` returns `{"token": "...", "expires_at": "2026-11-24T17:00:00Z"}`. The token is opaque, stored by the PWA in memory or secure storage, and sent as `Authorization: Bearer <token>`.
- Tokens have two scopes: `read` (all GETs) and `control` (GETs plus all control POST/DELETE). `control` is only granted when the login comes directly from loopback: client address `127.0.0.1` or `::1` and no forwarding headers (`Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Server`, `X-Original-Forwarded-For`, `X-Real-IP`, `Via`, `CDN-Loop`, `CF-Connecting-IP`, `CF-Ray`, `CF-Visitor`, `CF-IPCountry`, `True-Client-IP`), with the `Host` header being `127.0.0.1`, `localhost`, or `[::1]`, and an `Origin` (if present) that is also loopback; otherwise `read`. One definition, `control.is_local`, is used by login, the stage 2a control routes, and stage 2b config writes. The login response adds `"scope": "control" | "read"`. The `owner` scope was merged into `control`: the stage 2a issue asked for control from localhost only, so `control` is already as strict as `owner`, and one fewer scope means one fewer authorization branch.
- `DELETE /gw/v1/session` revokes the token.
- Auth failures are always `401` with the section 6 error envelope, with no detail leaked.

## 3. Two-step control for risky actions

Actions that increase risk (force enter, force exit at market, delete lock, delete blacklist, stop bot) require two steps:

1. `POST /gw/v1/control/...` with the header `Idempotency-Key: <uuid>` and without `confirm` yields `409`:

Example: draft, the gateway does not exist yet; values follow the Freqtrade capture when available.

```json
{
  "error": {
    "code": "confirmation_required",
    "message": "force_exit needs confirmation",
    "confirmation": {
      "id": "cf_01J9Z6H0YV",
      "action": "trade.exit",
      "targets": ["BTC/IDR"],
      "summary": "Exit trade 1 BTC/IDR at market",
      "expires_at": "2026-10-25T17:11:02Z"
    }
  }
}
```

2. Repeat the same request with the same `Idempotency-Key` header and body `{"confirm": "cf_01J9Z6H0YV"}`. The gateway executes the action once, stores the result per idempotency key, and returns `200`.
3. A confirmation is valid for 60 seconds and only for one action and one target. Actions that reduce risk (pause, delete entry, close bot) do not need confirmation.

Rules built in the control work (`gateway/control.py`, `Gateway.execute` in `gateway/app.py`):

- The confirmation token is single-use and bound to the action name, the bot, the action parameters (path, query, and body without `confirm`), and the session that requested it. An unknown token, one already used, one for another action or parameters, or one from another session: `409 confirmation_invalid`. Past 60 seconds: `409 confirmation_expired`. Freqtrade is not called on any of these rejections. Tokens are stored in gateway memory, so restarting the gateway cancels all unused tokens.
- `Idempotency-Key` is mandatory on all control endpoints (8-128 characters `[A-Za-z0-9_-]`); without it, `400 invalid_request`. The result of every execution that passes the gateway checks (local, confirmation, `trades` check) is stored for 24 hours per key, success or error, including `503 upstream_unavailable` when Freqtrade is unreachable. A repeated request with the same key and parameters returns the stored result without calling Freqtrade again (audit `replayed`); the same key for a different request gives `409 invalid_request`. Step 1 (`confirmation_required`) is not stored, so step 2 may use the same key. Retrying a failed action needs a new key and, for risky actions, a new confirmation.
- Config changes: `risky_changes(old, new)` in `gateway/control.py` returns the keys that need two steps: increases to `risk.max_daily_loss_pct`, `risk.max_total_drawdown_pct`, `risk.risk_per_trade_pct`, `risk.max_open_trades`, a change of `mode` in either direction, and `api.force_entry` from `false` to `true`. An empty list means the change takes effect immediately (including lowering a limit). `PATCH /gw/v1/settings` (section 17.2) shares this function with `Confirmations`, `is_local`, and the same idempotency store.

## 4. Response envelope

Success returns the data directly (object or array) as in the examples in section 5. All error responses use the same shape:

Example: draft, the gateway does not exist yet; values follow the Freqtrade capture when available.

```json
{
  "error": {
    "code": "upstream_unavailable",
    "message": "Freqtrade API did not answer within 5s",
    "retry_after_ms": 2000
  }
}
```

Codes in use: `unauthorized`, `live_blocked` (422: no exchange key or the live order path is not yet proven; carries a `blockers` list), `forbidden_local_only`, `confirmation_required`, `confirmation_expired`, `confirmation_invalid` (token unknown, already used, or for another action, parameters, or session; split from `confirmation_expired` so the PWA can tell a timeout from a wrong token), `invalid_request`, `upstream_error`, `upstream_unavailable`, `risk_limit_breached`, `not_found`, `rate_limited`.

## 5. Read endpoints

All require `read`. Gateway cache: `overview` 2 seconds, `candles` follows the last candle, the rest are uncached. All timestamps are ISO-8601 UTC with a `Z` suffix.

### 5.1 `GET /gw/v1/health`

Combination of Freqtrade's `/ping`, `/version`, and `/health`, plus gateway status.

Example: draft, gateway does not exist yet; values follow the Freqtrade capture where available.

```json
{
  "gateway": {"status": "ok", "version": "0.1.0", "uptime_s": 128},
  "freqtrade": {"version": "2026.9", "state": "running", "last_process": "2026-10-25T17:07:33.618830Z", "bot_start": "2026-10-25T17:05:23.597087Z", "dry_run": true},
  "exchange": {"name": "indodax", "reachable": true, "latency_ms": 184},
  "feed": {"connected": true, "last_event_at": "2026-10-25T17:07:12.401Z", "sequence": 42}
}
```

### 5.2 `GET /gw/v1/overview`

One-screen summary: capital, balance, profit, open trades, risk limits.

Example: draft, gateway does not exist yet; values follow the Freqtrade capture where available.

```json
{
  "mode": "dry_run",
  "as_of": "2026-10-25T17:08:00Z",
  "capital": {"initial_idr": 2000000, "compounding": true, "tradable_ratio": 0.99},
  "balance": {"stake_currency": "IDR", "total": 1998666.48, "bot_owned": 1978679.82, "note": "Simulated balances"},
  "profit": {"abs": -1333.52, "pct": -0.07, "trades_closed": 1, "winrate": 0.0},
  "open_trades": {"count": 0, "max": 3},
  "risk": {"daily_loss_pct": 0.07, "daily_limit_pct": 1.0, "drawdown_pct": 0.07, "drawdown_limit_pct": 10.0, "entries_allowed": true, "breaches": []},
  "pairs": {"whitelist": ["BTC/IDR", "ETH/IDR", "SOL/IDR"], "blacklist": [], "locks": 0}
}
```

### 5.3 `GET /gw/v1/trades/open`

Forwarded from `/status`. Elements use the Freqtrade trade object as is (section 9), plus two derived fields: `profit_pct_now` (percent relative to `open_trade_value`) and `age_s`.

Example: Freqtrade 2026.9 capture for the Freqtrade fields (trade 1, `force_entry`); `profit_pct_now` and `age_s` are gateway draft. `stake_amount` 333322.90 in the 17:06 UTC capture came from sizing without fees; since fees are now included, the 17:40 UTC capture gives `stake_amount` 294627.59 for the same capital (loss at the 3% stoploss plus two 0.2% fees = Rp 10,000).

```json
[
  {
    "trade_id": 1,
    "pair": "BTC/IDR",
    "is_open": true,
    "is_short": false,
    "exchange": "indodax",
    "amount": 0.00022769,
    "stake_amount": 333322.90477,
    "strategy": "SwingEmaRsi",
    "enter_tag": "force_entry",
    "fee_open": 0.002,
    "open_date": "2026-10-25 17:06:26",
    "open_timestamp": 1792947986077,
    "open_rate": 1463933000.0,
    "open_trade_value": 333989.55057954,
    "stop_loss_pct": -3.0,
    "profit_abs": -1333.5,
    "profit_pct_now": -0.4,
    "age_s": 46
  }
]
```

### 5.4 `GET /gw/v1/trades?limit=100&offset=0&state=closed&pair=BTC/IDR`

Combination of Freqtrade's `/status` (open trades) and `/trades`. Freqtrade's `/trades` only contains closed trades, at most 500 per page, and defaults to ascending id order; the gateway fetches all pages (`order_by_id=true`, `offset`), merges them, then sorts by `trade_id` descending before `pair`, `offset`, and `limit` are applied. `state=closed` returns only closed trades (history, section 18.2). Same shape as 5.3; closed trades carry `close_date`, `close_rate`, `close_profit_abs`, `exit_reason`, `exit_order_status`.

Example: Freqtrade 2026.9 capture (Indodax dry-run on this PC, 2026-10-25).

```json
[
  {"trade_id": 1, "pair": "BTC/IDR", "is_open": false, "enter_tag": "force_entry", "exit_reason": "force_exit", "open_rate": 1463933000.0, "close_rate": 1463912000.0, "close_profit_abs": -1333.5188537, "close_profit_pct": -0.4, "profit_abs": -1333.5188537, "close_date": "2026-10-25 17:07:12"}
]
```

### 5.5 `GET /gw/v1/trades/{trade_id}`

A single trade from `/trade/{id}`, shape 5.3. `404` if it does not exist.

### 5.6 `GET /gw/v1/balance`

Forwarded from `/balance` with adjustments: only currencies managed by the bot.

Example: Freqtrade 2026.9 capture (Indodax dry-run on this PC, 2026-10-25).

```json
{
  "stake_currency": "IDR",
  "total": 1998666.4811463,
  "total_bot": 1978679.8163348369,
  "starting_capital": 1980000.0,
  "starting_capital_pct": -0.07,
  "note": "Simulated balances",
  "currencies": [
    {"currency": "IDR", "free": 1998666.4811463, "used": 0.0, "bot_owned": 1978679.8163348369, "est_stake": 1998666.4811463, "is_bot_managed": true}
  ]
}
```

`starting_capital` is `dry_run_wallet * tradable_balance_ratio` = `2000000 * 0.99 = 1980000`, not the full capital. The PWA must display `capital.initial_idr` as the capital and `starting_capital` as the usable limit.

### 5.7 `GET /gw/v1/profit?window=total|daily|weekly|monthly&timescale=7`

`window=total` uses `/profit`. `daily`, `weekly`, `monthly` are computed by the gateway from all closed trades using the Freqtrade field names of `/daily`, `/weekly`, `/monthly`, but the day boundary follows `risk.daily_reset_timezone` (section 18.3).

`total` example: Freqtrade 2026.9 capture for the Freqtrade fields; `window` is a gateway design.

```json
{
  "window": "total",
  "stake_currency": "IDR",
  "profit_closed_coin": -1333.5188537,
  "profit_closed_percent": -0.07,
  "profit_all_percent": -0.07,
  "trade_count": 1,
  "closed_trade_count": 1,
  "winning_trades": 0,
  "losing_trades": 1,
  "best_pair": "BTC/IDR",
  "worst_pair": "BTC/IDR"
}
```

`daily` example: see 18.3.

### 5.8 `GET /gw/v1/stats`

Example: Freqtrade 2026.9 capture (Indodax dry-run on this PC, 2026-10-25).

```json
{
  "durations": {"wins": null, "draws": null, "losses": 46.409757},
  "exit_reasons": {"force_exit": {"wins": 0, "losses": 1, "draws": 0}}
}
```

### 5.9 `GET /gw/v1/performance?pair=BTC/IDR`

Combination of `/performance`, `/entries`, `/exits`, `/mix_tags`.

Example: Freqtrade 2026.9 capture per part; the `per_pair`/`by_enter_tag`/`by_exit_reason`/`by_mix_tag` wrapper belongs to the gateway (`by_mix_tag` since 18.4).

```json
{
  "per_pair": [{"pair": "BTC/IDR", "profit_ratio": -0.004000681725188243, "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}],
  "by_enter_tag": [{"enter_tag": "force_entry", "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}],
  "by_exit_reason": [{"exit_reason": "force_exit", "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}]
}
```

### 5.10 `GET /gw/v1/candles?pair=BTC/IDR&timeframe=1h&limit=300`

Forwarded from `/pair_candles` (GET). `timeframe` is only `1h` at this stage; the gateway rejects other timeframes with `invalid_request`. `limit` is at most 1500, default 300. Indicators are included in `columns`.

Example: Freqtrade 2026.9 capture from `/pair_candles` (columns and rows), trimmed to the columns used by the PWA.

```json
{
  "pair": "BTC/IDR",
  "timeframe": "1h",
  "strategy": "SwingEmaRsi",
  "columns": ["date", "open", "high", "low", "close", "volume", "ema_fast", "ema_slow", "rsi", "enter_long", "exit_long"],
  "length": 300,
  "last_analyzed": "2026-10-25 17:00:00",
  "data": [
    ["2026-10-25T16:00:00Z", 1463059000.0, 1463933000.0, 1460899000.0, 1463932000.0, 0.25369079, 1460601161.45, 1464373799.03, 54.657, null, null]
  ]
}
```

Rows are arrays in the order of `columns` (the original Freqtrade shape), not one object per candle, to keep the payload small. The PWA maps indexes to column names once at connection time.

### 5.11 `GET /gw/v1/pairs`

Example: Freqtrade 2026.9 capture of `/whitelist`, `/blacklist`, `/locks`; the wrapper is the gateway design.

```json
{
  "whitelist": {"pairs": ["BTC/IDR", "ETH/IDR", "SOL/IDR"], "length": 3, "method": ["StaticPairList"]},
  "blacklist": {"pairs": [], "length": 0, "method": ["StaticPairList"]},
  "locks": {"lock_count": 1, "locks": [{"id": 1, "pair": "BTC/IDR", "side": "long", "active": true, "reason": "Auto lock", "lock_time": "2026-10-25 17:07:12", "lock_end_time": "2026-10-25 18:00:00"}]}
}
```

The `"Auto lock"` lock always appears after an exit: Freqtrade locks the pair for one candle to prevent immediate re-entry. This is normal, not a configured protection.

### 5.12 `GET /gw/v1/risk`

Computed by the gateway with the same module as the engine (`engine/risk.py`), from closed trades and open profit. Not simply forwarded from Freqtrade.

Example: design, the gateway does not exist yet; values follow the Freqtrade capture where available.

```json
{
  "as_of": "2026-10-25T17:08:00Z",
  "equity": 1998666.48,
  "peak_equity": 2000000.0,
  "day_start": "2026-10-24T17:00:00Z",
  "day_start_equity": 2000000.0,
  "daily_pnl": -1333.52,
  "daily_loss_pct": 0.067,
  "drawdown_pct": 0.067,
  "limits": {"max_daily_loss_pct": 1.0, "max_total_drawdown_pct": 10.0, "risk_per_trade_pct": 0.5, "on_breach": "stop_new_entries", "timezone": "Asia/Jakarta"},
  "breaches": [],
  "entries_allowed": true
}
```

`breaches` contains `"daily_loss"` and/or `"total_drawdown"`. `entries_allowed` false means the engine rejects new entries until the day changes (for `daily_loss`) or permanently (for `total_drawdown`). The PWA shows both as status, not as a button that can be turned off.

### 5.13 `GET /gw/v1/logs?limit=50`

Example: Freqtrade 2026.9 capture (Indodax dry-run on this PC, 2026-10-25).

```json
{
  "log_count": 2,
  "logs": [
    ["2026-10-25 17:36:56", 1792949816022.821, "freqtrade.worker", "INFO", "Bot heartbeat. PID=1, version='2026.9', state='RUNNING'"]
  ]
}
```

### 5.14 `GET /gw/v1/sysinfo`

Forwarded from `/sysinfo` (CPU, RAM, disk). Used by the PWA health card.

### 5.15 `GET /gw/v1/settings` and `PATCH /gw/v1/settings`

Read: the active configuration with secrets stripped (`api_key`, `api_key_env`, `password`, `jwt_secret_key`, `ws_token` are always `null` plus a `configured: true|false` marker). Write: `PATCH` with the shape and rules in section 17.2 (only from loopback, schema validation in `engine/settings.py`, `409 risk_limit_breached`, `restart_required`).

## 6. Control endpoints

All require `control` from direct loopback (section 2; otherwise `403 forbidden_local_only`), an `Idempotency-Key` header (section 3), and accept `?bot=A|B` (default is the first bot). All write one audit row `{actor, ip, action, targets, idempotency_key, result, detail}` and send it as a `gw.audit` event (section 14). The body has no fields other than those named; unknown fields return `400 invalid_request`. A `200` response is the Freqtrade response as is.

| Endpoint | Forwarded to | Confirmation | Effect |
| --- | --- | --- | --- |
| `POST /gw/v1/control/pause` | `POST /pause` | no | Stops processing new entries, open trades are still managed |
| `POST /gw/v1/control/resume` | `POST /start` | no | Resumes processing |
| `POST /gw/v1/control/stop-entry` | `POST /stopentry` | no | Kill switch: no new entries until `resume`; the gateway resends after a bot restart (section 14) |
| `POST /gw/v1/control/stop` | `POST /stop` | yes | Bot stops completely, open trades are not managed |
| `POST /gw/v1/control/reload-config` | `POST /reload_config` | no | Reloads the Freqtrade config |
| `POST /gw/v1/trades` | `POST /forceenter` | yes | Forced entry; rejected with `risk_limit_breached` if `entries_allowed` is false |
| `POST /gw/v1/trades/{id}/exit` | `POST /forceexit` body `{"tradeid": "<id>"}` | yes | Forced exit of one trade |
| `POST /gw/v1/trades/exit-all` | `POST /forceexit` body `{"tradeid": "all"}` | yes | Forced exit of all open trades (added: force exit of all positions is required; Freqtrade accepts it via `tradeid: "all"`) |
| `POST /gw/v1/locks` body `{"pair", "until", "side", "reason"}` | `POST /locks` (one-lock array) | no | Locks the pair until `until` (ISO-8601 with timezone, must be in the future); `side` defaults to `*` |
| `DELETE /gw/v1/locks/{lock_id}` | `DELETE /locks/{lockid}` | yes | Unlocks one lock |
| `POST /gw/v1/locks/delete` | `POST /locks/delete` body `{"pair": "BTC/IDR"}` or `{"lockid": 1}` | yes | Unlocks by pair |
| `POST /gw/v1/blacklist` body `{"pairs": ["SOL/IDR"]}` | `POST /blacklist` body `{"blacklist": [...]}` | no | Adds pairs to the blacklist |
| `DELETE /gw/v1/blacklist?pairs=BTC/IDR` | `DELETE /blacklist?pairs_to_delete=BTC/IDR` | yes | Removes from the blacklist |

In Freqtrade 2026.9 `/pause`, `/stopentry`, and `/stopbuy` are a single handler (`api_trading.py`, `RPC._rpc_pause`, state `PAUSED`), so `pause` and `stop-entry` have the same effect; both are kept because the PWA already uses both names. On endpoints without a required body, `confirm` is sent as a JSON body `{"confirm": "..."}`, including on `DELETE`.

Example `POST /gw/v1/trades`:

Example: draft, the gateway does not exist yet; values follow the Freqtrade capture where one exists.

```json
{"pair": "BTC/IDR", "side": "long", "stake_amount": null, "confirm": "cf_01J9Z6H0YV"}
```

`stake_amount: null` means the engine computes it via `custom_stake_amount` (0.5% risk per trade). The `200` response contains the trade object resulting from section 5.3; `422` if the pair is not in the whitelist. Checks before the confirmation token is issued and repeated in step 2: `409 invalid_request` if `api.force_entry` in the bot config is `false` (default), `422` if outside the whitelist, `409 risk_limit_breached` if `/gw/v1/risk` returns `entries_allowed: false`. If Freqtrade replies `200` without a `trade_id` (for example `{"status": "Error entering long trade ..."}`), the gateway replies `502 upstream_error` with that status text.

## 7. WebSocket event feed

### 7.1 Connection

`GET /gw/v1/events` with an `Authorization: Bearer <token>` header (or `?token=` for browsers that cannot set headers on WebSocket). The gateway keeps one WebSocket connection per bot to Freqtrade at all times, with or without a client, because fills, heartbeats, and fill gaps must be recorded even when the PWA is closed. Those Freqtrade messages are event-based and cheap. What only runs while a client is present is the candle request (section 7.4): without a client subscribed to `gw.candles` for a given pair, the gateway does not call `/pair_candles`.

### 7.2 Server messages

Every message is a single JSON object with `type`. Forwarded Freqtrade events have a monotonically increasing `seq` per gateway connection and an ISO-8601 `ts`. Gateway-derived events use a `type` prefixed with `gw.`.

Label: the `data` content for `entry`, `entry_fill`, `exit`, `exit_fill`, `status`, `warning`, `whitelist`, `analyzed_df` is a Freqtrade 2026.9 capture (in Freqtrade the event fields sit at the top level of the message, not in `data`; the gateway moves them into `data`). The `seq`/`ts` wrapper and all `gw.*` events are a draft.

```json
{"type": "gw.hello", "seq": 0, "ts": "2026-10-25T17:05:30.000Z", "data": {"gateway_version": "0.1.0", "freqtrade_version": "2026.9", "dry_run": true, "whitelist": ["BTC/IDR", "ETH/IDR", "SOL/IDR"], "sequence_resume_window": 200}}
```

```json
{"type": "entry", "seq": 1, "ts": "2026-10-25T17:06:26.077Z", "data": {"trade_id": 1, "pair": "BTC/IDR", "enter_tag": "force_entry", "direction": "long", "limit": 1463933000.0, "order_rate": 1463933000.0, "open_rate": 1463933000.0, "order_type": "limit", "stake_amount": 333322.90477, "stake_currency": "IDR", "base_currency": "BTC", "quote_currency": "IDR", "amount": 0.00022769, "open_date": "2026-10-25 17:06:26", "current_rate": 1463933000.0, "sub_trade": false}}
```

```json
{"type": "entry_fill", "seq": 2, "ts": "2026-10-25T17:06:26.077Z", "data": {"trade_id": 1, "pair": "BTC/IDR", "open_rate": 1463933000.0, "amount": 0.00022769, "stake_amount": 333322.90477, "open_date": "2026-10-25 17:06:26", "sub_trade": false}}
```

```json
{"type": "exit", "seq": 3, "ts": "2026-10-25T17:07:12.310Z", "data": {"trade_id": 1, "pair": "BTC/IDR", "gain": "loss", "limit": 1463912000.0, "order_rate": 1463912000.0, "order_type": "limit", "amount": 0.00022769, "open_rate": 1463933000.0, "close_rate": 1463912000.0, "current_rate": 1463912000.0, "profit_amount": -1333.5188537, "profit_ratio": -0.004000681725188243, "enter_tag": "force_entry", "exit_reason": "force_exit", "open_date": "2026-10-25 17:06:26", "close_date": "2026-10-25 17:07:12", "stake_amount": 333322.90477, "sub_trade": false, "final_profit_ratio": -0.004000681725188243, "is_final_exit": true}}
```

```json
{"type": "exit_fill", "seq": 4, "ts": "2026-10-25T17:07:12.401Z", "data": {"trade_id": 1, "pair": "BTC/IDR", "gain": "loss", "close_rate": 1463912000.0, "profit_amount": -1333.5188537, "profit_ratio": -0.004000681725188243, "exit_reason": "force_exit", "close_date": "2026-10-25 17:07:12", "is_final_exit": true}}
```

```json
{"type": "status", "seq": 5, "ts": "2026-10-25T17:09:00.000Z", "data": {"status": "running"}}
```

```json
{"type": "warning", "seq": 6, "ts": "2026-10-25T17:05:23.600Z", "data": {"status": "Dry run is enabled. All trades are simulated."}}
```

```json
{"type": "whitelist", "seq": 7, "ts": "2026-10-25T17:10:00.000Z", "data": ["BTC/IDR", "ETH/IDR", "SOL/IDR"]}
```

```json
{"type": "analyzed_df", "seq": 8, "ts": "2026-10-25T17:36:51.853Z", "data": {"key": ["BTC/IDR", "1h", "spot"], "la": "2026-10-25T17:36:51.853684+00:00", "df": {"__type__": "dataframe", "__value__": "{\"columns\":[\"date\",\"open\",\"high\",\"low\",\"close\",\"volume\",\"ema_fast\",\"ema_slow\",\"rsi\",\"enter_tag\",\"enter_long\",\"exit_tag\",\"exit_long\"],\"index\":[647],\"data\":[[1792944000000,1463059000.0,1463933000.0,1460899000.0,1463932000.0,0.25369079,1460601161.45,1464373799.03,54.657,\"\",null,\"\",null]]}"}}}
```

`df` is wrapped as `{"__type__": "dataframe", "__value__": "<string>"}`; `__value__` is pandas JSON in `split` orientation (`columns`, `index`, `data`) with `date` in epoch milliseconds. The gateway parses that string once and forwards the rows to the PWA via `gw.candles`; the PWA never receives this raw form.

Gateway-derived events (draft):

```json
{"type": "gw.risk", "seq": 9, "ts": "2026-10-25T17:10:05.000Z", "data": {"equity": 1998666.48, "daily_loss_pct": 0.067, "drawdown_pct": 0.067, "entries_allowed": true, "breaches": []}}
```

```json
{"type": "gw.risk_denied", "seq": 10, "ts": "2026-10-25T17:35:01.730Z", "data": {"pair": "ETH/IDR", "breaches": ["daily_loss"], "daily_loss_pct": 1.25, "drawdown_pct": 1.25, "equity": 1975000.0}}
```

`gw.risk_denied` originates from the engine. When the risk layer rejects an entry, the strategy calls `dp.send_msg`; Freqtrade sends it to the WebSocket as `strategy_msg` only if the config contains `"apiserver": {"allow_custom_messages": true}` (`rpc/rpc_manager.py` `process_msg_queue`, module name `apiserver`), which `engine/launch.py` renders for `trade` and `webserver`. The gateway subscribes to `strategy_msg`, parses `msg`, and maps `event: risk_guard_denied` to this type.

Freqtrade 2026.9 capture (`/api/v1/message/ws`, 2026-10-25 17:35 UTC, one losing trade of Rp 25,000 seeded, then `forceenter ETH/IDR`):

```json
{"type": "strategy_msg", "msg": "{\"event\": \"risk_guard_denied\", \"pair\": \"ETH/IDR\", \"breaches\": [\"daily_loss\"], \"daily_loss_pct\": 1.25, \"drawdown_pct\": 1.25, \"equity\": 1975000.0}"}
```

Negative control on the same bot without the `apiserver` key: the denial still occurs (`User denied entry for ETH/IDR.` in the log) but the WebSocket only receives `new_candle`, zero `strategy_msg`.

`gw.risk_denied` is a status signal, not a denial count. The strategy calls `dp.send_msg` without `always_send`, so Freqtrade suppresses messages with identical content for one timeframe (`data/dataprovider.py`, `PeriodicCache` with a ttl of one candle, 1 hour on this bot). Repeated denials with the same numbers within one candle produce only one event; a new event appears when the pair or the risk numbers change, or when the candle rolls over. The PWA shows the latest status and must not sum these events.

```json
{"type": "gw.candles", "seq": 11, "ts": "2026-10-25T18:00:01.000Z", "data": {"pair": "BTC/IDR", "timeframe": "1h", "candles": [["2026-10-25T17:00:00Z", 1463932000.0, 1464200000.0, 1463800000.0, 1464100000.0, 0.31, 1460700000.0, 1464400000.0, 56.1, null, null]]}}
```

```json
{"type": "gw.error", "seq": 12, "ts": "2026-10-25T18:00:02.000Z", "data": {"code": "upstream_unavailable", "message": "Freqtrade websocket closed", "retry_ms": 2000}}
```

### 7.3 Client messages

```json
{"type": "subscribe", "topics": ["entry", "entry_fill", "exit", "exit_fill", "status", "warning", "gw.risk", "gw.risk_denied", "gw.candles"], "candles": [{"pair": "BTC/IDR", "timeframe": "1h", "limit": 300}]}
```

```json
{"type": "resume", "last_seq": 40}
```

`resume` requests a replay of events with `seq > last_seq` from the buffer of the last 200 events. The replay follows the subscription that is active when `resume` is received, so the client sends `subscribe` first, then `resume` (section 11.5). If `last_seq` is older than the buffer, the gateway sends a new `gw.hello` followed by `gw.resync` containing the latest snapshot (whitelist, open trades, balance); the client redraws from the snapshot instead of guessing.

```json
{"type": "ping"}
```

The server replies `{"type": "pong", "ts": "..."}`. The gateway sends a ping every 20 seconds and disconnects a client that fails to respond twice.

### 7.4 Candle snapshots and deltas

- When the first client calls `subscribe`, the gateway sends the requested candle snapshot (`limit` at most 1500) as a single `gw.candles` message with the marker `snapshot: true` in `data`.
- After that, the gateway only sends new candles (`snapshot: false`) when the next candle closes. The source is the Freqtrade `new_candle` event or the latest `analyzed_df`.
- The gateway only requests candles from Freqtrade while at least one client is subscribed to that pair. With no clients, there are no candle requests; this keeps the load flat (plan section "Live transport and performance").
- If a `seq` is missing or the candle gap is more than two candles, the gateway sends a new snapshot for that pair with `data.reset: true`.

## 8. Freqtrade 2026.9 reference in use

Verified working on the Indodax dry-run bot on this PC. Everything below is under `/api/v1` unless stated otherwise. Auth: HTTP Basic or `POST /token/login` then `Authorization: Bearer <jwt>`; the WebSocket needs `?token=<ws_token or jwt>`. The gateway uses the 15-minute JWT from `/token/login`, not `ws_token`: the Freqtrade uvicorn access log prints the full WebSocket URL including the query, so a static `ws_token` would end up stored in journald (proven on the dry-run bot 2026-10-26).

| Path | Method | Used by the gateway for |
| --- | --- | --- |
| `/ping` | GET | health, no auth |
| `/version`, `/show_config`, `/sysinfo`, `/health`, `/logs?limit=` | GET | 5.1, 5.13, 5.14 |
| `/balance` | GET | 5.6 |
| `/status` | GET | 5.3 |
| `/trades?limit=`, `/trade/{id}`, `DELETE /trades/{id}` | GET, GET, DELETE | 5.4, 5.5 |
| `/profit`, `/profit_all` | GET | 5.7 |
| `/daily`, `/weekly`, `/monthly` | GET | 5.7 |
| `/stats`, `/count` | GET | 5.8 |
| `/performance`, `/entries`, `/exits`, `/mix_tags` | GET | 5.9 |
| `/pair_candles` | GET | 5.10 |
| `/whitelist` | GET | 5.11 |
| `/blacklist` | GET, POST, DELETE `?pairs_to_delete=` | 5.11, 6 |
| `/locks` | GET, POST (array `{pair, until, side, reason}`) | 5.11, 6 |
| `/locks/{lockid}` | DELETE | 6 |
| `/locks/delete` | POST `{pair?, lockid?}` | 6 |
| `/forceenter`, `/forceexit` | POST | 6, requires `force_entry_enable: true` |
| `/pause`, `/start`, `/stop`, `/stopentry`, `/reload_config` | POST | 6 |
| `/token/login`, `/token/refresh` | POST | gateway internal session |
| `/message/ws` | WebSocket | 7 |

`/forceenter` request: `{"pair": "BTC/IDR", "side": "long", "stakeamount": null, "entry_tag": null, "leverage": 1.0}`. The response contains the full trade object (example in section 5.3) with `trade_id`.

`/forceexit` request: `{"tradeid": "1", "ordertype": null, "amount": null}`. Response `{"result": "Created exit order for trade 1."}`.

The Freqtrade WebSocket client (the gateway) sends `{"type": "subscribe", "data": ["entry", "exit", "entry_fill", "exit_fill", "entry_cancel", "exit_cancel", "status", "warning", "exception", "strategy_msg", "protection_trigger", "protection_trigger_global", "whitelist", "new_candle"]}`, `{"type": "whitelist"}`, and `{"type": "analyzed_df", "data": {"limit": 2, "pair": "BTC/IDR"}}`.

## 9. Meaning of the trade fields used by the PWA

| Field | Meaning |
| --- | --- |
| `stake_amount` | IDR used for this trade (result of `custom_stake_amount`) |
| `open_trade_value` | Value at entry including the opening fee |
| `fee_open`, `fee_close` | Fee ratio; Indodax taker 0.2% is written `0.002` |
| `enter_tag` | strategy signal: `rule_<entry>` for `RuleStrategy` (default `rule_rsi_dip`), `ema_cross_up` for `SwingEmaRsi`; `force_entry` for a manual entry |
| `exit_reason` | `roi`, `stop_loss`, `force_exit`, `emergency_exit`; a strategy exit carries its tag: `rule_<exit>` for a `RuleStrategy` exit signal, `rule_lock`, `rule_trail` or `rule_time` for its rule exits, `ema_cross_down_or_rsi` for `SwingEmaRsi` |
| `profit_abs`, `profit_pct` | Absolute profit/loss in IDR and percent of entry value |
| `stop_loss_pct` | Per-trade loss limit, `-3.0` means -3% |
| `is_final_exit` | True when the trade is actually closed (not a partial exit) |

## 10. Constraints that must be reflected in the contract

- The Freqtrade `/show_config` response contains `api_server.jwt_secret_key` and `api_server.ws_token` in their original form (only `password` is masked). The gateway must not forward them as-is: take only the fields needed by 5.1 (`version`, `dry_run`, `stake_currency`, `timeframe`, `max_open_trades`, `state`) and never return the entire `/show_config` object to the browser.

- Indodax is not an officially supported exchange in Freqtrade 2026.9; Freqtrade uses a generic exchange class and prints a warning at start. This contract remains valid, but there is no Indodax-specific subclass.
- Indodax does not provide `fetchMyTrades` and `watchOHLCV` (reported by Freqtrade as `missing opt`); trade history is taken from the bot database, not from the exchange.
- A single Indodax OHLCV request with a long range only returns the latest candles (1h: ±649 candles, ≈27 days; 1d: 1000 candles). This is a per-request limit, not a history limit: per 500-candle window, 1h is available at least since 2023-10-01 (stage 2e, docs/stage2-backtest.md). The chart contract does not change: long-term charts in the PWA still use 1d, because the gateway does not yet have a windowed history endpoint.
- There is no endpoint to change strategy values directly (stoploss, ROI) other than via files. Changes are made via `PATCH /gw/v1/settings` then `POST /gw/v1/control/reload-config`: `/reload_config` discards the old bot instance, reloads the config and strategy, then creates a new instance (`worker._reconfigure`), so the change takes effect without a container restart.
- Stage 0a does not expose `/forceenter` to the PWA by default: `api.force_entry` stays `false` unless enabled for testing.

## 11. Additions for PWA stage 1

All content in this section is `draft`: used by the PWA (`pwa/`) and the mock gateway (`pwa/mock-gateway`), not yet present in the real gateway. The gateway stage must recapture the shapes.

### 11.1 `GET /gw/v1/equity?window=day|7d|total&bots=A,B`

Equity curve for today's trace (Summary) and the Bot A vs Bot B comparison (Charts). `start_equity` is the starting equity of the window (00:00 WIB for `day`, initial capital for `7d`). `window=total` and `series[].start_equity`: section 18.5.

```json
{"window": "7d", "start_equity": 2000000, "series": [{"bot": "A", "label": "Bot A", "strategy": "rules only", "points": [["2026-10-18T18:00:00Z", 2000000.0]]}, {"bot": "B", "label": "Bot B", "strategy": "rules + shadow swarm", "points": [["2026-10-18T18:00:00Z", 2000000.0]]}]}
```

### 11.2 `GET /gw/v1/decisions?limit=20` and the `gw.decision` event

Filters, `outcome`, quorum, the decision to be taken, and the `/gw/v1/decisions/{decision_id}` detail: section 18.1.

One swarm `VoterLog` row (`swarm/tb_swarm/runner.py` on the stage 0b branch) plus `pair`, `timeframe`, `candle`, `mode` (`shadow` or `gate`), `verdict` (`allow`, `reduce`, `skip`), `iqr_limit`, and `provider` per voter. The `request` field and the voter error text are not sent to the browser.

```json
{"decision_id": "dec_x", "ts": "2026-10-25T17:02:05Z", "pair": "BTC/IDR", "timeframe": "1h", "candle": "2026-10-25T17:00:00Z", "mode": "shadow", "status": "skip", "reason": "quorum_not_met", "required": 5, "answered": 2, "verdict": "skip", "iqr_limit": 0.25, "aggregate": null, "voters": [{"voter_id": "v1", "provider": "modelrouter", "model": "jev-1.13", "status": "timeout", "latency_s": 30.0, "answers": null}]}
```

### 11.3 Web Push

- `GET /gw/v1/push/key` returns `{"public_key": "<VAPID base64url>"}`.
- `POST /gw/v1/push/subscriptions` body `{"subscription": <PushSubscription.toJSON()>, "kinds": ["fill", "risk_breach", "kill_switch", "heartbeat_lost", "quorum_failed", "daily_summary"], "lang": "en"}`; `kinds` and `lang` are optional (all kinds, `en`). Response `201 {"endpoint", "kinds", "lang"}`. `lang` is the language of the message text: an empty or unknown code gives `en`, a regional code such as `id-ID` gives `id`. `DELETE` body `{"endpoint": "..."}` returns `{"removed"}`.
- `POST /gw/v1/push/test` sends one sample `daily_summary` to the subscriptions that ask for it and returns `{"sent", "failed"}`.
- All push routes need a session. New errors: `400 invalid_request` when the endpoint is not `https` on port 443 at `fcm.googleapis.com`, `*.push.services.mozilla.com`, `*.push.apple.com` or `*.notify.windows.com` (or the URL parsers disagree about the host), `p256dh` is not a P-256 point, `auth` is not 16 bytes, or a kind is unknown; `409 push_limit` at 20 subscriptions.
- Push payload: `{"kind", "title", "body", "lang", "url", "ts", "id"}`. The text comes from the per-language catalog `gateway/locales/<lang>.json`, because the service worker has no PWA catalog; adding a push language is one JSON file. `url` uses the hashes of the English PWA: `fill` `/#activity`, `risk_breach` and `kill_switch` and `daily_summary` `/#summary`, `heartbeat_lost` `/#system`, `quorum_failed` `/#swarm`. Urgency is `high` except `daily_summary` (`normal`); TTL 600 seconds; delivery does not follow redirects. The service worker displays everything as a visible notification (an iOS requirement); `risk_breach`, `kill_switch`, `heartbeat_lost` use `requireInteraction`.
- Triggers follow `notify.web_push` in the bot config: `fill` (`entry_fill` or `exit_fill`), `risk_breach` (only a new `daily_loss` or `total_drawdown` breach), `kill_switch` (control pause or stop-entry), `heartbeat_lost` (once per occurrence), `quorum_failed` (a `skip` decision with `quorum_not_met`), `daily_summary` (once per local bot day, on the first tick after the day changes, using yesterday's profit).
- Gateway configuration: `push_contact` (`mailto:` or `https://`, default `mailto:trading-bot@localhost`) and `push_allow_local_endpoints` (default `false`, for tests only). The VAPID private key is `<state_dir>/vapid_private.pem`, mode 0600, created once. Ledger tables: `push_subscriptions`, `push_state`.
- `GET /gw/v1/health` may carry `gateway.sample_data: true`; the PWA then displays the label "sample data" (key `top.sample` in its message catalog).

### 11.4 WebSocket closure

An invalid token closes the feed with code `4401`; the PWA stops reconnecting and returns to the login screen. Other codes trigger reconnection with backoff.


### 11.5 Topic subscription

Every `subscribe` message from the PWA carries the complete list of topics and the complete list of ladder pairs (`FEED_TOPICS` in `pwa/src/lib/state.ts`), not an addition. The gateway treats `subscribe` as a replacement: topics and pairs not mentioned stop being sent. The ladder snapshot is only sent for pairs newly added to the list. `gw.hello`, `gw.resync`, `gw.error`, and `pong` are always sent without a subscription. A new connection starts with no topics, and `resume` replay is filtered by the subscription active at that time; therefore the PWA's greeting after connecting is always `subscribe` then `resume`. The mock gateway filters with the same rules.

### 11.6 Data freshness in the PWA

The last-data clock only advances through events coming from the Freqtrade WebSocket (all topics in 11.5 except `gw.decision`) or through `overview.as_of` from a successful REST refresh. `gw.decision` originates from the swarm log, not from Freqtrade, so it is not considered evidence that Freqtrade is alive. `gw.hello`, `gw.resync`, `gw.error`, and `pong` also do not advance it. Every `gw.error`, whatever its code, makes the status board show as stale until the next data event arrives; if the last core refresh failed, until a core refresh succeeds again. The first data event after an error triggers an immediate core refresh, at most once per 10 seconds.

The REST refresh is split in two. The core (`/health`, `/overview`, `/risk`) determines the status board; if it fails, the board shows "Unknown" or shows as stale with its error. The panels (`/trades/open`, `/trades`, `/equity` x2, `/decisions`, `/sysinfo`, `/logs`) are populated individually; a panel that fails uses its last data and its error is shown on the System screen and in the place of that panel.

### 11.7 Poll budget per client

One open PWA sends 10 GETs per refresh: every 30 seconds while the feed is connected, on `gw.hello` or `gw.resync`, and when the tab becomes visible again. Plus 2 GETs after each order event, and one `/candles` per pair opened for the first time. Roughly 20 requests per minute per client alongside one WebSocket. The gateway stage (gateway CPU measurement) measures gateway CPU with this budget; if it is too expensive, `/overview` and `/risk` can be replaced by `gw.risk` events and the panel intervals lengthened.

## 12. Nice-to-have N2 additions

All content in this section is `draft`: built in the PWA and the mock gateway; the real gateway was not yet on main at the time of writing. The news and Fear and Greed fetcher already exists and is tested (`engine/news.py`, `tests/test_news.py`); the real gateway creates one `Feeds(settings.data.news_rss, <whitelist pair assets>, settings.data.fear_greed)` and calls it in the two routes below via `await asyncio.to_thread(feeds.news, asset, limit)` and `await asyncio.to_thread(feeds.sentiment, days)`. `Feeds` uses blocking urllib (15-second timeout per source, sequential, one lock), so calling it directly in an async handler can hold up the event loop for up to about 30 seconds when the cache is cold or expired.

Reason for the contract change: the time machine needs a longer per-pair decision history than the last 20 rows, and the news layer needs data fetched on the PC (the PWA must not call third parties directly, section 1).

### 12.1 `GET /gw/v1/decisions?pair=BTC/IDR&before=<ISO>&limit=200`

Adds two optional parameters to 11.2. `pair` filters a single pair; `before` returns decisions whose `candle` is before that time (next page). `limit` is 1 to 500, default 20. Order remains newest first. Without the new parameters, the shape and content are the same as 11.2. The time machine on the Charts screen calls `pair` + `limit=200` only when opened, then appends new `gw.decision` events to the already-loaded history; there is no additional polling.

### 12.2 `GET /gw/v1/news?pair=BTC/IDR&limit=50`

CoinDesk and Cointelegraph RSS headlines that mention the pair's base asset (whole word, case-insensitive: symbol and name, for example BTC or Bitcoin). Without `pair`, all headlines. `limit` is 1 to 100, default 50; values outside the range are clamped to the limit. The RSS description is not sent because it contains third-party HTML; links are only `http` or `https`. The gateway fetches feeds only when there is a request and caches them for 15 minutes; if one source fails, its last items are still used and `ok: false` along with the error is sent. `enabled: false` when `data.news_rss` is empty.

```json
{"as_of": "2026-10-26T04:46:40Z", "enabled": true, "sources": [{"id": "coindesk", "name": "CoinDesk", "url": "https://www.coindesk.com/", "feed": "https://www.coindesk.com/arc/outboundfeeds/rss/", "ok": true, "error": null, "fetched_at": "2026-10-26T04:46:40Z"}], "items": [{"id": "n_3f2a9c0d1e4b5a67", "source": "coindesk", "title": "Bitcoin slips below $60K", "url": "https://www.coindesk.com/markets/btc-slips", "published": "2026-10-25T15:00:00Z", "assets": ["BTC"]}]}
```

### 12.3 `GET /gw/v1/sentiment?days=30`

Daily Fear and Greed Index from alternative.me (`https://api.alternative.me/fng/`), oldest first, 1 to 365 days. Cached for 1 hour. `source` must be displayed as attribution (an alternative.me requirement). `classification` is the original alternative.me text (`Extreme Fear`, `Fear`, `Neutral`, `Greed`, `Extreme Greed`); the PWA translates it. `enabled: false` and `points: []` when `data.fear_greed` is false.

```json
{"as_of": "2026-10-26T04:46:40Z", "enabled": true, "source": {"name": "Fear & Greed Index", "provider": "alternative.me", "url": "https://alternative.me/crypto/fear-and-greed-index/", "ok": true, "error": null, "fetched_at": "2026-10-26T04:46:40Z"}, "points": [{"date": "2026-10-26", "value": 50, "classification": "Neutral"}]}
```

### 12.4 Poll budget

News, sentiment, and decision history do not take part in the 30-second refresh (11.7). The PWA requests them when a layer or the time machine is switched on, when the pair is changed, and when the Chart screen is reopened. News (per pair) and sentiment are not requested again within 15 minutes; decision history is requested once each time the time machine is opened.

## 12. Gateway stage 1

Code: `gateway/` (FastAPI and uvicorn from the same Freqtrade image). Configuration: `config/gateway.example.yaml`, schema `gateway/settings.py`. Run with: `scripts/stack.sh` (see README).

### 12.1 What was built

- Session per section 2: `POST` and `DELETE /gw/v1/session`, opaque token stored as a SHA-256 hash in `gateway.sqlite`, valid for `session_days` (default 30). Password from the `GW_PASSWORD` variable (minimum 12 characters; the gateway refuses to start if shorter). Five failures within 60 seconds cause new sessions to be rejected with `429 rate_limited`. Scope is `read` only (the control-scope work adds `control`, section 2).
- Error envelope per section 4 for all errors, including 404 for unknown routes and 400 for validation.
- Read endpoints per sections 5.1 through 5.15 (GET) and 11.1, 11.2.
- Feed per sections 7 and 11.4 through 11.5: `gw.hello`, `subscribe` replaces the subscription, `resume` with a 200-event buffer followed by `gw.hello` and `gw.resync` if too late, `ping`/`pong`, a `gw.candles` snapshot per new pair, a `gw.candles` delta when Freqtrade sends `new_candle`, a `reset: true` snapshot if the candle gap is more than two candles, `4401` for an invalid token. WebSocket ping every 20 seconds, disconnect after 40 seconds without a reply (uvicorn).

### 12.2 Additions and shape differences

- Two bots: per-bot endpoints accept `?bot=A|B`; without it the first bot in the configuration is used (Bot A). `/gw/v1/candles` always comes from Bot A (same pair and strategy). Every feed event from a bot carries a `bot` field at the top level of the message, alongside `type`, `seq`, `ts`, `data`. `gw.hello` carries `bots: [{id, label, strategy}]`.
- `/gw/v1/health` adds `bots` (heartbeat, age, number of starts, start-check result, open positions, feed connection status, shadow service health), `providers` (per provider from the last 20 decisions: calls, successes, p50 and max latency, last status), and `load` (gateway CPU over the last 10 seconds and the average since start, RSS, loadavg, number of clients). `exchange.latency_ms` is measured from `GET https://indodax.com/api/server_time` every 60 seconds.
- `/gw/v1/equity` adds `unavailable` (bots that did not respond).
- `/gw/v1/decisions` and `gw.decision` add `bot` and `usage` (tokens and cost of that decision). `voters[].model` is the model reported by the response.
- `/gw/v1/settings` is read-only: `providers[].api_key` is always `null` plus `api_key_configured`. Freqtrade API credentials are not in the configuration file (only the environment variable names), so nothing needs to be redacted in the `api` section.
- New derived events: `gw.heartbeat` (every 60 seconds per bot), `gw.heartbeat_lost` (heartbeat age above `heartbeat_lost_s`, default 180 seconds), `gw.bot_restart`, `gw.startup_check` (from `strategy_msg` when the bot starts), `gw.audit`.
- New endpoints:
  - `GET /gw/v1/costs?window=day|7d|total`: number of decisions, voter calls, input, output, and reasoning tokens, cost per bot and per provider, plus `cap` (`max_cost_idr_per_day`, `enforced: false`). Informational only; it does not limit anything. `cost` is the figure reported by the provider; nutaraline does not report cost, so it is `null`. Analyst tokens are on their own `analyst` row (`reports` and `asks`: `calls`, input, output, reasoning tokens, `cost`), computed from successful `analyst.report` and `analyst.ask` audits in the same window (all bots, including timer-recorded reports); they are not included in the decision, voter, and voter token totals above, and `cost` stays `null` as long as the provider does not report it (no rupiah cost is made up).
  - `GET /gw/v1/audit?limit=50`: audit log. Contents: `session.create` (`ok` or `denied`) and `session.delete` with IP; `config.observed` and `config.changed` for each bot's configuration file (checked every 10 seconds with SHA-256; `detail.changes` contains the changed keys with old and new values, `api_key` only as `<set>` or `null`; `result: invalid` if the new file does not pass the schema).
  - `GET /gw/v1/metrics`: `fill_latency_ms` (n, p50, p95, min, max, last 20 samples), gateway load, status of each upstream connection, feed sequence number.

### 12.2a Full history and secrets in logs

- `/gw/v1/risk`, `/gw/v1/overview`, `gw.risk`, `/gw/v1/equity`, and `/gw/v1/trades` use ALL closed trades, paged 500 per request until the count equals Freqtrade's `total_trades`. If the pages do not add up to `total_trades` (for example a trade closed between two pages), the answer is `502 upstream_error` with `retry_after_ms`, not a risk figure from partial history.
- Uvicorn inside Freqtrade logs the WebSocket URL together with its query (`?token=`) to the `uvicorn.error` logger, and Freqtrade's `/api/v1/logs` reads the same log. The strategy installs a filter on `uvicorn.error` and `uvicorn.access` when loaded (before the API server starts) that replaces `token=...` with `token=<redacted>`; `/gw/v1/logs` redacts with `gateway/redact.py` as a second layer (`token=[redacted]`, provider key values known to the gateway, `Authorization`, `x-api-key`, `sk-` patterns).
- The feed ignores binary frames and non-numeric `candles[].limit`, without dropping the connection.

### 12.3 Fill latency

When `entry_fill` or `exit_fill` arrives from Freqtrade, the gateway records the receive time (ms), then fetches `/trade/{id}` and uses the `order_filled_timestamp` of the order on the same side. Latency = receive time minus the fill time recorded by Freqtrade. Same clock (one host). Measurement tools: `scripts/measure_gateway.py fills|clients --out <file.json>` and `scripts/gateway_cpu.sh <container> <seconds> <label>`; the raw output is kept outside the repository.

### 12.4 Not yet built

- Controls of sections 3 and 6 and the `control` scope are built in the control work (section 14). `PATCH /gw/v1/settings`, provider, key, voter: the settings-editing work (section 17).
- `sample_data` is always `false`.


## 13. Analytics N1

All GETs and `POST /replay` are read-only and require any gateway session (read scope is enough), as in section 5. Three actions change something and follow sections 1, 2, and 6: `POST /gw/v1/analytics/scoreboard/apply` (writes `enabled: false` to the config), `POST /gw/v1/analytics/backtest` and `DELETE /gw/v1/analytics/backtest` (start and stop a job on the webserver instance). All three are accepted only from a direct loopback connection with a control-scope session, the same as the section 6 actions (`gateway.control.is_local`); otherwise `403 forbidden_local_only` and one `forbidden` audit row. Every other call writes exactly one audit row with the result (`ok` or `failed`), including an apply that changes nothing. Errors use the section 4 envelope, plus the code `invalid_config` (500) if the bot config fails validation. The code is in `analytics/` and is attached to the gateway app via `analytics.routes.install(app, context, reader)`; `context` provides: `source(bot)` (config, decision and trade database); `trades(bot)` (ALL closed trades plus open positions, with no count limit; the gateway pages like `/gw/v1/risk` and fails closed if the count does not match, because equity, peak, and annual tax are wrong if history is truncated); `analysis()` (webserver client or `None`); `can_control(request)` (`gateway.control.is_local(request)`, i.e. a direct client from `127.0.0.1` or `::1` without a `Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP`, `CF-Connecting-IP`, `CF-Ray`, or `True-Client-IP` header, and a session marked `control`; one guard for sections 6 and 13); and `audit(action, result, request=, targets=, detail=)` which writes the section 6 row (`actor` is `owner` for allowed calls and `<scope>_session` for `forbidden` rows, as in section 6, and `ip` is taken by the gateway from `request`, `idempotency_key` from the header only if it meets the section 6 rules; `request=None` means actor `gateway`, used by the auto-disable loop). Action names: `analytics.scoreboard.apply`, `analytics.scoreboard.auto_disable`, `analytics.backtest.start`, `analytics.backtest.stop`.

Status: wired into gateway stage 1. `gateway/analytics_context.py` provides `context`, and `gateway/app.py` calls `analytics.routes.install(app, gateway.analytics, reader)` with the same `reader` as section 5. `analysis_url` in the gateway config (loopback address of the webserver instance, using the same `FT_API_*` credentials and a different port from the bot) fills `analysis()`; without it signals and backtest answer `404 not_found`. Proven 2026-10-26 on a real gateway process (image from SHA 3412672) against Freqtrade 2026.9 dry-run with one BTC/IDR trade from a dry-run `forceenter` and a webserver instance: all routes in this section answered with the documented shape; `POST /backtest` answered 202 and then completed (15 trades, 2026-10-03 to 2026-10-25); `X-Forwarded-For` on apply and backtest answered `403 forbidden_local_only` without changing the config. The scoreboard, replay, and `auto_disable_loop` were tested on a synthetic decision database because the dry-run bot has no real decisions yet (13.9).

The `bot` parameter (bot letter, default first bot) applies to all endpoints except those that use the webserver instance (13.2 and 13.6), which only use `bot` to read the config.

### 13.1 What-if preview

`GET /gw/v1/analytics/limits/whatif?max_daily_loss_pct=2.0` accepts one or more of `max_daily_loss_pct`, `max_total_drawdown_pct`, `risk_per_trade_pct`, `max_open_trades`. The response compares the current config (`current`) with the proposal (`proposed`) on the same trades: limits in rupiah (`limits_idr`), whether the current state violates those limits (`now`), and the state if all open stops are filled (`all_stops_hit`). A proposal that violates the limit ordering (`risk_per_trade_pct` <= `max_daily_loss_pct` <= `max_total_drawdown_pct`) is rejected with `422 invalid_request`; other fields are rejected. Nothing is written to the config.

Example: shape from a test with one open BTC/IDR position and a Rp 12,000 loss today; not bot data.

```json
{"equity": 1985303.0, "open_positions": 1, "delta_idr": {"max_daily_loss_idr": 20000.0, "daily_floor_idr": -20000.0, "max_total_drawdown_idr": 0.0, "risk_per_trade_idr": 0.0, "trades_to_daily_limit": 2.0}, "changed": ["max_daily_loss_pct"]}
```

`proposed.limits_idr` in that example: `{"max_daily_loss_idr": 40000.0, "daily_floor_idr": 1960000.0, "max_total_drawdown_idr": 200000.0, "drawdown_floor_idr": 1800000.0, "risk_per_trade_idr": 9926.5, "max_open_trades": 3, "max_open_risk_idr": 29779.5, "trades_to_daily_limit": 4.0}`; `proposed.all_stops_hit`: `{"additional_loss_idr": 7485.0, "positions_without_stop": 0, "daily_loss_pct": 1.109, "drawdown_pct": 1.109, "breaches": []}`. Positions without `stop_loss_abs` are counted in `positions_without_stop`, not guessed.

`POST /gw/v1/analytics/replay` replays recorded voter answers without new LLM calls. Body: `{"bot": "B", "min_voters_answered": 3, "max_spread": 0.25, "exclude_voters": ["v4"], "limit": 500}`; all optional. An unspecified `max_spread` uses the config value, `"max_spread": null` means no spread limit. The quorum, tie, and spread rules use the same function as the runner (`tb_swarm.outcome.settle`). Response: `recorded_verdicts` and `replayed_verdicts`, `transitions` (for example `"allow->skip": 3`), up to 50 changed decisions (`changed`), and `trade_groups`: number of closed trades and total `profit_abs` per pair of recorded side and replayed side (`take->skip` and so on). Those figures are data, not a conclusion of profit or loss. Decisions without voter records (cancelled at restart, swarm down) go into `not_replayable`.

### 13.2 Strategy signals on the chart

`GET /gw/v1/analytics/signals?pair=BTC/IDR&from=2026-10-10&to=2026-10-25`. Verified in the vendor code and on a real instance: Freqtrade 2026.9's `/pair_history` and `/backtest` are mounted with `is_webserver_mode` (`webserver.py`), so a bot in `trade` mode answers `503 Bot is not in the correct state`; both need a separate `webserver` instance with downloaded OHLCV data (`download-data`) in its userdir. Maximum window is 60 days; the pair must be in `exchange.pairs`.

Response: `candles` (`[ts, open, high, low, close]`, `ts` ISO UTC) and `signals` (`{"ts", "kind": "enter" | "exit", "rate", "tag"}`), plus `enter_signals` and `exit_signals`. These are strategy signals on historical data, not orders executed by the bot.

Example: capture from a real webserver instance (Freqtrade 2026.9, Indodax, strategy SwingEmaRsi, BTC/IDR 1h, 2026-10-10 to 2026-10-25): 361 candles, 14 signals (5 enter, 9 exit), 0.49 seconds.

```json
{"ts": "2026-10-13T06:00:00Z", "kind": "enter", "rate": 1492556000.0, "tag": "ema_cross_up"}
```

### 13.3 Voter scoreboard

`GET /gw/v1/analytics/scoreboard?bot=B&limit=2000` scores each voter on closed trades (decisions are linked to trades through `trade_custom_data` key `shadow_decision_id` (`engine.decisions.SHADOW_KEY`, written by the strategy when bot B's entry fills), a column verified to exist in the real Freqtrade database). Definitions (also sent in `definition`): take probability = sum of the `allow` and `reduce` probabilities (without probabilities: 1 if that was the choice); outcome = closed trade with `profit_abs` > 0; per voter it computes `accuracy`, `base_rate`, `majority_accuracy` (accuracy of a majority-class guesser, `max(base, 1 - base)`), plus `calls`, `answered`, `answer_rate`. Voters whose answers all carry probabilities (`kind: probabilistic`) are also scored with `brier`, `brier_baseline` (constant guesser at the base rate), `ece`, and calibration `bins`. Voters whose answers are partly `choice` only (`kind: choice_only`; the `llm_structured` adapter sends only a choice, and a one-zero probability would make Brier and ECE score the answer format, not its quality) are scored on accuracy only; `brier`, `ece`, and `bins` are `null`.

`status`: `insufficient` if the sample is < `analytics.scoreboard.min_samples`; otherwise `drifting` if (`probabilistic`) `ece` > `max_ece` or `brier` > `brier_baseline` + `brier_margin`, or (`choice_only`) `accuracy` < `majority_accuracy` - `accuracy_margin`; otherwise `ok`. `shortfall` is an ordering measure (brier - baseline, or majority - accuracy). These thresholds are the initial choices, not yet calibrated on real data (there are no traded decisions in the database yet); change them through config.

`POST /gw/v1/analytics/scoreboard/apply` (control from loopback) disables the voters that are `plan.recommended` in the reading above, also when `auto_disable` is false (a manual apply is the caller's decision): `drifting` voters that are still active are written as `enabled: false` in config (validated before writing, atomic write, never reducing active voters below `swarm.min_voters_answered`, also when `swarm.enabled` is false; the rest are in `plan.kept_for_quorum`). The write uses a shared process lock and refuses to overwrite if the file's contents changed since they were read (`409 invalid_request`); writers in other processes are still protected only by that content check. The gateway runs the `plan.disable` plan every `interval_s` through `analytics.service.auto_disable_loop` only if `analytics.scoreboard.auto_disable` is true; `false` turns off automatic disabling. The loop starts with the gateway for bots that have `decisions` (bots without a decision database are not scored and write no audit rows), re-reads the bot config every 30 seconds so `auto_disable` takes effect without a gateway restart, and restarts with one log warning if it stops because of an unexpected error. The shadow swarm service reads config at start, so a disabled voter stops being called only after that service restarts; hot reload is not proven.

### 13.4 Stress test

`GET /gw/v1/analytics/stress?drop_pct=10` (default `analytics.stress.drop_pct`, 10). All open positions drop by `drop_pct` from the current price at the same time. Two states are computed with the engine's limit rules (`engine/risk.py`): `stop_fills` (the stop fills at the stop price if the price falls through it) and `stop_missed` (the stop does not fill, a price gap; the position is valued at the dropped price). Stop loss runs on the bot side (plan section 2), so a price gap may skip past it and both are shown.

Example: shape taken from a test (one BTC/IDR position of Rp 300,000, stop -3%, loss of Rp 12,000 today); not bot data.

```json
{"drop_pct": 10.0, "stop_fills": {"open_pnl": -10182.0, "equity": 1977818.0, "equity_change_idr": -7485.0, "daily_loss_pct": 1.109, "drawdown_pct": 1.109, "breaches": ["daily_loss"], "entries_allowed": false}, "stop_missed": {"open_pnl": -32487.3, "equity": 1955512.7, "equity_change_idr": -29790.3, "daily_loss_pct": 2.224, "drawdown_pct": 2.224, "breaches": ["daily_loss"], "entries_allowed": false}}
```

### 13.5 CSV export and tax summary

`GET /gw/v1/analytics/export/trades.csv` downloads the trade history (columns: `trade_id, pair, is_open, enter_tag, exit_reason, open_date, close_date, open_rate, close_rate, amount, stake_amount, fee_open, fee_close, profit_abs, profit_pct`). Text cells starting with `=`, `+`, `-`, `@`, tab, or CR are prefixed with `'` so they are not read as formulas.

`GET /gw/v1/analytics/export/tax?year=2026` sums the sale value (`amount` x `close_rate`) of closed trades per month (month and `year` in `risk.daily_reset_timezone`, the same zone as the risk day; the response carries `timezone`) and multiplies it by `analytics.tax.pph22_final_pct` (default 0.21). Basis, read from a Directorate General of Taxes article (pajak.go.id, 31 July 2025, edited 8 September 2025): PMK 50/2025, effective 1 August 2025, final PPh Article 22 on crypto asset sales through a PPMSE that is a domestic PAKD is 0.21% of the transaction value; 1% if the PPMSE is not a domestic PAKD. Not proven: Indodax's status as a PAKD, the official text of the PMK articles (only through the DJP article), VAT on platform services and platform fees (not computed). The response carries `basis` with all of this. This is information from dry-run data, not tax advice and not a tax report; dry-run does not withhold real tax.

### 13.6 Backtest from the UI

Uses the same webserver instance as 13.2. Verified prerequisite: the `webserver` launcher uses `strategy_path` in the rendered config, not the `--strategy` argument (Freqtrade 2026.9 rejects `--strategy` for `webserver`; that error was already in the launcher).

- `POST /gw/v1/analytics/backtest` (control from loopback) body `{"timerange": "20261003-20261025", "max_open_trades": 3, "dry_run_wallet": 2000000}` (`timerange` required, the rest optional with defaults from config). Strategy, `timeframe`, `stake_amount: "unlimited"`, and `enable_protections: false` are fixed by the gateway. Replies `202` with the job status.
- `GET /gw/v1/analytics/backtest`: status (`status`, `running`, `step`, `progress`) and, when finished, `result` containing the Freqtrade summary figures without the trade list; `results_per_pair` and `exit_reason_summary` are included.
- `DELETE /gw/v1/analytics/backtest` (control from loopback): stop the running job and then clean up.
- `GET /gw/v1/analytics/backtest/history` and `GET /gw/v1/analytics/backtest/history/result?filename=...`: saved results (file names only `[A-Za-z0-9._-]`).

Indodax 1h OHLCV history is limited to about 27 days (section 10), so the 1h backtest range is too. Backtest results use historical data and guarantee nothing for live conditions. Real example: BTC, ETH, SOL, 2026-10-03 to 2026-10-25, 2,000,000 IDR: 15 trades, finished in 2.04 seconds (profit and loss figures are not shown here because they are not a conclusion).

### 13.7 More than 3 pairs and the portfolio view

`exchange.pairs` in config is not limited to three; `risk.max_open_trades` may go up to 20. Verified on Indodax (`list-pairs --quote IDR`: 421 active IDR pairs) and in Freqtrade: 8 pairs (BTC, ETH, SOL, DOGE, XRP, ADA, BNB, AVAX /IDR) each downloaded 601 1h candles and a backtest 2026-10-05 to 2026-10-25 with `max_open_trades: 8` produced result rows for all eight. Each additional pair adds voter calls per entry candidate (LLM cost); that has not been measured.

`GET /gw/v1/analytics/portfolio` groups open positions per pair against equity: `pairs_configured`, `slots_used` and `slots_max`, `exposure_idr`, `exposure_pct`, `cash_idr`, and per pair `open_trades`, `stake_idr`, `pnl_idr`, `risk_at_stop_idr`, `share_of_equity_pct`, `over_limit` (exceeds `analytics.portfolio.max_pair_share_pct`, default 50). Positions on pairs that have left the config appear in `pairs_not_in_config`.

### 13.8 Config

```yaml
analytics:
  scoreboard: {enabled: true, auto_disable: true, min_samples: 30, max_ece: 0.25, brier_margin: 0.05, accuracy_margin: 0.05, bins: 5, interval_s: 3600}
  stress: {drop_pct: 10.0}
  tax: {pph22_final_pct: 0.21}
  portfolio: {max_pair_share_pct: 50.0}
```

The `analytics` section may be absent; the defaults above apply. Unknown keys are rejected like in other sections.

### 13.9 Not proven and not built

- The PWA side (N2).
- Analytics actions through a remote read session (undecided; currently rejected like the section 6 actions).
- Scoreboard and replay on real traded decisions: the current bot database has no decisions; what was tested is test data and the real column schema.
- The `drifting` thresholds (`max_ece`, `brier_margin`, `accuracy_margin`, `min_samples`) are not calibrated.
- Indodax's PAKD status and the official text of PMK 50/2025.
- Hot reload of disabled voters in the shadow swarm service.

## 14. Stage 2a controls

Code: `gateway/control.py` (local rules, confirmation token, idempotency, config change classification) and `Gateway.execute` plus routes in `gateway/app.py`. Tests: `tests/test_control.py`.

### 14.1 Kill switch

`POST /gw/v1/control/stop-entry` (or `pause`) calls `POST /stopentry` only; open trades are not touched (the test counts calls to the Freqtrade stub: only `/stopentry`). It is reflected in the feed twice: a `gw.audit` event from the gateway right after Freqtrade replies, and a `status` event from Freqtrade (`{"status": "paused"}`, sent by `worker.py` when the state changes). The gateway records the kill switch per bot in the `entry_stops` table; `resume` clears it. Freqtrade starts with `initial_state: running` (`engine/launch.py`), so every time the WebSocket connection to Freqtrade reconnects (bot restart or gateway restart) and `/show_config` reports `running` while a kill switch is recorded, the gateway sends `POST /stopentry` again and writes an audit with `actor: "gateway"`. `stop` also records the kill switch: a Freqtrade restarted after `stop` comes back `running`, then the gateway sends `/stopentry`, so the worst outcome after a restart is `paused` (open trades are managed again, with no new entries), not entries running again. Only `resume` clears this record.

### 14.2 Audit log

The `audit` table in `gateway.sqlite` is append-only: SQLite triggers reject `UPDATE` and `DELETE` (`audit is append-only`). Every control action writes one row per attempt with a `result`:

| `result` | Meaning |
| --- | --- |
| `ok` | Freqtrade carried out the action |
| `failed` | Freqtrade rejected or did not reply; `detail.error` and `detail.message` |
| `confirmation_required` | Step 1 of a risky action; token issued (the token id is not recorded) |
| `rejected` | Rejected by the gateway before Freqtrade: wrong or expired token, wrong idempotency key, `trades` check failed; `detail.error` |
| `replayed` | Stored result returned for the same idempotency key |
| `forbidden` | `read` session or request through proxy/tunnel; `actor` `read_session` or `control_session`; `idempotency_key` is recorded only if its format is valid, otherwise `null` |

`actor` is `owner` for `control` sessions and `gateway` for the re-sent kill switch. `targets[0]` is the bot id, the rest are action targets (pair, trade id, `lock:<id>`, `all`). `detail.params` are the action parameters; keys whose name contains `key`, `password`, `secret`, or `token` are replaced with `<set>` (or `null`). A request without a valid token is rejected with `401` and no audit row, so that parties without a session cannot fill this append-only table.

`GET /gw/v1/audit` (scope `read`) returns an array of rows, newest first, with optional filters combined by AND:

| Parameter | Meaning |
| --- | --- |
| `limit` | 1-500, default 50 |
| `before_id` | Pagination: only rows with a smaller `id`; fill in the `id` of the last row of the previous page |
| `action` | Prefix of the action name, for example `control.`, `trade.exit`, `config.` |
| `result` | Exact, for example `failed` |
| `actor` | Exact |
| `target` | One element of `targets` matching exactly (bot id, pair, trade id) |
| `since`, `until` | ISO-8601 with time zone; `ts >= since` and `ts < until` |

Action names: `control.pause`, `control.stop_entry`, `control.resume`, `control.stop`, `control.reload_config`, `trade.enter`, `trade.exit`, `trade.exit_all`, `pair.lock`, `pair.unlock`, `pair.blacklist`, `pair.unblacklist`, plus `session.*` and `config.*` from stage 1.

### 14.3 Live test (2026-10-26)

One Indodax dry-run bot (`trading-bot/engine` with `api.force_entry: true` only for this test) and the gateway on loopback, then stopped. Measured from a client on the same machine: `stop-entry` answered in 17.9 ms; the `gw.audit` event arrived 18.1 ms after the request was sent and the Freqtrade event `status: paused` at 905.6 ms; `/gw/v1/health` then reported `state: paused`. Force enter BTC/IDR: step 1 `409 confirmation_required`, step 2 `200` in 592 ms (trade 1 opened). Kill switch with an open trade: trade 1 stayed open. Force exit without step 2: `409`, trade stayed open; with step 2: `200` in 771 ms and the trade closed; the same token used again: `409 confirmation_invalid`. Lock, unlock (two steps), add and remove blacklist (two steps): `200` in 12-21 ms. Request with `X-Forwarded-For`: `403 forbidden_local_only`, audit row `forbidden`. `docker restart` of the bot while the kill switch was active: the gateway re-sent `/stopentry` 8.1 seconds after the restart command (audit `actor: gateway`), state returned to `paused`. The values of `GW_PASSWORD` and `FT_API_PASSWORD` do not appear in the 500 audit rows.

### 14.4 Not yet proven

- The window between Freqtrade start and the kill switch being re-sent: the gateway's WebSocket reconnection uses backoff 1, 2, 4, ... up to 30 seconds, so the bot can run without the kill switch for a few seconds after a restart.
- Classification of configuration changes (`risky_changes`) is connected to `PATCH /gw/v1/settings` in section 17.2.
- Control from a remote PWA is intentionally absent (loopback only); if the kill switch later has to be reachable from a phone through a tunnel, that is a new security decision.
- Tunnel detection depends on forward headers. Cloudflare Tunnel adds `CF-Connecting-IP` and `X-Forwarded-For` according to its documentation, but this has not been tested with a real tunnel. A tunnel that adds no headers (for example `ssh -L`) looks local. uvicorn also rewrites the client address from `X-Forwarded-For` when the connection comes from 127.0.0.1 (live test: the audit row recorded the IP from that header), so the local rule is rejected twice for such requests.

## 15. PWA stage 2

The stage 2 screens (Control, Configuration, Providers and keys, Swarm per decision, History, A vs B, Audit) use the gateway contract already built, as is, and only write a design for endpoints that no branch owns yet. At the time of writing (2026-10-26) gateway stage 1 and 2a (section 14) are on `main`, while 2b and 2c are not. Section 2b is in section 17 of this document; `main` uses number 12 twice (N2 and gateway stage 1), so references to the two use the task name.

### 15.1 Contract used as is

- Control and audit: 2a (sections 2, 3, 6, and 14 in this document, `main` a63e1e3). Session scope comes from the login `scope` (`control` only from direct loopback, otherwise `read`); `Idempotency-Key` is a fresh UUID v4 per press; `409 confirmation_required` shows step 2 from `error.confirmation`; step 2 repeats the same request with the same key and body `{"confirm": "<id>"}`, including on `DELETE`; `confirmation_expired` and `confirmation_invalid` go back to step 1. The kill switch "Stop new entries" calls `stop-entry`; per section 14.1 `stop-entry`, `pause`, and `stop` are all recorded by the gateway and re-applied after the bot restarts, only `resume` clears it.
- Configuration, providers, keys, voters, roles, import: section 17. The PWA sends `PATCH /gw/v1/settings?bot=` with nested `changes` containing only the keys that changed, without `mode`, `bot_id`, `api`, `shadow`, `providers`, `swarm.voters`; voters via `PUT` and `DELETE /gw/v1/voters/{id}`; analysts via `PUT /gw/v1/roles`; providers via `PUT` and `DELETE /gw/v1/providers/{id}`; keys via `PUT` and `DELETE /gw/v1/providers/{id}/key`; import via `GET` and `POST /gw/v1/providers/import`; the change log from `GET /gw/v1/settings/changes`. Two steps follow the `raising_keys` of 2b (the four risk limits and `capital.initial_idr` going up). Schema errors `400 invalid_request` carry `loc: message` in `message`; the PWA maps `loc` to the field with the same name and shows the rest above the form. `restart_required: true` is shown as "takes effect after the bot is restarted".
- Provider and voter registry per bot (`?bot=`): the PWA uses a Bot selector on the Configuration and Providers screens, and warns that two bots are changed twice.

### 15.2 Intentionally absent from the PWA

- Enabling or disabling providers remotely. Plan 4.5 item 4 mentions it, but 2b limits `read` sessions to reading and connection tests, and the schema has no `providers[].enabled` yet. The decision is tracked in a separate task; until then, the remote Providers screen is only status and Test connection.
- A reason note per configuration change: 2b does not accept that field; the change log is who, when, keys, old and new values from `/gw/v1/settings/changes`.

### 15.3 Design for endpoints that no branch owns yet

The content is `draft`, awaiting the swarm-per-decision, history, and A vs B task. Used by the PWA and the mock gateway; the gateway task re-captures the shape.

- `GET /gw/v1/decisions` adds `status=ok|skip` and `bot=A|B` alongside `pair`, `before` (the `candle` time, section N2), and `limit`. Every row and every `gw.decision` event adds `outcome`:

```json
{"state": "settled", "basis": "price", "horizon_h": 4, "price_at": 1463932000, "price_after": 1471200000, "return_pct": 0.5, "return_after_fees_pct": 0.1, "trade_id": null, "is_open": null, "profit_abs": null, "profit_pct": null, "settles_at": "2026-10-25T21:00:00Z"}
```

  `basis: "trade"`: the bot actually entered; `trade_id`, `is_open`, `profit_abs`, `profit_pct` come from that trade. `basis: "price"`: entry was skipped; the candle close `horizon_h` hours afterwards compared with the price at decision time, before and after two-sided fees; a rough assumption, not a trade. `state`: `pending` (horizon not yet passed or trade still open), `insufficient_data` (no candle after the horizon), `settled`. The PWA gives no number for the first two and does not sum them.
- `GET /gw/v1/trades?limit=50&offset=0&state=closed&bot=A`: `offset` after `trade_id` descending order, `state=closed` only closed trades.
- Daily, weekly, monthly per bot: section 5.7 with `bot`. Per exit reason and duration: 5.8. Per pair, entry tag, exit reason: 5.9.
- `GET /gw/v1/equity` adds `window=total` (since the start of the dry-run, one point per hour). `GET /gw/v1/profit?window=total&bot=B` forwards `max_drawdown` (ratio) and `max_drawdown_abs` from Freqtrade's `/profit`.
- `GET /gw/v1/overview?bot=` adds `state` (`running`, `paused`, `stopped`) from that bot's `/show_config`, so that the Control screen reads Bot B's state. Without it the PWA uses `/gw/v1/health` for the first bot and writes "state not readable" for the other bot.

## 16. Stage 3a: analyst agent and live mode control

The endpoints in this section are built in `gateway/analyst.py` and `gateway/modeapi.py` and tested through the real gateway with a test client (`tests/test_gateway_analyst.py`, `tests/test_gateway_mode.py`). The shape of reports and answers was captured from the live test of 2026-10-26 on model `deepseek-v4.1-flash-1017` at nutaraline; the PWA does not call them yet (stage 2d).

Process split: the gateway does not hold provider keys. The gateway writes a data snapshot to `<userdir bot>/<analyst.data_dir>` (`metrics.json`, `trades.jsonl`, `voter_decisions.jsonl`), then forwards the request to the analyst service (`python -m engine.analyst_service`, loopback, header `X-Analyst-Token`), which holds the model key and has only three read tools. The service token (`ANALYST_TOKEN`) is in the environment of the gateway and the service; the model key is only in the service.

### 16.1 Daily report

- `GET /gw/v1/analyst/reports?bot=B` (read): `{"bot": "B", "report_at": "00:10", "days": ["2026-10-26"]}`, newest first.
- `GET /gw/v1/analyst/reports/{day}?bot=B` (read): one report; `404 not_found` if it does not exist yet, `400 invalid_request` if `day` is not a date.
- `POST /gw/v1/analyst/reports?bot=B` body `{"day": "2026-10-26"}` (a stage 2a control action: `control` session, loopback client, `Idempotency-Key` required; repeating the same key returns the same report without running the model again; empty `day` means today in the risk time zone): refreshes the snapshot, runs the analyst, saves the report, writes an audit row `analyst.report`. One report per day; recreating with a new key replaces the old one. `day` must be a real date from 13 days ago up to today (`400 invalid_request` otherwise, before the model is called). Uses the same per-minute budget as ask (section 16.2). `409 invalid_request` if the report for that day is currently being created. The analyst service gives one total deadline of 90 seconds (including queueing and a single repair), below the gateway deadline of 120 seconds.
- The gateway scheduler creates yesterday's report once per day after `analyst.report_at` (default 00:10), retrying at the earliest 15 minutes after a failure, audit `analyst.report` with `actor: scheduler`. The `ok` audit row of a report, manual or scheduled, contains `day`, `model`, `tokens`, and `latency_s`; `/gw/v1/costs` sums `tokens` from those rows.

Example: capture from the live test of 2026-10-26 (a day without bot data; text trimmed). The analyst language was `id` in that run, so the summary is Indonesian; the language comes from `analyst.language` in the bot config (default `en`; the allowed values are the codes in `swarm/tb_swarm/languages.py`) and the report carries it in `language`.

```json
{"day": "2026-10-26", "generated_at": "2026-10-26T01:09:00Z", "model": "deepseek-v4.1-flash-1017", "language": "id", "summary": "Tidak ada data untuk 2026-10-26 (timezone Asia/Jakarta). ...", "anomalies": [], "suggestions": [], "tools_used": [{"name": "get_metrics", "args": {}}, {"name": "get_trade_history", "args": {"day": "2026-10-26"}}, {"name": "get_voter_log", "args": {"day": "2026-10-26"}}], "usage": {"input_tokens": 2788, "output_tokens": 363, "reasoning_tokens": 0, "cost": null}, "latency_s": 11.263}
```

Each element of `anomalies` and `suggestions` has the form `{"title", "detail", "evidence": ["dec_18_btc", "22"], "grounded": true}`. `grounded` is computed by the code of the analyst service (`tb_swarm.analyst`), not by the model: true only if `evidence` is not empty and every entry exactly equals one key name or one scalar value in the JSON that a tool returned when that report was created, not a text fragment: "22" is not verified just because it appears inside a timestamp, and a tool's notes or error messages are not evidence. Short numbers and common key names (e.g. `22`, `status`) can match without supporting the finding's claim, so `grounded` only means that every piece of evidence was actually returned by a tool; it is not proof that the finding's content is true. The PWA shows false as "not yet verified" and must not show true as "proven". Suggestions are advice; no path applies them.

### 16.2 Ask the analyst agent

`POST /gw/v1/analyst/ask` (read) body `{"question": "Kenapa BTC dilewati jam 02:00?", "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], "bot": "B"}`. Question 1 to 2,000 characters, history at most 20 turns (the server does not store conversations; the client resends its history). Response `{"answer", "model", "tools_used", "usage", "latency_s"}`. At most 6 questions or manual report generations per minute across the whole gateway, the rest get `429 rate_limited` with `retry_after_ms`. The `analyst.ask` audit records the tool name, tokens, and latency, not the question text. The snapshot is refreshed at most every 30 seconds. Tool output is capped at 20,000 characters: the newest lines are kept and the first output line states how many lines are shown out of how many matched; the per-day summary in `metrics.json` is shown newest day first with a list of omitted days, and `get_metrics(day=...)` reads one specific day.

Example: live test capture 2026-10-26 with analyst language `id` (a request to read `.env` was refused; text trimmed; the question means "Why was BTC skipped at 02:00?").

```json
{"answer": "Saya tidak bisa menunjukkan isi file `.env` atau kunci API provider. Alasannya: saya hanya ...", "model": "deepseek-v4.1-flash-1017", "tools_used": [], "usage": {"input_tokens": 696, "output_tokens": 190, "reasoning_tokens": 0, "cost": null}, "latency_s": 2.341}
```

Errors from this section: `404 not_found` (bot without an `analyst` section in its config), `503 upstream_unavailable` (analyst service unreachable), `503 upstream_error` (`ANALYST_TOKEN` missing from the gateway environment), `502 upstream_error` (provider failed; the message contains only the error kind, never the key or the provider response body), `504 upstream_unavailable` (service did not answer within 120 seconds).

### 16.3 Live mode

- `GET /gw/v1/mode?bot=B` (read): `{"bot": "B", "mode": "dry_run", "live_allowed": false, "exchange_key_configured": false, "blockers": [{"code": "exchange_key_missing", "message": "..."}, {"code": "live_engine_unproven", "message": "..."}]}`. `state_problem` appears when `mode.json` cannot be read (read as dry_run).
- `POST /gw/v1/control/mode?bot=B` body `{"mode": "live", "confirm": null}`: a stage 2a control action (section 14) with no rule of its own. It requires a `control`-scope session (born only from loopback login), the local rule `control.is_local` (section 17.1), and an `Idempotency-Key` of the form `^[A-Za-z0-9_-]{8,128}$`; otherwise `403 forbidden_local_only` or `400 invalid_request`, recorded in the audit, and a malformed key is never stored. Idempotency, confirmation, and its errors are the same as for other actions: the same key with a different request `409 invalid_request`, an unknown confirmation token, one already used, or one belonging to another session or parameters `409 confirmation_invalid`, expired (60 seconds) `409 confirmation_expired`.
  1. Without `confirm` toward live: if live is allowed, `409 confirmation_required` with a `confirmation` object (action `mode.change`, target `live`); the mode does not change. If not allowed, `422 live_blocked` with `blockers` (all conditions not yet met, the first reason in `message`).
  2. Repeat with `confirm: "cf_..."` and a new key: the conditions are checked again inside `ModeController.apply` (so no path bypasses it), then `200` with the mode status. A mode equal to the recorded one is not a change and does not ask for confirmation.
  3. Returning to `dry_run` takes only one step (lowering risk, section 3).
- Live conditions (all must be met, checked in steps 1 and 2): (a) the engine has recorded that it started with `INDODAX_API_KEY` and `INDODAX_API_SECRET` filled in (`capabilities.json` in the userdir, booleans only; the gateway does not hold exchange keys); (b) `engine.modectl.LIVE_ENGINE_PROVEN` is true. (b) is false in this build: the Indodax live order path has never been proven, so live cannot be enabled through this endpoint even if the key is present. Changing its value is a small live-stage decision, together with proving the order path.
- Audit `mode.change` (form in section 14) for every attempt: `ok`, `rejected` (codes `live_blocked`, `confirmation_invalid`, and others), `forbidden`, `confirmation_required`; the `live_blocked` rejection audit contains `error` and `message` (the first blocker message), not the blocker code and not the key value. The engine refuses to start if `mode.json` records live while `LIVE_ENGINE_PROVEN` is false.

Contract change: new error code `live_blocked` (422) in the list in section 4. Mode and manual report generation use stage 2a `gateway.execute` (local-only, `control` scope, `Idempotency-Key` in the ledger, `Confirmations` confirmation) through `Action.run`, a local action that is not forwarded to Freqtrade; there is no second control rule. Reason: the exchange key must not be in the gateway process that faces the PWA, and two local-only rules in the `/gw/v1/control/*` namespace would diverge.

## 17. Gateway stage 2b: configuration, providers, keys, voters

Code: `gateway/admin.py` (routes), `gateway/configstore.py` (read, validate, diff, atomic write), `gateway/providers.py` (providers, import, connection test), `gateway/redact.py`. All routes are under `/gw/v1`. The `?bot=A|B` parameter selects the bot's configuration file; without it the first bot is used. The provider and voter registries live in each bot's file, so a PWA that changes them for both bots makes two calls.

### 17.1 Access rules

- All writes in this section (PATCH, PUT, DELETE, import, and import preview) use the 2a mechanism (sections 2, 3, 14): a `control`-scope session and a request that comes directly from the bot engine machine. Failing either: `403 forbidden_local_only` and one `admin.denied` audit line (result `forbidden`, actor `<scope>_session`, `detail`: method, path, reason `not_local` or `scope`). The `owner` scope does not exist (merged into `control` by 2a).
- `control.is_local` (one definition for login, 2a control routes, and 2b writes) requires: peer address `127.0.0.1` or `::1`, no relay headers (`FORWARD_HEADERS`), `Host` header `127.0.0.1`, `localhost`, or `[::1]`, and `Origin` (if present) loopback. Its limit: `Host` and `Origin` are sent by the client, so that condition stops browsers that come in through a tunnel, not a client that forges headers. Through a raw TCP forward (`ssh -R`, `frp` or `ngrok tcp`, `socat`) the peer address stays `127.0.0.1` and the client is free to send `Host: 127.0.0.1` without `Origin`. The real protection is that the gateway port is not exposed through a TCP forward (17.8). The peer address `::ffff:127.0.0.1` is rejected (the gateway listens only on `127.0.0.1` or `::1`).
- Lowering the risk limit is also local-only (section 5.15 is stricter than plan 4.2 rule 2). A remote PWA can only read and test connections (17.3).
- `Idempotency-Key` is mandatory on all section 17 writes (8 to 128 characters `[A-Za-z0-9_-]`, same as 2a); without it `400 invalid_request`. A successful result (`200`) is stored for 24 hours per key in the ledger (`Ledger.store_result`, survives restart). Same key and same request: the stored result is returned without writing again (audit `replayed`). Same key with a different request: `409 invalid_request`. A key that is still running: `409 invalid_request`. The audit line stores the `Idempotency-Key` header only if its form is valid (`control.loggable_key`), otherwise `null`. Rejections (400, 409) are not stored. The only comparison value stored is the SHA-256 of the request; for key writes this includes the submitted key value (hash, not value).
- One write runs at a time per bot (per-bot lock), so read-modify-write cycles do not overwrite each other.

### 17.2 Configuration changes

`PATCH /gw/v1/settings?bot=A`, body `{"changes": {...}, "confirm": "cf_..."}`. `changes` is merged into the file: objects are merged per key, other values (including lists) replace. The resulting file must pass the same `engine/settings.py` schema as the engine; otherwise `400 invalid_request` with `loc: message` (the submitted value is never returned and never enters the audit), and the file does not change. Not changeable through this route (`400`): `mode`, `bot_id`, `api`, `shadow`, `providers` (use 17.3 and 17.4), `swarm.voters` (use 17.5).

Two steps (section 3) use `control.risky_changes(old, new)` on the old and new file: an increase in `risk.max_daily_loss_pct`, `risk.max_total_drawdown_pct`, `risk.risk_per_trade_pct`, `risk.max_open_trades`. 2b addition: an increase in `capital.initial_idr` (larger capital raises all limits in rupiah). A single request containing even one increase needs confirmation as a whole; lowering takes effect immediately. Pairs, fees, swarm, data, and notifications are not risk limits.

```json
{"error": {"code": "confirmation_required", "message": "raising risk limits needs a second step",
 "confirmation": {"id": "cf_3A9F00C2B1D45E77", "action": "config.update", "targets": ["A"],
 "summary": "Raise risk.max_daily_loss_pct 1.0 -> 2.0", "expires_at": "2026-10-26T01:10:00Z"}}}
```

Repeat the same request with `"confirm": "cf_..."` and the same or a new `Idempotency-Key`. The token uses 2a `Confirmations`: single use, 60 seconds, bound to `digest({"request": digest(action, bot, params without confirm), "session": digest(session token)})`. Unknown id, already used, for a different change, or from another session: `409 confirmation_invalid` (a non-matching token is not burned). Past 60 seconds: `409 confirmation_expired`. Confirmation is required only if the change still raises a limit when step 2 is recomputed against the file at that time.

Lowering `risk.max_daily_loss_pct` or `risk.max_total_drawdown_pct` to equal to or below the daily loss or drawdown already reached (from `GET /gw/v1/risk`): `409 risk_limit_breached`. If Freqtrade does not answer, the check is skipped and the audit records `risk_check: skipped_upstream_unavailable` (lowering is the safe direction).

Success (`200`):

```json
{"bot": "A", "changes": [{"key": "risk.max_daily_loss_pct", "old": 2.0, "new": 0.8}], "restart_required": true, "audit_id": 41}
```

`restart_required` is always `true` if the file changed: the engine and the swarm service read the configuration at start; reload without restart is not proven (`POST /gw/v1/control/reload-config` reloads the Freqtrade configuration, not this bot's schema). The gateway does not restart anything. With no actual change: `{"changes": [], "restart_required": false}`, no write and no audit.

The file is written atomically (temporary file, fsync, rename, fsync directory) with mode `0600`; YAML comments are not preserved because the file is rewritten from data. Write failure: `500 config_unwritable`, the old file intact. The file hash is stored in the ledger so the file watcher (12.2 gateway stage 1) does not record the same write again as `config.changed`.

`GET /gw/v1/settings/changes?bot=A&limit=50` (`read`): change log, one entry per key: `{audit_id, ts, actor, ip, action, bot, key, old, new}`. `actor` is `owner` for writes through the gateway, `file` for file edits detected by the watcher. The source is the audit log (`action` prefixed `config.`).

`GET /gw/v1/settings` (5.15) adds `providers[].api_key_last4`. `api_key` stays `null`. `api_key_env` (variable name only) is also shown, unlike the sentence in 5.15 that says it is `null`, because the Provider screen needs to show the variable name being read.

### 17.3 Providers

`GET /gw/v1/providers?bot=A` (`read`):

```json
{"bot": "A", "providers": [{"id": "nutaraline", "type": "openai-completions", "base_url": "https://nutaraline.co.uk/v1",
 "host": "nutaraline.co.uk", "models": ["deepseek-v4.1-flash-1017"], "active_models": ["deepseek-v4.1-flash-1017"],
 "key": {"source": "env", "configured": true, "last4": null, "env_name": "NUTARALINE_API_KEY", "env_set": true},
 "last_test": {"tested_at": "2026-10-26T01:00:00.000Z", "model": "deepseek-v4.1-flash-1017", "ok": true, "status": 200, "latency_ms": 840, "error": null, "detail": null}}]}
```

`key.source`: `config` (`api_key` in the file, `last4` holds the last 4 characters if the key is at least 12 characters, otherwise `null`), `env` (variable name in `env_name`, `env_set` whether that variable is filled in the gateway process), or `none`. `active_models`: models of that provider used by an active analyst or voter. `last_test` is `null` if never tested; read from the `provider.test` audit after a gateway restart. `host` has no user and password; `null` if `base_url` is still `from_import`.

- `PUT /gw/v1/providers/{id}` body `{"type", "base_url", "models"}` (`type`: the six `ProviderType` types in `engine/settings.py` (three chat types and `systemone`, `openai-decisions`, `openrouter-decisions`); the PWA uses the same list (`pwa/src/lib/providerTypes.ts`, guarded by a test against the schema)): add or change (id lowercase letters, digits, `_`, `-`; `import` is reserved). A new provider uses `api_key_env: <ID_UPPERCASE>_API_KEY` (`-` becomes `_`), matching the name in the local `.env`. Changing an existing provider keeps its key. `base_url` must not contain a user or password. A body containing `api_key` is rejected (`400`).
- `DELETE /gw/v1/providers/{id}`: delete; rejected `400` if still referenced by a voter or the analyst (schema message).
- `POST /gw/v1/providers/{id}/test`, optional body `{"model": "..."}` (must be in the provider's model list; default is the first model), `read` scope is enough (plan 4.5 item 4: a remote PWA may test). One small call with the prompt `Reply with the single word: ok` (the word `ping` is avoided: nutaraline answers `403` "Ping/probe inference dinonaktifkan" for the prompt `ping`, measured 2026-10-26): `openai-completions` to `{base}/chat/completions` (`max_tokens` 16), `openai-responses` to `{base}/responses` (`max_output_tokens` 16), `anthropic-messages` to `{base}/messages` if `base` ends in `/v1`, otherwise `{base}/v1/messages`; decision types use the swarm wire adapter with one `noul` question (`predicate` for `openai-decisions`): `systemone` to `{base}/v1/systemone`, `openai-decisions` to `{base}/v1/decisions` (body `input` and `questions` as lists), `openrouter-decisions` to `{base}/api/alpha/decisions`. Proven live 2026-10-26 for `systemone` (`jev-latest`, 200) and `openai-decisions` (`gpt-6-luna-decisions`, 200) at `api.experientiallabs.ai`; `openrouter-decisions` was tested only with a mock transport (no OpenRouter key). The key is sent only to the stored `base_url`, never to an address from the body; redirects are not followed. Result: `{"bot", "provider", "model", "ok", "status", "latency_ms", "error", "detail", "tested_at"}`. `ok` is true if the status is 2xx and the body is JSON. `error`: `unauthorized`, `not_found`, `rate_limited`, `rejected`, `upstream_error`, `timeout`, `connect_error`, `invalid_response`, `no_key`, `base_url_unresolved`. `detail` holds the provider's error message (max 160 characters) after filtering. A 5-second interval per provider (`429 rate_limited` with `retry_after_ms`); at most 2 tests running at once; 30-second timeout. `base_url: from_import` is not guessed from `models.yml`: the engine and swarm do not resolve it either, so the result is `base_url_unresolved`.
- Test results are recorded in the audit: `provider.test`, `targets: [bot, provider]`, result `ok` or `failed`, `actor` `owner` or `remote`.

### 17.4 Key

Local only and `control` (17.1).

- `PUT /gw/v1/providers/{id}/key` body `{"api_key": "..."}` or `{"api_key_env": "VARIABLE_NAME"}` (exactly one of them; the other is left empty in the file). `api_key`: 8 to 1024 characters without spaces. `api_key_env`: uppercase letters, digits, `_`. The response contains `provider` (form 17.3) and the diff, with `api_key` shown as `****` plus the last 4 characters (or `<set>` if the key is short).
- `DELETE /gw/v1/providers/{id}/key`: clears both.
- The raw key is written only to the bot configuration file. If that file is inside a git work tree and is not ignored (or git cannot confirm), the gateway rejects it (`400`, use `api_key_env`). No endpoint returns the full key; validation errors do not echo the submitted value.
- Logs: `gateway/redact.py` is attached to every log record of the gateway process (`python -m gateway`). What is filtered: key values known to the gateway (from the file and from the referenced environment variables), `Authorization` (Bearer and Basic), `?token=` and similar in URLs (including the `?token=` of the WebSocket feed), `x-api-key`, `sk-...` patterns, and tracebacks.

### 17.5 Voters and roles

The voter registry is `swarm.voters` in the configuration file; adding or replacing a voter only changes the file (no code).

- `GET /gw/v1/voters?bot=B` (`read`): `{"bot", "swarm": {"enabled", "mode", "min_voters_answered", "enabled_voters"}, "voters": [{id, adapter, provider, model, variation, timeout_s, weight, enabled, last_test}]}`. `last_test` is the last connection test of that voter's provider, not per-voter voting health (does not exist yet).
- `PUT /gw/v1/voters/{id}` body `{adapter, provider, model, variation, timeout_s, weight, enabled}`: add (at the end of the list) or replace (in place). The provider must exist, the model must be registered in that provider, and the `min_voters_answered` quorum must not exceed the number of enabled voters; otherwise `400` and the file is left intact.
- `DELETE /gw/v1/voters/{id}`: `404` if it does not exist; `400` if the quorum would no longer be met.
- `GET /gw/v1/roles` and `PUT /gw/v1/roles` body `{"analyst": {"provider", "model"}, "voters": {"v1": {"provider", "model"}}}`: choose the provider and model for the analyst agent (`llm.analyst_model`) and each voter in one atomic write and one audit row. Unknown voter: `404`.

Every write in section 17 writes one audit row `config.update`, `config.provider.upsert|delete|key|import`, `config.voter.upsert|delete`, or `config.roles` (`actor`, `ip`, `idempotency_key`, result `ok`, `rejected`, `forbidden`, `replayed`, or `confirmation_required`, `detail.changes` contains the key, old value, and new value with `api_key` masked) and broadcasts a `gw.audit` event.

### 17.6 Import from omp models.yml

The file is read locally by the gateway from `models_yml` in `config/gateway.yaml` (default `~/.omp/agent/models.yml`); the path cannot be supplied through a request.

- `GET /gw/v1/providers/import?bot=A`: preview, per provider `{name, id, type, base_url, host, models, key_source, exists, blocker}`. `key_source`: `literal`, `env` (the value is an uppercase variable name), `command` (value prefixed with `!`), `none`. The key value never appears in the response. `blocker` is filled for unsupported API types, non-http(s) URLs, no models, or a name that cannot become an id.
- `POST /gw/v1/providers/import` body `{"providers": [{"name", "with_key": false, "models": null, "replace": false}]}`: one atomic write. Without `with_key`, the provider uses the default `api_key_env` (17.3) and the key value in `models.yml` is not read into the configuration. `with_key: true` copies the key only for the checked providers: `literal` becomes `api_key`, `env` becomes `api_key_env`; `command` is rejected (`400`, the command is not executed), `none` is rejected. `models` (if given) must be a non-empty subset of the file's models. An existing provider is skipped unless `replace: true` (updates type, URL, models; the key stays unless checked). Response: `results: [{name, id, result: created|updated|skipped, reason?, with_key}]`.

### 17.7 Additional error codes

`config_unwritable` (500). `forbidden_local_only`, `confirmation_required`, `confirmation_invalid`, `confirmation_expired`, `risk_limit_breached`, `rate_limited`, `not_found`, `invalid_request` already exist (sections 4 and 14).

### 17.8 Not yet proven

- Reloading the configuration without a restart (hence `restart_required` is always `true`).
- Connection tests against real providers other than those recorded in the closing comment of the provider connection-test work; the `openai-responses` and `anthropic-messages` types with real keys are tested only if mentioned there.
- Connection test of `openrouter-decisions` against real OpenRouter (no key); the `models.yml` import only recognizes three chat types.
- Behavior behind a real tunnel (tested with a synthetic relay header, not a real Cloudflare Tunnel).
- Raw TCP forwards (`ssh -R`, `frp` or `ngrok tcp`, `socat`) look local because the peer is `127.0.0.1` and the client writes its own `Host`; `control.is_local` cannot tell them apart. Mitigation is operational only: do not expose the gateway port through a TCP forward.
- A key written with `api_key` requires a configuration directory the gateway can write to; compose currently mounts `./config` as `:ro` for the bot, so the gateway needs its own writable volume (not yet set up).
## 18. Stage 2c: per-decision swarm, history, equity curve A vs B

This section recaptures the design of 15.3 (PWA stage 2) with the real gateway; the field names `outcome`, `window=total`, `state=closed`, the `status`/`pair`/`before` filters, and `overview.state` follow 15.3 so that the PWA on `main` works unchanged. Differences from 15.3 are written down along with the reasons. The examples are taken from an Indodax dry-run recording on this PC (2026-10-26 00:54-03:03 UTC, bot A and bot B, 7 real nutaraline and experientiallabs voters, entry and exit via `forceenter`/`forceexit`); the recording is in `tests/data/stage2c/` (made by `scripts/record_fixture.py`, `/health` added from the same bot at about 03:2x UTC) and tested by `tests/test_recorded_history.py`. These numbers are evidence of shape and formula, not a conclusion about profit or loss.

### 18.1 Decisions: `GET /gw/v1/decisions`, `GET /gw/v1/decisions/{decision_id}`, event `gw.decision`

Parameters of `/gw/v1/decisions`: `bot`, `pair`, `status=ok|skip`, `before` (ISO with time zone; decisions with `candle` up to that time, so the page boundary is fetched again — section 18.1 item 5 and 12.1 N2), `limit` (1-500, default 20), `horizons` (1-4 numbers 1-48, default `1,2,4`), `cost_pct` (0-10, default 0.82). Newest first. The detail of one decision accepts `bot`, `horizons`, `cost_pct`; not found: `404 not_found`; horizon outside 1-48: `400 invalid_request`.

Every row, the detail, and the `gw.decision` event carry the form of 11.2 plus:

- `requested_at` (when the strategy sent the candidate), `rate` (the requested entry price), `entry_tag`.
- `voters[].answers` (each voter's answers, already in 11.2) and `aggregate.questions.verdict`: `median_probabilities` (median per option), `spread` (q25, q75, iqr, min, max probability of the winning option), `votes`, `agreement`, `tie`.
- `quorum`: `required`, `answered`, `met`.
- `would_take`: `verdict`, `action` (`allow` "enter at full size", `reduce` "enter at half size", `skip` "stay out"), `applied` (`true` only in `mode: veto`; in `shadow` the bot still enters). A failed quorum is always `skip` (fail-closed, stage 0b runner).
- `outcome` (form 15.3): `state` (`pending`, `insufficient_data`, `settled`), `basis` (`trade` if the decision shadows a real trade, `price` if there is no trade), `horizon_h` (the longest requested horizon), `price_at` (= `rate`), `price_after`, `return_pct`, `return_after_fees_pct` (longest horizon, `null` if not yet closed), `trade_id`, `is_open`, `profit_abs`, `profit_pct` (from the trade, `null` on `price`), `settles_at` (close of the horizon candle if `price` and `pending`), plus:
  - `round_trip_cost_pct`: the cost that is subtracted. The default 0.82 is the upper bound of an Indodax buy-sell cycle in plan section 1 (0.2% fee twice plus tax; tax from a secondary source, not yet proven).
  - `effect`: what changes if the decision is followed. `allow`: `same_as_rules`. `skip`: `avoided_loss` (the skipped entry turned out to lose), `missed_gain` (turned out to gain), `flat`. `reduce`: `reduced_loss`, `reduced_gain`, `flat`. Not yet closed: `pending` or `insufficient_data`. The basis of assessment is the same as `basis`: the trade's `profit_pct` (already including Freqtrade fees) or `return_after_fees_pct`.
  - `trade`: the shadowed trade (`trade_id`, `is_open`, `enter_tag`, `exit_reason`, `open_rate`, `close_rate`, `open_date`, `close_date`, `profit_abs`, `profit_pct`) or `null`. Looked up via the custom data `shadow_decision_id` in the bot's dry-run database (`<userdir>/tradesv3.dryrun.sqlite`, read-only), because Freqtrade's `/trades` does not carry custom data.
  - `forward`: one entry per horizon: `candles`, `until` (close of the h-th candle), `state`, and if `settled`: `close`, `return_pct` (= close / `rate` - 1), `net_pct` (= `return_pct` - `round_trip_cost_pct`), `max_up_pct`, `max_down_pct` (high and low in that window). Horizon h = h candles starting from the candle in which `requested_at` falls; the strategy's entry happens right after the signal candle closes, so h candles ~ h hours after entry. For an entry in the middle of a candle (this recording, `forceenter`) the window includes the part of the candle before the entry. `insufficient_data` if the candle is older than the `/pair_candles` window (1500 candles requested; Indodax gives about 649 1h candles) or has gaps. Candles are fetched once per pair per 60 seconds.

Differences from 15.3 and the reasons: (1) `basis` follows the presence or absence of a trade, not the verdict: in `mode: shadow` every decision shadows an entry that actually happens, including those whose verdict is `skip`, so the result of that trade is the answer to "did the skipped entry turn out profitable or not"; `price` is used if the trade does not exist (the entry was not filled, or `mode: veto` later). (2) The price fields are still filled on `basis: trade` as a comparison. (3) `effect`, `trade`, `forward`, `round_trip_cost_pct`, `quorum`, `would_take` are additions. (4) `gw.decision` is sent when the decision completes, so the `outcome` in the event is almost always `pending`; the PWA re-reads the list or detail for results that have closed. If Freqtrade does not respond when the event is created, the event is sent without `outcome`. (5) The `before` page cursor uses the same key order as the sorting: `candle` descending then `ts` descending, and `before` is inclusive (`candle <= ?`). Consequently rows on the boundary candle appear again on the next page, so the client drops `decision_id`s it already has (the PWA does this in `Swarm.svelte`); the next page stops if the response is empty. Limit: if one candle holds as many as `limit` decisions or more, the next page repeats that candle and paging gets stuck on it; this recording has at most three decisions on one candle (three pairs, `max_open_trades` 3). The first version (16c8db5) used `candle < ?` so decisions on the boundary candle were lost without any sign; the test `test_pages_union_to_every_decision_on_a_shared_candle` fails on that version and passes now.

Live evidence (2026-10-26 04:26 UTC, real gateway from this branch against the same two dry-run bots, gateway `main` 0468d19 on the next port as a comparison; the script and raw numbers are kept outside the repository): timeout `gw.decision` 17.0 seconds after `POST /forceenter` ETH/IDR, contents `status ok`, 7 of 7 voters, `verdict skip`, `quorum.met true`, `would_take.applied false`, `outcome.state pending`, `basis price`, `effect pending`. That forced entry used a limit order and was not filled, and the order was then cancelled by Freqtrade (trade 5 deleted, `entry_cancel`), so `trade` stayed `null` and the assessment moved to price; this example proves `basis: price` appears on its own without engineering. The list order uses the index `decisions_candle_seq (candle, settle_seq)` created by the writer schema (`engine/decisions.py`). Without that index, `ORDER BY candle DESC, settle_seq DESC` is run by SQLite with a temporary b-tree over all rows: on a database of 8760 decisions (a year, `request` 8.2 KB and `voters` 3.4 KB per row) `recent(20)` takes 117.0 ms and the SQL alone 85.9 ms; with the index `recent(20)` is 1.1 ms, `recent(500)` 29.0 ms, SQL alone 0.35 ms, query plan `SEARCH decisions USING INDEX decisions_candle_seq (candle<?)` without `TEMP B-TREE`. An old database created before the index existed only uses the index after the engine (writer) restarts and runs the schema; the gateway only reads. `tests/test_decisions.py::test_recent_sorts_with_an_index_instead_of_a_temp_btree` reads the query plan of `recent()` and fails if `TEMP B-TREE` appears.

Reading the trade database: `linked_trades` runs in `asyncio.to_thread`, so the loop serving the feed and the kill switch is not held up. Measured with a 5 ms ticker while reading a database of 8760 trades (a year at 24 decisions/day): call p50 10.8-15.6 ms, longest loop stall 7.2-9.3 ms, whereas calling directly in the loop (version 16c8db5) gave stalls of 205.7-285.5 ms. Database locked by another writer: version 16c8db5 failed with `OperationalError` after 5007.6 ms and then 500; now 501.6 ms and then `503 upstream_error`. `entry_tag` is read via `json_extract` so a 500-row request no longer parses about 4 MB of JSON. Cost p50 (15 cold calls spaced 2.2 seconds apart, then 30 warm, ms): `/decisions` before (list without `outcome`) 2.58 / 2.64 and after (with `outcome`) 21.6 / 3.35; `/trades` 14.03 / 1.29 then 21.18 / 2.58; `/equity` 33.4 / 2.95 then 37.22 / 1.98; `/profit` daily 15.7 / 1.88 then 17.21 / 2.38; `/performance` 18.1 / 1.69 then 23.09 / 1.99 (one extra `/mix_tags` call); `/risk` 19.21 / 2.09 then 25.29 / 1.88. No endpoint is more than about 19 ms slower at cold p50; that is the price of completeness (all trade pages, `outcome`, `mix_tags`), and the PWA's 30-second poll stays under 4 ms warm except `/decisions` with `outcome` (3.35 ms).

Example (recording, `GET /gw/v1/decisions/c59379cf6c83405aa91898467d700b11`, trimmed to two voters):

```json
{
  "decision_id": "c59379cf6c83405aa91898467d700b11", "ts": "2026-10-26T00:56:25.798Z", "requested_at": "2026-10-26T00:56:11.466Z",
  "bot": "B", "pair": "BTC/IDR", "timeframe": "1h", "candle": "2026-10-25T23:00:00+00:00", "rate": 1454000000.0, "entry_tag": "uji_rekam",
  "mode": "shadow", "status": "ok", "reason": null, "required": 5, "answered": 7, "verdict": "skip", "iqr_limit": null,
  "aggregate": {"questions": {"verdict": {"winner": "skip", "tie": false, "median_probabilities": {"allow": 0.0, "reduce": 0.0, "skip": 1.0}, "agreement": 1.0, "votes": {"allow": 0, "reduce": 0, "skip": 7}, "spread": {"q25": 1.0, "q75": 1.0, "iqr": 0.0, "minimum": 1.0, "maximum": 1.0}}}, "voters": 7},
  "voters": [
    {"voter_id": "v1", "provider": "nutaraline", "model": "deepseek-v4.1-flash-1017", "status": "ok", "latency_s": 1.58, "error_kind": null, "answers": {"verdict": {"type": "choice", "choice": "skip", "confidence": null, "probabilities": null}}},
    {"voter_id": "v2", "provider": "experientiallabs", "model": "deepseek-v4.1-flash-1017", "status": "ok", "latency_s": 9.86, "error_kind": null, "answers": {"verdict": {"type": "choice", "choice": "skip", "confidence": null, "probabilities": null}}}
  ],
  "quorum": {"required": 5, "answered": 7, "met": true},
  "would_take": {"verdict": "skip", "action": "stay out", "applied": false},
  "outcome": {
    "state": "settled", "basis": "trade", "horizon_h": 4, "round_trip_cost_pct": 0.82,
    "price_at": 1454000000.0, "price_after": null, "return_pct": null, "return_after_fees_pct": null,
    "trade_id": 1, "is_open": false, "profit_abs": -981.93363272, "profit_pct": -0.3326, "settles_at": null, "effect": "avoided_loss",
    "trade": {"trade_id": 1, "is_open": false, "enter_tag": "uji_rekam", "exit_reason": "force_exit", "open_rate": 1454000000.0, "close_rate": 1454972000.0, "open_date": "2026-10-26 00:56:11", "close_date": "2026-10-26 01:01:23", "profit_abs": -981.93363272, "profit_pct": -0.3326},
    "forward": [
      {"candles": 1, "until": "2026-10-26T01:00:00Z", "state": "settled", "close": 1453999000.0, "return_pct": -0.0001, "net_pct": -0.8201, "max_up_pct": 0.1843, "max_down_pct": -0.0417},
      {"candles": 2, "until": "2026-10-26T02:00:00Z", "state": "settled", "close": 1449038000.0, "return_pct": -0.3413, "net_pct": -1.1613, "max_up_pct": 0.1843, "max_down_pct": -0.619},
      {"candles": 4, "until": "2026-10-26T04:00:00Z", "state": "pending"}
    ]
  }
}
```

Other decisions in the same recording: SOL/IDR 3 of 7 voters answered (four `failed` from nutaraline), `status: skip`, `reason: quorum_not_met`, `quorum.met: false`, trade still open, so `state: pending`, `effect: pending`. ETH/IDR without a trade link (tested with the link removed, imitating `veto`): first candle `return_pct` 0.261 but `return_after_fees_pct` -0.559, so `avoided_loss`; with `cost_pct=0` it becomes `missed_gain`.

### 18.2 Full trade history

`/gw/v1/trades?state=closed&offset=&limit=` (5.4). The bot's trade database is read in a separate thread with a busy timeout of 0.5 seconds: if Freqtrade is writing, `/gw/v1/decisions` answers `503 upstream_error` with `retry_after_ms: 1000` (not 500) and the `gw.decision` event is still sent without `outcome`. All closed trades are read in pages of 500 (`closed_trades` from the closed-trades paging fix, fails closed if the number of pages does not match `total_trades`) for history, `/risk`, `/overview`, `gw.risk`, `/equity`, the periods in 18.3, and the decisions in 18.1. Its tests are `tests/test_gateway.py::test_risk_and_history_page_past_freqtrades_500_trade_limit` and `test_short_trade_page_fails_closed` (same fix); `offset` and `state=closed` are in `tests/test_recorded_history.py`.

### 18.3 `GET /gw/v1/profit?window=daily|weekly|monthly&timescale=N&bot=`

Computed by the gateway, newest first, fields follow Freqtrade's `/daily` (`date`, `abs_profit`, `starting_balance`, `rel_profit`, `trade_count`) plus `start` (start of the period in UTC), `wins`, `losses`, `draws` (sign of `close_profit`, Freqtrade `/stats` rule), plus `timezone`. Weeks start on Monday, months start on the 1st (same as Freqtrade). `window=total` remains Freqtrade's `/profit` as is (including `max_drawdown` and `max_drawdown_abs`, 15.3).

Differences from Freqtrade's `/daily` and the reasons: (1) the day boundary is in `risk.daily_reset_timezone` (Asia/Jakarta), the same as the daily loss meter, whereas Freqtrade uses the UTC date so trades that close 00:00-07:00 WIB fall into the previous day; (2) `starting_balance` = `capital.initial_idr` plus closed profit before the period, the same as the risk module, whereas Freqtrade counts backwards from the current stake balance (bot B recording: 1,980,048.57, because that balance uses `tradable_balance_ratio` 0.99 and open positions). Freqtrade's `/daily` is still listed in section 8 as a comparison.

```json
{"window": "daily", "timezone": "Asia/Jakarta", "stake_currency": "IDR", "data": [
  {"date": "2026-10-26", "start": "2026-10-25T17:00:00Z", "abs_profit": -4857.38042602, "starting_balance": 2000000.0, "rel_profit": -0.00242869, "trade_count": 3, "wins": 0, "losses": 3, "draws": 0},
  {"date": "2026-10-25", "start": "2026-10-24T17:00:00Z", "abs_profit": 0.0, "starting_balance": 2000000.0, "rel_profit": 0.0, "trade_count": 0, "wins": 0, "losses": 0, "draws": 0}
]}
```

### 18.4 Per exit reason and entry tag

`/gw/v1/performance` adds `by_mix_tag` from Freqtrade's `/mix_tags` (pairs of entry tag and exit reason). `/gw/v1/stats` remains Freqtrade's `/stats` (wins, losses, draws per exit reason and average duration). `profit_ratio` per group as is from Freqtrade: in `/performance`, `/entries`, `/exits` profit is divided by the group's entry cost (`_generic_performance_query`), in `/mix_tags` it is the sum of `close_profit`. Freqtrade 2026.9's `/mix_tags` `profit_pct` is wrong for groups of more than one trade: `round(profit + ratio * 100, 2)` (`Trade.get_mix_tag_performance`, operator order); the recording `uji_rekam force_exit` gives -0.34 for ratio -0.009527. The gateway recomputes `by_mix_tag[].profit_pct = round(profit_ratio * 100, 2)` (recording: -0.95); the vendor code is not modified. Bot B recording: `by_enter_tag` `uji_rekam` 2 trades -2,807.97, `force_entry` 1 trade -2,049.41; `exit_reasons.force_exit` 0 wins 3 losses.

### 18.5 `GET /gw/v1/equity?window=total&bots=A,B`

Since the dry-run started, for stacked A and B curves. `start` = the earliest `bot_start` from the `/health` of the requested bots (`bot_start_time` in Freqtrade's KeyValueStore: stored once when the database is created and unchanged after restarts; `bot_startup` is the last start). `/health` is used, not `/profit` which carries the same value, because on this PC `/health` takes 3-6 ms and `/profit` 25-66 ms per call. Both series begin at the same `start` with the initial capital, then one point per closed trade, and the last point at the current time includes unrealised profit of open positions. Each series carries `start_equity`.

Difference from 15.3: one point per closed trade, not one point per hour. Closed equity only changes when a trade closes; hourly points would only repeat that value, or need per-candle prices for open positions, which the gateway does not compute yet (not built).

```json
{"window": "total", "start": "2026-10-26T00:54:49Z", "start_equity": 2000000.0, "unavailable": [], "series": [
  {"bot": "A", "label": "Bot A", "strategy": "rules only", "start_equity": 2000000.0, "points": [["2026-10-26T00:54:49.005Z", 2000000.0], ["2026-10-26T01:01:23.565Z", 1999018.07], ["2026-10-26T02:03:01.066Z", 1996780.8], ["2026-10-26T03:03:02.189Z", 1994954.95], ["2026-10-26T03:03:50.000Z", 1992500.3]]},
  {"bot": "B", "label": "Bot B", "strategy": "rules + shadow swarm", "start_equity": 2000000.0, "points": [["2026-10-26T00:54:49.005Z", 2000000.0], ["2026-10-26T01:01:23.889Z", 1999018.07], ["2026-10-26T02:03:05.261Z", 1996968.65], ["2026-10-26T03:03:02.845Z", 1995142.62], ["2026-10-26T03:03:50.000Z", 1992687.99]]}
]}
```

### 18.6 `GET /gw/v1/overview?bot=`

Adds `state` from that bot's `/show_config` (15.3).

### 18.7 Not yet proven

- Decisions in `mode: veto` (not yet in the engine): `basis: price` was tested with the trade link removed from the recording and observed as `pending` in the live test (the entry was not filled).
- Live trades: the `tradesv3.dryrun.sqlite` database exists only in dry-run; in live, `outcome.trade` is `null` and evaluation uses price.
- The 0.21% tax in the default `cost_pct`: secondary source.
- The real strategy path (entry from a signal, not `forceenter`): no signal during the recording.
- A `basis: price` that is already `settled` (price-close horizon): only seen as `pending` in the live test; its `settled` is tested via a test with the trade link removed.
- Paging stops entirely when one candle holds `limit` or more decisions; there is no id cursor yet.
- `recent`, `get`, and `settled_after` are still called in the event loop. With an index the cost is 1.1-1.5 ms for `limit` 20 and 29.0 ms for `limit` 500; moving them to a thread requires a `check_same_thread=False` connection and has not been done.
- The new query plan was tested on a small database and on the 8760-row benchmark on this PC, not on the production database.
- PWA stage 2 on `main` against this real gateway: the shape follows 15.3, but the screen was not run in a browser at the time of writing.
