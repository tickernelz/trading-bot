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
- Token punya dua lingkup: `read` (semua GET) dan `control` (GET plus semua POST/DELETE kontrol). `control` hanya diberikan bila login datang langsung dari loopback: alamat klien `127.0.0.1` atau `::1` dan tanpa header forward (`Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Server`, `X-Original-Forwarded-For`, `X-Real-IP`, `Via`, `CDN-Loop`, `CF-Connecting-IP`, `CF-Ray`, `CF-Visitor`, `CF-IPCountry`, `True-Client-IP`), dengan header `Host` berupa `127.0.0.1`, `localhost`, atau `[::1]`, dan `Origin` (bila ada) yang juga loopback; selain itu `read`. Satu definisi, `control.is_local`, dipakai login, rute kontrol 2a, dan tulis konfigurasi 2b (ZHA-3775). Respons login menambah `"scope": "control" | "read"`. Lingkup `owner` dilebur ke `control` (ZHA-3774): issue tahap 2a meminta kontrol hanya dari localhost, jadi `control` sudah seketat `owner`, dan satu lingkup lebih sedikit berarti satu cabang otorisasi lebih sedikit.
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

Aturan yang dibangun di ZHA-3774 (`gateway/control.py`, `Gateway.execute` di `gateway/app.py`):

- Token konfirmasi sekali pakai dan terikat pada nama aksi, bot, parameter aksi (path, query, dan body tanpa `confirm`), dan sesi yang memintanya. Token tak dikenal, sudah dipakai, untuk aksi atau parameter lain, atau dari sesi lain: `409 confirmation_invalid`. Lewat 60 detik: `409 confirmation_expired`. Freqtrade tidak dipanggil pada semua penolakan itu. Token disimpan di memori gateway, jadi restart gateway membatalkan semua token yang belum dipakai.
- `Idempotency-Key` wajib di semua endpoint kontrol (8-128 karakter `[A-Za-z0-9_-]`); tanpa itu `400 invalid_request`. Hasil setiap eksekusi yang melewati pemeriksaan gateway (lokal, konfirmasi, pemeriksaan `trades`) disimpan 24 jam per kunci, sukses maupun galat, termasuk `503 upstream_unavailable` saat Freqtrade tidak terjangkau. Request ulang dengan kunci dan parameter yang sama mengembalikan hasil tersimpan tanpa memanggil Freqtrade lagi (audit `replayed`); kunci yang sama untuk request lain `409 invalid_request`. Langkah 1 (`confirmation_required`) tidak disimpan, jadi langkah 2 boleh memakai kunci yang sama. Mencoba lagi aksi yang gagal butuh kunci baru dan, untuk aksi berisiko, konfirmasi baru.
- Perubahan konfigurasi: `risky_changes(old, new)` di `gateway/control.py` mengembalikan kunci yang butuh dua langkah: kenaikan `risk.max_daily_loss_pct`, `risk.max_total_drawdown_pct`, `risk.risk_per_trade_pct`, `risk.max_open_trades`, perubahan `mode` ke arah mana pun, dan `api.force_entry` dari `false` ke `true`. Daftar kosong berarti perubahan berlaku langsung (termasuk menurunkan batas). `PATCH /gw/v1/settings` (bagian 15.2) memakai fungsi ini bersama `Confirmations`, `is_local`, dan penyimpanan idempotensi yang sama.

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

Kode yang dipakai: `unauthorized`, `forbidden_local_only`, `confirmation_required`, `confirmation_expired`, `confirmation_invalid` (ZHA-3774: token tak dikenal, sudah dipakai, atau untuk aksi, parameter, atau sesi lain; dipisah dari `confirmation_expired` supaya PWA bisa membedakan waktu habis dari token yang salah), `invalid_request`, `upstream_error`, `upstream_unavailable`, `risk_limit_breached`, `not_found`, `rate_limited`.

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

Baca: konfigurasi aktif dengan rahasia dipangkas (`api_key`, `api_key_env`, `password`, `jwt_secret_key`, `ws_token` selalu `null` plus penanda `configured: true|false`). Tulis: `PATCH` dengan bentuk dan aturan di bagian 15.2 (hanya dari loopback, validasi skema `engine/settings.py`, `409 risk_limit_breached`, `restart_required`).

## 6. Endpoint kontrol

Semua butuh `control` dari loopback langsung (bagian 2; selain itu `403 forbidden_local_only`), header `Idempotency-Key` (bagian 3), dan menerima `?bot=A|B` (bawaan bot pertama). Semua menulis satu baris audit `{actor, ip, action, targets, idempotency_key, result, detail}` dan mengirimnya sebagai event `gw.audit` (bagian 14). Body tanpa field lain selain yang disebut; field asing `400 invalid_request`. Respons `200` adalah respons Freqtrade apa adanya.

| Endpoint | Diteruskan ke | Konfirmasi | Efek |
| --- | --- | --- | --- |
| `POST /gw/v1/control/pause` | `POST /pause` | tidak | Berhenti memproses entry baru, trade terbuka tetap dikelola |
| `POST /gw/v1/control/resume` | `POST /start` | tidak | Kembali memproses |
| `POST /gw/v1/control/stop-entry` | `POST /stopentry` | tidak | Kill switch: tidak ada entry baru sampai `resume`; gateway mengirim ulang setelah bot restart (bagian 14) |
| `POST /gw/v1/control/stop` | `POST /stop` | ya | Bot berhenti total, trade terbuka tidak dikelola |
| `POST /gw/v1/control/reload-config` | `POST /reload_config` | tidak | Muat ulang config Freqtrade |
| `POST /gw/v1/trades` | `POST /forceenter` | ya | Entry paksa; ditolak `risk_limit_breached` bila `entries_allowed` false |
| `POST /gw/v1/trades/{id}/exit` | `POST /forceexit` body `{"tradeid": "<id>"}` | ya | Exit paksa satu trade |
| `POST /gw/v1/trades/exit-all` | `POST /forceexit` body `{"tradeid": "all"}` | ya | Exit paksa semua trade terbuka (ditambah ZHA-3774: issue meminta force exit semua posisi; Freqtrade menerimanya lewat `tradeid: "all"`) |
| `POST /gw/v1/locks` body `{"pair", "until", "side", "reason"}` | `POST /locks` (array satu kunci) | tidak | Kunci pasangan sampai `until` (ISO-8601 dengan zona, harus di masa depan); `side` bawaan `*` |
| `DELETE /gw/v1/locks/{lock_id}` | `DELETE /locks/{lockid}` | ya | Buka satu kunci |
| `POST /gw/v1/locks/delete` | `POST /locks/delete` body `{"pair": "BTC/IDR"}` atau `{"lockid": 1}` | ya | Buka kunci per pasangan |
| `POST /gw/v1/blacklist` body `{"pairs": ["SOL/IDR"]}` | `POST /blacklist` body `{"blacklist": [...]}` | tidak | Tambah pasangan ke blacklist |
| `DELETE /gw/v1/blacklist?pairs=BTC/IDR` | `DELETE /blacklist?pairs_to_delete=BTC/IDR` | ya | Hapus dari blacklist |

Di Freqtrade 2026.9 `/pause`, `/stopentry`, dan `/stopbuy` adalah satu handler (`api_trading.py`, `RPC._rpc_pause`, state `PAUSED`), jadi `pause` dan `stop-entry` berefek sama; keduanya dipertahankan karena PWA sudah memakai dua nama itu. Pada endpoint tanpa body wajib, `confirm` dikirim sebagai body JSON `{"confirm": "..."}`, termasuk pada `DELETE`.

