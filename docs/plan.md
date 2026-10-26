# Plan final bot trading otonom 24 jam (revisi 10)

Disusun 2026-10-25 setelah riset mendalam (dokumen research-swarm-pwa pada issue ini). Arahan Zhafron yang dipenuhi: modal Rp 2 juta; profit masuk lagi jadi modal; analisis memakai berita dan social; demo dulu; decision model (System One) sebagai bantuan cepat untuk LLM dan harus mendukung banyak model, bukan hanya Jev; analisis dengan swarm dan median; jalan di semua OS, mobile lewat PWA. Belum ada kode, akun, atau uang yang disentuh.

Perubahan revisi 4 (arahan Zhafron 2026-10-25): (1) semua pengaturan dibuat configurable; (2) backend LLM memakai deepagents supaya provider dari mana pun bisa dipakai; (3) batas rugi default mengikuti usulan Wira dan tetap configurable; (4) PDF plan beserta mockup dikerjakan tim lebih dulu sebelum task tahap 0 dan 1.

Perubahan revisi 5 (Zhafron 2026-10-25): biaya compute LLM bukan batasan karena Zhafron punya banyak provider AI; yang diutamakan adalah kemampuan maksimal bot. Batas biaya tetap tersedia di konfigurasi tetapi default mati.

Perubahan revisi 6 (Zhafron 2026-10-25): provider AI yang dipakai adalah yang aktif di omp models.yml; daftar dan temuannya ada di bagian 4.3.

Perubahan revisi 7 (Zhafron 2026-10-25): (a) bot berjalan di PC Zhafron sendiri; (b) model uji: deepseek-v4.1-flash-1017 di provider nutaraline untuk semua peran LLM selama testing; (c) ada UI setup provider dan key, dan Wira yang mengatur penyimpanan key supaya aman (bagian 4.5); (d) UI/UX harus unik, bukan AI slop, dengan skill impeccable (bagian 12); (e) proyek disimpan di ~/Projects dengan git (bagian 11).

Perubahan revisi 8 (Zhafron 2026-10-25): aplikasi dibuat full features, termasuk grafik live, aksi live, dan pratinjau live; daftar fitur must-have dan nice-to-have mengikuti saran Wira (bagian 13).

Perubahan revisi 9 (Zhafron 2026-10-25): (a) secret tidak perlu terlalu dalam: API key boleh lewat variabel lingkungan atau langsung di config; keyring dibuang (bagian 4.5); (b) Freqtrade dijadikan vendor lewat git submodule supaya modifikasi mudah dan fleksibel (bagian 11); (c) yang memakai aplikasi adalah Zhafron di PC-nya sendiri, tema visual mengikuti keputusan Wira; (d) mode full otonom: setelah plan selesai, pekerjaan berjalan sampai selesai tanpa menunggu persetujuan per langkah, Zhafron mengoreksi sambil jalan (jendela otonom 24 jam).

Perubahan revisi 10 (Zhafron 2026-10-25): (a) destruktif diizinkan ("full otonom destruktif true"); uang sungguhan dan push ke remote tetap di luar yang Wira kerjakan sendiri; (b) arah visual diputuskan Wira dan ditulis di PRODUCT.md dan DESIGN.md (bagian 12); (c) task tahap 0 dan 1 dibuat (bagian 8).

## 1. Pernyataan jujur tentang hasil

- Profit setiap hari tidak bisa dijamin. Yang dijamin adalah batas: bot berhenti membuka posisi baru bila rugi harian lewat batas.
- Rp 100 ribu per hari butuh 5% per hari dari Rp 2 juta: tidak realistis. 0,1% per hari = Rp 2.000, 0,3% = Rp 6.000 (compound 0,1% per hari setahun = +44%, sudah ambisius). Tujuan tahap awal adalah membuktikan sistem, bukan penghasilan.
- Swarm dan median adalah filter yang diukur, bukan sumber profit yang diasumsikan. Bukti ensemble menaikkan profit trading belum kutemukan; bukti yang ada untuk prediksi peristiwa, bukan harga (detail di dokumen riset).
- Biaya Indodax: fee 0,2% (API publik 2026-10-25) dan pajak 0,21% (sumber sekunder), jadi satu siklus beli-jual 0,61-0,82%. Strategi harus untung rata-rata di atas itu per trade, jadi swing 1-4 jam, bukan scalping.

## 2. Arsitektur

Satu mesin, empat lapis, satu panel kontrol:

1. Engine: Freqtrade (Python) berjalan di PC Zhafron (native Windows, Docker, atau WSL2; pilihan dibahas di bagian 4.5 dan 10). Strategi aturan swing 1-4 jam menghasilkan kandidat entry. Profit jadi modal lagi lewat stake_amount "unlimited" dengan tradable_balance_ratio 0.99 (terverifikasi di dokumen Freqtrade).
2. Swarm (hanya penyaring): sekumpulan voter beragam menjawab pertanyaan bertipe yang sama; hasilnya digabung dengan median. Hanya boleh membatalkan atau mengecilkan entry. Tidak pernah menambah risiko, tidak menyentuh exit dan stop loss.
3. Lapisan risiko deterministik: risiko per trade, batas rugi harian dan total, kill switch, ukuran posisi. Tidak melewati AI.
4. Order dan exit: deterministik. Stop loss berjalan di sisi bot (Indodax tidak terdokumentasi mendukung stoploss on exchange), jadi PC harus selalu menyala dan batas rugi ketat lebih penting.
5. System 2: LLM besar seperti Wira hanya untuk review harian dan riset strategi di luar loop order.
6. Panel kontrol: PWA (bagian 6).

## 3. Swarm dan median

Dua kelompok voter, dua tugas:

