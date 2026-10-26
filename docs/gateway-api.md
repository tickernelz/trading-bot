# Kontrak API gateway dan feed event

Kontrak untuk tugas PWA (tahap 1) dan gateway tahap 2. Diturunkan dari bagian 13 plan revisi 10 dan dari REST/WebSocket Freqtrade 2026.9 yang benar-benar ada di `vendor/freqtrade`. Path `/gw/...` adalah kontrak kita, bukan path Freqtrade; path Freqtrade ada di bagian 8.

Setiap contoh JSON diberi satu dari dua label:

- `tangkapan Freqtrade 2026.9`: diambil dari bot dry-run Indodax yang berjalan di PC ini pada 2026-10-25 (REST, WebSocket `/api/v1/message/ws`, dan `strategy_msg` penolakan risiko). Nilai boleh dipangkas, nama field dan bentuknya tidak diubah.
- `rancangan`: bentuk milik gateway yang ditulis sebelum gateway ada (sesi, konfirmasi, envelope galat, ringkasan, event `gw.*`). Gateway tahap 1 (`gateway/`, ZHA-3764) sudah membangun bagian baca, sesi, envelope, dan feed; yang dibangun, yang berbeda, dan yang belum ada dicatat di bagian 12. Kontrol (bagian 3 dan 6) dan `PATCH /gw/v1/settings` belum dibangun.

## 1. Topologi dan batas kepercayaan

```text
PWA (browser) --HTTPS/WebSocket--> gateway --HTTP/WebSocket 127.0.0.1:8080--> Freqtrade REST/WS
```

- Freqtrade REST/WS hanya listen di loopback (`api.listen: 127.0.0.1`, `api.port: 8080` di `config/config.yaml`). Gateway satu-satunya klien.
- Gateway memegang kredensial Freqtrade (`FT_API_USERNAME`, `FT_API_PASSWORD`) dan tidak pernah mengirimkannya ke browser. `FT_API_JWT_SECRET` hanya dipegang bot. `ws_token` Freqtrade tidak dipakai (bagian 8).
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

Contoh: rancangan, gateway belum ada; nilai mengikuti tangkapan Freqtrade bila ada.

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

Contoh: rancangan, gateway belum ada; nilai mengikuti tangkapan Freqtrade bila ada.

```json
{
  "error": {
    "code": "upstream_unavailable",
    "message": "Freqtrade API did not answer within 5s",
    "retry_after_ms": 2000
  }
}
```

Kode yang dipakai: `unauthorized`, `live_blocked`, `forbidden_local_only`, `confirmation_required`, `confirmation_expired`, `invalid_request`, `upstream_error`, `upstream_unavailable`, `risk_limit_breached`, `not_found`, `rate_limited`.

## 5. Endpoint baca

Semua butuh `read`. Cache di gateway: `overview` 2 detik, `candles` mengikuti candle terakhir, sisanya tanpa cache. Semua timestamp ISO-8601 UTC dengan akhiran `Z`.

### 5.1 `GET /gw/v1/health`

Gabungan `/ping`, `/version`, dan `/health` Freqtrade, ditambah status gateway.

Contoh: rancangan, gateway belum ada; nilai mengikuti tangkapan Freqtrade bila ada.

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

Contoh: rancangan, gateway belum ada; nilai mengikuti tangkapan Freqtrade bila ada.

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

Contoh: tangkapan Freqtrade 2026.9 untuk field Freqtrade (trade 1, `force_entry`); `profit_pct_now` dan `age_s` rancangan gateway. `stake_amount` 333322.90 di tangkapan 17:06 UTC berasal dari ukuran tanpa biaya; sejak biaya ikut dihitung, tangkapan 17:40 UTC memberi `stake_amount` 294627.59 untuk modal yang sama (rugi di stoploss 3% plus dua kali biaya 0,2% = Rp 10.000).

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

### 5.4 `GET /gw/v1/trades?limit=100&pair=BTC/IDR`

Gabungan `/status` (trade terbuka) dan `/trades` Freqtrade. `/trades` Freqtrade hanya memuat trade tertutup, maksimal 500 per halaman, dan bawaannya urut id naik; gateway mengambil semua halaman (`order_by_id=true`, `offset`), menggabungkan, lalu mengurutkan `trade_id` turun sebelum `pair` dan `limit` diterapkan. Bentuk sama dengan 5.3; trade tertutup membawa `close_date`, `close_rate`, `close_profit_abs`, `exit_reason`, `exit_order_status`.

Contoh: tangkapan Freqtrade 2026.9 (dry-run Indodax di PC ini, 2026-10-25).

