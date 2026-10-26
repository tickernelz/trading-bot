# trading-bot

Bot trading otonom 24 jam (crypto spot, dry-run dulu) dengan swarm voter dan median sebagai penyaring entry, plus panel kontrol PWA.

Status: tahap 1 (dua bot dry-run, swarm bayangan, gateway). Belum ada akun atau uang yang terhubung, belum ada API key exchange, dan belum ada mode live. Profit tidak dijamin.

## Isi

- vendor/freqtrade: engine Freqtrade sebagai git submodule, terkunci di tag 2026.9
- engine/: launcher, skema konfigurasi, lapisan risiko, strategi
- engine/settings.py: skema tunggal config/config.yaml, divalidasi sebelum mesin start
- engine/risk.py: batas rugi harian, batas drawdown, ukuran posisi berbasis risiko
- engine/news.py: pengambil judul RSS CoinDesk dan Cointelegraph serta Fear and Greed alternative.me untuk lapisan grafik (cache 15 menit dan 1 jam, diambil hanya saat diminta)
- engine/strategies/swing_ema_rsi.py: strategi swing 1h (EMA 20/50 + RSI) dengan gerbang risiko
- engine/launch.py: validasi config, render config Freqtrade (database trade di userdir), exec Freqtrade
- engine/heartbeat.py: berkas heartbeat dan log start per bot
- engine/shadow.py, engine/shadow_client.py: layanan swarm bayangan bot B dan pengirim kandidat dari strategi
- engine/decisions.py: penyimpanan SQLite keputusan swarm dan penghubung ke trade
- gateway/: gateway antara PWA dan bot (docs/gateway-api.md bagian 12); konfigurasi, provider, key, voter (bagian 17)
- scripts/stack.sh: menjalankan bot A, bot B, layanan bayangan, layanan analis, gateway, dan PWA sebagai unit systemd user
- scripts/measure_gateway.py: ukur jeda fill dan beban klien gateway
- scripts/stack_report.py: ringkasan satu lari mesin
- scripts/record_fixture.py: rekam jawaban Freqtrade dan keputusan swarm dari lari dry-run ke tests/data untuk tes gateway (docs/gateway-api.md bagian 13)
- docker/Dockerfile, docker-compose.yml: image turunan dari vendor/freqtrade, jaringan host
- docs/plan.md: plan final
- docs/gateway-api.md: kontrak API gateway dan feed event untuk PWA
- docs/research-swarm-pwa.md: riset dan sumber
- pwa: panel PWA baca-saja tahap 1 dan gateway tiruan berdata contoh (lihat pwa/README.md)
- config/config.example.yaml: contoh konfigurasi
- tests/: tes pytest untuk skema, lapisan risiko, strategi, launcher
- .env.example: nama variabel lingkungan

## Setelah clone

    git clone --recurse-submodules <url>
    git config core.hooksPath .githooks
    mkdir -p .agents/skills && ln -s ~/.agents/skills/impeccable .agents/skills/impeccable

Bila sudah clone tanpa --recurse-submodules: git submodule update --init

## Menjalankan dry-run

Butuh Docker di mesin yang sama; diuji di WSL2 dengan Docker Engine 29.9.2.

    cp .env.example .env
    mkdir -p user_data
    cp config/config.example.yaml config/config.yaml

Isi FT_API_USERNAME, FT_API_PASSWORD, FT_API_JWT_SECRET (minimal 32 karakter) di .env (jangan di-commit). Hanya trade dan webserver yang membuka API dan membutuhkan ketiganya; download-data, backtesting, dan show-config berjalan tanpa API server. Config contoh menyalakan swarm bayangan, jadi trade dan webserver juga butuh SHADOW_TOKEN (minimal 32 karakter, sama dengan milik layanan bayangan); untuk bot aturan saja set `swarm.enabled: false` dan hapus bagian `shadow`. `ws_token` Freqtrade sengaja tidak dipakai: gateway menyambung WebSocket dengan JWT 15 menit (docs/gateway-api.md bagian 8). Lalu:

    docker compose build bot
    docker compose up -d bot
    docker compose logs -f bot

Bot listen di 127.0.0.1:8080 (api.listen dan api.port di config). Bila konfigurasi tidak valid, kontainer berhenti dengan kode 2 dan pesan refusing to start; tidak ada order yang dibuat.