A. Voter decision model (pertanyaan bertipe pada state: indikator, berita yang sudah ditandai, Fear and Greed):
- noul: apakah entry ini searah dengan berita terbaru; apakah ada berita risiko (regulasi, peretasan exchange, makro).
- score: sentimen berita pada skala berurutan.
- choice: izinkan, kecilkan, atau lewati.
B. Voter jalur harga (shadow dulu): Kronos (MIT; mini, small, base terbuka), satu model dasar time series umum, dan model FreqAI (LightGBM). Masing-masing memberi prakiraan return horizon entry.

Agregasi (nilai awal usulan, ditentukan ulang dari data shadow, bukan hasil tuning):
- Tiap voter A dijalankan dengan urutan opsi diacak (urutan opsi terbukti mengubah hasil di laporan satu model: 72% vs 21%).
- Gabungkan dengan median probabilitas dan ukur sebaran (selisih kuartil). Sebaran besar berarti voter tidak sepakat: lewati.
- Kuorum: minimal 5 dari 7 voter A menjawab; kurang dari itu, entry baru dilewati (fail-closed).
- Voter B: entry hanya lolos bila median prakiraan return di atas ambang biaya (0,82% + margin) dan mayoritas voter searah.
- Bobot awal sama untuk semua voter. Bobot tidak disetel dari data kecil (risiko overfit). Voter yang kalibrasinya buruk di forward test dikeluarkan, bukan diberi bobot lagi.
- Keberagaman: vendor dan keluarga model berbeda, karena voter yang kesalahannya berkorelasi mengulang kesalahan yang sama.

## 4. Dukungan banyak model decision (bukan hanya Jev)

Antarmuka DecisionProvider dengan adapter:
1. System One wire (/v1/systemone): Jev (TypeSafe), Solar Decide, Hanzo Kai, dan semua server yang meniru wire itu. Ollama (native sejak 0.35.0) dan vLLM menyajikannya lokal untuk model open-weight (Clef, d1, Tev1, pplx-decider, dan lain-lain).
2. OpenRouter Decisions API (POST /api/alpha/decisions, alpha): satu API key OpenRouter, tagihan satu akun.
3. OpenAI Decisions API (bentuk sendiri).
4. Cadangan LLM biasa dengan structured output (103 model berstruktur murah di OpenRouter, 11 gratis) lewat adapter yang meniru choice, noul, score; AnyJev (Nokia, Apache 2.0) sebagai referensi cara mengubah LLM menjadi decision model.

Registri voter berupa berkas konfigurasi: model, adapter, harga, batas waktu, status kesehatan. Voter yang gagal atau lambat dibuang untuk keputusan itu; kuorum menentukan hasil. Menambah model baru berarti menambah satu baris konfigurasi, bukan kode. Katalog decision model di OpenRouter diambil di tahap 0 memakai API key.

### 4.1 Backend LLM: deepagents

Terverifikasi hari ini: deepagents (langchain-ai/deepagents) lisensi MIT, versi PyPI 0.7.32 (diunggah 2026-10-23), Python 3.11 atau lebih baru. Model ditulis dengan format provider:model, misalnya openai:gpt-5.4 atau anthropic:claude-sonnet-4-6 (contoh dari dokumen); semua model LangChain yang mendukung tool calling bisa dipakai, termasuk OpenRouter dan Ollama (dokumen deepagents). Jadi provider diganti lewat satu string konfigurasi.

Pembagian peran:
- Agen analis System 2 (review harian, riset strategi, penjelasan keputusan): deepagents dengan model dari konfigurasi. Tool-nya hanya baca (metrik, riwayat trade, log voter). Tidak ada tool yang bisa membuat order atau mengubah konfigurasi.
- Voter cepat: lewat adapter DecisionProvider. Adapter cadangan LLM memakai string provider:model yang sama lewat LangChain dengan structured output.
- Belum ada angka apakah harness deepagents (perencanaan, filesystem, konteks) menambah latensi dan token per keputusan voter. Diukur di tahap 0. Bila selisihnya kecil, semua lewat deepagents; bila besar, voter cepat memakai pemanggilan langsung dan deepagents hanya untuk agen analis. Keputusan setelah angkanya keluar, dan keduanya tetap hanya pengaturan konfigurasi.

Catatan keamanan dari review sebelumnya (ZHA-3610, deepagents 0.7.13, belum diuji ulang di 0.7.32): sub-agent tanpa daftar tools mewarisi semua tools induknya, dan aturan keselamatan yang hanya ada di system prompt induk tidak sampai ke sub-agent. Karena itu batas risiko tidak boleh bergantung pada prompt: ditegakkan di kode (strategi, gateway), dan agen LLM tidak diberi tool yang bisa menempatkan order. Uji ulang di tahap 0 sebelum agen analis dipasang.

### 4.2 Semua configurable

Satu berkas konfigurasi YAML. API key boleh lewat variabel lingkungan (api_key_env) atau langsung di config/config.yaml (api_key); config.yaml dan .env ada di .gitignore dan tidak masuk repo. Berkas divalidasi skema saat start; konfigurasi salah berarti bot tidak start, bukan jalan dengan nilai tebakan. Nilai di bawah adalah default usulan Wira, semuanya bisa diubah Zhafron.

