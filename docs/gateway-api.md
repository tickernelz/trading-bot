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
- Token punya dua lingkup: `read` (semua GET) dan `control` (GET plus semua POST/DELETE kontrol). `control` hanya diberikan bila login datang langsung dari loopback: alamat klien `127.0.0.1` atau `::1` dan tanpa header forward (`Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP`, `CF-Connecting-IP`, `CF-Ray`, `True-Client-IP`); selain itu `read`. Respons login menambah `"scope": "control" | "read"`. Lingkup `owner` dilebur ke `control` (ZHA-3774): issue tahap 2a meminta kontrol hanya dari localhost, jadi `control` sudah seketat `owner`, dan satu lingkup lebih sedikit berarti satu cabang otorisasi lebih sedikit.
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
- Perubahan konfigurasi: `risky_changes(old, new)` di `gateway/control.py` mengembalikan kunci yang butuh dua langkah: kenaikan `risk.max_daily_loss_pct`, `risk.max_total_drawdown_pct`, `risk.risk_per_trade_pct`, `risk.max_open_trades`, perubahan `mode` ke arah mana pun, dan `api.force_entry` dari `false` ke `true`. Daftar kosong berarti perubahan berlaku langsung (termasuk menurunkan batas). `PATCH /gw/v1/settings` milik ZHA-3775 memakai fungsi ini bersama `Confirmations` dan `is_local`; sampai itu masuk, aturan konfigurasi baru terbukti di tes unit, belum di endpoint.

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

Kode yang dipakai: `unauthorized`, `live_blocked` (422, ZHA-3779: tak ada key exchange atau jalur order live belum terbukti; membawa daftar `blockers`), `forbidden_local_only`, `confirmation_required`, `confirmation_expired`, `confirmation_invalid` (ZHA-3774: token tak dikenal, sudah dipakai, atau untuk aksi, parameter, atau sesi lain; dipisah dari `confirmation_expired` supaya PWA bisa membedakan waktu habis dari token yang salah), `invalid_request`, `upstream_error`, `upstream_unavailable`, `risk_limit_breached`, `not_found`, `rate_limited`.

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

### 5.4 `GET /gw/v1/trades?limit=100&offset=0&state=closed&pair=BTC/IDR`

Gabungan `/status` (trade terbuka) dan `/trades` Freqtrade. `/trades` Freqtrade hanya memuat trade tertutup, maksimal 500 per halaman, dan bawaannya urut id naik; gateway mengambil semua halaman (`order_by_id=true`, `offset`), menggabungkan, lalu mengurutkan `trade_id` turun sebelum `pair`, `offset`, dan `limit` diterapkan. `state=closed` hanya trade tertutup (riwayat, bagian 17.2). Bentuk sama dengan 5.3; trade tertutup membawa `close_date`, `close_rate`, `close_profit_abs`, `exit_reason`, `exit_order_status`.

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

`window=total` memakai `/profit`. `daily`, `weekly`, `monthly` dihitung gateway dari semua trade tertutup dengan nama field `/daily`, `/weekly`, `/monthly` Freqtrade, tetapi batas hari mengikuti `risk.daily_reset_timezone` (bagian 17.3).

Contoh `total`: tangkapan Freqtrade 2026.9 untuk field Freqtrade; `window` rancangan gateway.

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

Contoh `daily`: lihat 17.3.

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

Contoh: tangkapan Freqtrade 2026.9 per bagian; pembungkus `per_pair`/`by_enter_tag`/`by_exit_reason`/`by_mix_tag` milik gateway (`by_mix_tag` sejak 17.4).

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

### 11.1 `GET /gw/v1/equity?window=day|7d|total&bots=A,B`

Kurva ekuitas untuk jejak hari ini (Ringkas) dan perbandingan Bot A vs Bot B (Grafik). `start_equity` adalah ekuitas awal jendela (00.00 WIB untuk `day`, modal awal untuk `7d`). `window=total` dan `series[].start_equity`: bagian 17.5.

```json
{"window": "7d", "start_equity": 2000000, "series": [{"bot": "A", "label": "Bot A", "strategy": "aturan saja", "points": [["2026-10-18T18:00:00Z", 2000000.0]]}, {"bot": "B", "label": "Bot B", "strategy": "aturan + swarm bayangan", "points": [["2026-10-18T18:00:00Z", 2000000.0]]}]}
```

### 11.2 `GET /gw/v1/decisions?limit=20` dan event `gw.decision`

Filter, `outcome`, kuorum, keputusan yang akan diambil, dan detail `/gw/v1/decisions/{decision_id}`: bagian 17.1.

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
  - `GET /gw/v1/costs?window=day|7d|total`: jumlah keputusan, panggilan voter, token masuk, keluar, dan reasoning, biaya per bot dan per provider, plus `cap` (`max_cost_idr_per_day`, `enforced: false`). Hanya informasi; tidak membatasi apa pun. `cost` adalah angka yang dilaporkan provider; nutaraline tidak melaporkan biaya, jadi `null`. Token analis ada di baris sendiri `analyst` (`reports` dan `asks`: `calls`, token masuk, keluar, reasoning, `cost`), dihitung dari audit `analyst.report` dan `analyst.ask` berhasil dalam jendela yang sama (semua bot, termasuk laporan pencatat waktu); tidak masuk ke jumlah keputusan, voter, dan token voter di atas, dan `cost` tetap `null` selama provider tidak melaporkannya (tidak ada biaya rupiah yang dikarang).
  - `GET /gw/v1/audit?limit=50`: log audit. Isinya: `session.create` (`ok` atau `denied`) dan `session.delete` dengan IP; `config.observed` dan `config.changed` untuk berkas konfigurasi tiap bot (diperiksa tiap 10 detik dengan SHA-256; `detail.changes` berisi kunci yang berubah dengan nilai lama dan baru, `api_key` hanya `<set>` atau `null`; `result: invalid` bila berkas baru tidak lolos skema).
  - `GET /gw/v1/metrics`: `fill_latency_ms` (n, p50, p95, min, maks, 20 sampel terakhir), beban gateway, status tiap koneksi upstream, nomor urut feed.

### 12.2a Riwayat lengkap dan rahasia di log

