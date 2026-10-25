# Kontrak API gateway dan feed event

Kontrak untuk tugas PWA (tahap 1) dan gateway tahap 2. Diturunkan dari bagian 13 plan revisi 10 dan dari REST/WebSocket Freqtrade 2026.9 yang benar-benar ada di `vendor/freqtrade`. Semua contoh JSON di bawah diambil dari bot dry-run yang berjalan di PC ini pada 2026-10-25 17:06 UTC dengan exchange Indodax (bukan karangan). Path `/gw/...` adalah kontrak kita, bukan path Freqtrade; path Freqtrade ada di bagian 8.

## 1. Topologi dan batas kepercayaan

```text
PWA (browser) --HTTPS/WebSocket--> gateway --HTTP/WebSocket 127.0.0.1:8080--> Freqtrade REST/WS
```

- Freqtrade REST/WS hanya listen di loopback (`api.listen: 127.0.0.1`, `api.port: 8080` di `config/config.yaml`). Gateway satu-satunya klien.
- Gateway memegang kredensial Freqtrade (`FT_API_USERNAME`, `FT_API_PASSWORD`, `FT_API_JWT_SECRET`, `FT_API_WS_TOKEN` dari `.env`) dan tidak pernah mengirimkannya ke browser.
- Gateway memelihara satu koneksi WebSocket ke Freqtrade, bukan satu per tab PWA.
- PWA tidak boleh memanggil Freqtrade langsung, termasuk untuk candle. Semua lewat gateway supaya satu tempat menegakkan auth, audit, dan penghematan bandwidth.
- Gateway hanya untuk satu pemilik (single owner). Tidak ada multi-tenant pada rencana ini.
- Zona sensitif (ubah API key, ubah config, aktifkan mode live) hanya dari `127.0.0.1` pada mesin bot, bukan lewat tunnel. Hal ini mengikuti plan bagian 4.5.

## 2. Autentikasi gateway

- `POST /gw/v1/session` dengan body `{"password": "..."}` mengembalikan `{"token": "...", "expires_at": "2026-11-24T17:00:00Z"}`. Token opaque, disimpan PWA di memory atau secure storage, dikirim sebagai `Authorization: Bearer <token>`.
- Token punya dua lingkup: `read` (semua GET) dan `control` (semua POST/DELETE trading). Lingkup `owner` hanya diberikan bila login berasal dari loopback.
- `DELETE /gw/v1/session` mencabut token.
- Kesalahan auth selalu `401` dengan envelope kesalahan bagian 6, tanpa bocoran detail.

## 3. Kontrol dua langkah untuk aksi berisiko

Aksi yang menambah risiko (force enter, force exit ke pasar, hapus lock, hapus blacklist, stop bot) wajib dua langkah:

1. `POST /gw/v1/control/...` dengan header `Idempotency-Key: <uuid>` dan tanpa `confirm` menghasilkan `409`:

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

2. Ulangi request yang sama dengan header `Idempotency-Key` yang sama dan body `{"confirm": "cf_01J9Z6H0YV"}`. Gateway menjalankan aksi sekali, menyimpan hasil per kunci idempotensi, dan mengembalikan `200`.
3. Konfirmasi berlaku 60 detik dan hanya untuk satu aksi serta satu sasaran. Aksi yang menurunkan risiko (pause, hapus entry, tutup bot) tidak butuh konfirmasi.

## 4. Envelope respons

Sukses mengembalikan data langsung (objek atau array) seperti contoh di bagian 5. Semua respons galat memakai bentuk yang sama:

```json
{
  "error": {
    "code": "upstream_unavailable",
    "message": "Freqtrade API did not answer within 5s",
    "retry_after_ms": 2000
  }
}
```

Kode yang dipakai: `unauthorized`, `forbidden_local_only`, `confirmation_required`, `confirmation_expired`, `invalid_request`, `upstream_error`, `upstream_unavailable`, `risk_limit_breached`, `not_found`, `rate_limited`.

## 5. Endpoint baca

Semua butuh `read`. Cache di gateway: `overview` 2 detik, `candles` mengikuti candle terakhir, sisanya tanpa cache. Semua timestamp ISO-8601 UTC dengan akhiran `Z`.

### 5.1 `GET /gw/v1/health`

Gabungan `/ping`, `/version`, dan `/health` Freqtrade, ditambah status gateway.