Contoh `POST /gw/v1/trades`:

Contoh: rancangan, gateway belum ada; nilai mengikuti tangkapan Freqtrade bila ada.

```json
{"pair": "BTC/IDR", "side": "long", "stake_amount": null, "confirm": "cf_01J9Z6H0YV"}
```

`stake_amount: null` berarti mesin menghitung lewat `custom_stake_amount` (0,5% risiko per trade). Respons `200` berisi objek trade hasil bagian 5.3; `422` bila pasangan tidak ada di whitelist. Pemeriksaan sebelum token konfirmasi diberikan dan diulang di langkah 2: `409 invalid_request` bila `api.force_entry` di konfigurasi bot `false` (bawaan), `422` bila di luar whitelist, `409 risk_limit_breached` bila `/gw/v1/risk` memberi `entries_allowed: false`. Bila Freqtrade menjawab `200` tanpa `trade_id` (misalnya `{"status": "Error entering long trade ..."}`), gateway menjawab `502 upstream_error` dengan teks status itu.

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
- Satu permintaan OHLCV Indodax dengan rentang panjang hanya mengembalikan candle terbaru (1h: ±649 candle, ≈27 hari; 1d: 1000 candle). Ini batas satu permintaan, bukan batas riwayat: per jendela 500 candle, 1h tersedia minimal sejak 2023-10-01 (tahap 2e, docs/stage2-backtest.md). Kontrak grafik tidak berubah: grafik jangka panjang di PWA tetap memakai 1d, karena gateway belum punya endpoint riwayat berjendela.
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

## 12. Tambahan nice-to-have N2 (ZHA-3781)

Semua isi bagian ini `rancangan`: dibangun di PWA dan gateway tiruan; gateway nyata (ZHA-3764) belum ada di main saat ditulis. Pengambil data berita dan Fear and Greed sudah ada dan dites (`engine/news.py`, `tests/test_news.py`); gateway nyata membuat satu `Feeds(settings.data.news_rss, <aset pair whitelist>, settings.data.fear_greed)` dan memanggilnya di dua rute di bawah lewat `await asyncio.to_thread(feeds.news, asset, limit)` dan `await asyncio.to_thread(feeds.sentiment, days)`. `Feeds` memakai urllib yang memblok (timeout 15 detik per sumber, berurutan, satu kunci), jadi memanggilnya langsung di handler async bisa menahan event loop sampai sekitar 30 detik saat cache dingin atau kedaluwarsa.

Alasan perubahan kontrak: mesin waktu butuh riwayat keputusan per pair yang lebih panjang dari 20 baris terakhir, dan lapisan berita butuh data yang diambil di PC (PWA tidak boleh memanggil pihak ketiga langsung, bagian 1).

### 12.1 `GET /gw/v1/decisions?pair=BTC/IDR&before=<ISO>&limit=200`

Menambah dua parameter opsional ke 11.2. `pair` menyaring satu pair; `before` mengembalikan keputusan dengan `candle` sebelum waktu itu (halaman berikutnya). `limit` 1 sampai 500, bawaan 20. Urutan tetap terbaru dulu. Tanpa parameter baru, bentuk dan isi sama dengan 11.2. Mesin waktu di layar Grafik memanggil `pair` + `limit=200` hanya saat dibuka, lalu menambah `gw.decision` baru ke riwayat yang sudah dimuat; tidak ada poll tambahan.

### 12.2 `GET /gw/v1/news?pair=BTC/IDR&limit=50`

Judul RSS CoinDesk dan Cointelegraph yang menyebut aset dasar pair (kata utuh, tanpa beda huruf besar: simbol dan nama, misalnya BTC atau Bitcoin). Tanpa `pair`, semua judul. `limit` 1 sampai 100, bawaan 50; nilai di luar rentang dipotong ke batasnya. Deskripsi RSS tidak dikirim karena berisi HTML pihak ketiga; tautan hanya `http` atau `https`. Gateway mengambil umpan hanya saat ada permintaan dan menyimpannya 15 menit; bila satu sumber gagal, item terakhirnya tetap dipakai dan `ok: false` beserta galatnya dikirim. `enabled: false` bila `data.news_rss` kosong.

```json
{"as_of": "2026-10-26T04:46:40Z", "enabled": true, "sources": [{"id": "coindesk", "name": "CoinDesk", "url": "https://www.coindesk.com/", "feed": "https://www.coindesk.com/arc/outboundfeeds/rss/", "ok": true, "error": null, "fetched_at": "2026-10-26T04:46:40Z"}], "items": [{"id": "n_3f2a9c0d1e4b5a67", "source": "coindesk", "title": "Bitcoin slips below $60K", "url": "https://www.coindesk.com/markets/btc-slips", "published": "2026-10-25T15:00:00Z", "assets": ["BTC"]}]}
```

### 12.3 `GET /gw/v1/sentiment?days=30`

Fear and Greed Index harian dari alternative.me (`https://api.alternative.me/fng/`), terlama dulu, 1 sampai 365 hari. Disimpan 1 jam. `source` wajib ditampilkan sebagai atribusi (syarat alternative.me). `classification` adalah teks asli alternative.me (`Extreme Fear`, `Fear`, `Neutral`, `Greed`, `Extreme Greed`); PWA menerjemahkannya. `enabled: false` dan `points: []` bila `data.fear_greed` false.

```json
{"as_of": "2026-10-26T04:46:40Z", "enabled": true, "source": {"name": "Fear & Greed Index", "provider": "alternative.me", "url": "https://alternative.me/crypto/fear-and-greed-index/", "ok": true, "error": null, "fetched_at": "2026-10-26T04:46:40Z"}, "points": [{"date": "2026-10-26", "value": 50, "classification": "Neutral"}]}
```

### 12.4 Anggaran poll

Berita, sentimen, dan riwayat keputusan tidak ikut refresh 30 detik (11.7). PWA memintanya saat lapisan atau mesin waktu dinyalakan, saat pair diganti, dan saat layar Grafik dibuka lagi. Berita (per pair) dan sentimen tidak diminta ulang dalam 15 menit; riwayat keputusan diminta sekali setiap mesin waktu dibuka.

## 12. Gateway tahap 1 (ZHA-3764)

Kode: `gateway/` (FastAPI dan uvicorn dari image Freqtrade yang sama). Konfigurasi: `config/gateway.example.yaml`, skema `gateway/settings.py`. Menjalankan: `scripts/stage1.sh` (lihat README).

### 12.1 Yang dibangun

- Sesi bagian 2: `POST` dan `DELETE /gw/v1/session`, token opaque disimpan sebagai hash SHA-256 di `gateway.sqlite`, berlaku `session_days` (bawaan 30). Kata sandi dari variabel `GW_PASSWORD` (minimal 12 karakter; gateway menolak start bila kurang). Lima kegagalan dalam 60 detik membuat sesi baru ditolak `429 rate_limited`. Lingkup hanya `read` (ZHA-3774 menambah `control`, bagian 2).
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
- Uvicorn di dalam Freqtrade mencatat URL WebSocket beserta query (`?token=`) ke logger `uvicorn.error`, dan `/api/v1/logs` Freqtrade membaca log yang sama. Strategi memasang filter pada `uvicorn.error` dan `uvicorn.access` saat dimuat (sebelum API server start) yang mengganti `token=...` menjadi `token=<redacted>`; `/gw/v1/logs` menyensor dengan `gateway/redact.py` sebagai lapis kedua (`token=[redacted]`, nilai key provider yang dikenal gateway, `Authorization`, `x-api-key`, pola `sk-`).
- Feed mengabaikan frame biner dan `candles[].limit` yang bukan angka, tanpa memutus koneksi.