```json
[
  {"trade_id": 1, "pair": "BTC/IDR", "is_open": false, "enter_tag": "force_entry", "exit_reason": "force_exit", "open_rate": 1463933000.0, "close_rate": 1463912000.0, "close_profit_abs": -1333.5188537, "close_profit_pct": -0.4, "profit_abs": -1333.5188537, "close_date": "2026-10-25 17:07:12"}
]
```

### 5.5 `GET /gw/v1/trades/{trade_id}`

Satu trade dari `/trade/{id}`, bentuk 5.3. `404` bila tidak ada.

### 5.6 `GET /gw/v1/balance`

Diteruskan dari `/balance` dengan penyesuaian: hanya mata uang yang dikelola bot.

Contoh: tangkapan Freqtrade 2026.9 (dry-run Indodax di PC ini, 2026-10-25).

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

Contoh: tangkapan Freqtrade 2026.9 untuk field Freqtrade; `window` rancangan gateway.

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

Contoh: tangkapan Freqtrade 2026.9 (dry-run Indodax di PC ini, 2026-10-25).

```json
{
  "durations": {"wins": null, "draws": null, "losses": 46.409757},
  "exit_reasons": {"force_exit": {"wins": 0, "losses": 1, "draws": 0}}
}
```

### 5.9 `GET /gw/v1/performance?pair=BTC/IDR`

Gabungan `/performance`, `/entries`, `/exits`, `/mix_tags`.

Contoh: tangkapan Freqtrade 2026.9 per bagian; pembungkus `per_pair`/`by_enter_tag`/`by_exit_reason` rancangan gateway.

```json
{
  "per_pair": [{"pair": "BTC/IDR", "profit_ratio": -0.004000681725188243, "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}],
  "by_enter_tag": [{"enter_tag": "force_entry", "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}],
  "by_exit_reason": [{"exit_reason": "force_exit", "profit_pct": -0.4, "profit_abs": -1333.5188537, "count": 1}]
}
```

### 5.10 `GET /gw/v1/candles?pair=BTC/IDR&timeframe=1h&limit=300`

Diteruskan dari `/pair_candles` (GET). `timeframe` hanya `1h` pada tahap ini; gateway menolak timeframe lain dengan `invalid_request`. `limit` maksimal 1500, default 300. Indikator ikut dalam `columns`.

Contoh: tangkapan Freqtrade 2026.9 dari `/pair_candles` (kolom dan baris), dipangkas ke kolom yang dipakai PWA.

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

Contoh: tangkapan Freqtrade 2026.9 dari `/whitelist`, `/blacklist`, `/locks`; pembungkus rancangan gateway.

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

Contoh: rancangan, gateway belum ada; nilai mengikuti tangkapan Freqtrade bila ada.

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

### 5.13 `GET /gw/v1/logs?limit=50`

Contoh: tangkapan Freqtrade 2026.9 (dry-run Indodax di PC ini, 2026-10-25).

