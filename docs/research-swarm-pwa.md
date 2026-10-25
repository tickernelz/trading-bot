# Riset mendalam: swarm dan median, decision model multi-vendor, PWA (2026-10-25)

Atas arahan Zhafron: bot harus bisa analisa dengan perkiraan swarm (banyak bot lalu diambil median), decision model harus mendukung banyak model (bukan hanya Jev), aplikasi harus jalan di semua OS termasuk Android dan iOS (PWA untuk mobile), riset mendalam dulu baru plan final. Semua angka di bawah dari sumber yang kubaca hari ini; yang belum terverifikasi ditandai.

## 1. Ringkasan temuan

1. Tidak ada satu repo siap pakai bertema swarm dan median yang terbukti untuk trading. Yang ada: simulasi sosial multi-agent (MiroFish, MiroShark), model forecasting yang bisa membuat banyak jalur harga (Kronos) atau kumpulan model (model dasar time series, FreqAI), ensemble LLM untuk prediksi peristiwa, dan ensemble agen RL (FinRL).
2. Bukti ensemble ada untuk prediksi peristiwa (ensemble 12 LLM sepadan dengan crowd manusia). Bukti ensemble menaikkan profit trading belum kutemukan. Bukti di sekitarnya hati-hati: sebagian besar LLM agent tidak mengalahkan buy-and-hold di StockBench; model dasar time series hanya sedikit mengalahkan random walk pada saham.
3. Swarm tetap layak dibangun, tetapi sebagai filter yang diukur lewat forward test, bukan sumber profit yang diasumsikan.
4. Decision model: ekosistemnya multi-vendor (daftar awesome-system-one memuat 19 hosted dan 24 open-weight). Wire /v1/systemone jadi bentuk standar, dan Ollama serta vLLM menyajikannya secara lokal. Dukungan banyak model mudah dibuat.
5. PWA cocok untuk Android, iOS, dan desktop sebagai panel kontrol dan notifikasi, bukan tempat bot berjalan. API Freqtrade tidak boleh dibuka langsung ke internet.

## 2. Repo dan metode swarm

| Nama | Jenis | Fakta yang kubaca | Peran di bot ini |
|---|---|---|---|
| MiroFish (666ghj) | simulasi sosial ribuan agen dengan memori, bahan awal berita atau sinyal keuangan | 81.796 bintang, lisensi AGPL-3.0. Butuh LLM API format OpenAI (README menyarankan Qwen-plus) dan Zep Cloud. README: "High consumption, try simulations with fewer than 40 rounds first". Belum ada benchmark terhadap hasil historis (artikel LinkedIn; crabtalk: "exploration tool, not a prediction engine" sampai ada backtest) | Bukan inti v1. Opsional untuk eksplorasi skenario berita |
| MiroShark | sama, 100+ agen di Twitter, Reddit, pasar prediksi | 1.480 bintang, AGPL-3.0. Klaim README: 1 dolar per simulasi, kurang dari 10 menit. Bukti akurasi belum kutemukan | Sama dengan MiroFish |
| Kronos (shiyu-coder) | model dasar candlestick (K-line) | 43.706 bintang, MIT, diterima AAAI 2026. Model terbuka: mini 4,1 juta, small 24,7 juta, base 102,3 juta parameter (large 499 juta tidak terbuka). Fungsi predict punya parameter sample_count: jumlah jalur prakiraan yang dibuat lalu dirata-rata. Klaim paper (self-reported): RankIC +93% dari model dasar time series terbaik. Evaluasi independen trading tidak kutemukan | Satu voter jalur harga dalam mode bayangan. Median antar jalur dibuat sendiri (memanggil berulang dengan benih berbeda; [INFERENCE] belum diuji) |
| Model dasar time series umum (Chronos, TimesFM, Moirai, TimeGPT) | prakiraan return | Paper independen arXiv 2606.27100 (return harian lima saham AS): model pretrained menang 8 dari 10 perbandingan tingkat tugas atas baseline neural, tetapi keunggulan atas random walk kecil dan jarang; uji Diebold-Mariano menolak hanya untuk Chronos di AMZN dan Moirai-2.0 di GOOG. Kesimpulan paper: berguna sebagai prior praktis, bukan mesin alpha yang andal | Voter cadangan; jangan diharapkan menghasilkan alpha |
| FreqAI (Freqtrade) | pelatihan model ML per pair (LightGBM, XGBoost, CatBoost, PyTorch di dokumen) | Sudah menyatu dengan engine, ada dry-run | Voter ML murah |
| FinRL ensemble (AI4Finance) | ensemble agen RL (PPO, A2C, DDPG) | Pola ensemble dari Yang dkk. 2020. Hasilnya belum kubaca | Referensi pola, tidak dipakai v1 |
| TradingAgents | debat multi-agent LLM | README: untuk riset, bukan saran trading (dibaca di revisi 1) | Bahan riset |