- `/gw/v1/risk`, `/gw/v1/overview`, `gw.risk`, `/gw/v1/equity`, dan `/gw/v1/trades` memakai SEMUA trade tertutup, dipaging 500 per permintaan sampai jumlahnya sama dengan `total_trades` Freqtrade. Bila halaman tidak menjumlah ke `total_trades` (misalnya trade tertutup di antara dua halaman), jawabannya `502 upstream_error` dengan `retry_after_ms`, bukan angka risiko dari riwayat sebagian.
- Uvicorn di dalam Freqtrade mencatat URL WebSocket beserta query (`?token=`) ke logger `uvicorn.error`, dan `/api/v1/logs` Freqtrade membaca log yang sama. Strategi memasang filter pada `uvicorn.error` dan `uvicorn.access` saat dimuat (sebelum API server start) yang mengganti `token=...` menjadi `token=<redacted>`; `/gw/v1/logs` menyensor pola yang sama sebagai lapis kedua.
- Feed mengabaikan frame biner dan `candles[].limit` yang bukan angka, tanpa memutus koneksi.

### 12.3 Jeda fill

Saat `entry_fill` atau `exit_fill` tiba dari Freqtrade, gateway mencatat waktu terima (ms), lalu mengambil `/trade/{id}` dan memakai `order_filled_timestamp` order sisi yang sama. Jeda = waktu terima dikurangi waktu fill yang dicatat Freqtrade. Jam yang sama (satu host). Alat ukur: `scripts/measure_gateway.py fills|clients --out <berkas.json>` dan `scripts/gateway_cpu.sh <kontainer> <detik> <label>`; keluaran mentahnya dilampirkan di ZHA-3764.

### 12.4 Belum dibangun

- `PATCH /gw/v1/settings` (ZHA-3775). Kontrol bagian 3 dan 6 dan lingkup `control` dibangun di ZHA-3774 (bagian 14).
- Web Push bagian 11.3: `/gw/v1/push/*` menjawab `404 not_found`; PWA hanya bisa memakai Web Push dengan gateway tiruan.
- `sample_data` selalu `false`.


## 13. Analitik N1 (ZHA-3780)

Semua GET dan `POST /replay` hanya membaca dan butuh sesi gateway apa pun (lingkup read cukup), seperti bagian 5. Tiga aksi mengubah sesuatu dan mengikuti bagian 1, 2, dan 6: `POST /gw/v1/analytics/scoreboard/apply` (menulis `enabled: false` ke config), `POST /gw/v1/analytics/backtest` dan `DELETE /gw/v1/analytics/backtest` (memulai dan menghentikan job di instans webserver). Ketiganya hanya diterima dari koneksi loopback langsung dengan sesi lingkup control, sama dengan aksi bagian 6 (`gateway.control.is_local`); selain itu `403 forbidden_local_only` dan satu baris audit `forbidden`. Setiap pemanggilan lain menulis tepat satu baris audit dengan hasil (`ok` atau `failed`), termasuk apply yang tidak mengubah apa pun. Galat memakai envelope bagian 4, ditambah kode `invalid_config` (500) bila config bot gagal divalidasi. Kode ada di `analytics/` dan dipasang ke aplikasi gateway lewat `analytics.routes.install(app, context, reader)`; `context` menyediakan: `source(bot)` (config, basis data keputusan dan trade); `trades(bot)` (SEMUA trade tertutup ditambah posisi terbuka, tanpa batas jumlah; gateway memagina seperti `/gw/v1/risk` dan gagal tertutup bila jumlahnya tidak cocok, karena ekuitas, puncak, dan pajak tahunan salah bila riwayat terpotong); `analysis()` (klien webserver atau `None`); `can_control(request)` (`gateway.control.is_local(request)`, yaitu klien langsung dari `127.0.0.1` atau `::1` tanpa header `Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP`, `CF-Connecting-IP`, `CF-Ray`, atau `True-Client-IP`, dan sesi bertanda `control`; satu penjaga untuk bagian 6 dan 13); dan `audit(action, result, request=, targets=, detail=)` yang menulis baris bagian 6 (`actor` `owner` bagi panggilan yang diizinkan dan `<lingkup>_session` bagi baris `forbidden`, seperti bagian 6, dan `ip` diambil gateway dari `request`, `idempotency_key` dari header hanya bila memenuhi aturan bagian 6; `request=None` berarti aktor `gateway`, dipakai loop penonaktifan otomatis). Nama aksi: `analytics.scoreboard.apply`, `analytics.scoreboard.auto_disable`, `analytics.backtest.start`, `analytics.backtest.stop`.

Status: terpasang di gateway tahap 1 (ZHA-3798). `gateway/analytics_context.py` menyediakan `context`, dan `gateway/app.py` memanggil `analytics.routes.install(app, gateway.analytics, reader)` dengan `reader` yang sama seperti bagian 5. `analysis_url` di config gateway (alamat loopback instans webserver, memakai kredensial `FT_API_*` yang sama dan port berbeda dari bot) mengisi `analysis()`; tanpa itu sinyal dan backtest menjawab `404 not_found`. Terbukti 2026-10-26 pada proses gateway sungguhan (image dari SHA 3412672) terhadap Freqtrade 2026.9 dry-run dengan satu trade BTC/IDR dari `forceenter` dry-run dan instans webserver: semua rute bagian ini menjawab dengan bentuk yang tertulis; `POST /backtest` menjawab 202 lalu selesai (15 trade, 2026-10-03 sampai 2026-10-25); `X-Forwarded-For` pada apply dan backtest menjawab `403 forbidden_local_only` tanpa mengubah config. Papan skor, replay, dan `auto_disable_loop` diuji pada basis data keputusan sintetis karena bot dry-run belum punya keputusan nyata (13.9).

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

`POST /gw/v1/analytics/scoreboard/apply` (control dari loopback) menonaktifkan voter yang `plan.recommended` di bacaan di atas, juga bila `auto_disable` false (apply manual adalah keputusan pemanggil): voter `drifting` yang masih aktif ditulis `enabled: false` di config (divalidasi sebelum ditulis, penulisan atomik, tidak pernah menurunkan voter aktif di bawah `swarm.min_voters_answered`, juga saat `swarm.enabled` false; sisanya di `plan.kept_for_quorum`). Penulisan memakai kunci proses bersama dan menolak menimpa bila isi berkas berubah sejak dibaca (`409 invalid_request`); penulis di proses lain tetap hanya terlindungi oleh pemeriksaan isi itu. Gateway menjalankan rencana `plan.disable` tiap `interval_s` lewat `analytics.service.auto_disable_loop` hanya bila `analytics.scoreboard.auto_disable` true; `false` mematikan penonaktifan otomatis. Loop dimulai bersama gateway untuk bot yang punya `decisions` (bot tanpa basis keputusan tidak dinilai dan tidak menulis baris audit), membaca ulang config bot tiap 30 detik sehingga `auto_disable` berlaku tanpa restart gateway, dan dimulai ulang dengan satu peringatan log bila berhenti karena galat tak terduga. Layanan swarm bayangan membaca config saat start, jadi voter yang dinonaktifkan baru berhenti dipanggil setelah layanan itu mulai ulang; hot reload belum terbukti.

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