```json
{
  "log_count": 2,
  "logs": [
    ["2026-10-25 17:36:56", 1792949816022.821, "freqtrade.worker", "INFO", "Bot heartbeat. PID=1, version='2026.9', state='RUNNING'"]
  ]
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
| `DELETE /gw/v1/locks/{lock_id}` | `DELETE /locks/{lockid}` | ya | Buka satu kunci |
| `POST /gw/v1/locks/delete` | `POST /locks/delete` body `{"pair": "BTC/IDR"}` atau `{"lockid": 1}` | ya | Buka kunci per pasangan |
| `POST /gw/v1/blacklist` | `POST /blacklist` | tidak | Tambah pasangan ke blacklist |
| `DELETE /gw/v1/blacklist?pairs=BTC/IDR` | `DELETE /blacklist` | ya | Hapus dari blacklist |

Contoh `POST /gw/v1/trades`:

Contoh: rancangan, gateway belum ada; nilai mengikuti tangkapan Freqtrade bila ada.

```json
{"pair": "BTC/IDR", "side": "long", "stake_amount": null, "confirm": "cf_01J9Z6H0YV"}
```

`stake_amount: null` berarti mesin menghitung lewat `custom_stake_amount` (0,5% risiko per trade). Respons `200` berisi objek trade hasil bagian 5.3; `422` bila pasangan tidak ada di whitelist.

## 7. Feed event WebSocket

### 7.1 Koneksi

`GET /gw/v1/events` dengan header `Authorization: Bearer <token>` (atau `?token=` untuk browser yang tidak bisa menetapkan header pada WebSocket). Gateway menjaga satu koneksi WebSocket per bot ke Freqtrade sepanjang waktu, dengan atau tanpa klien, karena fill, heartbeat, dan jeda fill harus tercatat juga saat PWA tertutup. Pesan Freqtrade itu berbasis event dan murah. Yang hanya berjalan saat ada klien adalah permintaan kandel (bagian 7.4): tanpa klien yang berlangganan `gw.candles` untuk suatu pair, gateway tidak memanggil `/pair_candles`.

### 7.2 Pesan server

Semua pesan satu objek JSON dengan `type`. Event Freqtrade yang diteruskan punya `seq` naik monoton per koneksi gateway serta `ts` ISO-8601. Event turunan gateway memakai `type` berawalan `gw.`.

Label: isi `data` untuk `entry`, `entry_fill`, `exit`, `exit_fill`, `status`, `warning`, `whitelist`, `analyzed_df` adalah tangkapan Freqtrade 2026.9 (di Freqtrade field event berada di tingkat atas pesan, bukan di `data`; gateway memindahkannya ke `data`). Pembungkus `seq`/`ts` dan semua event `gw.*` adalah rancangan.

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

`df` dibungkus `{"__type__": "dataframe", "__value__": "<string>"}`; `__value__` adalah JSON pandas orientasi `split` (`columns`, `index`, `data`) dengan `date` dalam milidetik epoch. Gateway mengurai string itu sekali dan meneruskan baris ke PWA lewat `gw.candles`; PWA tidak pernah menerima bentuk mentah ini.

Event turunan gateway (rancangan):

```json
{"type": "gw.risk", "seq": 9, "ts": "2026-10-25T17:10:05.000Z", "data": {"equity": 1998666.48, "daily_loss_pct": 0.067, "drawdown_pct": 0.067, "entries_allowed": true, "breaches": []}}
```

```json
{"type": "gw.risk_denied", "seq": 10, "ts": "2026-10-25T17:35:01.730Z", "data": {"pair": "ETH/IDR", "breaches": ["daily_loss"], "daily_loss_pct": 1.25, "drawdown_pct": 1.25, "equity": 1975000.0}}
```

`gw.risk_denied` berasal dari mesin. Saat lapisan risiko menolak entry, strategi memanggil `dp.send_msg`; Freqtrade mengirimnya ke WebSocket sebagai `strategy_msg` hanya bila config memuat `"apiserver": {"allow_custom_messages": true}` (`rpc/rpc_manager.py` `process_msg_queue`, nama modul `apiserver`), yang dirender `engine/launch.py` untuk `trade` dan `webserver`. Gateway berlangganan `strategy_msg`, mengurai `msg`, dan memetakan `event: risk_guard_denied` ke tipe ini.

Tangkapan Freqtrade 2026.9 (`/api/v1/message/ws`, 2026-10-25 17:35 UTC, satu trade rugi Rp 25.000 disemai lalu `forceenter ETH/IDR`):

```json
{"type": "strategy_msg", "msg": "{\"event\": \"risk_guard_denied\", \"pair\": \"ETH/IDR\", \"breaches\": [\"daily_loss\"], \"daily_loss_pct\": 1.25, \"drawdown_pct\": 1.25, \"equity\": 1975000.0}"}
```

Kontrol negatif pada bot yang sama tanpa kunci `apiserver`: penolakan tetap terjadi (`User denied entry for ETH/IDR.` di log) tetapi WebSocket hanya menerima `new_candle`, nol `strategy_msg`.

`gw.risk_denied` adalah sinyal status, bukan hitungan penolakan. Strategi memanggil `dp.send_msg` tanpa `always_send`, sehingga Freqtrade menekan pesan yang isinya identik selama satu timeframe (`data/dataprovider.py`, `PeriodicCache` dengan ttl satu candle, 1 jam di bot ini). Penolakan berulang dengan angka yang sama dalam satu candle hanya menghasilkan satu event; event baru muncul bila pasangan atau angka risiko berubah, atau candle berganti. PWA menampilkan status terakhir dan tidak boleh menjumlahkan event ini.

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

`resume` meminta pemutaran ulang event dengan `seq > last_seq` dari buffer 200 event terakhir. Pemutaran ulang mengikuti langganan yang aktif saat `resume` diterima, jadi klien mengirim `subscribe` lebih dulu, lalu `resume` (bagian 11.5). Bila `last_seq` lebih tua dari buffer, gateway mengirim `gw.hello` baru lalu `gw.resync` berisi snapshot terbaru (whitelist, trade terbuka, saldo); klien menggambar ulang dari snapshot, bukan menebak.

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

Terverifikasi jalan pada bot dry-run Indodax di PC ini. Semua di bawah `/api/v1` kecuali disebut lain. Auth: HTTP Basic atau `POST /token/login` lalu `Authorization: Bearer <jwt>`; WebSocket butuh `?token=<ws_token atau jwt>`. Gateway memakai JWT 15 menit dari `/token/login`, bukan `ws_token`: log akses uvicorn Freqtrade mencetak URL WebSocket lengkap dengan query, sehingga `ws_token` statis akan tersimpan di journald (terbukti di bot dry-run 2026-10-26).

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
| `/whitelist` | GET | 5.11 |
| `/blacklist` | GET, POST, DELETE `?pairs_to_delete=` | 5.11, 6 |
| `/locks` | GET, POST (array `{pair, until, side, reason}`) | 5.11, 6 |
| `/locks/{lockid}` | DELETE | 6 |
| `/locks/delete` | POST `{pair?, lockid?}` | 6 |
| `/forceenter`, `/forceexit` | POST | 6, butuh `force_entry_enable: true` |
| `/pause`, `/start`, `/stop`, `/stopentry`, `/reload_config` | POST | 6 |
| `/token/login`, `/token/refresh` | POST | sesi internal gateway |
| `/message/ws` | WebSocket | 7 |

Request `/forceenter`: `{"pair": "BTC/IDR", "side": "long", "stakeamount": null, "entry_tag": null, "leverage": 1.0}`. Respons memuat objek trade penuh (contoh bagian 5.3) dengan `trade_id`.

Request `/forceexit`: `{"tradeid": "1", "ordertype": null, "amount": null}`. Respons `{"result": "Created exit order for trade 1."}`.

Klien WebSocket Freqtrade (gateway) mengirim `{"type": "subscribe", "data": ["entry", "exit", "entry_fill", "exit_fill", "entry_cancel", "exit_cancel", "status", "warning", "exception", "strategy_msg", "protection_trigger", "protection_trigger_global", "whitelist", "new_candle"]}`, `{"type": "whitelist"}`, dan `{"type": "analyzed_df", "data": {"limit": 2, "pair": "BTC/IDR"}}`.

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

## 11. Tambahan untuk PWA tahap 1

Semua isi bagian ini `rancangan`: dipakai PWA (`pwa/`) dan gateway tiruan (`pwa/mock-gateway`), belum ada di gateway nyata. Tahap gateway wajib menangkap ulang bentuknya.

### 11.1 `GET /gw/v1/equity?window=day|7d&bots=A,B`

Kurva ekuitas untuk jejak hari ini (Ringkas) dan perbandingan Bot A vs Bot B (Grafik). `start_equity` adalah ekuitas awal jendela (00.00 WIB untuk `day`, modal awal untuk `7d`).

```json
{"window": "7d", "start_equity": 2000000, "series": [{"bot": "A", "label": "Bot A", "strategy": "aturan saja", "points": [["2026-10-18T18:00:00Z", 2000000.0]]}, {"bot": "B", "label": "Bot B", "strategy": "aturan + swarm bayangan", "points": [["2026-10-18T18:00:00Z", 2000000.0]]}]}
```

### 11.2 `GET /gw/v1/decisions?limit=20` dan event `gw.decision`

Satu baris `VoterLog` swarm (`swarm/tb_swarm/runner.py` di cabang tahap 0b) ditambah `pair`, `timeframe`, `candle`, `mode` (`shadow` atau `gate`), `verdict` (`izinkan`, `kecilkan`, `lewati`), `iqr_limit`, dan `provider` per voter. Field `request` dan teks galat voter tidak dikirim ke browser.

```json
{"decision_id": "dec_x", "ts": "2026-10-25T17:02:05Z", "pair": "BTC/IDR", "timeframe": "1h", "candle": "2026-10-25T17:00:00Z", "mode": "shadow", "status": "skip", "reason": "quorum_not_met", "required": 5, "answered": 2, "verdict": "lewati", "iqr_limit": 0.25, "aggregate": null, "voters": [{"voter_id": "v1", "provider": "modelrouter", "model": "jev-1.13", "status": "timeout", "latency_s": 30.0, "answers": null}]}
```

### 11.3 Web Push

- `GET /gw/v1/push/key` mengembalikan `{"public_key": "<VAPID base64url>"}`.
- `POST /gw/v1/push/subscriptions` body `{"subscription": <PushSubscription.toJSON()>, "kinds": ["fill", "risk_breach", "kill_switch", "heartbeat_lost", "quorum_failed", "daily_summary"]}`; `DELETE` body `{"endpoint": "..."}`.
- `POST /gw/v1/push/test` mengirim satu `daily_summary` uji.
- Payload push: `{"kind", "title", "body", "url", "ts", "id"}`. Service worker menampilkan semuanya sebagai notifikasi terlihat (syarat iOS); `risk_breach`, `kill_switch`, `heartbeat_lost` memakai `requireInteraction`.
- `GET /gw/v1/health` boleh membawa `gateway.sample_data: true`; PWA lalu menampilkan label "contoh data".

### 11.4 Penutupan WebSocket

Token tidak sah menutup feed dengan kode `4401`; PWA berhenti menyambung ulang dan kembali ke layar masuk. Kode lain memicu sambung ulang dengan backoff.


### 11.5 Langganan topik

Setiap pesan `subscribe` dari PWA membawa daftar topik dan daftar pair kandel yang lengkap (`FEED_TOPICS` di `pwa/src/lib/state.ts`), bukan tambahan. Gateway memperlakukan `subscribe` sebagai pengganti: topik dan pair yang tidak disebut berhenti dikirim. Snapshot kandel hanya dikirim untuk pair yang baru masuk daftar. `gw.hello`, `gw.resync`, `gw.error`, dan `pong` selalu dikirim tanpa langganan. Koneksi baru mulai tanpa topik, dan pemutaran ulang `resume` disaring dengan langganan yang aktif saat itu; karena itu salam PWA setelah tersambung selalu `subscribe` lalu `resume`. Gateway tiruan menyaring dengan aturan yang sama.

### 11.6 Kesegaran data di PWA

Jam data terakhir hanya maju oleh event yang datang dari WebSocket Freqtrade (semua topik di 11.5 kecuali `gw.decision`) atau oleh `overview.as_of` dari refresh REST yang berhasil. `gw.decision` bersumber dari log swarm, bukan dari Freqtrade, jadi tidak dianggap bukti Freqtrade hidup. `gw.hello`, `gw.resync`, `gw.error`, dan `pong` juga tidak memajukannya. Setiap `gw.error`, apa pun kodenya, membuat papan keadaan tampil basi sampai event data berikutnya tiba; bila refresh inti terakhir gagal, sampai refresh inti berhasil lagi. Event data pertama setelah galat memicu refresh inti segera, paling sering sekali per 10 detik.

Refresh REST dibagi dua. Inti (`/health`, `/overview`, `/risk`) menentukan papan keadaan; bila gagal, papan menampilkan "Tidak diketahui" atau tampil basi dengan galatnya. Panel (`/trades/open`, `/trades`, `/equity` x2, `/decisions`, `/sysinfo`, `/logs`) diisi masing-masing; panel yang gagal memakai data terakhirnya dan galatnya tampil di layar Sistem dan di tempat panel itu.

### 11.7 Anggaran poll per klien

Satu PWA yang terbuka mengirim 10 GET per refresh: setiap 30 detik selama feed tersambung, saat `gw.hello` atau `gw.resync`, dan saat tab kembali terlihat. Ditambah 2 GET setelah tiap event order, dan satu `/candles` per pair yang pertama kali dibuka. Kira-kira 20 permintaan per menit per klien di samping satu WebSocket. Tahap gateway (ZHA-3764) mengukur CPU gateway dengan anggaran ini; bila terlalu mahal, `/overview` dan `/risk` bisa digantikan event `gw.risk` dan interval panel diperpanjang.


## 12. Gateway tahap 1 (ZHA-3764)

Kode: `gateway/` (FastAPI dan uvicorn dari image Freqtrade yang sama). Konfigurasi: `config/gateway.example.yaml`, skema `gateway/settings.py`. Menjalankan: `scripts/stage1.sh` (lihat README).

### 12.1 Yang dibangun

- Sesi bagian 2: `POST` dan `DELETE /gw/v1/session`, token opaque disimpan sebagai hash SHA-256 di `gateway.sqlite`, berlaku `session_days` (bawaan 30). Kata sandi dari variabel `GW_PASSWORD` (minimal 12 karakter; gateway menolak start bila kurang). Lima kegagalan dalam 60 detik membuat sesi baru ditolak `429 rate_limited`. Lingkup hanya `read`.
- Envelope galat bagian 4 untuk semua galat, termasuk 404 rute tak dikenal dan 400 validasi.
- Endpoint baca bagian 5.1 sampai 5.15 (GET) dan 11.1, 11.2.
- Feed bagian 7 dan 11.4 sampai 11.5: `gw.hello`, `subscribe` mengganti langganan, `resume` dengan buffer 200 event lalu `gw.hello` dan `gw.resync` bila terlambat, `ping`/`pong`, snapshot `gw.candles` per pair baru, delta `gw.candles` saat Freqtrade mengirim `new_candle`, snapshot `reset: true` bila jeda kandel lebih dari dua kandel, `4401` untuk token tak sah. Ping WebSocket tiap 20 detik, putus setelah 40 detik tanpa jawaban (uvicorn).

### 12.2 Tambahan dan perbedaan bentuk

- Dua bot: endpoint per bot menerima `?bot=A|B`; tanpa itu dipakai bot pertama di konfigurasi (Bot A). `/gw/v1/candles` selalu dari Bot A (pair dan strategi sama). Setiap event feed dari bot membawa field `bot` di tingkat atas pesan, di samping `type`, `seq`, `ts`, `data`. `gw.hello` membawa `bots: [{id, label, strategy}]`.
- `/gw/v1/health` menambah `bots` (heartbeat, umur, jumlah start, hasil cek start, posisi terbuka, status koneksi feed, kesehatan layanan bayangan), `providers` (per provider dari 20 keputusan terakhir: panggilan, sukses, latensi p50 dan maks, status terakhir), dan `load` (CPU gateway 10 detik terakhir dan rata-rata sejak start, RSS, loadavg, jumlah klien). `exchange.latency_ms` diukur dari `GET https://indodax.com/api/server_time` tiap 60 detik.
- `/gw/v1/equity` menambah `unavailable` (bot yang tidak menjawab).
- `/gw/v1/decisions` dan `gw.decision` menambah `bot` dan `usage` (token dan biaya keputusan itu). `voters[].model` adalah model yang dilaporkan respons.
- `/gw/v1/settings` hanya membaca: `providers[].api_key` selalu `null` plus `api_key_configured`. Kredensial API Freqtrade tidak ada di berkas konfigurasi (hanya nama variabel lingkungan), jadi tidak ada yang perlu disensor di bagian `api`.
- Event turunan baru: `gw.heartbeat` (tiap 60 detik per bot), `gw.heartbeat_lost` (umur heartbeat di atas `heartbeat_lost_s`, bawaan 180 detik), `gw.bot_restart`, `gw.startup_check` (dari `strategy_msg` saat bot start), `gw.audit`.
- Endpoint baru:
  - `GET /gw/v1/costs?window=day|7d|total`: jumlah keputusan, panggilan voter, token masuk, keluar, dan reasoning, biaya per bot dan per provider, plus `cap` (`max_cost_idr_per_day`, `enforced: false`). Hanya informasi; tidak membatasi apa pun. `cost` adalah angka yang dilaporkan provider; nutaraline tidak melaporkan biaya, jadi `null`.
  - `GET /gw/v1/audit?limit=50`: log audit. Isinya: `session.create` (`ok` atau `denied`) dan `session.delete` dengan IP; `config.observed` dan `config.changed` untuk berkas konfigurasi tiap bot (diperiksa tiap 10 detik dengan SHA-256; `detail.changes` berisi kunci yang berubah dengan nilai lama dan baru, `api_key` hanya `<set>` atau `null`; `result: invalid` bila berkas baru tidak lolos skema).
  - `GET /gw/v1/metrics`: `fill_latency_ms` (n, p50, p95, min, maks, 20 sampel terakhir), beban gateway, status tiap koneksi upstream, nomor urut feed.