### 12.3 Jeda fill

Saat `entry_fill` atau `exit_fill` tiba dari Freqtrade, gateway mencatat waktu terima (ms), lalu mengambil `/trade/{id}` dan memakai `order_filled_timestamp` order sisi yang sama. Jeda = waktu terima dikurangi waktu fill yang dicatat Freqtrade. Jam yang sama (satu host). Alat ukur: `scripts/measure_gateway.py fills|clients --out <berkas.json>` dan `scripts/gateway_cpu.sh <kontainer> <detik> <label>`; keluaran mentahnya dilampirkan di ZHA-3764.

### 12.4 Belum dibangun

- Kontrol bagian 3 dan 6 dan lingkup `control` dibangun di ZHA-3774 (bagian 14). `PATCH /gw/v1/settings`, provider, key, voter: ZHA-3775 (bagian 15).
- Web Push bagian 11.3: `/gw/v1/push/*` menjawab `404 not_found`; PWA hanya bisa memakai Web Push dengan gateway tiruan.
- `sample_data` selalu `false`.

## 13. Analitik N1 (ZHA-3780)

Semua GET dan `POST /replay` hanya membaca dan butuh sesi gateway apa pun (lingkup read cukup), seperti bagian 5. Tiga aksi mengubah sesuatu dan mengikuti bagian 1, 2, dan 6: `POST /gw/v1/analytics/scoreboard/apply` (menulis `enabled: false` ke config), `POST /gw/v1/analytics/backtest` dan `DELETE /gw/v1/analytics/backtest` (memulai dan menghentikan job di instans webserver). Ketiganya hanya diterima dari loopback dengan sesi lingkup control; selain itu `403 forbidden_local_only` dan satu baris audit `forbidden`. Setiap pemanggilan lain menulis tepat satu baris audit dengan hasil (`ok` atau `failed`), termasuk apply yang tidak mengubah apa pun. Galat memakai envelope bagian 4, ditambah kode `invalid_config` (500) bila config bot gagal divalidasi. Kode ada di `analytics/` dan dipasang ke aplikasi gateway lewat `analytics.routes.install(app, context, reader)`; `context` menyediakan: `source(bot)` (config, basis data keputusan dan trade); `trades(bot)` (SEMUA trade tertutup ditambah posisi terbuka, tanpa batas jumlah; gateway memagina seperti `/gw/v1/risk` dan gagal tertutup bila jumlahnya tidak cocok, karena ekuitas, puncak, dan pajak tahunan salah bila riwayat terpotong); `analysis()` (klien webserver atau `None`); `can_control(request)` (loopback langsung dan sesi lingkup control, fungsi yang sama dengan penjaga bagian 6); dan `audit(action, result, request=, targets=, detail=)` yang menulis baris bagian 6 (`actor` dan `ip` diambil gateway dari `request`, `idempotency_key` dari header; `request=None` berarti aktor `gateway`, dipakai loop penonaktifan otomatis). Nama aksi: `analytics.scoreboard.apply`, `analytics.scoreboard.auto_disable`, `analytics.backtest.start`, `analytics.backtest.stop`.

Status: rancangan untuk gateway. Modul dan rute lulus tes dan dijalankan terhadap Freqtrade 2026.9 nyata (lihat 13.2 dan 13.6), tetapi belum dipasang ke gateway: `gateway/` tidak memanggil `analytics.routes.install`, jadi rute `/gw/v1/analytics/*` belum ada di gateway yang berjalan. Pemasangan dikerjakan di ZHA-3798.

Parameter `bot` (huruf bot, default bot pertama) berlaku di semua endpoint kecuali yang memakai instans webserver (13.2 dan 13.6), yang hanya memakai `bot` untuk membaca config.

### 13.1 Pratinjau what-if

`GET /gw/v1/analytics/limits/whatif?max_daily_loss_pct=2.0` menerima salah satu atau beberapa dari `max_daily_loss_pct`, `max_total_drawdown_pct`, `risk_per_trade_pct`, `max_open_trades`. Respons membandingkan config sekarang (`current`) dengan usulan (`proposed`) pada trade yang sama: batas dalam rupiah (`limits_idr`), apakah keadaan sekarang melanggar batas itu (`now`), dan keadaan bila semua stop terbuka terisi (`all_stops_hit`). Usulan yang melanggar urutan batas (`risk_per_trade_pct` <= `max_daily_loss_pct` <= `max_total_drawdown_pct`) ditolak `422 invalid_request`; field lain ditolak. Tidak ada yang ditulis ke config.

Contoh: bentuk dari tes dengan satu posisi BTC/IDR terbuka dan rugi Rp 12.000 hari ini; bukan data bot.

```json
{"equity": 1985303.0, "open_positions": 1, "delta_idr": {"max_daily_loss_idr": 20000.0, "daily_floor_idr": -20000.0, "max_total_drawdown_idr": 0.0, "risk_per_trade_idr": 0.0, "trades_to_daily_limit": 2.0}, "changed": ["max_daily_loss_pct"]}
```

`proposed.limits_idr` pada contoh itu: `{"max_daily_loss_idr": 40000.0, "daily_floor_idr": 1960000.0, "max_total_drawdown_idr": 200000.0, "drawdown_floor_idr": 1800000.0, "risk_per_trade_idr": 9926.5, "max_open_trades": 3, "max_open_risk_idr": 29779.5, "trades_to_daily_limit": 4.0}`; `proposed.all_stops_hit`: `{"additional_loss_idr": 7485.0, "positions_without_stop": 0, "daily_loss_pct": 1.109, "drawdown_pct": 1.109, "breaches": []}`. Posisi tanpa `stop_loss_abs` dihitung di `positions_without_stop`, bukan ditebak.

`POST /gw/v1/analytics/replay` memutar ulang jawaban voter yang tercatat tanpa panggilan LLM baru. Body: `{"bot": "B", "min_voters_answered": 3, "max_spread": 0.25, "exclude_voters": ["v4"], "limit": 500}`; semua opsional. `max_spread` yang tidak ditulis memakai nilai config, `"max_spread": null` berarti tanpa batas sebaran. Aturan kuorum, seri, dan sebaran memakai fungsi yang sama dengan runner (`tb_swarm.outcome.settle`). Respons: `recorded_verdicts` dan `replayed_verdicts`, `transitions` (misalnya `"izinkan->lewati": 3`), sampai 50 keputusan yang berubah (`changed`), dan `trade_groups`: jumlah trade tertutup dan total `profit_abs` per pasangan sisi tercatat dan sisi ulang (`take->skip` dan seterusnya). Angka itu data, bukan kesimpulan untung atau rugi. Keputusan tanpa catatan voter (dibatalkan saat restart, swarm mati) masuk `not_replayable`.

### 13.2 Sinyal strategi di grafik