- Sisi PWA (N2, Agent Arif).
- Aksi analitik lewat sesi read jarak jauh (ZHA-3788 belum memutuskan; sekarang ditolak seperti aksi bagian 6).
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
- Klasifikasi perubahan konfigurasi (`risky_changes`) belum terhubung ke endpoint; menunggu `PATCH /gw/v1/settings` (ZHA-3775).
- Kontrol dari PWA jarak jauh sengaja tidak ada (hanya loopback); bila nanti kill switch harus bisa dari ponsel lewat tunnel, itu keputusan keamanan baru.
- Deteksi tunnel bergantung pada header forward. Cloudflare Tunnel menambah `CF-Connecting-IP` dan `X-Forwarded-For` menurut dokumentasinya, tetapi belum diuji dengan tunnel sungguhan. Tunnel yang tidak menambah header (misalnya `ssh -L`) terlihat sebagai lokal. uvicorn juga menulis ulang alamat klien dari `X-Forwarded-For` bila koneksi datang dari 127.0.0.1 (uji hidup: baris audit mencatat IP dari header itu), jadi aturan lokal tertolak dua kali untuk request semacam itu.

## 15. PWA tahap 2 (ZHA-3777)

Layar tahap 2 (Kontrol, Konfigurasi, Provider dan key, Swarm per keputusan, Riwayat, A vs B, Audit) memakai kontrak gateway yang sudah dibangun di cabang tugasnya, apa adanya, dan hanya menulis rancangan untuk endpoint yang belum dimiliki cabang mana pun. Saat ditulis (2026-10-26) gateway tahap 1 (ZHA-3764) dan 2a (ZHA-3774, bagian 14) sudah di `main`, sedangkan 2b dan 2c belum. Cabang 2b memakai nomor 14 untuk bagiannya sendiri dan `main` memakai nomor 12 dua kali (N2 dan gateway tahap 1), jadi rujukan di bawah memakai nama tugas, bukan nomor.

### 15.1 Kontrak yang dipakai apa adanya

- Kontrol dan audit: ZHA-3774 (bagian 2, 3, 6, dan 14 di dokumen ini, `main` a63e1e3). Lingkup sesi dari `scope` login (`control` hanya dari loopback langsung, selain itu `read`); `Idempotency-Key` UUID v4 baru per tekan; `409 confirmation_required` menampilkan langkah 2 dari `error.confirmation`; langkah 2 mengulang permintaan yang sama dengan kunci yang sama dan body `{"confirm": "<id>"}`, termasuk pada `DELETE`; `confirmation_expired` dan `confirmation_invalid` kembali ke langkah 1. Kill switch "Hentikan entry baru" memanggil `stop-entry`; menurut bagian 14.1 `stop-entry`, `pause`, dan `stop` sama-sama dicatat gateway dan dipasang ulang setelah bot restart, hanya `resume` yang menghapusnya.
- Konfigurasi, provider, key, voter, peran, impor: ZHA-3775 (`feat/stage-2b-config`, bagian "Gateway tahap 2b" di cabang itu). PWA mengirim `PATCH /gw/v1/settings?bot=` dengan `changes` bersarang yang hanya memuat kunci yang berubah, tanpa `mode`, `bot_id`, `api`, `shadow`, `providers`, `swarm.voters`; voter lewat `PUT` dan `DELETE /gw/v1/voters/{id}`; analis lewat `PUT /gw/v1/roles`; provider lewat `PUT` dan `DELETE /gw/v1/providers/{id}`; key lewat `PUT` dan `DELETE /gw/v1/providers/{id}/key`; impor lewat `GET` dan `POST /gw/v1/providers/import`; catatan perubahan dari `GET /gw/v1/settings/changes`. Dua langkah mengikuti `raising_keys` 2b (empat batas risiko dan `capital.initial_idr` naik). Galat skema `400 invalid_request` membawa `loc: pesan` di `message`; PWA memetakan `loc` ke kolom yang sama namanya dan menampilkan sisanya di atas formulir. `restart_required: true` ditampilkan sebagai "berlaku setelah bot di-restart".
- Registri provider dan voter per bot (`?bot=`): PWA memakai pemilih Bot di layar Konfigurasi dan Provider, dan mengingatkan bahwa dua bot diubah dua kali.

### 15.2 Yang sengaja tidak ada di PWA

- Mengaktifkan atau menonaktifkan provider dari jarak jauh. Plan 4.5 butir 4 menyebutnya, tetapi 2b membatasi sesi `read` ke baca dan uji koneksi, dan skema belum punya `providers[].enabled`. Keputusan ada di ZHA-3796; sampai itu, layar Provider jarak jauh hanya status dan Uji koneksi.
- Catatan alasan per perubahan konfigurasi: 2b tidak menerima field itu; catatan perubahan adalah siapa, kapan, kunci, nilai lama dan baru dari `/gw/v1/settings/changes`.

### 15.3 Rancangan untuk endpoint yang belum dimiliki cabang mana pun

Isi `rancangan`, menunggu ZHA-3776 (swarm per keputusan, riwayat, A vs B). Dipakai PWA dan gateway tiruan; tugas gateway menangkap ulang bentuknya.

- `GET /gw/v1/decisions` menambah `status=ok|skip` dan `bot=A|B` di samping `pair`, `before` (waktu `candle`, bagian N2 ZHA-3781), dan `limit`. Setiap baris dan event `gw.decision` menambah `outcome`:

```json
{"state": "settled", "basis": "price", "horizon_h": 4, "price_at": 1463932000, "price_after": 1471200000, "return_pct": 0.5, "return_after_fees_pct": 0.1, "trade_id": null, "is_open": null, "profit_abs": null, "profit_pct": null, "settles_at": "2026-10-25T21:00:00Z"}
```

  `basis: "trade"`: bot benar-benar masuk; `trade_id`, `is_open`, `profit_abs`, `profit_pct` dari trade itu. `basis: "price"`: entry dilewati; penutupan kandel `horizon_h` jam sesudahnya dibanding harga saat keputusan, sebelum dan sesudah biaya dua sisi; pengandaian kasar, bukan trade. `state`: `pending` (horizon belum lewat atau trade masih terbuka), `insufficient_data` (kandel sesudah horizon tidak ada), `settled`. PWA tidak memberi angka untuk dua yang pertama dan tidak menjumlahkannya.
- `GET /gw/v1/trades?limit=50&offset=0&state=closed&bot=A`: `offset` sesudah urutan `trade_id` turun, `state=closed` hanya trade tertutup.
- Harian, mingguan, bulanan per bot: bagian 5.7 dengan `bot`. Per alasan exit dan durasi: 5.8. Per pair, tag entry, alasan exit: 5.9.
- `GET /gw/v1/equity` menambah `window=total` (sejak start dry-run, satu titik per jam). `GET /gw/v1/profit?window=total&bot=B` meneruskan `max_drawdown` (rasio) dan `max_drawdown_abs` dari `/profit` Freqtrade.
- `GET /gw/v1/overview?bot=` menambah `state` (`running`, `paused`, `stopped`) dari `/show_config` bot itu, supaya layar Kontrol membaca keadaan Bot B. Tanpa itu PWA memakai `/gw/v1/health` untuk bot pertama dan menulis "keadaan tidak terbaca" untuk bot lain.

## 16. Tahap 3a: agen analis dan kontrol mode live

Endpoint di bagian ini dibangun di `gateway/analyst.py` dan `gateway/modeapi.py` dan diuji lewat gateway nyata dengan klien uji (`tests/test_gateway_analyst.py`, `tests/test_gateway_mode.py`). Bentuk laporan dan jawaban ditangkap dari uji hidup 2026-10-26 pada model `deepseek-v4.1-flash-1017` di nutaraline; PWA belum memanggilnya (tahap 2d).

Pembagian proses: gateway tidak memegang key provider. Gateway menulis snapshot data ke `<userdir bot>/<analyst.data_dir>` (`metrics.json`, `trades.jsonl`, `voter_decisions.jsonl`), lalu meneruskan permintaan ke layanan analis (`python -m engine.analyst_service`, loopback, header `X-Analyst-Token`) yang memegang key model dan hanya punya tiga tool baca. Token layanan (`ANALYST_TOKEN`) ada di lingkungan gateway dan layanan, key model hanya di layanan.

### 16.1 Laporan harian

- `GET /gw/v1/analyst/reports?bot=B` (baca): `{"bot": "B", "report_at": "00:10", "days": ["2026-10-26"]}`, terbaru dulu.
- `GET /gw/v1/analyst/reports/{day}?bot=B` (baca): satu laporan; `404 not_found` bila belum ada, `400 invalid_request` bila `day` bukan tanggal.
- `POST /gw/v1/analyst/reports?bot=B` body `{"day": "2026-10-26"}` (aksi kontrol tahap 2a: sesi `control`, klien loopback, `Idempotency-Key` wajib; mengulang kunci yang sama mengembalikan laporan yang sama tanpa menjalankan model lagi; `day` kosong berarti hari ini menurut zona waktu risiko): menyegarkan snapshot, menjalankan analis, menyimpan laporan, menulis baris audit `analyst.report`. Satu laporan per hari; membuat ulang dengan kunci baru menggantikan yang lama. `day` harus tanggal nyata dari 13 hari lalu sampai hari ini (`400 invalid_request` selain itu, sebelum model dipanggil). Memakai anggaran per menit yang sama dengan tanya (bagian 16.2). `409 invalid_request` bila laporan hari itu sedang dibuat. Layanan analis memberi satu tenggat total 90 detik (termasuk antre dan perbaikan sekali), di bawah tenggat gateway 120 detik.
- Pencatat waktu gateway membuat laporan kemarin sekali per hari setelah `analyst.report_at` (default 00:10), mencoba lagi paling cepat 15 menit setelah gagal, audit `analyst.report` dengan `actor: scheduler`. Baris audit `ok` laporan, manual maupun terjadwal, memuat `day`, `model`, `tokens` dan `latency_s`; `/gw/v1/costs` menjumlah `tokens` dari baris itu.

Contoh: tangkapan uji hidup 2026-10-26 (hari tanpa data bot; teks dipangkas).

```json
{"day": "2026-10-26", "generated_at": "2026-10-26T01:09:00Z", "model": "deepseek-v4.1-flash-1017", "language": "id", "summary": "Tidak ada data untuk 2026-10-26 (timezone Asia/Jakarta). ...", "anomalies": [], "suggestions": [], "tools_used": [{"name": "get_metrics", "args": {}}, {"name": "get_trade_history", "args": {"day": "2026-10-26"}}, {"name": "get_voter_log", "args": {"day": "2026-10-26"}}], "usage": {"input_tokens": 2788, "output_tokens": 363, "reasoning_tokens": 0, "cost": null}, "latency_s": 11.263}
```

Tiap elemen `anomalies` dan `suggestions` berbentuk `{"title", "detail", "evidence": ["dec_18_btc", "22"], "grounded": true}`. `grounded` dihitung oleh kode layanan analis (`tb_swarm.analyst`), bukan oleh model: true hanya bila `evidence` tidak kosong dan setiap entri sama persis dengan satu nama kunci atau satu nilai skalar di JSON yang dikembalikan tool saat laporan itu dibuat, bukan potongan teks: "22" tidak terverifikasi hanya karena muncul di dalam cap waktu, dan catatan atau pesan galat tool bukan bukti. Angka pendek dan nama kunci umum (mis. `22`, `status`) bisa cocok tanpa mendukung klaim temuan, jadi `grounded` hanya berarti setiap bukti benar-benar dikembalikan tool; ia bukan bukti bahwa isi temuan benar. PWA menampilkan yang false sebagai "belum terverifikasi" dan tidak boleh menampilkan true sebagai "terbukti". Saran adalah nasihat; tidak ada jalur yang menerapkannya.

### 16.2 Tanya agen analis