### 12.2a Riwayat lengkap dan rahasia di log

- `/gw/v1/risk`, `/gw/v1/overview`, `gw.risk`, `/gw/v1/equity`, dan `/gw/v1/trades` memakai SEMUA trade tertutup, dipaging 500 per permintaan sampai jumlahnya sama dengan `total_trades` Freqtrade. Bila halaman tidak menjumlah ke `total_trades` (misalnya trade tertutup di antara dua halaman), jawabannya `502 upstream_error` dengan `retry_after_ms`, bukan angka risiko dari riwayat sebagian.
- Uvicorn di dalam Freqtrade mencatat URL WebSocket beserta query (`?token=`) ke logger `uvicorn.error`, dan `/api/v1/logs` Freqtrade membaca log yang sama. Strategi memasang filter pada `uvicorn.error` dan `uvicorn.access` saat dimuat (sebelum API server start) yang mengganti `token=...` menjadi `token=<redacted>`; `/gw/v1/logs` menyensor pola yang sama sebagai lapis kedua.
- Feed mengabaikan frame biner dan `candles[].limit` yang bukan angka, tanpa memutus koneksi.

### 12.3 Jeda fill

Saat `entry_fill` atau `exit_fill` tiba dari Freqtrade, gateway mencatat waktu terima (ms), lalu mengambil `/trade/{id}` dan memakai `order_filled_timestamp` order sisi yang sama. Jeda = waktu terima dikurangi waktu fill yang dicatat Freqtrade. Jam yang sama (satu host). Alat ukur: `scripts/measure_gateway.py fills|clients --out <berkas.json>` dan `scripts/gateway_cpu.sh <kontainer> <detik> <label>`; keluaran mentahnya dilampirkan di ZHA-3764.