`GET /gw/v1/analytics/signals?pair=BTC/IDR&from=2026-10-10&to=2026-10-25`. Terverifikasi di vendor dan di instans nyata: `/pair_history` dan `/backtest` Freqtrade 2026.9 dipasang dengan `is_webserver_mode` (`webserver.py`), jadi bot mode `trade` menjawab `503 Bot is not in the correct state`; keduanya butuh satu instans `webserver` terpisah dengan data OHLCV terunduh (`download-data`) di userdir-nya. Jendela maksimum 60 hari; pasangan harus ada di `exchange.pairs`.

Respons: `candles` (`[ts, open, high, low, close]`, `ts` ISO UTC) dan `signals` (`{"ts", "kind": "enter" | "exit", "rate", "tag"}`), ditambah `enter_signals` dan `exit_signals`. Ini sinyal strategi pada data historis, bukan order yang dijalankan bot.

Contoh: tangkapan instans webserver nyata (Freqtrade 2026.9, Indodax, strategi SwingEmaRsi, BTC/IDR 1h, 2026-10-10 sampai 2026-10-25): 361 candle, 14 sinyal (5 enter, 9 exit), 0,49 detik.

```json
{"ts": "2026-10-13T06:00:00Z", "kind": "enter", "rate": 1492556000.0, "tag": "ema_cross_up"}
```

### 13.3 Papan skor voter

`GET /gw/v1/analytics/scoreboard?bot=B&limit=2000` menilai tiap voter pada trade yang sudah tertutup (keputusan dihubungkan ke trade lewat `trade_custom_data` kunci `shadow_decision_id` (`engine.decisions.SHADOW_KEY`, ditulis strategi saat entry bot B terisi), kolom yang terverifikasi ada di basis data Freqtrade nyata). Definisi (juga dikirim di `definition`): probabilitas ambil = jumlah probabilitas `izinkan` dan `kecilkan` (tanpa probabilitas: 1 bila pilihannya itu); hasil = trade tertutup dengan `profit_abs` > 0; per voter dihitung `accuracy`, `base_rate`, `majority_accuracy` (akurasi penebak kelas mayoritas, `max(base, 1 - base)`), serta `calls`, `answered`, `answer_rate`. Voter yang semua jawabannya membawa probabilitas (`kind: probabilistic`) juga dinilai dengan `brier`, `brier_baseline` (penebak konstan pada laju dasar), `ece`, dan `bins` kalibrasi. Voter yang sebagian jawabannya hanya `choice` (`kind: choice_only`; adapter `llm_structured` hanya mengirim pilihan, dan probabilitas satu-nol akan membuat Brier dan ECE menilai format jawaban, bukan mutunya) hanya dinilai dengan akurasi; `brier`, `ece`, dan `bins` bernilai `null`.

`status`: `insufficient` bila sampel < `analytics.scoreboard.min_samples`; selain itu `drifting` bila (`probabilistic`) `ece` > `max_ece` atau `brier` > `brier_baseline` + `brier_margin`, atau (`choice_only`) `accuracy` < `majority_accuracy` - `accuracy_margin`; selain itu `ok`. `shortfall` adalah ukuran urutan (brier - baseline, atau majority - accuracy). Ambang itu pilihan awal tugas ini, belum dikalibrasi dari data nyata (belum ada keputusan bertrade di basis data sekarang); ubah lewat config.

`POST /gw/v1/analytics/scoreboard/apply` (control dari loopback) menonaktifkan voter yang `plan.recommended` di bacaan di atas, juga bila `auto_disable` false (apply manual adalah keputusan pemanggil): voter `drifting` yang masih aktif ditulis `enabled: false` di config (divalidasi sebelum ditulis, penulisan atomik, tidak pernah menurunkan voter aktif di bawah `swarm.min_voters_answered`, juga saat `swarm.enabled` false; sisanya di `plan.kept_for_quorum`). Penulisan memakai kunci proses bersama dan menolak menimpa bila isi berkas berubah sejak dibaca (`409 invalid_request`); penulis di proses lain tetap hanya terlindungi oleh pemeriksaan isi itu. Gateway menjalankan rencana `plan.disable` tiap `interval_s` lewat `analytics.service.auto_disable_loop` hanya bila `analytics.scoreboard.auto_disable` true; `false` mematikan penonaktifan otomatis. Layanan swarm bayangan membaca config saat start, jadi voter yang dinonaktifkan baru berhenti dipanggil setelah layanan itu mulai ulang; hot reload belum terbukti.

### 13.4 Uji stres

`GET /gw/v1/analytics/stress?drop_pct=10` (default `analytics.stress.drop_pct`, 10). Semua posisi terbuka turun sebesar `drop_pct` dari harga sekarang secara bersamaan. Dua keadaan dihitung dengan aturan batas mesin (`engine/risk.py`): `stop_fills` (stop terisi di harga stop bila harga jatuh melewatinya) dan `stop_missed` (stop tidak terisi, celah harga; posisi dinilai di harga jatuh). Stop loss berjalan di sisi bot (plan bagian 2), jadi celah harga mungkin melewatinya dan keduanya ditampilkan.

Contoh: bentuk dari tes (satu posisi BTC/IDR Rp 300.000, stop -3%, rugi Rp 12.000 hari ini); bukan data bot.

```json
{"drop_pct": 10.0, "stop_fills": {"open_pnl": -10182.0, "equity": 1977818.0, "equity_change_idr": -7485.0, "daily_loss_pct": 1.109, "drawdown_pct": 1.109, "breaches": ["daily_loss"], "entries_allowed": false}, "stop_missed": {"open_pnl": -32487.3, "equity": 1955512.7, "equity_change_idr": -29790.3, "daily_loss_pct": 2.224, "drawdown_pct": 2.224, "breaches": ["daily_loss"], "entries_allowed": false}}
```

### 13.5 Ekspor CSV dan ringkasan pajak

`GET /gw/v1/analytics/export/trades.csv` mengunduh riwayat trade (kolom: `trade_id, pair, is_open, enter_tag, exit_reason, open_date, close_date, open_rate, close_rate, amount, stake_amount, fee_open, fee_close, profit_abs, profit_pct`). Sel teks yang diawali `=`, `+`, `-`, `@`, tab, atau CR diawali `'` agar tidak dibaca sebagai rumus.

`GET /gw/v1/analytics/export/tax?year=2026` menjumlahkan nilai jual (`amount` x `close_rate`) trade tertutup per bulan (bulan dan `year` dalam `risk.daily_reset_timezone`, zona yang sama dengan hari risiko; respons membawa `timezone`) dan mengalikannya dengan `analytics.tax.pph22_final_pct` (default 0,21). Dasar, dibaca dari artikel Direktorat Jenderal Pajak (pajak.go.id, 31 Juli 2025, disunting 8 September 2025): PMK 50/2025, berlaku 1 Agustus 2025, PPh Pasal 22 final atas penjualan aset kripto lewat PPMSE yang merupakan PAKD dalam negeri 0,21% dari nilai transaksi; 1% bila PPMSE bukan PAKD dalam negeri. Belum terbukti: status Indodax sebagai PAKD, teks resmi pasal PMK (hanya lewat artikel DJP), PPN atas jasa platform dan biaya platform (tidak dihitung). Respons membawa `basis` dengan semua itu. Ini informasi dari data dry-run, bukan nasihat pajak dan bukan laporan pajak; dry-run tidak memotong pajak sungguhan.

### 13.6 Backtest dari UI