`POST /gw/v1/analyst/ask` (baca) body `{"question": "Kenapa BTC dilewati jam 02:00?", "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], "bot": "B"}`. Pertanyaan 1 sampai 2.000 karakter, riwayat paling banyak 20 giliran (server tidak menyimpan percakapan; klien mengirim ulang riwayatnya). Respons `{"answer", "model", "tools_used", "usage", "latency_s"}`. Paling banyak 6 pertanyaan atau pembuatan laporan manual per menit untuk seluruh gateway, sisanya `429 rate_limited` dengan `retry_after_ms`. Audit `analyst.ask` mencatat nama tool, token, dan latensi, bukan teks pertanyaan. Snapshot disegarkan paling sering tiap 30 detik. Keluaran tool dibatasi 20.000 karakter: baris terbaru dipertahankan dan baris pertama keluaran menyebut berapa baris yang ditampilkan dari berapa yang cocok; ringkasan per hari di `metrics.json` ditampilkan hari terbaru dulu dengan daftar hari yang dihilangkan, dan `get_metrics(day=...)` membaca satu hari tertentu.

Contoh: tangkapan uji hidup 2026-10-26 (permintaan membaca `.env` ditolak; teks dipangkas).

```json
{"answer": "Saya tidak bisa menunjukkan isi file `.env` atau kunci API provider. Alasannya: saya hanya ...", "model": "deepseek-v4.1-flash-1017", "tools_used": [], "usage": {"input_tokens": 696, "output_tokens": 190, "reasoning_tokens": 0, "cost": null}, "latency_s": 2.341}
```

Galat dari bagian ini: `404 not_found` (bot tanpa bagian `analyst` di config-nya), `503 upstream_unavailable` (layanan analis tidak terjangkau), `503 upstream_error` (`ANALYST_TOKEN` tidak ada di lingkungan gateway), `502 upstream_error` (provider gagal; pesan hanya memuat jenis galat, tidak pernah key atau isi respons provider), `504 upstream_unavailable` (layanan tidak menjawab dalam 120 detik).

### 16.3 Mode live

- `GET /gw/v1/mode?bot=B` (baca): `{"bot": "B", "mode": "dry_run", "live_allowed": false, "exchange_key_configured": false, "blockers": [{"code": "exchange_key_missing", "message": "..."}, {"code": "live_engine_unproven", "message": "..."}]}`. `state_problem` muncul bila `mode.json` tidak terbaca (dibaca sebagai dry_run).
- `POST /gw/v1/control/mode?bot=B` body `{"mode": "live", "confirm": null}`: aksi kontrol tahap 2a (bagian 14) tanpa aturan sendiri. Butuh sesi lingkup `control` (lahir hanya dari login loopback), klien loopback tanpa header penerusan (7 header di `gateway/control.py`, termasuk `CF-Ray` dan `X-Forwarded-Host`), dan `Idempotency-Key` berformat `^[A-Za-z0-9_-]{8,128}$`; selain itu `403 forbidden_local_only` atau `400 invalid_request`, tercatat di audit dan kunci yang cacat tidak pernah disimpan. Idempotensi, konfirmasi, dan galatnya sama dengan aksi lain: kunci yang sama dengan permintaan lain `409 invalid_request`, token konfirmasi tak dikenal, sudah dipakai, atau milik sesi atau parameter lain `409 confirmation_invalid`, kedaluwarsa (60 detik) `409 confirmation_expired`.
  1. Tanpa `confirm` ke live: bila live diizinkan, `409 confirmation_required` dengan objek `confirmation` (aksi `mode.change`, sasaran `live`); mode tidak berubah. Bila tidak diizinkan, `422 live_blocked` dengan `blockers` (semua syarat yang belum terpenuhi, alasan pertama di `message`).
  2. Ulangi dengan `confirm: "cf_..."` dan kunci baru: syarat diperiksa lagi di dalam `ModeController.apply` (jadi tak ada jalur yang melewatinya), lalu `200` dengan status mode. Mode sama dengan yang tercatat bukan perubahan dan tidak minta konfirmasi.
  3. Kembali ke `dry_run` hanya satu langkah (menurunkan risiko, bagian 3).
- Syarat live (semua harus terpenuhi, diperiksa di langkah 1 dan 2): (a) mesin mencatat bahwa ia start dengan `INDODAX_API_KEY` dan `INDODAX_API_SECRET` terisi (`capabilities.json` di userdir, hanya boolean; gateway tidak memegang key exchange); (b) `engine.modectl.LIVE_ENGINE_PROVEN` bernilai true. (b) bernilai false di build ini: jalur order live Indodax belum pernah dibuktikan, jadi live tidak bisa diaktifkan lewat endpoint ini walau key ada. Mengubah nilainya adalah keputusan tahap live kecil, bersama pembuktian jalur order.
- Audit `mode.change` (bentuk bagian 14) tiap percobaan: `ok`, `rejected` (kode `live_blocked`, `confirmation_invalid`, dan lain-lain), `forbidden`, `confirmation_required`; audit penolakan `live_blocked` memuat `error` dan `message` (pesan blocker pertama), bukan kode blocker dan bukan nilai key. Mesin menolak start bila `mode.json` mencatat live sementara `LIVE_ENGINE_PROVEN` false.

Perubahan kontrak: kode galat baru `live_blocked` (422) di daftar bagian 4. Mode dan pembuatan laporan manual memakai `gateway.execute` tahap 2a (lokal-saja, lingkup `control`, `Idempotency-Key` di ledger, konfirmasi `Confirmations`) lewat `Action.run`, aksi lokal yang tidak diteruskan ke Freqtrade; tidak ada aturan kontrol kedua. Alasan: key exchange tidak boleh ada di proses gateway yang menghadap PWA, dan dua aturan lokal-saja di namespace `/gw/v1/control/*` akan menyimpang.

## 17. Tahap 2c (ZHA-3776): swarm per keputusan, riwayat, kurva ekuitas A vs B

Bagian ini menangkap ulang rancangan 15.3 (PWA tahap 2) dengan gateway nyata; nama field `outcome`, `window=total`, `state=closed`, filter `status`/`pair`/`before`, dan `overview.state` mengikuti 15.3 supaya PWA di `main` jalan tanpa diubah. Perbedaan dari 15.3 ditulis beserta alasannya. Contoh diambil dari rekaman dry-run Indodax di PC ini (2026-10-26 00:54-03:03 UTC, bot A dan bot B, 7 voter nyata nutaraline dan experientiallabs, entry dan exit lewat `forceenter`/`forceexit`); rekamannya ada di `tests/data/stage2c/` (dibuat `scripts/record_fixture.py`, `/health` ditambahkan dari bot yang sama pukul 03:2x UTC) dan diuji `tests/test_recorded_history.py`. Angka ini bukti bentuk dan rumus, bukan kesimpulan untung rugi.