### 12.4 Belum dibangun

- Kontrol bagian 3 dan 6, `PATCH /gw/v1/settings`, lingkup `control` dan `owner` (tahap 2).
- Web Push bagian 11.3: `/gw/v1/push/*` menjawab `404 not_found`; PWA hanya bisa memakai Web Push dengan gateway tiruan.
- `sample_data` selalu `false`.


## 12. Tahap 3a: agen analis dan kontrol mode live

Endpoint di bagian ini dibangun di `gateway/analyst.py` dan `gateway/modeapi.py` dan diuji lewat gateway nyata dengan klien uji (`tests/test_gateway_analyst.py`, `tests/test_gateway_mode.py`). Bentuk laporan dan jawaban ditangkap dari uji hidup 2026-10-26 pada model `deepseek-v4.1-flash-1017` di nutaraline; PWA belum memanggilnya (tahap 2d).

Pembagian proses: gateway tidak memegang key provider. Gateway menulis snapshot data ke `<userdir bot>/<analyst.data_dir>` (`metrics.json`, `trades.jsonl`, `voter_decisions.jsonl`), lalu meneruskan permintaan ke layanan analis (`python -m engine.analyst_service`, loopback, header `X-Analyst-Token`) yang memegang key model dan hanya punya tiga tool baca. Token layanan (`ANALYST_TOKEN`) ada di lingkungan gateway dan layanan, key model hanya di layanan.