Memakai instans webserver yang sama dengan 13.2. Prasyarat yang terverifikasi: launcher `webserver` memakai `strategy_path` di config yang dirender, bukan argumen `--strategy` (Freqtrade 2026.9 menolak `--strategy` untuk `webserver`; kesalahan itu ada di launcher sebelum tugas ini).

- `POST /gw/v1/analytics/backtest` (control dari loopback) body `{"timerange": "20261003-20261025", "max_open_trades": 3, "dry_run_wallet": 2000000}` (`timerange` wajib, lainnya opsional dengan default dari config). Strategi, `timeframe`, `stake_amount: "unlimited"`, dan `enable_protections: false` ditetapkan gateway. Jawab `202` dengan status job.
- `GET /gw/v1/analytics/backtest`: status (`status`, `running`, `step`, `progress`) dan, bila selesai, `result` berisi angka ringkas Freqtrade tanpa daftar trade; `results_per_pair` dan `exit_reason_summary` ikut.
- `DELETE /gw/v1/analytics/backtest` (control dari loopback): hentikan job yang berjalan lalu bersihkan.
- `GET /gw/v1/analytics/backtest/history` dan `GET /gw/v1/analytics/backtest/history/result?filename=...`: hasil tersimpan (nama berkas hanya `[A-Za-z0-9._-]`).

Riwayat OHLCV 1h Indodax terbatas sekitar 27 hari (bagian 10), jadi rentang backtest 1h juga. Hasil backtest memakai data historis dan tidak menjamin apa pun untuk kondisi live. Contoh nyata: BTC, ETH, SOL, 2026-10-03 sampai 2026-10-25, 2.000.000 IDR: 15 trade, selesai dalam 2,04 detik (angka untung rugi tidak ditampilkan di sini karena bukan kesimpulan).

### 13.7 Lebih dari 3 pair dan tampilan portofolio

`exchange.pairs` di config tidak dibatasi tiga; `risk.max_open_trades` boleh sampai 20. Terverifikasi di Indodax (`list-pairs --quote IDR`: 421 pasangan IDR aktif) dan di Freqtrade: 8 pasangan (BTC, ETH, SOL, DOGE, XRP, ADA, BNB, AVAX /IDR) terunduh 601 candle 1h masing-masing dan backtest 2026-10-05 sampai 2026-10-25 dengan `max_open_trades: 8` menghasilkan baris hasil untuk kedelapannya. Tiap pasangan tambahan menambah panggilan voter per kandidat entry (biaya LLM); itu belum diukur.

`GET /gw/v1/analytics/portfolio` mengelompokkan posisi terbuka per pasangan terhadap ekuitas: `pairs_configured`, `slots_used` dan `slots_max`, `exposure_idr`, `exposure_pct`, `cash_idr`, dan per pasangan `open_trades`, `stake_idr`, `pnl_idr`, `risk_at_stop_idr`, `share_of_equity_pct`, `over_limit` (melewati `analytics.portfolio.max_pair_share_pct`, default 50). Posisi pada pasangan yang sudah keluar dari config muncul di `pairs_not_in_config`.

### 13.8 Config

```yaml
analytics:
  scoreboard: {enabled: true, auto_disable: true, min_samples: 30, max_ece: 0.25, brier_margin: 0.05, accuracy_margin: 0.05, bins: 5, interval_s: 3600}
  stress: {drop_pct: 10.0}
  tax: {pph22_final_pct: 0.21}
  portfolio: {max_pair_share_pct: 50.0}
```

Bagian `analytics` boleh tidak ada; default di atas berlaku. Kunci tak dikenal ditolak seperti bagian lain.

### 13.9 Belum terbukti dan belum dibangun

- Pemasangan `install` dan `auto_disable_loop` ke gateway nyata (ZHA-3798), dan sisi PWA (N2, Agent Arif).
- Papan skor dan replay pada keputusan bertrade nyata: basis data bot sekarang tidak punya keputusan; yang diuji adalah data tes dan skema kolom nyata.
- Ambang `drifting` (`max_ece`, `brier_margin`, `accuracy_margin`, `min_samples`) belum dikalibrasi.
- Status PAKD Indodax dan teks resmi PMK 50/2025.
- Hot reload voter yang dinonaktifkan di layanan swarm bayangan.

## 14. Kontrol tahap 2a (ZHA-3774)

Kode: `gateway/control.py` (aturan lokal, token konfirmasi, idempotensi, klasifikasi perubahan konfigurasi) dan `Gateway.execute` plus rute di `gateway/app.py`. Tes: `tests/test_control.py`.

### 14.1 Kill switch

`POST /gw/v1/control/stop-entry` (atau `pause`) memanggil `POST /stopentry` saja; trade terbuka tidak disentuh (tes menghitung panggilan ke stub Freqtrade: hanya `/stopentry`). Tercermin di feed dua kali: event `gw.audit` dari gateway segera setelah Freqtrade menjawab, dan event `status` dari Freqtrade (`{"status": "paused"}`, dikirim `worker.py` saat state berubah). Gateway mencatat kill switch per bot di tabel `entry_stops`; `resume` menghapusnya. Freqtrade start dengan `initial_state: running` (`engine/launch.py`), jadi setiap kali koneksi WebSocket ke Freqtrade tersambung lagi (bot restart atau gateway restart) dan `/show_config` melaporkan `running` sementara kill switch tercatat, gateway mengirim `POST /stopentry` lagi dan mencatat audit dengan `actor: "gateway"`. `stop` juga mencatat kill switch: Freqtrade yang di-restart setelah `stop` kembali `running`, lalu gateway mengirim `/stopentry`, jadi hasil terburuk setelah restart adalah `paused` (trade terbuka kembali dikelola, tanpa entry baru), bukan entry yang jalan lagi. Hanya `resume` yang menghapus catatan ini.

### 14.2 Log audit

Tabel `audit` di `gateway.sqlite` append-only: trigger SQLite menolak `UPDATE` dan `DELETE` (`audit is append-only`). Setiap aksi kontrol menulis satu baris per percobaan dengan `result`:

| `result` | Arti |
| --- | --- |
| `ok` | Freqtrade menjalankan aksi |
| `failed` | Freqtrade menolak atau tidak menjawab; `detail.error` dan `detail.message` |
| `confirmation_required` | Langkah 1 aksi berisiko; token diberikan (id token tidak dicatat) |
| `rejected` | Ditolak gateway sebelum Freqtrade: token salah atau kedaluwarsa, kunci idempotensi salah, pemeriksaan `trades` gagal; `detail.error` |
| `replayed` | Hasil tersimpan dikembalikan untuk kunci idempotensi yang sama |
| `forbidden` | Sesi `read` atau request lewat proxy/tunnel; `actor` `read_session` atau `control_session`; `idempotency_key` hanya dicatat bila formatnya sah, selain itu `null` |

`actor` adalah `owner` untuk sesi `control` dan `gateway` untuk kill switch yang dikirim ulang. `targets[0]` adalah id bot, sisanya sasaran aksi (pair, id trade, `lock:<id>`, `all`). `detail.params` adalah parameter aksi; kunci yang namanya memuat `key`, `password`, `secret`, atau `token` diganti `<set>` (atau `null`). Request tanpa token sah ditolak `401` tanpa baris audit, supaya pihak tanpa sesi tidak bisa mengisi tabel append-only ini.

`GET /gw/v1/audit` (lingkup `read`) mengembalikan array baris terbaru dulu, dengan filter opsional yang digabung AND:

| Parameter | Arti |
| --- | --- |
| `limit` | 1-500, bawaan 50 |
| `before_id` | Paginasi: hanya baris dengan `id` lebih kecil; isi dengan `id` baris terakhir halaman sebelumnya |
| `action` | Awalan nama aksi, misalnya `control.`, `trade.exit`, `config.` |
| `result` | Persis, misalnya `failed` |
| `actor` | Persis |
| `target` | Salah satu elemen `targets` sama persis (id bot, pair, id trade) |
| `since`, `until` | ISO-8601 dengan zona; `ts >= since` dan `ts < until` |

Nama aksi: `control.pause`, `control.stop_entry`, `control.resume`, `control.stop`, `control.reload_config`, `trade.enter`, `trade.exit`, `trade.exit_all`, `pair.lock`, `pair.unlock`, `pair.blacklist`, `pair.unblacklist`, plus `session.*` dan `config.*` dari tahap 1.

### 14.3 Uji hidup (2026-10-26)

Satu bot dry-run Indodax (`trading-bot/engine` dengan `api.force_entry: true` hanya untuk uji ini) dan gateway di loopback, lalu dihentikan. Terukur dari klien di mesin yang sama: `stop-entry` dijawab 17,9 ms; event `gw.audit` tiba 18,1 ms setelah request dikirim dan event Freqtrade `status: paused` 905,6 ms; `/gw/v1/health` lalu melaporkan `state: paused`. Force enter BTC/IDR: langkah 1 `409 confirmation_required`, langkah 2 `200` dalam 592 ms (trade 1 terbuka). Kill switch dengan trade terbuka: trade 1 tetap terbuka. Force exit tanpa langkah 2: `409`, trade tetap terbuka; dengan langkah 2: `200` dalam 771 ms dan trade tertutup; token yang sama dipakai lagi: `409 confirmation_invalid`. Lock, unlock (dua langkah), tambah dan hapus blacklist (dua langkah): `200` dalam 12-21 ms. Request dengan `X-Forwarded-For`: `403 forbidden_local_only`, baris audit `forbidden`. `docker restart` bot saat kill switch aktif: gateway mengirim ulang `/stopentry` 8,1 detik setelah perintah restart (audit `actor: gateway`), state kembali `paused`. Nilai `GW_PASSWORD` dan `FT_API_PASSWORD` tidak muncul di 500 baris audit.

### 14.4 Belum terbukti

- Jendela antara Freqtrade start dan kill switch dikirim ulang: koneksi ulang WebSocket gateway memakai backoff 1, 2, 4, ... sampai 30 detik, jadi bot bisa berjalan tanpa kill switch beberapa detik setelah restart.
- Klasifikasi perubahan konfigurasi (`risky_changes`) terhubung ke `PATCH /gw/v1/settings` di bagian 15.2.
- Kontrol dari PWA jarak jauh sengaja tidak ada (hanya loopback); bila nanti kill switch harus bisa dari ponsel lewat tunnel, itu keputusan keamanan baru.
- Deteksi tunnel bergantung pada header forward. Cloudflare Tunnel menambah `CF-Connecting-IP` dan `X-Forwarded-For` menurut dokumentasinya, tetapi belum diuji dengan tunnel sungguhan. Tunnel yang tidak menambah header (misalnya `ssh -L`) terlihat sebagai lokal. uvicorn juga menulis ulang alamat klien dari `X-Forwarded-For` bila koneksi datang dari 127.0.0.1 (uji hidup: baris audit mencatat IP dari header itu), jadi aturan lokal tertolak dua kali untuk request semacam itu.

## 15. Gateway tahap 2b: konfigurasi, provider, key, voter (ZHA-3775)

Kode: `gateway/admin.py` (rute), `gateway/configstore.py` (baca, validasi, selisih, tulis atomik), `gateway/providers.py` (provider, impor, uji koneksi), `gateway/locality.py`, `gateway/redact.py`. Semua rute di bawah `/gw/v1`. Parameter `?bot=A|B` memilih berkas konfigurasi bot; tanpa itu dipakai bot pertama. Registri provider dan voter ada di berkas tiap bot, jadi PWA yang mengubahnya untuk dua bot memanggil dua kali.

### 15.1 Aturan akses

- Semua tulis di bagian ini (PATCH, PUT, DELETE, impor, dan pratinjau impor) memakai mekanisme 2a (bagian 2, 3, 14): sesi berlingkup `control` dan permintaan yang datang langsung dari mesin bot. Gagal salah satu: `403 forbidden_local_only` dan satu baris audit `admin.denied` (hasil `forbidden`, aktor `<lingkup>_session`, `detail`: metode, jalur, alasan `not_local` atau `scope`). Lingkup `owner` tidak ada (dilebur ke `control` oleh 2a).
- `control.is_local` (satu definisi untuk login, rute kontrol 2a, dan tulis 2b) menuntut: alamat peer `127.0.0.1` atau `::1`, tanpa header relai (`FORWARD_HEADERS`), header `Host` `127.0.0.1`, `localhost`, atau `[::1]`, dan `Origin` (bila ada) loopback. Batasnya: `Host` dan `Origin` dikirim klien, jadi syarat itu menahan browser yang masuk lewat tunnel, bukan klien yang memalsukan header. Lewat forward TCP mentah (`ssh -R`, `frp` atau `ngrok tcp`, `socat`) alamat peer tetap `127.0.0.1` dan klien bebas mengirim `Host: 127.0.0.1` tanpa `Origin`. Perlindungan nyata adalah port gateway tidak diekspos lewat forward TCP (15.8). Alamat peer `::ffff:127.0.0.1` ditolak (gateway hanya listen di `127.0.0.1` atau `::1`).
- Menurunkan batas risiko juga hanya dari lokal (bagian 5.15 lebih ketat daripada plan 4.2 aturan 2). PWA jarak jauh hanya bisa membaca dan menguji koneksi (15.3).
- `Idempotency-Key` wajib di semua tulis bagian 15 (8 sampai 128 karakter `[A-Za-z0-9_-]`, sama dengan 2a); tanpa itu `400 invalid_request`. Hasil sukses (`200`) disimpan 24 jam per kunci di ledger (`Ledger.store_result`, tahan restart). Kunci dan permintaan yang sama: hasil tersimpan dikembalikan tanpa menulis ulang (audit `replayed`). Kunci yang sama dengan permintaan lain: `409 invalid_request`. Kunci yang sedang berjalan: `409 invalid_request`. Baris audit menyimpan header `Idempotency-Key` hanya bila bentuknya sah (`control.loggable_key`), selain itu `null`. Penolakan (400, 409) tidak disimpan. Yang disimpan sebagai pembanding hanya SHA-256 dari permintaan; untuk penulisan key itu termasuk nilai key yang dikirim (hash, bukan nilai).
- Satu tulis berjalan sekaligus per bot (kunci per bot), baca-ubah-tulis tidak saling menimpa.

### 15.2 Perubahan konfigurasi

`PATCH /gw/v1/settings?bot=A`, body `{"changes": {...}, "confirm": "cf_..."}`. `changes` digabung ke dalam: objek digabung per kunci, nilai lain (termasuk daftar) menggantikan. Berkas hasil harus lolos skema `engine/settings.py` yang sama dengan mesin; bila tidak, `400 invalid_request` dengan `loc: pesan` (nilai kiriman tidak pernah dikembalikan dan tidak masuk audit), berkas tidak berubah. Tidak bisa diubah lewat rute ini (`400`): `mode`, `bot_id`, `api`, `shadow`, `providers` (pakai 15.3 dan 15.4), `swarm.voters` (pakai 15.5).