```json
{
  "gateway": {"status": "ok", "version": "0.1.0", "uptime_s": 128},
  "freqtrade": {"version": "2026.9", "state": "running", "last_process": "2026-10-25T17:07:33.618830Z", "bot_start": "2026-10-25T17:05:23.597087Z", "dry_run": true},
  "exchange": {"name": "indodax", "reachable": true, "latency_ms": 184},
  "feed": {"connected": true, "last_event_at": "2026-10-25T17:07:12.401Z", "sequence": 42}
}
```

### 5.2 `GET /gw/v1/overview`

Ringkasan satu layar: modal, saldo, profit, trade terbuka, batas risiko.

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

Diteruskan dari `/status`. Elemen memakai objek trade Freqtrade apa adanya (bagian 9), ditambah dua field turunan: `profit_pct_now` (persen terhadap `open_trade_value`) dan `age_s`.

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
    "enter_tag": "ema_cross_up",
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

### 5.4 `GET /gw/v1/trades?limit=100&pair=BTC/IDR`

Diteruskan dari `/trades` (trade terbuka dan tertutup). Bentuk sama dengan 5.3; trade tertutup membawa `close_date`, `close_rate`, `close_profit_abs`, `exit_reason`, `exit_order_status`.

```json
[
  {"trade_id": 1, "pair": "BTC/IDR", "is_open": false, "enter_tag": "force_entry", "exit_reason": "force_exit", "open_rate": 1463933000.0, "close_rate": 1463912000.0, "close_profit_abs": -1333.5188537, "close_profit_pct": -0.4, "profit_abs": -1333.5188537, "close_date": "2026-10-25 17:07:12"}
]
```

### 5.5 `GET /gw/v1/trades/{trade_id}`

Satu trade dari `/trade/{id}`, bentuk 5.3. `404` bila tidak ada.

### 5.6 `GET /gw/v1/balance`

Diteruskan dari `/balance` dengan penyesuaian: hanya mata uang yang dikelola bot.

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

`starting_capital` adalah `dry_run_wallet * tradable_balance_ratio` = `2000000 * 0.99 = 1980000`, bukan modal penuh. PWA harus menampilkan `capital.initial_idr` sebagai modal dan `starting_capital` sebagai batas yang boleh dipakai.

### 5.7 `GET /gw/v1/profit?window=total|daily|weekly|monthly&timescale=7`

`window=total` memakai `/profit`; lainnya memakai `/daily`, `/weekly`, `/monthly`.

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

```json
{
  "window": "daily",
  "stake_currency": "IDR",
  "data": [
    {"date": "2026-10-25", "abs_profit": -1333.5188537, "rel_profit": -0.00067349, "starting_balance": 1980013.335188537, "trade_count": 1}
  ]
}
```

### 5.8 `GET /gw/v1/stats`

```json
{
  "durations": {"wins": null, "draws": null, "losses": 46.409757},
  "exit_reasons": {"force_exit": {"wins": 0, "losses": 1, "draws": 0}}
}
```

### 5.9 `GET /gw/v1/performance?pair=BTC/IDR`

Gabungan `/performance`, `/entries`, `/exits`, `/mix_tags`.

```json
{
  "per_pair": [{"pair": "BTC/IDR", "profit_ratio": -0.004000681725188243, "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}],
  "by_enter_tag": [{"enter_tag": "force_entry", "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}],
  "by_exit_reason": [{"exit_reason": "force_exit", "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}]
}
```

### 5.10 `GET /gw/v1/candles?pair=BTC/IDR&timeframe=1h&limit=300`

Diteruskan dari `/pair_candles` (GET). `timeframe` hanya `1h` pada tahap ini; gateway menolak timeframe lain dengan `invalid_request`. `limit` maksimal 1500, default 300. Indikator ikut dalam `columns`.

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

Baris adalah array sesuai urutan `columns` (bentuk asli Freqtrade), bukan objek per candle, supaya payload kecil. PWA memetakan indeks ke nama kolom sekali saat koneksi.

### 5.11 `GET /gw/v1/pairs`

```json
{
  "whitelist": {"pairs": ["BTC/IDR", "ETH/IDR", "SOL/IDR"], "length": 3, "method": ["StaticPairList"]},
  "blacklist": {"pairs": [], "length": 0, "method": ["StaticPairList"]},
  "locks": {"lock_count": 1, "locks": [{"id": 1, "pair": "BTC/IDR", "side": "long", "active": true, "reason": "Auto lock", "lock_time": "2026-10-25 17:07:12", "lock_end_time": "2026-10-25 18:00:00"}]}
}
```

Lock `"Auto lock"` selalu muncul setelah exit: Freqtrade mengunci pasangan selama satu candle untuk mencegah masuk ulang langsung. Itu normal, bukan proteksi yang dikonfigurasi.