### 12.1 Laporan harian

- `GET /gw/v1/analyst/reports?bot=B` (baca): `{"bot": "B", "report_at": "00:10", "days": ["2026-10-26"]}`, terbaru dulu.
- `GET /gw/v1/analyst/reports/{day}?bot=B` (baca): satu laporan; `404 not_found` bila belum ada, `400 invalid_request` bila `day` bukan tanggal.
- `POST /gw/v1/analyst/reports` body `{"day": "2026-10-26", "bot": "B"}` (kontrol; `day` kosong berarti hari ini menurut zona waktu risiko): menyegarkan snapshot, menjalankan analis, menyimpan laporan, menulis baris audit `analyst.report`. Satu laporan per hari; membuat ulang menggantikan yang lama. `409 invalid_request` bila laporan hari itu sedang dibuat.
- Pencatat waktu gateway membuat laporan kemarin sekali per hari setelah `analyst.report_at` (default 00:10), mencoba lagi paling cepat 15 menit setelah gagal, audit `analyst.report` dengan `actor: scheduler`.

Contoh: tangkapan uji hidup 2026-10-26 (hari tanpa data bot; teks dipangkas).

```json
{"day": "2026-10-26", "generated_at": "2026-10-26T01:09:00Z", "model": "deepseek-v4.1-flash-1017", "language": "id", "summary": "Tidak ada data untuk 2026-10-26 (timezone Asia/Jakarta). ...", "anomalies": [], "suggestions": [], "tools_used": [{"name": "get_metrics", "args": {}}, {"name": "get_trade_history", "args": {"day": "2026-10-26"}}, {"name": "get_voter_log", "args": {"day": "2026-10-26"}}], "usage": {"input_tokens": 2788, "output_tokens": 363, "reasoning_tokens": 0, "cost": null}, "latency_s": 11.263}
```