## 3. Bukti: yang diketahui dan yang belum

- Wisdom of the silicon crowd (Schoenegger dkk., Science Advances 2024): ensemble 12 LLM memprediksi 31 pertanyaan biner, dibandingkan 925 forecaster manusia selama 3 bulan; crowd LLM mengalahkan benchmark tanpa informasi dan tidak berbeda signifikan dari crowd manusia; ada bias acquiescence. Ini peristiwa, bukan harga.
- Halawi dkk. (NeurIPS 2024): sistem LM dengan retrieval, agregasi memakai trimmed mean, mendekati forecaster manusia kompetitif. Ini peristiwa, bukan harga.
- StockBench (arXiv 2510.02209): LLM agent trading saham multi-bulan tanpa kontaminasi data; sebagian besar model kesulitan mengalahkan buy-and-hold, beberapa menunjukkan potensi.
- Alpha Arena (Nof1), laporan sekunder: enam model, masing-masing 10.000 dolar di Hyperliquid, dua untung dan empat rugi 31-63%. Sumber primer belum kubaca; sumber lain menyebut hasil publik berakhir Desember 2025 (penamaan Season 1 dan 1.5 berbeda antar sumber).
- Bias look-ahead (arXiv 2512.23847): LLM terlatih dari berita masa lalu, sehingga backtest sinyal LLM atas data lama bocor. Karena itu bukti hanya dari forward test.
- Prinsip: model yang kesalahannya berkorelasi mengulang kesalahan yang sama, jadi median hanya membantu bila voter benar-benar beragam (vendor dan keluarga model berbeda).
- Belum ada: bukti bahwa swarm dengan median menaikkan profit bersih setelah fee untuk crypto spot pada modal kecil.

## 4. Decision model multi-vendor

Daftar: github.com/andyrewlee/awesome-system-one (dibaca 2026-10-25).
- Hosted (19 nama): Celeris-1, Decider (Perplexity), Decider 1, GLiDE, Hanzo Kai, Instinct, Jev, Jev Router, kettei, Snowflake Decision, Mercury Decide, Microsoft-Decision-1, OpenAI Decisions API, Sage, Solar Decide, Span-01, SPX-CD, SubQ Snap, wity-1.
- Open-weight (24 nama): basal-omni, Clef, Chon, CLM, Cua-S1, d1, Decisio, GEV-26B-Decide, GLiNER2.5-Decide, H2O-Lightning-4B, Intern-Decision, Jeva, Jev-Omni, Laya, mammoth/elephant, NeuDecide, OneJev, Quyet, StartLux-Decision, Strands Decider, Surogate Rune, Torchcast Decision, Vela, xor.
- Wire standar: bentuk request TypeSafe /v1/systemone. Ollama menyajikannya native sejak 0.35.0 (pull Nimble 9B, Tev1, d1, Clef, Clef-Flash, pplx-decider). vLLM upstream menyajikan /v1/systemone untuk model decision. Ada juga AnyJev (Nokia, Apache 2.0) yang mengubah LLM apa pun menjadi decision model tanpa training, dan beberapa server open-source lain.
- OpenAI Decisions API punya bentuk sendiri (plugin llm-openai-decisions menunjukkan predicate, choice, score).
- Gerbang hosted: OpenRouter (Decisions API, alpha), Vercel AI Gateway, Cloudflare Workers AI, LLMGateway (menurut README entri Jev). Di /api/v1/models OpenRouter hanya typesafe/jev-router muncul; model decision lain lewat endpoint Decisions, katalog langsungnya belum kutemukan.
- Harga yang tercantum: Jev 0,042 dolar per juta token input, output gratis; Clef-flash 0,038 dolar per juta input di Workers AI; Celeris-1 dan Decider 1 0,04 dolar per juta input.
- Peringatan: satu model open-weight di daftar melaporkan akurasi 72% vs 21% pada soal yang sama hanya karena urutan opsi dibalik. Urutan opsi harus diacak per voter dan hasilnya digabung.
- Cadangan tanpa decision model: LLM biasa dengan structured output. Di OpenRouter (467 model, diambil 2026-10-25) ada 103 model berstruktur dengan harga masukan sampai 0,2 dolar per juta, dan 11 model gratis berstruktur.