```yaml
mode: dry_run                     # live butuh konfirmasi dua langkah
capital:
  initial_idr: 2000000
  compounding: true               # stake_amount unlimited, tradable_balance_ratio 0.99
risk:
  max_daily_loss_pct: 1.0         # Rp 20.000 pada modal Rp 2 juta
  max_total_drawdown_pct: 10.0    # Rp 200.000
  risk_per_trade_pct: 0.5         # Rp 10.000
  max_open_trades: 3
  leverage: none                  # spot saja
  on_breach: stop_new_entries     # kill switch
exchange:
  name: indodax                   # dukungan Freqtrade belum terbukti, diuji di tahap 0
  pairs: [BTC/IDR, ETH/IDR, SOL/IDR]
  timeframe: 1h
providers:
  - id: nutaraline
    type: openai-completions       # openai-completions, openai-responses, anthropic-messages
    base_url: from_import          # diambil dari omp models.yml, berakhiran /v1
    api_key_env: NUTARALINE_API_KEY   # nama variabel lingkungan; atau isi api_key di bawah
    api_key: null                  # boleh diisi langsung di config.yaml lokal (tidak di-commit)
    models: [deepseek-v4.1-flash-1017]
swarm:
  enabled: true
  mode: shadow                    # shadow atau veto; veto hanya setelah kriteria adopsi lolos
  shuffle_options: true
  min_voters_answered: 5
  max_spread: tbd                 # ditetapkan dari data shadow di tahap 0
  voters:
    - id: v1
      adapter: llm_structured      # systemone, openrouter_decisions, openai_decisions, llm_structured
      provider: nutaraline
      model: deepseek-v4.1-flash-1017
      variation: option_order     # option_order, temperature, prompt_variant
      timeout_s: 30               # angka awal, diukur di tahap 0
      weight: 1.0
      enabled: true
llm:
  backend: deepagents
  analyst_model: nutaraline:deepseek-v4.1-flash-1017   # id provider bot : model; model uji
compute:
  max_cost_idr_per_day: off       # default mati; isi angka bila ingin batas
  on_exceed: skip_new_entries     # berlaku hanya bila batas diisi
  log_cost: true                  # biaya dan token dicatat sebagai informasi
data:
  news_rss: [coindesk, cointelegraph]
  fear_greed: true
  social: off                     # aktif setelah akses Reddit diverifikasi
notify:
  web_push: true
```

Aturan perubahan konfigurasi:
1. Setiap perubahan dicatat: siapa, kapan, nilai lama dan baru.
2. Dari PWA, menurunkan batas risiko berlaku langsung. Menaikkan batas risiko atau pindah ke mode live butuh konfirmasi dua langkah. Keputusan menaikkan batas tetap di tangan Zhafron.
3. Menambah atau mengganti voter dan backend LLM hanya mengubah konfigurasi, bukan kode.
4. Mengganti mode swarm dari shadow ke veto hanya setelah kriteria adopsi di bagian 8 terpenuhi atau Zhafron memutuskan lain.
5. Protections bawaan Freqtrade belum kukonfirmasi dari dokumen, jadi batas rugi harian diimplementasikan dan diuji sendiri di tahap 0.
6. Ukuran posisi berdasarkan risk_per_trade_pct diterapkan lewat custom_stake_amount di strategi (callback ini disebut di dokumen Freqtrade); rancangan rincinya di tahap 0.

### 4.3 Provider AI yang sudah dimiliki Zhafron (dari omp models.yml)

Dibaca 2026-10-25 dari ~/.omp/agent/models.yml. Yang diambil hanya nama provider, tipe API, host, dan id model. API key tidak disalin ke dokumen ini; key diberikan lewat variabel lingkungan atau config lokal (bagian 4.5).

| Provider | Tipe API | Host | Jumlah id model |
|---|---|---|---|
| sub2api-codex | openai-responses | localhost:62173 | 18 |
| sub2api-agy | openai-completions | localhost:62173 | 21 |
| sub2api-claude, sub2api-claude-kaitech, sub2api-claude-all | anthropic-messages | localhost:62173 | 7 masing-masing |
| sub2api-mimo | openai-completions | localhost:62173 | 8 |
| omniroute | openai-completions | localhost:20128 | 20 |
| xai-hm | openai-responses | gateway.example.com | 17 |
| modelrouter | openai-completions | modelrouter.id | 23 |
| tiprouter | openai-completions | tiprouter.my.id | 18 |
| nutaraline | openai-completions | nutaraline.co.uk | 23 |
| lucif | anthropic-messages | lucif.ai | 2 |
| experientiallabs | openai-completions | api.experientiallabs.ai | 272 |

Total 13 provider dan 443 id model (sebagian id sama muncul di beberapa gateway).

Temuan:
1. Keluarga model beragam menurut id (jumlah provider yang memuatnya): Claude 8, Gemini 6, GPT 5, DeepSeek 5, GLM 5, Nemotron 5, Mimo 5, MiniMax 4, Hunyuan 4, Kimi 3, Step 3, Solar 3, Longcat 3, Qwen 2, serta Mistral, Llama, Grok, dan Cohere di satu provider. Voter swarm dipilih per keluarga model, bukan per gateway: id yang sama di dua gateway belum tentu model yang berbeda, dan itu bukan dua voter independen ([INFERENCE]).
2. Decision model sudah ada di provider Zhafron menurut id model: jev-1.13 di modelrouter; jev-latest, clef, clef-flash, dan gpt-6-luna-decisions di experientiallabs. Belum terbukti gateway itu menyajikan endpoint decisions atau /v1/systemone dan bukan hanya chat completions; diuji di tahap 0 dengan key yang disediakan Zhafron. Id mercury-2 dan mercury-3 di experientiallabs kemungkinan model chat biasa, bukan Mercury Decide; belum diverifikasi.
3. models.yml tidak memuat OpenRouter. Jadi OpenRouter API key tidak lagi wajib; adapter OpenRouter Decisions tetap didukung sebagai opsi.
4. Tiga tipe API muncul: openai-completions, openai-responses, anthropic-messages. Adapter llm_structured harus mendukung ketiganya. Dukungan base URL kustom untuk ketiganya lewat LangChain dan deepagents belum kuverifikasi dari dokumen yang kubaca; diuji di tahap 0 ([INFERENCE]: kelas chat OpenAI dan Anthropic menerima base URL kustom).
5. 7 dari 13 provider beralamat localhost (sub2api-*, omniroute): hanya terjangkau dari PC Zhafron. Bot berjalan di PC Zhafron (diputuskan 2026-10-25), jadi provider localhost terjangkau. Bila bot suatu hari dipindah ke VPS, voter pada provider localhost tidak terjangkau kecuali ada tunnel. 6 provider lain beralamat publik (xai-hm, modelrouter, tiprouter, nutaraline, lucif, experientiallabs).
6. Beberapa gateway tampak pihak ketiga; ketersediaan dan kebijakan tiap gateway tidak kuketahui. Desain kuorum dan voter gagal dibuang (bagian 3) memang untuk itu. Voter disebar ke lebih dari satu gateway supaya satu gateway mati tidak menjatuhkan kuorum.
7. Registri voter menyimpan nama variabel lingkungan untuk key (api_key_env), atau nilainya di config.yaml lokal yang tidak di-commit.