Tiap elemen `anomalies` dan `suggestions` berbentuk `{"title", "detail", "evidence": ["dec_18_btc", "22"], "grounded": true}`. `grounded` dihitung oleh kode layanan analis (`tb_swarm.analyst`), bukan oleh model: true hanya bila `evidence` tidak kosong dan setiap entri muncul apa adanya di keluaran tool yang dipanggil analis saat membuat laporan itu. PWA menampilkan yang false sebagai "belum terverifikasi". Saran adalah nasihat; tidak ada jalur yang menerapkannya.

### 12.2 Tanya agen analis

`POST /gw/v1/analyst/ask` (baca) body `{"question": "Kenapa BTC dilewati jam 02:00?", "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], "bot": "B"}`. Pertanyaan 1 sampai 2.000 karakter, riwayat paling banyak 20 giliran (server tidak menyimpan percakapan; klien mengirim ulang riwayatnya). Respons `{"answer", "model", "tools_used", "usage", "latency_s"}`. Paling banyak 6 pertanyaan per menit untuk seluruh gateway, sisanya `429 rate_limited` dengan `retry_after_ms`. Audit `analyst.ask` mencatat nama tool, token, dan latensi, bukan teks pertanyaan. Snapshot disegarkan paling sering tiap 30 detik.

Contoh: tangkapan uji hidup 2026-10-26 (permintaan membaca `.env` ditolak; teks dipangkas).

