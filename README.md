# trading-bot

Bot trading otonom 24 jam (crypto spot, dry-run dulu) dengan swarm voter dan median sebagai penyaring entry, plus panel kontrol PWA.

Status: tahap 1 (dua bot dry-run, swarm bayangan, gateway). Belum ada akun atau uang yang terhubung, belum ada API key exchange, dan belum ada mode live. Profit tidak dijamin.

## Isi

- vendor/freqtrade: engine Freqtrade sebagai git submodule, terkunci di tag 2026.9
- engine/: launcher, skema konfigurasi, lapisan risiko, strategi
- engine/settings.py: skema tunggal config/config.yaml, divalidasi sebelum mesin start
- engine/risk.py: batas rugi harian, batas drawdown, ukuran posisi berbasis risiko
- engine/strategies/swing_ema_rsi.py: strategi swing 1h (EMA 20/50 + RSI) dengan gerbang risiko
- engine/launch.py: validasi config, render config Freqtrade (database trade di userdir), exec Freqtrade
- engine/heartbeat.py: berkas heartbeat dan log start per bot
- engine/shadow.py, engine/shadow_client.py: layanan swarm bayangan bot B dan pengirim kandidat dari strategi
- engine/decisions.py: penyimpanan SQLite keputusan swarm dan penghubung ke trade
- gateway/: gateway antara PWA dan bot (docs/gateway-api.md bagian 12)
- scripts/stage1.sh: menjalankan bot A, bot B, layanan bayangan, dan gateway sebagai unit systemd user
- scripts/measure_gateway.py: ukur jeda fill dan beban klien gateway
- scripts/stage1_report.py: ringkasan lari tahap 1
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

Isi FT_API_USERNAME, FT_API_PASSWORD, FT_API_JWT_SECRET (minimal 32 karakter), FT_API_WS_TOKEN di .env (jangan di-commit). Hanya trade dan webserver yang membuka API dan membutuhkan keempatnya; download-data, backtesting, dan show-config berjalan tanpa API server. Lalu:

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
| shadow-b | 8091 | Swarm voter nyata; mencatat jawaban, median, sebaran, kuorum, dan verdict yang AKAN diambil ke `bot-b/swarm_decisions.sqlite`. Tidak pernah memengaruhi order |
| gateway | 8090 | Sesi, endpoint baca, feed, kesehatan, biaya dan token, audit |

Mode `swarm.mode: veto` ditolak skema sampai gerbang dibangun. Trade yang dibayangi membawa custom data `shadow_decision_id`, sehingga `DecisionStore.outcomes(<tradesv3.dryrun.sqlite>)` bisa menghitung apakah entry yang akan dilewati ternyata rugi.

Setiap bot menulis `heartbeat.json` tiap loop dan menambah satu baris di `starts.jsonl` tiap start. Setelah start, bot menolak semua entry sampai cek start lolos: posisi terbuka dihargai dan batas rugi harian serta drawdown dinilai; hasilnya dikirim sebagai `strategy_msg` `startup_check`.

Direktori jalan (di luar repo), contoh `~/Projects/trading-bot-runs/stage1`:

    config/bot-a.yaml config/bot-b.yaml config/gateway.yaml
    secrets/ft.env        FT_API_USERNAME, FT_API_PASSWORD, FT_API_JWT_SECRET, FT_API_WS_TOKEN
    secrets/gateway.env   GW_PASSWORD (minimal 12 karakter)
    secrets/swarm.env     kunci provider voter, mis. NUTARALINE_API_KEY
    bot-a/ bot-b/ gateway/

`config/bot-*.yaml` berasal dari `config/config.example.yaml` dengan `bot_id`, `api.port`, dan `swarm.enabled` berbeda; `config/gateway.yaml` dari `config/gateway.example.yaml` dengan path di bawah `/opt/trading-bot/run`. Lalu:

    docker build -f docker/Dockerfile --build-context freqtrade-base=docker-image://trading-bot/freqtrade:2026.9 --target engine -t trading-bot/engine:<sha> .
    RUN_DIR=~/Projects/trading-bot-runs/stage1 IMAGE=trading-bot/engine:<sha> scripts/stage1.sh start
    RUN_DIR=... IMAGE=... scripts/stage1.sh status
    RUN_DIR=... scripts/stage1.sh stop bot-b

Ringkasan lari (uptime dari baris `Bot heartbeat` di journald dengan celah di atas 180 detik dihitung mati, restart, order per status, baris ERROR, keputusan swarm, jam bot B sejak jawaban voter nyata pertama, token, hasil trade yang dibayangi, jeda fill):

    PYTHONPATH=. python3 scripts/stage1_report.py --run-dir ~/Projects/trading-bot-runs/stage1 --unit-prefix trading-bot-stage1

Unit systemd user transien (`Restart=always`) bertahan saat sesi terminal atau server lain di-restart; restart dihitung dari `starts.jsonl`. Log: `journalctl --user -u trading-bot-stage1-bot-a`.

## Tes

    docker compose --profile test build tests
    docker compose --profile test run --rm tests

Tes berjalan di dalam image turunan Freqtrade, jadi versi Freqtrade, ccxt, dan pandas sama dengan produksi. Kontrol negatif: matikan pemeriksaan batas di engine/risk.py (ganti kedua if batas menjadi if False:) lalu jalankan tes; tes batas wajib gagal.

## Batasan Indodax yang terukur

- Freqtrade 2026.9 mencetak peringatan bahwa indodax tidak didukung resmi dan memakai kelas exchange generik, tetapi OHLCV 1h BTC/IDR, ETH/IDR, SOL/IDR terambil.
- ccxt 4.5.84 melaporkan biaya taker Indodax 0.2 sebagai rasio (bukan 0,2%), sehingga Freqtrade akan memakai biaya 20% bila tidak ditimpa. Karena itu exchange.fee_pct: 0.2 wajib di config dan dirender menjadi fee: 0.002.
- ccxt melaporkan fetchMyTrades dan watchOHLCV tidak tersedia (dilaporkan Freqtrade sebagai missing opt).
- Riwayat OHLCV 1h hanya sekitar 649 candle terakhir (27 hari) walaupun diminta 120 hari; permintaan 1d mengembalikan 1000 candle dalam satu panggilan. Backtest 1h karena itu terbatas pada sekitar 27 hari.

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