### 4.4 Model uji (diputuskan Zhafron 2026-10-25)

Selama testing semua peran LLM (agen analis dan semua voter) memakai deepseek-v4.1-flash-1017 di provider nutaraline. Dari models.yml (hanya bidang non-rahasia): nama "DeepSeek V4.1 Flash 1017 LoRA (nutaraline)", API openai-completions, base URL berakhiran /v1, auth apiKey, reasoning aktif, contextWindow 1.048.576, maxTokens 384.000.

- Karena reasoning aktif, latensi dan token per keputusan bisa lebih besar dari model non-reasoning. Timeout voter awal 30 detik adalah angka usulan yang diukur di tahap 0.
- Dukungan structured output untuk model ini belum terbukti. Diuji di tahap 0. Bila tidak ada, adapter llm_structured memakai keluaran JSON yang divalidasi skema, dan jawaban tidak valid dihitung sebagai voter gagal (kuorum).
- Satu model untuk semua voter berarti kesalahan voter berkorelasi. Swarm di fase testing hanya menguji mesin dan adapter, bukan nilai swarm. Voter beragam diaktifkan setelah mesin lolos.
- Format provider:model di konfigurasi memakai id provider milik bot (nutaraline). Backend menerjemahkannya ke integrasi LangChain: openai-completions menjadi kelas chat OpenAI dengan base_url kustom ([INFERENCE], diuji di tahap 0).

### 4.5 Setup provider dan key (UI) dan penyimpanan

Zhafron (revisi 9): secret tidak perlu terlalu dalam, boleh lewat env atau langsung di config. Keputusan sebelumnya (keyring dan Credential Locker) dibatalkan; dengan begitu pilihan native Windows atau Docker tidak lagi bergantung pada penyimpanan key.

UI (layar Provider):
- Daftar provider: nama, tipe API, host, status uji terakhir, model aktif.
- Tambah atau ubah provider: tipe API, base URL, daftar model.
- Kolom key: ditulis ke config/config.yaml (api_key) atau, bila diisi nama variabel, dibaca dari lingkungan (api_key_env). Setelah disimpan tampilan hanya memperlihatkan 4 karakter terakhir.
- Tombol Uji koneksi: satu panggilan kecil, menampilkan latensi dan hasil.
- Pilih provider dan model per peran (agen analis, tiap voter).
- Impor dari omp models.yml: dibaca lokal oleh aplikasi di PC (nama, tipe API, base URL, model; key hanya bila dicentang per provider).

Aturan sederhana yang tetap dipegang:
1. config/config.yaml dan .env ada di .gitignore; pemindaian rahasia pada staged diff dijalankan sebelum commit.
2. Tidak ada endpoint yang mengembalikan key utuh; key tidak ditulis ke log (log menyaring pola Authorization dan token).
3. Agen LLM (deepagents) tidak diberi tool yang membaca config atau .env.
4. Memasukkan atau mengganti key hanya dari PC (localhost), tidak dari PWA jarak jauh; PWA jarak jauh hanya menampilkan status, aktif atau nonaktif, dan uji koneksi.

Konsekuensi yang diterima Zhafron: key di config.yaml tersimpan sebagai teks biasa di disk PC. Cukup untuk bot pribadi di PC sendiri; bila repo atau berkas itu pernah tersalin keluar, key harus dianggap bocor dan diganti. Rekomendasi Wira: pakai env bila nyaman, config bila praktis.

Cara menjalankan di PC: dokumen Freqtrade merekomendasikan Docker untuk Windows (lebih mudah dan lebih aman), lalu WSL2; native lewat setup.ps1 (Python 3.12 atau lebih baru, 64 bit) bila memang diperlukan. Rekomendasi Wira sekarang: Docker, karena alasan memilih native (keyring) sudah gugur. Satu hal yang diuji di tahap 0: provider localhost (sub2api, omniroute) dari dalam kontainer harus lewat host.docker.internal atau jaringan host ([INFERENCE], belum diuji). Bila itu merepotkan, native Windows atau WSL2 jadi pilihan.

## 5. Sumber data

- Berita: RSS CoinDesk (25 item) dan Cointelegraph (30 item), terbaca 2026-10-25; tanpa arsip historis.
- Fear and Greed Index (alternative.me): 3.185 nilai harian sejak 2018-02-01, gratis, wajib mencantumkan sumber.
- Social (Reddit, X): belum diverifikasi akses dan biayanya; Reddit lebih dulu dicoba di tahap 0.
- Harga: data publik exchange lewat Freqtrade; dry-run tidak butuh API key atau akun.

## 6. Semua OS dan mobile (PWA)