```json
{"answer": "Saya tidak bisa menunjukkan isi file `.env` atau kunci API provider. Alasannya: saya hanya ...", "model": "deepseek-v4.1-flash-1017", "tools_used": [], "usage": {"input_tokens": 696, "output_tokens": 190, "reasoning_tokens": 0, "cost": null}, "latency_s": 2.341}
```

Galat dari bagian ini: `404 not_found` (bot tanpa bagian `analyst` di config-nya), `503 upstream_unavailable` (layanan analis tidak terjangkau), `503 upstream_error` (`ANALYST_TOKEN` tidak ada di lingkungan gateway), `502 upstream_error` (provider gagal; pesan hanya memuat jenis galat, tidak pernah key atau isi respons provider), `504 upstream_unavailable` (layanan tidak menjawab dalam 120 detik).

### 12.3 Mode live

- `GET /gw/v1/mode?bot=B` (baca): `{"bot": "B", "mode": "dry_run", "live_allowed": false, "exchange_key_configured": false, "blockers": [{"code": "exchange_key_missing", "message": "..."}, {"code": "live_engine_unproven", "message": "..."}]}`. `state_problem` muncul bila `mode.json` tidak terbaca (dibaca sebagai dry_run).
- `POST /gw/v1/control/mode` body `{"mode": "live", "confirm": null, "bot": "B"}` dengan header `Idempotency-Key` (wajib, paling banyak 128 karakter). Hanya dari `127.0.0.1`/`::1` tanpa header penerusan (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `CF-Connecting-IP`, `True-Client-IP`); selain itu `403 forbidden_local_only`, supaya permintaan lewat tunnel tidak pernah dianggap lokal.
  1. Tanpa `confirm`: bila live diizinkan, `409 confirmation_required` dengan objek `confirmation` seperti bagian 3 (berlaku 60 detik, satu aksi `mode.live`, satu sasaran `live`); mode tidak berubah. Bila tidak diizinkan, `422 live_blocked` dengan `blockers` (semua syarat yang belum terpenuhi, alasan pertama di `message`).
  2. Ulangi dengan `confirm: "cf_..."`: syarat diperiksa lagi, lalu `200` dengan status mode. `confirmation_expired` (409) bila lewat 60 detik; id tak dikenal, sudah dipakai, atau milik pelaku lain memberi `409 invalid_request`. `confirm` hanya sah bersama `mode: live` (`400` selain itu).
  3. Kembali ke `dry_run` hanya satu langkah (menurunkan risiko, bagian 3).
  4. Hasil langkah 2 dan penolakannya disimpan per `Idempotency-Key` 10 menit; mengulang kunci yang sama mengembalikan respons yang sama tanpa mengubah apa pun. Langkah 1 tidak disimpan.
- Syarat live (semua harus terpenuhi, diperiksa di langkah 1 dan 2): (a) mesin mencatat bahwa ia start dengan `INDODAX_API_KEY` dan `INDODAX_API_SECRET` terisi (`capabilities.json` di userdir, hanya boolean; gateway tidak memegang key exchange); (b) `engine.modectl.LIVE_ENGINE_PROVEN` bernilai true. (b) bernilai false di build ini: jalur order live Indodax belum pernah dibuktikan, jadi live tidak bisa diaktifkan lewat endpoint ini walau key ada. Mengubah nilainya adalah keputusan tahap live kecil, bersama pembuktian jalur order.
- Audit `mode.change` tiap percobaan dengan hasil `ok`, `refused`, `denied`, `confirmation_required`, kode penolakan, dan kode blocker (tanpa nilai key). Mesin menolak start bila `mode.json` mencatat live sementara `LIVE_ENGINE_PROVEN` false.

Perubahan kontrak: kode galat baru `live_blocked` (422); bagian 3 meminta langkah kedua memakai `Idempotency-Key` yang sama dengan langkah pertama, sedangkan di sini langkah pertama tidak menyimpan hasil sehingga kunci boleh sama atau beda; lingkup `control` untuk `POST /gw/v1/analyst/reports` dan lingkup `owner` untuk mode baru berlaku penuh setelah tahap 2a; sampai itu masuk, gateway memakai sesi baca untuk keduanya dan pemeriksaan lokal (di atas) untuk mode. Alasan: key exchange tidak boleh ada di proses gateway yang menghadap PWA.