Dua langkah (bagian 3) memakai `control.risky_changes(old, new)` pada berkas lama dan baru: kenaikan `risk.max_daily_loss_pct`, `risk.max_total_drawdown_pct`, `risk.risk_per_trade_pct`, `risk.max_open_trades`. Tambahan 2b: kenaikan `capital.initial_idr` (modal lebih besar menaikkan semua batas dalam rupiah). Satu permintaan yang memuat satu kenaikan saja seluruhnya butuh konfirmasi; menurunkan berlaku langsung. Pasangan, biaya, swarm, data, dan notifikasi bukan batas risiko.

```json
{"error": {"code": "confirmation_required", "message": "raising risk limits needs a second step",
 "confirmation": {"id": "cf_3A9F00C2B1D45E77", "action": "config.update", "targets": ["A"],
 "summary": "Raise risk.max_daily_loss_pct 1.0 -> 2.0", "expires_at": "2026-10-26T01:10:00Z"}}}
```

Ulangi permintaan yang sama dengan `"confirm": "cf_..."` dan `Idempotency-Key` yang sama atau baru. Token memakai `Confirmations` 2a: sekali pakai, 60 detik, terikat pada `digest({"request": digest(aksi, bot, params tanpa confirm), "session": digest(token sesi)})`. Id tak dikenal, sudah dipakai, untuk perubahan lain, atau dari sesi lain: `409 confirmation_invalid` (token yang tidak cocok tidak hangus). Lewat 60 detik: `409 confirmation_expired`. Konfirmasi hanya dituntut bila perubahan masih menaikkan saat langkah 2 dihitung ulang terhadap berkas saat itu.

Menurunkan `risk.max_daily_loss_pct` atau `risk.max_total_drawdown_pct` sampai sama dengan atau di bawah rugi harian atau drawdown yang sudah tercapai (dari `GET /gw/v1/risk`): `409 risk_limit_breached`. Bila Freqtrade tidak menjawab, pemeriksaan dilewati dan audit mencatat `risk_check: skipped_upstream_unavailable` (menurunkan adalah arah aman).

Sukses (`200`):

```json
{"bot": "A", "changes": [{"key": "risk.max_daily_loss_pct", "old": 2.0, "new": 0.8}], "restart_required": true, "audit_id": 41}
```

`restart_required` selalu `true` bila berkas berubah: mesin dan layanan swarm membaca konfigurasi saat start; muat ulang tanpa restart belum terbukti (`POST /gw/v1/control/reload-config` memuat ulang konfigurasi Freqtrade, bukan skema bot ini). Gateway tidak me-restart apa pun. Tanpa perubahan nyata: `{"changes": [], "restart_required": false}`, tanpa tulis dan tanpa audit.

Berkas ditulis atomik (berkas sementara, fsync, rename, fsync direktori) dengan mode `0600`; komentar YAML tidak dipertahankan karena berkas ditulis ulang dari data. Gagal tulis: `500 config_unwritable`, berkas lama utuh. Hash berkas disimpan di ledger sehingga pemantau berkas (12.2) tidak mencatat tulisan yang sama lagi sebagai `config.changed`.

`GET /gw/v1/settings/changes?bot=A&limit=50` (`read`): catatan perubahan, satu entri per kunci: `{audit_id, ts, actor, ip, action, bot, key, old, new}`. `actor` `owner` untuk tulisan lewat gateway, `file` untuk suntingan berkas yang terdeteksi pemantau. Sumbernya log audit (`action` berawalan `config.`).

`GET /gw/v1/settings` (5.15) menambah `providers[].api_key_last4`. `api_key` tetap `null`. `api_key_env` (hanya nama variabel) ikut tampil, berbeda dari kalimat 5.15 yang menyebutnya `null`, karena layar Provider perlu menampilkan nama variabel yang dibaca.

### 15.3 Provider

`GET /gw/v1/providers?bot=A` (`read`):

```json
{"bot": "A", "providers": [{"id": "nutaraline", "type": "openai-completions", "base_url": "https://nutaraline.co.uk/v1",
 "host": "nutaraline.co.uk", "models": ["deepseek-v4.1-flash-1017"], "active_models": ["deepseek-v4.1-flash-1017"],
 "key": {"source": "env", "configured": true, "last4": null, "env_name": "NUTARALINE_API_KEY", "env_set": true},
 "last_test": {"tested_at": "2026-10-26T01:00:00.000Z", "model": "deepseek-v4.1-flash-1017", "ok": true, "status": 200, "latency_ms": 840, "error": null, "detail": null}}]}
```

`key.source`: `config` (`api_key` di berkas, `last4` berisi 4 karakter terakhir bila kunci minimal 12 karakter, selain itu `null`), `env` (nama variabel di `env_name`, `env_set` apakah variabel itu terisi di proses gateway), atau `none`. `active_models`: model provider itu yang dipakai analis atau voter aktif. `last_test` `null` bila belum pernah diuji; dibaca dari audit `provider.test` setelah gateway restart. `host` tanpa user dan sandi; `null` bila `base_url` masih `from_import`.

- `PUT /gw/v1/providers/{id}` body `{"type", "base_url", "models"}` (`type`: tiga tipe chat dan `systemone`, `openai-decisions`, `openrouter-decisions` seperti `engine/settings.py`): tambah atau ubah (id huruf kecil, angka, `_`, `-`; `import` dipesan). Provider baru memakai `api_key_env: <ID_HURUF_BESAR>_API_KEY` (`-` jadi `_`), sesuai nama di `.env` lokal. Mengubah provider yang ada mempertahankan key-nya. `base_url` tidak boleh memuat user atau sandi. Body yang memuat `api_key` ditolak (`400`).
- `DELETE /gw/v1/providers/{id}`: hapus; ditolak `400` bila masih dirujuk voter atau analis (pesan skema).
- `POST /gw/v1/providers/{id}/test`, body opsional `{"model": "..."}` (harus ada di daftar model provider; bawaan model pertama), lingkup `read` cukup (plan 4.5 butir 4: PWA jarak jauh boleh menguji). Satu panggilan kecil dengan perintah `Reply with the single word: ok` (kata `ping` dihindari: nutaraline menjawab `403` "Ping/probe inference dinonaktifkan" untuk prompt `ping`, terukur 2026-10-26): `openai-completions` ke `{base}/chat/completions` (`max_tokens` 16), `openai-responses` ke `{base}/responses` (`max_output_tokens` 16), `anthropic-messages` ke `{base}/messages` bila `base` berakhiran `/v1`, selain itu `{base}/v1/messages`; tipe decision memakai wire adapter swarm dengan satu pertanyaan `noul` (`predicate` untuk `openai-decisions`): `systemone` ke `{base}/v1/systemone`, `openai-decisions` ke `{base}/v1/decisions` (badan `input` dan `questions` berupa daftar), `openrouter-decisions` ke `{base}/api/alpha/decisions`. Terbukti hidup 2026-10-26 untuk `systemone` (`jev-latest`, 200) dan `openai-decisions` (`gpt-6-luna-decisions`, 200) di `api.experientiallabs.ai`; `openrouter-decisions` hanya diuji dengan transport tiruan (tidak ada key OpenRouter). Key hanya dikirim ke `base_url` tersimpan, tidak pernah ke alamat dari body; redirect tidak diikuti. Hasil: `{"bot", "provider", "model", "ok", "status", "latency_ms", "error", "detail", "tested_at"}`. `ok` benar bila status 2xx dan badan JSON. `error`: `unauthorized`, `not_found`, `rate_limited`, `rejected`, `upstream_error`, `timeout`, `connect_error`, `invalid_response`, `no_key`, `base_url_unresolved`. `detail` memuat pesan galat provider (maks 160 karakter) setelah disaring. Jeda 5 detik per provider (`429 rate_limited` dengan `retry_after_ms`); maksimal 2 uji berjalan bersamaan; batas waktu 30 detik. `base_url: from_import` tidak ditebak dari `models.yml`: mesin dan swarm juga tidak menyelesaikannya, jadi hasilnya `base_url_unresolved`.
- Hasil uji dicatat di audit: `provider.test`, `targets: [bot, provider]`, hasil `ok` atau `failed`, `actor` `owner` atau `remote`.