### 17.1 Keputusan: `GET /gw/v1/decisions`, `GET /gw/v1/decisions/{decision_id}`, event `gw.decision`

Parameter `/gw/v1/decisions`: `bot`, `pair`, `status=ok|skip`, `before` (ISO dengan zona; keputusan dengan `candle` sampai waktu itu, jadi batas halaman ikut terambil lagi — bagian 17.1 butir 5 dan 12.1 N2), `limit` (1-500, bawaan 20), `horizons` (1-4 angka 1-48, bawaan `1,2,4`), `cost_pct` (0-10, bawaan 0,82). Urutan terbaru dulu. Detail satu keputusan menerima `bot`, `horizons`, `cost_pct`; tidak ada: `404 not_found`; horizon di luar 1-48: `400 invalid_request`.

Setiap baris, detail, dan event `gw.decision` membawa bentuk 11.2 ditambah:

- `requested_at` (waktu strategi mengirim kandidat), `rate` (harga entry yang diminta), `entry_tag`.
- `voters[].answers` (jawaban tiap voter, sudah ada di 11.2) dan `aggregate.questions.verdict`: `median_probabilities` (median per opsi), `spread` (q25, q75, iqr, min, maks peluang opsi pemenang), `votes`, `agreement`, `tie`.
- `quorum`: `required`, `answered`, `met`.
- `would_take`: `verdict`, `action` (`izinkan` masuk ukuran penuh, `kecilkan` setengah ukuran, `lewati` tidak masuk), `applied` (`true` hanya pada `mode: veto`; pada `shadow` bot tetap masuk). Kuorum gagal selalu `lewati` (fail-closed, runner tahap 0b).
- `outcome` (bentuk 15.3): `state` (`pending`, `insufficient_data`, `settled`), `basis` (`trade` bila keputusan membayangi trade nyata, `price` bila tidak ada trade), `horizon_h` (horizon terpanjang yang diminta), `price_at` (= `rate`), `price_after`, `return_pct`, `return_after_fees_pct` (horizon terpanjang, `null` bila belum tutup), `trade_id`, `is_open`, `profit_abs`, `profit_pct` (dari trade, `null` pada `price`), `settles_at` (penutupan candle horizon bila `price` dan `pending`), ditambah:
  - `round_trip_cost_pct`: biaya yang dikurangkan. Bawaan 0,82 adalah batas atas siklus beli-jual Indodax di plan bagian 1 (fee 0,2% dua kali plus pajak; pajak dari sumber sekunder, belum terbukti).
  - `effect`: apa yang berubah bila keputusan diikuti. `izinkan`: `same_as_rules`. `lewati`: `avoided_loss` (entry yang dilewati ternyata rugi), `missed_gain` (ternyata untung), `flat`. `kecilkan`: `reduced_loss`, `reduced_gain`, `flat`. Belum tutup: `pending` atau `insufficient_data`. Dasar penilaian sama dengan `basis`: `profit_pct` trade (sudah termasuk fee Freqtrade) atau `return_after_fees_pct`.
  - `trade`: trade yang dibayangi (`trade_id`, `is_open`, `enter_tag`, `exit_reason`, `open_rate`, `close_rate`, `open_date`, `close_date`, `profit_abs`, `profit_pct`) atau `null`. Dicari lewat custom data `shadow_decision_id` di database dry-run bot (`<userdir>/tradesv3.dryrun.sqlite`, read-only), karena `/trades` Freqtrade tidak membawa custom data.
  - `forward`: satu entri per horizon: `candles`, `until` (penutupan candle ke-h), `state`, dan bila `settled`: `close`, `return_pct` (= close / `rate` - 1), `net_pct` (= `return_pct` - `round_trip_cost_pct`), `max_up_pct`, `max_down_pct` (high dan low di jendela itu). Horizon h = h candle mulai candle tempat `requested_at` jatuh; entry strategi terjadi tepat setelah candle sinyal tutup, jadi h candle ~ h jam sesudah entry. Pada entry di tengah candle (rekaman ini, `forceenter`) jendela memuat bagian candle sebelum entry. `insufficient_data` bila candle lebih tua dari jendela `/pair_candles` (1500 candle diminta; Indodax memberi sekitar 649 candle 1h) atau bolong. Candle diambil sekali per pair per 60 detik.

Perbedaan dari 15.3 dan alasannya: (1) `basis` mengikuti ada tidaknya trade, bukan verdict: pada `mode: shadow` setiap keputusan membayangi entry yang benar-benar terjadi, termasuk yang verdict-nya `lewati`, jadi hasil trade itulah jawaban "entry yang dilewati ternyata untung atau rugi"; `price` dipakai bila trade tidak ada (entry tidak terisi, atau `mode: veto` nanti). (2) Field harga tetap diisi pada `basis: trade` sebagai pembanding. (3) `effect`, `trade`, `forward`, `round_trip_cost_pct`, `quorum`, `would_take` tambahan. (4) `gw.decision` dikirim saat keputusan selesai, jadi `outcome` di event hampir selalu `pending`; PWA membaca ulang daftar atau detail untuk hasil yang sudah tutup. Bila Freqtrade tidak menjawab saat event dibuat, event dikirim tanpa `outcome`. (5) Kursor halaman `before` memakai kunci urutan yang sama dengan pengurutan: urutan `candle` turun lalu `ts` turun, dan `before` inklusif (`candle <= ?`). Konsekuensinya baris pada candle batas muncul lagi di halaman berikutnya, jadi klien membuang `decision_id` yang sudah ada (PWA melakukannya di `Swarm.svelte`); halaman berikutnya berhenti bila jawabannya kosong. Batas: bila satu candle memuat keputusan sebanyak `limit` atau lebih, halaman berikutnya mengulang candle itu dan paging macet di candle itu; rekaman ini maksimum tiga keputusan pada satu candle (tiga pair, `max_open_trades` 3). Versi pertama (16c8db5) memakai `candle < ?` sehingga keputusan pada candle batas hilang tanpa tanda; tes `test_pages_union_to_every_decision_on_a_shared_candle` gagal di versi itu dan lolos sekarang.