Perintah Freqtrade lain memakai launcher yang sama, sehingga validasi tetap berlaku. Jalankan langsung dari image yang sudah dibangun (docker compose run akan membangun ulang image dasar yang butuh belasan menit):

    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev download-data --days 120 --timeframes 1h
    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev backtesting --timerange 20250601-
    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev show-config

Jaringan: network_mode host dipakai supaya bot bisa menjangkau provider LLM yang hanya listen di 127.0.0.1 host (dibuktikan di WSL2: 127.0.0.1:62173 dan 127.0.0.1:20128 menjawab 401 dari dalam kontainer, sedangkan host.docker.internal dengan host-gateway hanya menghasilkan 000). Jalur Docker Desktop di Windows belum diuji. api.listen dibatasi skema ke 127.0.0.1 atau ::1, jadi REST tidak pernah terbuka ke LAN; untuk Docker Desktop rencananya jaringan bridge dengan publish 127.0.0.1:8080:8080, tetap belum diuji.

## Tahap 1: dua bot, swarm bayangan, gateway

Empat proses, satu image (`trading-bot/engine`), semuanya hanya mendengarkan 127.0.0.1:

| Komponen | Port | Isi |
| --- | --- | --- |
| bot-a | 8080 | Freqtrade, aturan saja (`swarm.enabled: false`) |
| bot-b | 8081 | Freqtrade, aturan yang sama; tiap entry yang lolos lapisan risiko dikirim ke layanan bayangan tanpa menunggu jawaban |
| shadow-b | 8091 | `POST /candidates` hanya dengan header `X-Shadow-Token` yang sama dengan SHADOW_TOKEN. Swarm voter nyata; mencatat jawaban, median, sebaran, kuorum, dan verdict yang AKAN diambil ke `bot-b/swarm_decisions.sqlite`. Tidak pernah memengaruhi order |
| gateway | 8090 | Sesi, endpoint baca, feed, kesehatan, biaya dan token, audit |

Susunan voter contoh mengikuti tahap 0c (tujuh voter aktif di tujuh provider berbeda, docs/stage0-findings.md). Alasan tidak menaruh banyak voter pada satu key terukur 2026-10-26 02:0x UTC lewat `ShadowService` dengan voter nyata, satu kandidat BTC/IDR yang sama tiap ronde dan jeda 2 s antar ronde (keluaran mentah per keputusan dan per voter terlampir di ZHA-3764):

| Susunan | Ronde | Panggilan voter | Keputusan |
| --- | --- | --- | --- |
| 7 voter pada satu key nutaraline | 5 | 18 sah, 17 HTTP 429 "Laju request per key melebihi batas" | kuorum 5 gagal 3 dari 5 |
| 4 nutaraline + 3 experientiallabs | 8 | 56 dari 56 sah | 7 dari 7 menjawab di 8 dari 8; 5 `ok`, 3 `choice_tie` |
| 3 nutaraline + 2 tiprouter + 2 experientiallabs | 5 | tiprouter 0 dari 10 (6 HTTP 503, 4 timeout 30 s) | kuorum 5 tercapai karena 5 voter lain |

Latensi jawaban sah pembagian 4+3: nutaraline median 1,6 s maks 2,7 s; experientiallabs median 6,4 s maks 26,9 s. Maks experientiallabs dekat `timeout_s` 30, jadi timeout voter itu perlu dipantau. `choice_tie` adalah seri antar jawaban voter (aturan agregasi), bukan galat provider.

Mode `swarm.mode: veto` ditolak skema sampai gerbang dibangun. Trade yang dibayangi membawa custom data `shadow_decision_id`, sehingga `DecisionStore.outcomes(<tradesv3.dryrun.sqlite>)` bisa menghitung apakah entry yang akan dilewati ternyata rugi.

Setiap bot menulis `heartbeat.json` tiap loop dan menambah satu baris di `starts.jsonl` tiap start. Setelah start, bot menolak semua entry sampai cek start lolos: posisi terbuka dihargai dan batas rugi harian serta drawdown dinilai; hasilnya dikirim sebagai `strategy_msg` `startup_check`. Semua ini, ditambah pengiriman kandidat ke layanan bayangan, hanya berjalan di runmode `dry_run` dan `live`: Freqtrade juga memanggil `bot_start`, `bot_loop_start`, `confirm_trade_entry`, dan `order_filled` saat backtest, hyperopt, dan webserver, dan di sana strategi tidak menyentuh berkas bot hidup maupun voter. Launcher hanya merender alamat layanan bayangan dan mewajibkan SHADOW_TOKEN untuk perintah `trade`.