- Engine berjalan di PC Zhafron sendiri (diputuskan 2026-10-25). Bot tidak dijalankan di HP (HP membatasi proses latar belakang; [INFERENCE]). Konsekuensi PC: stop loss ada di sisi bot, jadi bila PC mati, tidur, restart (misalnya Windows Update), atau internet putus, posisi terbuka tidak terlindungi. Mitigasi usulan: dry-run dulu (tanpa risiko); live hanya setelah PC diatur tanpa sleep dan tanpa restart otomatis; heartbeat dari bot ke pemantau di luar PC yang mengirim notifikasi bila heartbeat berhenti (layanan pemantau belum dipilih); saat start ulang, bot memeriksa posisi terbuka dan batas rugi lebih dulu sebelum membuka posisi baru.
- API Freqtrade tetap di localhost dan tidak dibuka ke internet (peringatan dokumen). Antara PWA dan engine ada gateway kecil buatan sendiri: autentikasi, endpoint baca, kill switch, pengirim Web Push. Gateway diakses lewat HTTPS tunnel (usulan Cloudflare Tunnel dengan Access, atau jaringan privat), bukan port terbuka. Zhafron sudah punya Cloudflare named tunnel untuk subdomain domain pribadinya (catatan skill internal), jadi gateway bisa memakainya setelah disetujui; tidak dikerjakan sekarang.
- PWA: dasbor (profit, posisi terbuka, meter rugi harian, suara tiap voter, median, sebaran) dan notifikasi. FreqUI bukan PWA (tanpa manifest dan service worker), jadi PWA dibuat sendiri. Android dan desktop: dipasang dari browser Chrome atau Edge (pemasangan desktop belum kuverifikasi). iOS: iOS 16.4 atau lebih baru, harus ditambahkan ke Home Screen, izin push diminta lewat ketukan tombol, notifikasi harus terlihat.
- Tindakan berbahaya dari ponsel (mode live, menaikkan batas) butuh konfirmasi dua langkah. Versi pertama panel hanya baca ditambah notifikasi; kontrol menyusul setelah gateway diuji.
- Windows: tiga cara menjalankan Freqtrade: Docker (direkomendasikan dokumen), WSL2, atau native lewat setup.ps1. Rekomendasi sekarang Docker (bagian 4.5).

## 7. Biaya compute (bukan batasan)

Arahan Zhafron: biaya LLM tidak perlu terlalu dipikirkan karena provider AI-nya banyak; yang penting bot bisa maksimal.

- compute.max_cost_idr_per_day tetap ada di konfigurasi, default mati. Bila suatu hari diisi dan terlampaui, perilakunya mengikuti compute.on_exceed (default: lewati entry baru).
- Biaya dan token tetap dicatat sebagai informasi di log dan PWA. Pencatatan tidak membatasi apa pun.
- Konsekuensi: voter boleh memakai model yang lebih besar dan jumlah voter boleh lebih dari 7 (daftar voter hanya konfigurasi). Batas praktis bergeser dari uang ke latensi dan rate limit tiap provider. Untuk strategi 1-4 jam, latensi beberapa detik per keputusan kemungkinan masih dapat diterima ([INFERENCE]); diukur di tahap 0.
- Model lebih besar atau lebih mahal tidak otomatis lebih akurat. Keberagaman vendor dan kalibrasi voter tetap diuji di forward test sebelum swarm boleh membatalkan entry (kriteria adopsi di bagian 8).
- Perkiraan sebelumnya (7 voter murah, sekitar Rp 380 per hari pada harga 0,04 dolar per juta token) hanya sebagai pembanding; biaya dengan model besar belum diukur.

## 8. Tahap dan syarat lolos

| Tahap | Isi | Syarat lolos (usulan) |
|---|---|---|
| 0. Setup (1-2 hari) | Freqtrade dry-run (Docker atau VPS), uji Indodax via CCXT, spike adapter DecisionProvider (gateway milik Zhafron: jev dan clef di modelrouter dan experientiallabs, satu model chat biasa lewat llm_structured; Ollama lokal dan OpenRouter opsional), uji model uji deepseek-v4.1-flash-1017 di nutaraline (structured output, latensi, token reasoning), uji menjalankan submodule Freqtrade di Docker dan native Windows (termasuk jangkauan provider localhost dari kontainer), ambil katalog decision model, uji Kronos mini di CPU, pasang batas rugi default lewat konfigurasi, ukur latensi dan token voter lewat deepagents dibanding pemanggilan langsung | Dry-run jalan dengan data Indodax tanpa error; minimal 3 adapter menjawab pertanyaan yang sama |
| 1. Demo minggu 1 | Dry-run 7 hari non-stop. Bot A aturan saja; bot B aturan ditambah swarm dalam mode bayangan (hanya mencatat). Kerangka PWA baca-saja dan notifikasi dibangun paralel | Mesin stabil 24 jam, tidak ada order gagal, biaya dan token tercatat. Ini uji mesin, bukan bukti profit |
| 2. Minggu 2-4 | Backtest strategi aturan 2-3 tahun (tanpa sinyal berita), dry-run berlanjut, evaluasi swarm di forward test | Ekspektasi positif setelah fee dan pajak di data out-of-sample; kriteria adopsi swarm di bawah |
| 3. Live kecil, minimal 4 minggu | Porsi awal usulan Rp 500 ribu (25%), karena fee dan minimum order membuat porsi 5-10% terlalu kecil untuk diukur | Tidak melanggar batas rugi; selisih dengan dry-run wajar |
| 4. Naik bertahap | Tambah modal bertahap, review bulanan | review bulanan |

Kriteria adopsi swarm sebagai gerbang (setelah minimal 4 minggu bayangan dan minimal 30 keputusan veto; angka final ditetapkan di tahap 0): (a) trade yang akan dibatalkan rata-rata lebih rugi daripada yang diizinkan; (b) laba bersih atau drawdown bot B lebih baik dari bot A setelah fee dan pajak; (c) biaya compute dicatat sebagai informasi, bukan syarat (arahan Zhafron). Bila tidak terpenuhi, swarm tetap hanya menjadi laporan.