### 5.12 `GET /gw/v1/risk`

Dihitung gateway dengan modul yang sama seperti mesin (`engine/risk.py`), dari trade tertutup dan profit terbuka. Bukan sekadar diteruskan dari Freqtrade.

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

`breaches` berisi `"daily_loss"` dan/atau `"total_drawdown"`. `entries_allowed` false berarti mesin menolak entry baru sampai hari berganti (untuk `daily_loss`) atau selamanya (untuk `total_drawdown`). PWA menampilkan keduanya sebagai status, bukan sebagai tombol yang bisa dimatikan.

### 5.13 `GET /gw/v1/logs?limit=50&level=warning`

```json
{
  "logs": [["2026-10-25 17:07:12,401 - freqtrade.wallets - INFO - Wallets synced."]],
  "level": ["INFO"]
}
```

### 5.14 `GET /gw/v1/sysinfo`

Diteruskan dari `/sysinfo` (CPU, RAM, disk). Dipakai kartu kesehatan PWA.

### 5.15 `GET /gw/v1/settings` dan `PATCH /gw/v1/settings`

Baca: konfigurasi aktif dengan rahasia dipangkas (`api_key`, `api_key_env`, `password`, `jwt_secret_key`, `ws_token` selalu `null` plus penanda `configured: true|false`). Tulis: hanya dari loopback (`forbidden_local_only` bila tidak), memvalidasi dengan skema yang sama (`engine/settings.py`) dan menolak `409 risk_limit_breached` bila perubahan menurunkan batas di bawah rugi yang sudah berjalan. Perubahan yang butuh restart mesin mengembalikan `{"restart_required": true}`, tidak menjalankan restart sendiri.

## 6. Endpoint kontrol

Semua butuh `control`, dan semua menulis satu baris audit `{actor, ip, action, targets, idempotency_key, result}`.

| Endpoint | Diteruskan ke | Konfirmasi | Efek |
| --- | --- | --- | --- |
| `POST /gw/v1/control/pause` | `POST /pause` | tidak | Berhenti memproses entry baru, trade terbuka tetap dikelola |
| `POST /gw/v1/control/resume` | `POST /start` | tidak | Kembali memproses |
| `POST /gw/v1/control/stop-entry` | `POST /stopentry` | tidak | Tidak ada entry baru sampai dihapus |
| `POST /gw/v1/control/stop` | `POST /stop` | ya | Bot berhenti total, trade terbuka tidak dikelola |
| `POST /gw/v1/control/reload-config` | `POST /reload_config` | tidak | Muat ulang config Freqtrade |
| `POST /gw/v1/trades` | `POST /forceenter` | ya | Entry paksa; ditolak `risk_limit_breached` bila `entries_allowed` false |
| `POST /gw/v1/trades/{id}/exit` | `POST /forceexit` | ya | Exit paksa satu trade |
| `POST /gw/v1/locks` | `POST /locks` | tidak | Kunci pasangan sementara |
| `DELETE /gw/v1/locks?pair=BTC/IDR` | `DELETE /locks` | ya | Buka kunci |
| `POST /gw/v1/blacklist` | `POST /blacklist` | tidak | Tambah pasangan ke blacklist |
| `DELETE /gw/v1/blacklist?pairs=BTC/IDR` | `DELETE /blacklist` | ya | Hapus dari blacklist |

Contoh `POST /gw/v1/trades`:

```json
{"pair": "BTC/IDR", "side": "long", "stake_amount": null, "confirm": "cf_01J9Z6H0YV"}
```

`stake_amount: null` berarti mesin menghitung lewat `custom_stake_amount` (0,5% risiko per trade). Respons `200` berisi objek trade hasil bagian 5.3; `422` bila pasangan tidak ada di whitelist.

## 7. Feed event WebSocket

### 7.1 Koneksi

`GET /gw/v1/events` dengan header `Authorization: Bearer <token>` (atau `?token=` untuk browser yang tidak bisa menetapkan header pada WebSocket). Klien pertama yang membuka feed memicu gateway menyambung ke Freqtrade; klien terakhir yang pergi memicu gateway memutus Freqtrade setelah 30 detik tanpa klien.

### 7.2 Pesan server