Direktori jalan (di luar repo), contoh `~/Projects/trading-bot-runs/machine-test`:

    config/bot-a.yaml config/bot-b.yaml config/gateway.yaml
    secrets/ft.env        FT_API_USERNAME, FT_API_PASSWORD, FT_API_JWT_SECRET (bot-a, bot-b)
    secrets/shadow.env    SHADOW_TOKEN, minimal 32 karakter (bot-b, shadow-b)
    secrets/swarm.env     kunci provider voter, mis. NUTARALINE_API_KEY, EXPERIENTIALLABS_API_KEY (shadow-b)
    secrets/gateway.env   GW_PASSWORD (minimal 12 karakter), FT_API_USERNAME, FT_API_PASSWORD, ANALYST_TOKEN (gateway)
    secrets/analyst.env   key provider analis, ANALYST_TOKEN minimal 32 karakter (analyst-b)

Tiap proses hanya menerima berkas rahasia yang dipakainya: gateway tidak memegang JWT secret Freqtrade, bot tidak memegang kunci provider, layanan bayangan tidak memegang kredensial Freqtrade. Kontainer hanya memasang `config/` (baca saja) dan direktori data komponennya; `secrets/` tidak pernah masuk kontainer (`--env-file` dibaca di host).
    bot-a/ bot-b/ gateway/

PWA tidak punya direktori data: unit PWA melayani hasil build dari checkout repo (`pwa/`).

`config/bot-*.yaml` berasal dari `config/config.example.yaml` dengan `bot_id`, `api.port`, dan `swarm.enabled` berbeda; `config/gateway.yaml` dari `config/gateway.example.yaml` dengan path di bawah `/opt/trading-bot/run`. Lalu:

    docker build -f docker/Dockerfile --build-context freqtrade-base=docker-image://trading-bot/freqtrade:2026.9 --target engine -t trading-bot/engine:<sha> .
    RUN_DIR=~/Projects/trading-bot-runs/machine-test IMAGE=trading-bot/engine:<sha> scripts/stack.sh start
    RUN_DIR=... IMAGE=... scripts/stack.sh status
    RUN_DIR=... scripts/stack.sh stop bot-b

Ringkasan lari (uptime dari baris `Bot heartbeat` di journald dengan celah di atas 180 detik dihitung mati, restart, order per status, baris ERROR, keputusan swarm, jam bot B sejak jawaban voter nyata pertama, token, hasil trade yang dibayangi, jeda fill):

    PYTHONPATH=. python3 scripts/stack_report.py --run-dir ~/Projects/trading-bot-runs/machine-test --unit-prefix trading-bot-stack

Rekam data uji gateway dari lari yang sedang jalan (butuh `secrets/ft.env` dan `RUN_STARTED_AT` di direktori lari; `show_config` disimpan hanya field yang dipakai gateway):

    docker run --rm --network host -v $PWD:/src:ro -v <run-dir>:/run-dir:ro -v <out>:/out -w /src -e PYTHONPATH=/src --entrypoint python trading-bot/engine:<sha> scripts/record_fixture.py --run-dir /run-dir --out /out

Unit systemd user transien (`Restart=always`) bertahan saat sesi terminal atau server lain di-restart; restart dihitung dari `starts.jsonl`. Log: `journalctl --user -u trading-bot-stack-bot-a`.

Dampak ke mesin dibatasi: tiap kontainer membawa `--cpus` (bot 1.0; layanan bayangan, analis, dan gateway 0.5) dan `--memory`; unit PWA berjalan di host tanpa kontainer dengan `Nice=10` dan `CPUQuota=50%`. `stack.sh start pwa` menjalankan `npm ci` bila `pwa/node_modules` belum ada, `npm run build`, lalu `npm run preview` melayani `http://127.0.0.1:4173` dan meneruskan `/gw` ke `GATEWAY_URL`.

## Tahap 2b: konfigurasi, provider, key, voter