Selama testing semua voter memakai model uji yang sama (deepseek-v4.1-flash-1017), jadi swarm di fase itu hanya menguji mesin dan adapter, bukan nilai swarm: kesalahan model yang sama berkorelasi. Voter beragam diaktifkan setelah mesin lolos.

Seminggu demo hanya menguji mesin; strategi 1-4 jam menghasilkan sedikit trade per minggu (jumlahnya diukur di backtest), jadi belum cukup menilai untung rugi. Uang asli diusulkan setelah minimal 4 minggu dry-run.

## 9. Yang tidak dipakai dan alasannya

- MiroFish dan MiroShark: simulasi sosial boros token, lisensi AGPL-3.0, tanpa benchmark akurasi publik yang kutemukan. Bukan inti; boleh dicoba kemudian untuk eksplorasi skenario berita.
- Scalping, grid rapat, dan leverage: biaya 0,61-0,82% per siklus memakan margin; leverage memperbesar risiko.
- Swarm LLM besar di dalam loop order tidak lagi dikecualikan karena biaya (arahan Zhafron). Syaratnya hanya lolos uji latensi dan kalibrasi di tahap 0 dan forward test. LLM tidak memegang exit, stop loss, dan batas risiko.

## 10. Keputusan

Sudah diputuskan Zhafron: bot berjalan di PC sendiri; model uji deepseek-v4.1-flash-1017 di nutaraline; UI setup provider dan key dengan penyimpanan aman yang diatur Wira; UI/UX harus unik (bukan AI slop) dengan impeccable; proyek di ~/Projects dengan git; biaya compute LLM bukan batasan (batas biaya default mati); modal Rp 2 juta; profit masuk lagi jadi modal; demo dulu; semua configurable; backend LLM deepagents; batas rugi default sesuai usulan (1% per hari, 10% total, tetap configurable); PDF plan beserta mockup dibuat dulu oleh tim.

Masih dibutuhkan dari Zhafron: tidak ada yang menghalangi pekerjaan. Mode full otonom (revisi 9): Wira memutuskan sendiri dan Zhafron mengoreksi sambil jalan. Keputusan yang Wira ambil dan bisa dikoreksi:
1. Task tahap 0 dan 1 dibuat setelah plan ini (sebelumnya menunggu persetujuan; sekarang tercakup full otonom).
2. Tema dan arah visual diputuskan Wira (bagian 12), bukan hasil wawancara.
3. Cara menjalankan di PC: Docker dulu (bagian 4.5), diuji di tahap 0.
4. Repo tetap lokal tanpa remote dan tanpa LICENSE sampai Zhafron memutuskan (push dan lisensi tidak termasuk jendela otonom).
5. Exchange untuk tahap live: tidak dibutuhkan untuk demo; live tidak dimulai tanpa persetujuan eksplisit Zhafron (uang sungguhan di luar jendela otonom).

## 11. Proyek dan git

- Lokasi: ~/Projects/trading-bot (nama kerja, mudah diganti). Branch main. Identitas commit mengikuti ~/.gitconfig (Zhafron), tanpa Co-Authored-By.
- Freqtrade sebagai git submodule di vendor/freqtrade (arahan Zhafron revisi 9): url https://github.com/freqtrade/freqtrade.git, branch stable, shallow, terkunci di commit 1f394eae yang adalah tag 2026.9 (commit 568b46b). Strategi, konfigurasi, dan data pengguna ada di luar vendor lewat --strategy-path dan --userdir (dokumen Freqtrade), jadi isi vendor tidak diubah. Bila suatu saat engine perlu dimodifikasi: fork Freqtrade lalu ubah url di .gitmodules ke fork itu. Memperbarui versi: fetch tag baru di submodule, checkout, commit gitlink-nya (langkah ada di README).
- Ukuran: submodule shallow sekitar 58 MB berkas kerja dan 41 MB data git (diukur saat dipasang).
- Sudah ada di repo: README, .gitignore, .gitattributes, .editorconfig, .env.example, hook git, contoh konfigurasi tanpa komentar, salinan plan dan riset di docs/. PRODUCT.md dan DESIGN.md (seed) dari impeccable. Tautan skill impeccable di .agents/skills tidak di-commit.
- Dibuat di tahap 0, belum ada: strategi Freqtrade, gateway, adapter DecisionProvider dan voter, agen analis deepagents, PWA, docker-compose.
- Commit: Conventional Commits berbahasa Inggris, subject di bawah 72 karakter. Hook commit-msg menolak format salah dan trailer Co-Authored-By. Hook pre-commit menjalankan gerbang komentar pada kode kita (aturan Zhafron: tanpa komentar); isi vendor/freqtrade adalah kode pihak ketiga dan tidak diperiksa.
- Cabang: main dan cabang fitur (feat/..., fix/...). Worktree lewat ~/Projects/.worktrees.
- Tes: repo tanpa CI, jadi suite penuh lokal maksimal sekali per SHA final sebelum push; saat mengembangkan hanya tes terkait (aturan Zhafron).
- Alat: Python 3.12 atau lebih baru dengan uv; deepagents; kerangka PWA dipilih di tahap desain.
- Rahasia: config/config.yaml, .env, user_data, basis data, dan log tidak masuk repo (.gitignore).
- Remote dan lisensi: belum ada remote dan belum ada LICENSE. Freqtrade berlisensi GPL-3.0; strategi yang mengimpor Freqtrade kemungkinan ikut terikat ([INFERENCE], perlu penilaian hukum bila repo akan dibuka). Rekomendasi: repo privat, tanpa LICENSE, sampai Zhafron memutuskan.

## 12. UI/UX unik dengan impeccable

Zhafron: UI/UX harus unik dan tidak terlihat seperti AI slop; skill impeccable disiapkan.