Semua pesan satu objek JSON dengan `type`. Event Freqtrade yang diteruskan punya `seq` naik monoton per koneksi gateway serta `ts` ISO-8601. Event turunan gateway memakai `type` berawalan `gw.`.

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
{"type": "whitelist", "seq": 7, "ts": "2026-10-25T17:10:00.000Z", "data": {"BTC/IDR": null, "ETH/IDR": null, "SOL/IDR": null}}
```

```json
{"type": "analyzed_df", "seq": 8, "ts": "2026-10-25T17:10:00.000Z", "data": {"key": ["BTC/IDR", "1h", "spot"], "la": "2026-10-25 17:00:00+00:00", "df": {"date": ["2026-10-25T16:00:00Z"], "close": [1463932000.0], "ema_fast": [1460601161.45], "ema_slow": [1464373799.03], "rsi": [54.657]}}}
```

`df` adalah objek kolom ke array (bentuk asli Freqtrade), sehingga klien mengubahnya menjadi baris sekali.

Event turunan gateway:

```json
{"type": "gw.risk", "seq": 9, "ts": "2026-10-25T17:10:05.000Z", "data": {"equity": 1998666.48, "daily_loss_pct": 0.067, "drawdown_pct": 0.067, "entries_allowed": true, "breaches": []}}
```

```json
{"type": "gw.risk_denied", "seq": 10, "ts": "2026-10-25T17:11:00.000Z", "data": {"pair": "ETH/IDR", "breaches": ["daily_loss"], "daily_loss_pct": 1.004, "drawdown_pct": 1.12, "equity": 1979900.0}}
```

`gw.risk_denied` berasal dari mesin: saat sinyal muncul tetapi lapisan risiko menolak, strategi memanggil `dp.send_msg` dengan `{"event": "risk_guard_denied", ...}`, dan gateway memetakannya ke tipe ini.

```json
{"type": "gw.candles", "seq": 11, "ts": "2026-10-25T18:00:01.000Z", "data": {"pair": "BTC/IDR", "timeframe": "1h", "candles": [["2026-10-25T17:00:00Z", 1463932000.0, 1464200000.0, 1463800000.0, 1464100000.0, 0.31, 1460700000.0, 1464400000.0, 56.1, null, null]]}}
```

```json
{"type": "gw.error", "seq": 12, "ts": "2026-10-25T18:00:02.000Z", "data": {"code": "upstream_unavailable", "message": "Freqtrade websocket closed", "retry_ms": 2000}}
```

### 7.3 Pesan klien

```json
{"type": "subscribe", "topics": ["entry", "entry_fill", "exit", "exit_fill", "status", "warning", "gw.risk", "gw.risk_denied", "gw.candles"], "candles": [{"pair": "BTC/IDR", "timeframe": "1h", "limit": 300}]}
```

```json
{"type": "resume", "last_seq": 40}
```

`resume` meminta pemutaran ulang event dengan `seq > last_seq` dari buffer 200 event terakhir. Bila `last_seq` lebih tua dari buffer, gateway mengirim `gw.hello` baru lalu `gw.resync` berisi snapshot terbaru (whitelist, trade terbuka, saldo); klien menggambar ulang dari snapshot, bukan menebak.

```json
{"type": "ping"}
```

Server menjawab `{"type": "pong", "ts": "..."}`. Gateway mengirim ping setiap 20 detik dan memutus klien yang tidak menjawab dua kali.

### 7.4 Snapshot candle dan delta

- Saat klien pertama `subscribe`, gateway mengirim snapshot candle sesuai permintaan (`limit` maksimal 1500) sebagai satu pesan `gw.candles` dengan penanda `snapshot: true` pada `data`.
- Setelah itu, gateway hanya mengirim candle baru (`snapshot: false`) ketika candle berikutnya tertutup. Sumbernya event `new_candle` Freqtrade atau `analyzed_df` terbaru.
- Gateway hanya meminta candle ke Freqtrade selama ada klien yang berlangganan pasangan itu. Tanpa klien, tidak ada permintaan candle; ini yang menjaga beban tetap datar (plan bagian "Transport live dan performa").
- Bila `seq` hilang atau jeda candle lebih dari dua candle, gateway mengirim snapshot baru untuk pasangan itu dengan `data.reset: true`.

## 8. Referensi Freqtrade 2026.9 yang dipakai

Terverifikasi jalan pada bot dry-run Indodax di PC ini. Semua di bawah `/api/v1` kecuali disebut lain. Auth: HTTP Basic atau `POST /token/login` lalu `Authorization: Bearer <jwt>`; WebSocket butuh `?token=<ws_token atau jwt>`.

| Path | Metode | Dipakai gateway untuk |
| --- | --- | --- |
| `/ping` | GET | health, tanpa auth |
| `/version`, `/show_config`, `/sysinfo`, `/health`, `/logs?limit=` | GET | 5.1, 5.13, 5.14 |
| `/balance` | GET | 5.6 |
| `/status` | GET | 5.3 |
| `/trades?limit=`, `/trade/{id}`, `DELETE /trades/{id}` | GET, GET, DELETE | 5.4, 5.5 |
| `/profit`, `/profit_all` | GET | 5.7 |
| `/daily`, `/weekly`, `/monthly` | GET | 5.7 |
| `/stats`, `/count` | GET | 5.8 |
| `/performance`, `/entries`, `/exits`, `/mix_tags` | GET | 5.9 |
| `/pair_candles` | GET | 5.10 |
| `/whitelist`, `/blacklist`, `/locks` | GET, POST, DELETE | 5.11, 6 |
| `/forceenter`, `/forceexit` | POST | 6, butuh `force_entry_enable: true` |
| `/pause`, `/start`, `/stop`, `/stopentry`, `/reload_config` | POST | 6 |
| `/token/login`, `/token/refresh` | POST | sesi internal gateway |
| `/message/ws` | WebSocket | 7 |

Request `/forceenter`: `{"pair": "BTC/IDR", "side": "long", "stakeamount": null, "entry_tag": null, "leverage": 1.0}`. Respons memuat objek trade penuh (contoh bagian 5.3) dengan `trade_id`.

Request `/forceexit`: `{"tradeid": "1", "ordertype": null, "amount": null}`. Respons `{"result": "Created exit order for trade 1."}`.

Klien WebSocket Freqtrade mengirim `{"type": "subscribe", "data": ["entry", "exit", "entry_fill", "exit_fill", "status", "warning", "whitelist", "analyzed_df", "new_candle"]}`, `{"type": "whitelist"}`, dan `{"type": "analyzed_df", "data": {"limit": 2, "pair": "BTC/IDR"}}`.

## 9. Arti field trade yang dipakai PWA

| Field | Arti |
| --- | --- |
| `stake_amount` | IDR yang dipakai untuk trade ini (hasil `custom_stake_amount`) |
| `open_trade_value` | Nilai saat masuk termasuk biaya buka |
| `fee_open`, `fee_close` | Rasio biaya; Indodax taker 0,2% ditulis `0.002` |
| `enter_tag` | `ema_cross_up` untuk sinyal strategi, `force_entry` untuk entry manual |
| `exit_reason` | `roi`, `stop_loss`, `exit_signal`, `force_exit`, `emergency_exit` |
| `profit_abs`, `profit_pct` | Untung/rugi absolut dalam IDR dan persen terhadap nilai masuk |
| `stop_loss_pct` | Batas rugi per trade, `-3.0` berarti -3% |
| `is_final_exit` | True bila trade benar-benar tertutup (bukan exit sebagian) |

## 10. Batasan yang harus tercermin di kontrak

- Respons `/show_config` Freqtrade memuat `api_server.jwt_secret_key` dan `api_server.ws_token` dalam bentuk asli (hanya `password` yang disensor). Gateway tidak boleh meneruskannya apa adanya: ambil hanya field yang dibutuhkan 5.1 (`version`, `dry_run`, `stake_currency`, `timeframe`, `max_open_trades`, `state`) dan jangan pernah mengembalikan seluruh objek `/show_config` ke browser.

- Indodax bukan exchange yang didukung resmi Freqtrade 2026.9; Freqtrade memakai kelas exchange generik dan mencetak peringatan saat start. Kontrak ini tetap sah, tetapi tidak ada subclass khusus Indodax.
- Indodax tidak menyediakan `fetchMyTrades` dan `watchOHLCV` (dilaporkan Freqtrade sebagai `missing opt`); riwayat trade diambil dari database bot, bukan dari exchange.
- Riwayat OHLCV 1h Indodax hanya ±649 candle terakhir (≈27 hari) walau diminta lebih; permintaan 1d mengembalikan 1000 candle dalam satu panggilan (batas satu permintaan, bukan bukti batas exchange). Grafik jangka panjang di PWA harus memakai 1d, bukan 1h.
- Tidak ada endpoint untuk mengubah nilai strategi langsung (stoploss, ROI) selain lewat berkas. Perubahan dilakukan lewat `PATCH /gw/v1/settings` lalu `POST /gw/v1/control/reload-config`: `/reload_config` membuang instance bot lama, memuat ulang config dan strategi, lalu membuat instance baru (`worker._reconfigure`), jadi perubahan ikut berlaku tanpa restart kontainer.
- Tahap 0a tidak membuka `/forceenter` ke PWA secara default: `api.force_entry` tetap `false` kecuali dinyalakan untuk uji.