Gateway menulis konfigurasi bot lewat `PATCH /gw/v1/settings` (validasi skema `engine/settings.py`, catatan perubahan di audit, kenaikan batas risiko dua langkah), mengelola provider dan key (`/gw/v1/providers`, key hanya dari 127.0.0.1, tampilan 4 karakter terakhir, impor dari omp models.yml, uji koneksi), dan registri voter (`/gw/v1/voters`, `/gw/v1/roles`). Kontrak dan yang belum terbukti: docs/gateway-api.md bagian 17. Perubahan butuh restart mesin; gateway tidak me-restart apa pun.

## Kanal Telegram (nonaktif bawaan)

Kanal kontrol memakai Telegram bawaan Freqtrade (perintah /status, /profit, /balance, /daily, /stopentry, /start, /stop, /forceexit, /reload_config, /help, dan lainnya). Bawaannya mati. Untuk menyalakan, isi di config/config.yaml:

    notify:
      telegram:
        enabled: true
        token_env: TELEGRAM_BOT_TOKEN
        chat_id: "<id chat>"
        authorized_users: ["<id user Telegram>"]

lalu isi TELEGRAM_BOT_TOKEN di .env. Token hanya lewat variabel lingkungan (FREQTRADE__TELEGRAM__TOKEN), tidak pernah ditulis ke config Freqtrade yang dirender. Launcher menolak start bila kanal menyala tanpa chat_id, tanpa authorized_users, atau tanpa token. Hanya perintah trade yang memuat kanal ini.

Risiko yang diterima saat menyalakan: perintah Telegram dijalankan Freqtrade langsung, tanpa konfirmasi dua langkah dan tanpa log audit gateway (docs/gateway-api.md bagian 3). /forcelong tetap tertolak selama api.force_entry false. Pesan dari chat atau user lain diabaikan Freqtrade.

Bukti: tests/test_telegram_channel.py menjalankan modul Telegram Freqtrade asli terhadap Bot API tiruan lokal (chat pemilik mendapat jawaban /status, /stopentry, /help; /stopentry dari chat lain tidak mengubah keadaan). Belum terbukti dengan bot Telegram sungguhan karena belum ada token.

## Tes

    docker compose --profile test build tests
    docker compose --profile test run --rm tests

Tes berjalan di dalam image turunan Freqtrade, jadi versi Freqtrade, ccxt, dan pandas sama dengan produksi. Kontrol negatif: matikan pemeriksaan batas di engine/risk.py (ganti kedua if batas menjadi if False:) lalu jalankan tes; tes batas wajib gagal.

## Analitik

Paket analytics/ menyediakan pratinjau what-if batas risiko dan putar ulang jawaban voter, papan skor voter, uji stres turun 10 persen, ekspor CSV dan ringkasan pajak sebagai informasi, portofolio per pair, serta sinyal strategi dan backtest lewat instans Freqtrade mode webserver. Bentuk endpoint ada di bagian 13 docs/gateway-api.md; ambang dan tarif diatur di bagian analytics config. Rutenya dipasang ke gateway lewat `gateway/analytics_context.py`; `analysis_url` di config gateway menunjuk instans webserver (port 8092 di contoh) yang config-nya memakai `api.port: 8092`.

Sinyal dan backtest butuh instans mode webserver dengan data OHLCV di userdir-nya (bot mode trade menjawab 503 untuk /pair_history dan /backtest):

    docker run --rm --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev download-data --days 25 --timeframes 1h
    docker run -d --network host --env-file .env -v ./config:/opt/trading-bot/config:ro -v ./user_data:/freqtrade/user_data trading-bot/engine:dev webserver

Pair tambahan cukup ditulis di exchange.pairs (dan risk.max_open_trades dinaikkan); setiap pair menambah panggilan voter per kandidat entry.

## Batasan Indodax yang terukur

- Freqtrade 2026.9 mencetak peringatan bahwa indodax tidak didukung resmi dan memakai kelas exchange generik, tetapi OHLCV 1h BTC/IDR, ETH/IDR, SOL/IDR terambil.
- ccxt 4.5.84 melaporkan biaya taker Indodax 0.2 sebagai rasio (bukan 0,2%), sehingga Freqtrade akan memakai biaya 20% bila tidak ditimpa. Karena itu exchange.fee_pct: 0.2 wajib di config dan dirender menjadi fee: 0.002.
- ccxt melaporkan fetchMyTrades dan watchOHLCV tidak tersedia (dilaporkan Freqtrade sebagai missing opt).
- Satu permintaan OHLCV dengan rentang panjang hanya mengembalikan candle terbaru (1h: 649 candle, 27 hari), sehingga download-data Freqtrade berhenti di 27 hari. Riwayat 1h sendiri tersedia minimal sejak 2023-10-01: engine/history.py mengambilnya per jendela 500 candle (docs/stage2-backtest.md).