Status (2026-10-25, mode full otonom): PRODUCT.md dan DESIGN.md (seed) sudah ditulis di ~/Projects/trading-bot dan di-commit (54ed647). Zhafron mendelegasikan tema ke Wira dan tidak menjawab wawancara; jadi isi keduanya adalah keputusan Wira yang dikoreksi Zhafron sambil jalan. Skill impeccable ditautkan ke proyek (.agents/skills, tidak di-commit); context.mjs kini membaca PRODUCT.md.

Register: product. Pemakai: Zhafron saja, di PC (konfigurasi, analisa) dan di ponsel (sekilas, notifikasi, siang terik dan tengah malam).

Arah visual yang diputuskan (rincian di DESIGN.md):
- Creative North Star: papan informasi stasiun bertemu strip kertas seismograf. Satu jawaban besar yang terbaca dari jauh (aman, ditahan, berhenti) dan satu jejak garis tentang apa yang baru terjadi.
- Tema: terang sebagai bawaan (kontras tertinggi di bawah matahari), gelap mengikuti pengaturan sistem untuk malam; keduanya dirancang.
- Warna: strategi Restrained. Satu warna sinyal hangat (benih seed-041 dari palette.mjs untuk kunci trading-bot, oklch(0.673 0.217 38.6)) hanya untuk rugi, batas, peringatan, dan kill switch. Untung memakai biru tua. Pasangan biru dan jingga dipilih karena tetap terbedakan bagi buta warna merah-hijau; setiap angka juga memakai tanda plus atau minus dan arah. Tombol utama memakai tinta. Tanpa pita krem atau pasir.
- Tipografi: satu keluarga sans yang teknis dengan angka tabular wajib; keluarga konkret dipilih saat implementasi setelah dipastikan mendukung angka tabular. Skala tetap.
- Datar, tanpa bayangan lebar; gerak 150 sampai 250 ms hanya untuk perubahan keadaan.
- Dilarang: gaya Binance atau Robinhood, gamifikasi, template hero-metric, dasbor AI generik, tampilan bawaan FreqUI dan Nuxt UI.
- Uji cepat: bila layar langsung ditebak sebagai "dasbor trading" dari warna dan bentuk saja, arahnya gagal.

Aturan anti-slop dari skill yang berlaku untuk proyek ini:
- Tidak ada template hero-metric (angka besar, label kecil, statistik pendukung, aksen gradient): dasbor profit biasanya persis itu, jadi harus dihindari.
- Tidak ada grid kartu identik berulang, kartu bersarang, glassmorphism, gradient text, eyebrow kapital kecil di tiap bagian, penomoran 01/02/03 sebagai perancah, border 1px bersama bayangan lebar, radius kartu di atas 12-16px, ilustrasi SVG sketsa, latar garis diagonal.
- Tema gelap atau terang bukan default: ditulis satu kalimat adegan fisik (siapa, di mana, cahaya apa) sebelum memilih. Warna di OKLCH, kontras teks minimal 4.5:1.
- Product: satu keluarga huruf sudah cukup, skala tipografi tetap (bukan fluid), setiap komponen punya state default, hover, focus, active, disabled, loading, error; skeleton alih-alih spinner; empty state yang mengajar; modal bukan pilihan pertama; gerak 150-250 ms hanya untuk menyampaikan state; prefers-reduced-motion wajib.
- Uji category-reflex dua tingkat: tingkat satu, dasbor trading yang mudah ditebak adalah tema gelap dengan hijau dan merah neon plus grafik candlestick; tingkat dua, terminal-native dark mode. Arah yang dipilih harus lolos keduanya.

Warna dan semantik untung dan rugi: jangan hanya merah dan hijau (buta warna). Tambahkan tanda plus dan minus, arah panah, posisi, dan teks. Tombol utama memakai tinta, dan warna sinyal hanya untuk risiko, supaya tidak bentrok dengan semantik untung dan rugi. Benih warna sudah diambil: palette.mjs --from trading-bot memberi seed-041, dipakai sebagai warna sinyal risiko.

Layar yang dirancang: Dasbor, Grafik live, Aksi live, Pratinjau, Swarm, Konfigurasi, Provider dan key, Kill switch dan konfirmasi dua langkah, notifikasi, pasang PWA di iOS. Layar Provider dan key mengikuti bagian 4.5; di PWA jarak jauh kolom key tidak ada, hanya status, aktif atau nonaktif, dan uji koneksi.

Proses: impeccable shape lalu craft untuk tiap layar; critique dan audit sebelum rilis; detect.mjs (detektor pola bawaan skill, berjalan lokal) dibaca sebelum commit UI; hasil dilihat lewat screenshot di ukuran HP dan desktop.

## 13. Fitur lengkap (must-have dan nice-to-have)

Zhafron: aplikasi full features (grafik live, aksi live, pratinjau live), ikut saran Wira. Dasar tiap fitur diperiksa di dokumen Freqtrade 2026-10-25: REST API (/status, /trades, /balance, /profit, /daily, /weekly, /monthly, /exits, /entries, /mix_tags, /stats, /performance, /pair_candles, /pair_history, /plot_config, /health, /sysinfo, /logs, /pause, /start, /stopbuy, /stop, /forceexit, /locks, /blacklist) dan WebSocket pesan di /api/v1/message/ws (subscribe whitelist, analyzed_df, serta pesan fill). Fitur bertanda kustom dibangun sendiri di gateway dan PWA.

Tafsiran Wira atas "live preview" (koreksi bila maksud Zhafron lain): (1) pratinjau kandidat entry beserta jawaban voter sebelum order dikirim, dan di mode shadow menampilkan apa yang akan terjadi; (2) pratinjau what-if konfigurasi sebelum diterapkan; (3) pratinjau sinyal strategi di grafik.

### Must-have