## 5. PWA, semua OS, dan akses jarak jauh

- iOS: web push untuk web app Home Screen tersedia di iOS 16.4 atau lebih baru; izin diminta lewat gestur pengguna (ketuk tombol) dan subscribe dipanggil langsung dari handler gestur itu; Safari tidak mendukung push tak terlihat; tidak perlu Apple Developer Program (dokumen Apple).
- Syarat PWA bisa dipasang: HTTPS, atau localhost dan 127.0.0.1 saat pengembangan (MDN).
- Freqtrade REST API: default hanya localhost; dokumen menyarankan sangat kuat untuk tidak membuka API ke internet; FreqUI tidak mendukung HTTPS bawaan. Di Docker, API harus mendengarkan koneksi masuk dan port dipetakan ke 127.0.0.1:8080.
- FreqUI bukan PWA: di pohon repo frequi (321 berkas) tidak ada manifest atau service worker, dan package.json tanpa dependensi PWA. Perlu PWA sendiri.
- Titik integrasi: REST API Freqtrade, websocket pesan (/api/v1/message/ws), dan webhook (entry, exit, dan lainnya).
- Bot tidak dijalankan di HP; [INFERENCE] iOS dan Android membatasi proses latar belakang. Mesin di VPS atau PC lewat Docker (dokumen Freqtrade merekomendasikan Docker untuk Windows), mobile jadi panel kontrol dan notifikasi.
- Pemasangan PWA di desktop Chrome dan Edge belum kuverifikasi di run ini.

## 6. Belum terverifikasi

- Kronos di CPU VPS kecil (README tidak menyebut kebutuhan GPU; belum diuji) dan kecepatan inferensinya.
- Katalog langsung decision model di OpenRouter.
- Akses dan biaya Reddit dan X.
- Dukungan Freqtrade untuk Indodax.
- Alpha Arena dari sumber primer; hasil FinRL ensemble.
- Bukti swarm median menaikkan profit trading bersih.

## 7. Sumber

- https://github.com/666ghj/MiroFish
- https://github.com/MiroShark/MiroShark
- https://crabtalk.ai/blog/mirofish-swarm-prediction
- https://github.com/shiyu-coder/Kronos dan https://arxiv.org/abs/2508.02739
- https://arxiv.org/html/2606.27100
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11800985/
- https://arxiv.org/html/2402.18563v1
- https://arxiv.org/html/2510.02209
- https://arxiv.org/html/2512.23847v1
- https://syntheticalpha.beehiiv.com/p/the-receipts-are-in-ai-lost-synthetic-alpha-issue-5 dan https://www.traderank.ai/llm-trading-benchmark
- https://github.com/AI4Finance-Foundation/FinRL
- https://github.com/andyrewlee/awesome-system-one
- https://openrouter.ai/docs/guides/community/jev
- https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers
- https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable
- Dokumen Freqtrade: rest-api.md, webhook-config.md, freqai.md; repo freqtrade/frequi