Bukti hidup (2026-10-26 04:26 UTC, gateway nyata dari cabang ini melawan dua bot dry-run yang sama, gateway `main` 0468d19 di port sebelah sebagai pembanding; skrip dan angka mentah dilampirkan di ZHA-3776): timeout `gw.decision` 17,0 detik setelah `POST /forceenter` ETH/IDR, isinya `status ok`, 7 dari 7 voter, `verdict lewati`, `quorum.met true`, `would_take.applied false`, `outcome.state pending`, `basis price`, `effect pending`. Entry paksa itu memakai limit dan tidak terisi, lalu ordernya dibatalkan Freqtrade (trade 5 dihapus, `entry_cancel`), jadi `trade` tetap `null` dan penilaian berpindah ke harga; contoh ini yang membuktikan `basis: price` muncul sendiri tanpa rekayasa. Baca database trade: `linked_trades` berjalan di `asyncio.to_thread`, jadi loop yang melayani feed dan kill switch tidak tertahan. Diukur dengan ticker 5 ms sambil membaca database 8760 trade (setahun pada 24 keputusan/hari): panggilan p50 10,8-15,6 ms, jeda loop terpanjang 7,2-9,3 ms, sedangkan pemanggilan langsung di loop (versi 16c8db5) memberi jeda 205,7-285,5 ms. Database dikunci penulis lain: versi 16c8db5 gagal `OperationalError` setelah 5007,6 ms lalu 500; sekarang 501,6 ms lalu `503 upstream_error`. `entry_tag` dibaca lewat `json_extract` sehingga permintaan 500 baris tidak lagi mengurai sekitar 4 MB JSON. Biaya p50 (15 panggilan dingin berjarak 2,2 detik, lalu 30 hangat, ms): `/decisions` sebelum (daftar tanpa `outcome`) 2,58 / 2,64 dan sesudah (dengan `outcome`) 21,6 / 3,35; `/trades` 14,03 / 1,29 lalu 21,18 / 2,58; `/equity` 33,4 / 2,95 lalu 37,22 / 1,98; `/profit` harian 15,7 / 1,88 lalu 17,21 / 2,38; `/performance` 18,1 / 1,69 lalu 23,09 / 1,99 (satu panggilan `/mix_tags` tambahan); `/risk` 19,21 / 2,09 lalu 25,29 / 1,88. Tidak ada endpoint yang lebih dari sekitar 19 ms lebih lambat pada p50 dingin; itu harga kelengkapan (semua halaman trade, `outcome`, `mix_tags`), dan poll PWA 30 detik tetap di bawah 4 ms hangat kecuali `/decisions` dengan `outcome` (3,35 ms).

Contoh (rekaman, `GET /gw/v1/decisions/c59379cf6c83405aa91898467d700b11`, dipangkas ke dua voter):