| Fitur | Dasar | Tahap |
|---|---|---|
| Grafik live per pair: candlestick, penanda entry dan exit, overlay indikator | /pair_candles, WebSocket analyzed_df, /plot_config | 1 |
| Posisi dan order live, untung rugi berjalan, saldo | /status, /trades, /balance, /profit | 1 |
| Aksi live (feed waktu nyata): fill, jawaban voter, median, sebaran, kuorum, veto atau kecilkan, gerbang risiko, error, heartbeat | pesan WebSocket Freqtrade dan event kustom gateway | 1 |
| Pratinjau kandidat entry beserta jawaban voter sebelum order | kustom | 1 |
| Meter risiko: rugi harian dan total terhadap batas, penanda mode dry atau live | kustom, /profit | 1 |
| Notifikasi push: fill, batas rugi terlewati, kill switch, heartbeat hilang, kuorum gagal, ringkasan harian | Web Push (iOS 16.4 atau lebih baru, Home Screen) | 1 |
| Kesehatan: loop bot, beban sistem, status dan latensi tiap provider, heartbeat, log | /health, /sysinfo, /logs, kustom | 1 |
| Bot A vs bot B: kurva ekuitas bertumpuk selama dry-run | dua instance, kustom | 1 sampai 2 |
| Kontrol: jeda, lanjut, hentikan entry, force exit satu atau semua posisi, kunci pair, blacklist; yang berisiko butuh konfirmasi dua langkah | /pause, /start, /stopbuy, /forceexit, /locks, /blacklist | 2 |
| Layar Provider dan key, registri voter, editor konfigurasi dengan validasi skema dan catatan perubahan | kustom, bagian 4.5 | 2 |
| Tampilan swarm per keputusan dan hasil sesudahnya (apakah entry yang dilewati ternyata rugi) | kustom | 2 |
| Riwayat trade dan statistik: harian, mingguan, bulanan, per alasan exit, per tag entry | /trades, /daily, /weekly, /monthly, /exits, /entries, /mix_tags, /stats, /performance | 2 |
| Log audit: perubahan konfigurasi, key (tanpa nilai), mode, kontrol | kustom | 2 |
| Laporan harian dari agen analis: ringkasan, anomali, saran | deepagents, kustom | 3 |

### Nice-to-have

| Fitur | Dasar |
|---|---|
| Pratinjau what-if konfigurasi: efek batas dalam rupiah, dan putar ulang jawaban voter yang tercatat dengan kuorum atau ambang sebaran baru tanpa panggilan LLM baru | kustom |
| Pratinjau sinyal strategi di grafik untuk rentang waktu | /pair_history |
| Mesin waktu: geser ke keputusan lampau dengan jawaban voter di atas grafik | kustom |
| Backtest dan hasilnya dari UI | endpoint backtest belum kuverifikasi |
| Papan skor voter: kalibrasi dan akurasi, nonaktif otomatis bila melenceng | kustom |
| Lapisan berita dan sentimen di grafik (RSS, Fear and Greed) | kustom |
| Tanya agen analis (obrolan, tool baca saja), misalnya kenapa BTC dilewati jam tertentu | deepagents |
| Uji stres: skenario turun 10 persen terhadap posisi terbuka | kustom |
| Lencana ikon aplikasi dan tampilan terakhir saat offline (hanya baca) | PWA; Apple menyebut izin badging di iOS 16.4 |
| Ekspor CSV riwayat trade dan ringkasan pajak sebagai informasi, bukan nasihat pajak | kustom, PMK 50/2025 |
| Dua bahasa: Indonesia (default) dan Inggris | kustom |
| Kanal kontrol Telegram | perintah Telegram bawaan Freqtrade |
| Lebih dari 3 pair dan tampilan portofolio | konfigurasi |

### Sengaja tidak dibangun

- Copy trading dan papan peringkat publik.
- Leverage dan futures.
- Tombol tarik dana dan tombol all-in.
- Fitur yang menaikkan risiko secara otomatis.
- Key yang bisa dilihat kembali.

### Transport live dan performa

- Gateway menjaga satu koneksi WebSocket ke Freqtrade (/api/v1/message/ws dengan JWT 15 menit dari /token/login, bukan ws_token, karena log Freqtrade mencatat URL WebSocket beserta query; subscribe) dan mendorong delta ke PWA lewat WebSocket sendiri. Data kandle diambil hanya saat ada klien terhubung, supaya bot di PC tidak terbebani.
- iOS: WebSocket hanya hidup saat aplikasi terbuka di depan; saat di latar belakang kabar datang lewat Web Push. Safari tidak mendukung push tak terlihat, jadi notifikasi harus tampil (dokumen Apple).
- Sambungan terputus: sambung ulang dengan backoff dan tampilan menandai data basi.
- Metrik yang diukur di tahap 1: jeda dari fill di Freqtrade sampai tampil di PWA, dan beban CPU gateway saat klien terhubung. Belum ada angka.
- FreqUI memakai Vue dan Nuxt UI (README FreqUI) dan ECharts (package.json). Memakainya ulang bertentangan dengan permintaan UI unik, jadi PWA dibuat sendiri. Pustaka grafik dipilih di tahap desain.

### Urutan penyampaian

Tahap 1 (demo): semua fitur bertahap 1, hanya baca. Tahap 2: kontrol, konfigurasi, provider dan key, swarm, riwayat, audit. Tahap 3: laporan harian dan kontrol mode live. Nice-to-have menyusul, urutannya mengikuti data pemakaian. Full features berarti cakupan besar; estimasi waktu belum ada karena belum diukur, dan urutan ini menjaga bot tetap bisa dites lebih dulu.

## Sumber

Bukti dan tautan lengkap ada di dokumen research-swarm-pwa pada issue ini. Sumber revisi 1 dan 2 (AI-Trader, Hummingbot, NautilusTrader, TradingAgents, claude-trading-skills, Freqtrade, Indodax API, alternative.me, OpenRouter Jev) tetap berlaku.