### 15.4 Key

Hanya lokal dan `control` (15.1).

- `PUT /gw/v1/providers/{id}/key` body `{"api_key": "..."}` atau `{"api_key_env": "NAMA_VARIABEL"}` (tepat salah satu; yang satu lagi dikosongkan di berkas). `api_key`: 8 sampai 1024 karakter tanpa spasi. `api_key_env`: huruf besar, angka, `_`. Jawaban memuat `provider` (bentuk 15.3) dan selisih dengan `api_key` tampil `****` plus 4 karakter terakhir (atau `<set>` bila kunci pendek).
- `DELETE /gw/v1/providers/{id}/key`: kosongkan keduanya.
- Kunci mentah ditulis hanya ke berkas konfigurasi bot. Bila berkas itu berada di dalam git work tree dan tidak di-ignore (atau git tidak bisa memastikan), gateway menolak (`400`, pakai `api_key_env`). Tidak ada endpoint yang mengembalikan kunci utuh; galat validasi tidak memantulkan nilai kiriman.
- Log: `gateway/redact.py` dipasang pada setiap record log proses gateway (`python -m gateway`). Yang disaring: nilai kunci yang dikenal gateway (dari berkas dan variabel lingkungan yang dirujuk), `Authorization` (Bearer dan Basic), `?token=` dan sejenis di URL (termasuk `?token=` feed WebSocket), `x-api-key`, pola `sk-...`, dan traceback.

### 15.5 Voter dan peran

Registri voter adalah `swarm.voters` di berkas konfigurasi; menambah atau mengganti voter hanya mengubah berkas (tanpa kode).

- `GET /gw/v1/voters?bot=B` (`read`): `{"bot", "swarm": {"enabled", "mode", "min_voters_answered", "enabled_voters"}, "voters": [{id, adapter, provider, model, variation, timeout_s, weight, enabled, last_test}]}`. `last_test` adalah uji koneksi terakhir provider voter itu, bukan kesehatan voting per voter (belum ada).
- `PUT /gw/v1/voters/{id}` body `{adapter, provider, model, variation, timeout_s, weight, enabled}`: tambah (di akhir daftar) atau ganti (di tempat). Provider harus ada, model harus terdaftar di provider itu, dan kuorum `min_voters_answered` tidak boleh melebihi jumlah voter aktif; selain itu `400` dan berkas utuh.
- `DELETE /gw/v1/voters/{id}`: `404` bila tidak ada; `400` bila kuorum jadi tidak terpenuhi.
- `GET /gw/v1/roles` dan `PUT /gw/v1/roles` body `{"analyst": {"provider", "model"}, "voters": {"v1": {"provider", "model"}}}`: pilih provider dan model untuk agen analis (`llm.analyst_model`) dan tiap voter dalam satu tulis atomik dan satu baris audit. Voter yang tidak dikenal: `404`.

Setiap tulis di bagian 15 menulis satu baris audit `config.update`, `config.provider.upsert|delete|key|import`, `config.voter.upsert|delete`, atau `config.roles` (`actor`, `ip`, `idempotency_key`, hasil `ok`, `rejected`, `forbidden`, `replayed`, atau `confirmation_required`, `detail.changes` berisi kunci, nilai lama, dan nilai baru dengan `api_key` tersamar) dan menyiarkan event `gw.audit`.

### 15.6 Impor dari omp models.yml

Berkas dibaca lokal oleh gateway dari `models_yml` di `config/gateway.yaml` (bawaan `~/.omp/agent/models.yml`); jalurnya tidak bisa diberikan lewat permintaan.

- `GET /gw/v1/providers/import?bot=A`: pratinjau, per provider `{name, id, type, base_url, host, models, key_source, exists, blocker}`. `key_source`: `literal`, `env` (nilai berupa nama variabel huruf besar), `command` (nilai berawalan `!`), `none`. Nilai key tidak pernah ada di jawaban. `blocker` terisi untuk tipe API yang tidak didukung, URL bukan http(s), tanpa model, atau nama yang tidak bisa jadi id.
- `POST /gw/v1/providers/import` body `{"providers": [{"name", "with_key": false, "models": null, "replace": false}]}`: satu tulis atomik. Tanpa `with_key`, provider memakai `api_key_env` bawaan (15.3) dan nilai key di `models.yml` tidak dibaca ke konfigurasi. `with_key: true` menyalin key hanya untuk provider yang dicentang: `literal` menjadi `api_key`, `env` menjadi `api_key_env`; `command` ditolak (`400`, perintah tidak dijalankan), `none` ditolak. `models` (bila diisi) harus himpunan bagian tidak kosong dari model berkas. Provider yang sudah ada dilewati kecuali `replace: true` (memperbarui tipe, URL, model; key tetap kecuali dicentang). Jawaban: `results: [{name, id, result: created|updated|skipped, reason?, with_key}]`.

### 15.7 Kode galat tambahan

`config_unwritable` (500). `forbidden_local_only`, `confirmation_required`, `confirmation_invalid`, `confirmation_expired`, `risk_limit_breached`, `rate_limited`, `not_found`, `invalid_request` sudah ada (bagian 4 dan 14).

### 15.8 Belum terbukti

- Muat ulang konfigurasi tanpa restart (sebab `restart_required` selalu `true`).
- Uji koneksi terhadap provider nyata selain yang tercatat di komentar penutup ZHA-3775; tipe `openai-responses` dan `anthropic-messages` dengan key nyata hanya diuji bila disebut di sana.
- Uji koneksi `openrouter-decisions` terhadap OpenRouter nyata (tidak ada key); impor `models.yml` hanya mengenal tiga tipe chat.
- Perilaku di balik tunnel nyata (diuji dengan header relai buatan, bukan Cloudflare Tunnel sungguhan).
- Forward TCP mentah (`ssh -R`, `frp` atau `ngrok tcp`, `socat`) terlihat lokal karena peer `127.0.0.1` dan klien menulis `Host` sendiri; `control.is_local` tidak bisa membedakannya. Mitigasi hanya operasional: jangan ekspos port gateway lewat forward TCP.
- Kunci yang ditulis dengan `api_key` memerlukan direktori konfigurasi yang bisa ditulis gateway; compose saat ini memasang `./config` sebagai `:ro` untuk bot, jadi gateway perlu volume tulis sendiri (belum diatur).