## Backtest tahap 2

    IMAGE=trading-bot/engine:dev scripts/stage2_backtest.sh user_data/stage2

Mengunduh riwayat 1h tiga pair sejak 2023-10-01, lalu menjalankan delapan backtest yang matriksnya dikunci di engine/backtest_suite.py (in-sample dan out-of-sample, fee 0,2% dan pajak 0,21% per sisi, pembanding fee saja dan tanpa biaya, batas risiko apa adanya dan dimatikan). Hasil: report.json dan report.md di direktori keluaran. Temuan: docs/stage2-backtest.md.

## Memperbarui Freqtrade

    git -C vendor/freqtrade fetch --depth 1 origin tag <tag>
    git -C vendor/freqtrade checkout <tag>
    git add vendor/freqtrade
    git commit -m "build(vendor): bump freqtrade to <tag>"

Strategi dan data pengguna ada di luar vendor/freqtrade (--strategy-path dan --userdir), jadi isi vendor tidak diubah. Bila suatu saat perlu memodifikasi engine, fork Freqtrade lalu arahkan url di .gitmodules ke fork itu.

## Rahasia

API key boleh lewat variabel lingkungan (salin .env.example ke .env) atau langsung di config/config.yaml. Kedua berkas itu ada di .gitignore dan tidak boleh di-commit. Config Freqtrade yang dirender launcher tidak pernah memuat rahasia: kredensial API hanya masuk lewat variabel lingkungan FREQTRADE__API_SERVER__* saat exec.

## Aturan repo

- Commit memakai Conventional Commits berbahasa Inggris, subject di bawah 72 karakter, tanpa trailer Co-Authored-By.
- Tidak ada komentar di kode kita. Isi vendor/freqtrade adalah kode pihak ketiga dan tidak diubah.
- Belum ada remote dan belum ada berkas LICENSE (Freqtrade berlisensi GPL-3.0).


## Tahap 3a: agen analis dan kontrol mode live

Satu proses baru, `analyst-b` (port 8092, loopback), dan dua kelompok endpoint gateway; kontrak di `docs/gateway-api.md` bagian 16, angka dan batas bukti di `docs/stage3a-findings.md`.

| Komponen | Isi |
| --- | --- |
| analyst-b | `python -m engine.analyst_service`. Memegang key model analis (`secrets/analyst.env`: key provider dan `ANALYST_TOKEN` minimal 32 karakter). Menjalankan agen deepagents dengan tiga tool baca (metrik, riwayat trade, log voter) atas snapshot yang ditulis gateway; tanpa tool order, tanpa tool ubah konfigurasi, tanpa akses ke config atau `.env` |
| gateway | Menulis snapshot, meneruskan ke analyst-b (`ANALYST_TOKEN` ditambahkan ke `secrets/gateway.env`, key provider tidak), mencatat laporan harian setelah `analyst.report_at`, melayani `/gw/v1/analyst/*` dan `/gw/v1/mode` |

Laporan harian berisi ringkasan, anomali, dan saran; tiap temuan membawa daftar bukti dan penanda `grounded`, yang dihitung kode: true hanya bila setiap bukti muncul apa adanya di keluaran tool. Tanya analis (`POST /gw/v1/analyst/ask`) memakai tool yang sama.

Kontrol mode live: `POST /gw/v1/control/mode` dua langkah, hanya dari mesin bot sendiri, gagal tertutup. Live ditolak bila mesin tidak mencatat key exchange (`INDODAX_API_KEY`, `INDODAX_API_SECRET` di lingkungan bot, tidak pernah di gateway) dan selama `engine.modectl.LIVE_ENGINE_PROVEN` false. Nilai itu false di build ini karena jalur order live Indodax belum dibuktikan, jadi live tidak bisa menyala dari kode ini. Mesin menolak start bila `mode.json` di userdir bot mencatat live.