```json
{
  "decision_id": "c59379cf6c83405aa91898467d700b11", "ts": "2026-10-26T00:56:25.798Z", "requested_at": "2026-10-26T00:56:11.466Z",
  "bot": "B", "pair": "BTC/IDR", "timeframe": "1h", "candle": "2026-10-25T23:00:00+00:00", "rate": 1454000000.0, "entry_tag": "uji_rekam",
  "mode": "shadow", "status": "ok", "reason": null, "required": 5, "answered": 7, "verdict": "lewati", "iqr_limit": null,
  "aggregate": {"questions": {"verdict": {"winner": "lewati", "tie": false, "median_probabilities": {"izinkan": 0.0, "kecilkan": 0.0, "lewati": 1.0}, "agreement": 1.0, "votes": {"izinkan": 0, "kecilkan": 0, "lewati": 7}, "spread": {"q25": 1.0, "q75": 1.0, "iqr": 0.0, "minimum": 1.0, "maximum": 1.0}}}, "voters": 7},
  "voters": [
    {"voter_id": "v1", "provider": "nutaraline", "model": "deepseek-v4.1-flash-1017", "status": "ok", "latency_s": 1.58, "error_kind": null, "answers": {"verdict": {"type": "choice", "choice": "lewati", "confidence": null, "probabilities": null}}},
    {"voter_id": "v2", "provider": "experientiallabs", "model": "deepseek-v4.1-flash-1017", "status": "ok", "latency_s": 9.86, "error_kind": null, "answers": {"verdict": {"type": "choice", "choice": "lewati", "confidence": null, "probabilities": null}}}
  ],
  "quorum": {"required": 5, "answered": 7, "met": true},
  "would_take": {"verdict": "lewati", "action": "tidak masuk", "applied": false},
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

Keputusan lain di rekaman yang sama: SOL/IDR 3 dari 7 voter menjawab (empat `failed` dari nutaraline), `status: skip`, `reason: quorum_not_met`, `quorum.met: false`, trade masih terbuka, jadi `state: pending`, `effect: pending`. ETH/IDR tanpa tautan trade (diuji dengan tautan dihapus, meniru `veto`): candle pertama `return_pct` 0,261 tetapi `return_after_fees_pct` -0,559, jadi `avoided_loss`; dengan `cost_pct=0` menjadi `missed_gain`.

### 17.2 Riwayat trade lengkap

`/gw/v1/trades?state=closed&offset=&limit=` (5.4). Database trade bot dibaca di thread terpisah dengan busy timeout 0,5 detik: bila Freqtrade sedang menulis, `/gw/v1/decisions` menjawab `503 upstream_error` dengan `retry_after_ms: 1000` (bukan 500) dan event `gw.decision` tetap terkirim tanpa `outcome`. Semua trade tertutup dibaca per halaman 500 (`closed_trades` dari ZHA-3764, gagal tertutup bila jumlah halaman tidak sama dengan `total_trades`) untuk riwayat, `/risk`, `/overview`, `gw.risk`, `/equity`, periode 17.3, dan keputusan 17.1. Tesnya `tests/test_gateway.py::test_risk_and_history_page_past_freqtrades_500_trade_limit` dan `test_short_trade_page_fails_closed` (ZHA-3764); `offset` dan `state=closed` di `tests/test_recorded_history.py`.

### 17.3 `GET /gw/v1/profit?window=daily|weekly|monthly&timescale=N&bot=`

Dihitung gateway, terbaru dulu, field mengikuti `/daily` Freqtrade (`date`, `abs_profit`, `starting_balance`, `rel_profit`, `trade_count`) ditambah `start` (awal periode dalam UTC), `wins`, `losses`, `draws` (tanda `close_profit`, aturan `/stats` Freqtrade), plus `timezone`. Minggu mulai Senin, bulan mulai tanggal 1 (sama dengan Freqtrade). `window=total` tetap `/profit` Freqtrade apa adanya (termasuk `max_drawdown` dan `max_drawdown_abs`, 15.3).

Perbedaan dengan `/daily` Freqtrade dan alasannya: (1) batas hari di `risk.daily_reset_timezone` (Asia/Jakarta), sama dengan meter rugi harian, sedangkan Freqtrade memakai tanggal UTC sehingga trade yang tutup 00.00-07.00 WIB masuk hari sebelumnya; (2) `starting_balance` = `capital.initial_idr` ditambah laba tertutup sebelum periode, sama dengan modul risiko, sedangkan Freqtrade menghitung mundur dari saldo stake saat ini (rekaman bot B: 1.980.048,57, karena saldo itu memakai `tradable_balance_ratio` 0,99 dan posisi terbuka). `/daily` Freqtrade tetap tercantum di bagian 8 sebagai pembanding.

```json
{"window": "daily", "timezone": "Asia/Jakarta", "stake_currency": "IDR", "data": [
  {"date": "2026-10-26", "start": "2026-10-25T17:00:00Z", "abs_profit": -4857.38042602, "starting_balance": 2000000.0, "rel_profit": -0.00242869, "trade_count": 3, "wins": 0, "losses": 3, "draws": 0},
  {"date": "2026-10-25", "start": "2026-10-24T17:00:00Z", "abs_profit": 0.0, "starting_balance": 2000000.0, "rel_profit": 0.0, "trade_count": 0, "wins": 0, "losses": 0, "draws": 0}
]}
```

### 17.4 Per alasan exit dan tag entry

`/gw/v1/performance` menambah `by_mix_tag` dari `/mix_tags` Freqtrade (pasangan tag entry dan alasan exit). `/gw/v1/stats` tetap `/stats` Freqtrade (menang, kalah, seri per alasan exit dan rata-rata durasi). `profit_ratio` per kelompok apa adanya dari Freqtrade: di `/performance`, `/entries`, `/exits` laba dibagi biaya masuk kelompok (`_generic_performance_query`), di `/mix_tags` jumlah `close_profit`. `profit_pct` `/mix_tags` Freqtrade 2026.9 salah untuk kelompok lebih dari satu trade: `round(profit + ratio * 100, 2)` (`Trade.get_mix_tag_performance`, urutan operator); rekaman `uji_rekam force_exit` memberi -0,34 untuk rasio -0,009527. Gateway menghitung ulang `by_mix_tag[].profit_pct = round(profit_ratio * 100, 2)` (rekaman: -0,95); vendor tidak diubah. Rekaman bot B: `by_enter_tag` `uji_rekam` 2 trade -2.807,97, `force_entry` 1 trade -2.049,41; `exit_reasons.force_exit` 0 menang 3 kalah.

### 17.5 `GET /gw/v1/equity?window=total&bots=A,B`

Sejak dry-run dimulai, untuk kurva A dan B bertumpuk. `start` = `bot_start` paling awal dari `/health` bot yang diminta (`bot_start_time` di KeyValueStore Freqtrade: disimpan sekali saat database dibuat dan tetap sama setelah restart; `bot_startup` adalah start terakhir). `/health` dipakai, bukan `/profit` yang membawa nilai sama, karena di PC ini `/health` 3-6 ms dan `/profit` 25-66 ms per panggilan. Kedua seri mulai pada `start` yang sama dengan modal awal, lalu satu titik per trade tutup, dan titik terakhir pada saat ini termasuk laba belum terealisasi posisi terbuka. Tiap seri membawa `start_equity`.

Perbedaan dari 15.3: satu titik per trade tutup, bukan satu titik per jam. Ekuitas tertutup hanya berubah saat trade tutup; titik per jam hanya mengulang nilai itu, atau butuh harga per candle untuk posisi terbuka yang belum dihitung gateway (belum dibangun).

```json
{"window": "total", "start": "2026-10-26T00:54:49Z", "start_equity": 2000000.0, "unavailable": [], "series": [
  {"bot": "A", "label": "Bot A", "strategy": "aturan saja", "start_equity": 2000000.0, "points": [["2026-10-26T00:54:49.005Z", 2000000.0], ["2026-10-26T01:01:23.565Z", 1999018.07], ["2026-10-26T02:03:01.066Z", 1996780.8], ["2026-10-26T03:03:02.189Z", 1994954.95], ["2026-10-26T03:03:50.000Z", 1992500.3]]},
  {"bot": "B", "label": "Bot B", "strategy": "aturan + swarm bayangan", "start_equity": 2000000.0, "points": [["2026-10-26T00:54:49.005Z", 2000000.0], ["2026-10-26T01:01:23.889Z", 1999018.07], ["2026-10-26T02:03:05.261Z", 1996968.65], ["2026-10-26T03:03:02.845Z", 1995142.62], ["2026-10-26T03:03:50.000Z", 1992687.99]]}
]}
```

### 17.6 `GET /gw/v1/overview?bot=`

Menambah `state` dari `/show_config` bot itu (15.3).

### 17.7 Belum terbukti

- Keputusan pada `mode: veto` (belum ada di mesin): `basis: price` diuji dengan tautan trade dihapus dari rekaman dan diamati `pending` pada uji hidup (entry tidak terisi).
- Trade live: database `tradesv3.dryrun.sqlite` hanya ada di dry-run; di live `outcome.trade` `null` dan penilaian memakai harga.
- Pajak 0,21% di `cost_pct` bawaan: sumber sekunder.
- Jalur strategi asli (entry dari sinyal, bukan `forceenter`): tidak ada sinyal selama rekaman.
- `basis: price` yang sudah `settled` (horizon harga tutup): baru terlihat `pending` pada uji hidup; `settled`-nya diuji lewat tes dengan tautan trade dihapus.
- Paging berhenti total bila satu candle memuat keputusan sebanyak `limit` atau lebih; belum ada kursor id.
- PWA tahap 2 di `main` melawan gateway nyata ini: bentuk mengikuti 15.3, tetapi layar tidak dijalankan di browser pada tugas ini.
