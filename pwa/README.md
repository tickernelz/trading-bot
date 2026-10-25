# PWA tahap 1 (baca-saja)

Panel bot trading untuk ponsel dan desktop: keadaan aman, ditahan, atau berhenti; jejak untung rugi hari ini; meter risiko; posisi dan order; grafik kandel per pair; feed aksi; keputusan swarm beserta jawaban voter; kesehatan; Bot A vs Bot B; notifikasi Web Push. Tidak ada kontrol, provider dan key, atau konfigurasi (tahap 2).

Gateway nyata belum ada. Semua data datang dari gateway tiruan `mock-gateway/` dan PWA memberi label "contoh data" selama `/gw/v1/health` membawa `gateway.sample_data: true`. Endpoint yang dipakai: `docs/gateway-api.md` bagian 5, 7, dan 11.

## Menjalankan

    cd pwa
    NODE_ENV=development npm install
    npm run mock-gateway
    npm run build && npm run preview

Buka http://localhost:4173, kata sandi gateway tiruan `contoh` (ubah lewat `MOCK_GATEWAY_PASSWORD`). `npm run dev` memakai port 5173. Vite meneruskan `/gw` (HTTP dan WebSocket) ke `GATEWAY_URL`, bawaan `http://127.0.0.1:8090`.

Gateway tiruan punya rute uji tanpa token, hanya untuk pengembangan:

- `POST /gw/v1/dev/scenario` body `{"name": "aman" | "ditahan" | "berhenti"}`
- `POST /gw/v1/dev/drop` body `{"seconds": 20}` memutus semua sambungan dan menolak sambungan baru selama itu
- `POST /gw/v1/dev/push` body `{"kind": "fill" | "risk_breach" | "kill_switch" | "heartbeat_lost" | "quorum_failed" | "daily_summary"}`

Tes: `npm test` (backoff, klien feed, format angka bertanda, teks feed).

## Pilihan dan alasannya

- Kerangka: Svelte 5 dengan Vite 8, tanpa pustaka komponen. Runtime kecil (bundel utama 102,43 kB, gzip 36,68 kB) dan reaktivitas rune cocok untuk aliran event WebSocket. Tidak memakai Vue atau Nuxt UI supaya tampilan bawaan FreqUI dan Nuxt UI tidak terbawa.
- Grafik: TradingView Lightweight Charts 5.2.1 (Apache-2.0, atribusi ada di layar Sistem). Canvas, kandel, penanda masuk dan keluar, garis harga untuk stop loss, panel kedua untuk RSI. Dimuat malas hanya di layar Grafik (176,63 kB, gzip 57,44 kB). ECharts tidak dipakai karena itu pustaka FreqUI. Jejak harian dan sebaran voter digambar sendiri dengan SVG.
- Huruf: Atkinson Hyperlegible Next. Bukti angka tabular dan alasan penolakan Inter ada di `DESIGN.md` bagian Typography. Hanya subset latin dan latin-ext yang dimuat (34 kB dan 19 kB woff2).
- Service worker tulisan tangan (`public/sw.js`), tanpa Workbox: shell disimpan untuk dibuka offline, `/gw/` tidak pernah di-cache, push selalu tampil sebagai notifikasi terlihat.

## Terukur (Chromium headless, gateway tiruan di localhost, 2026-10-26)

- Installable: `Page.getInstallabilityErrors` kosong, manifest tanpa galat, service worker `activated` dan mengendalikan halaman.
- Web Push: langganan FCM dibuat lewat tombol; enam jenis push dikirim (masing-masing `sent: 1`), enam notifikasi tampil; `risk_breach`, `kill_switch`, `heartbeat_lost` dengan `requireInteraction`.
- Sambung ulang: gateway diputus 25 detik; percobaan pada 0; 1,0; 2,5; 6,6; 11,2; 23,4 detik, tersambung lagi pada 44,1 detik dan papan kembali dari mode basi ke "Aman". Jeda backoff 1 s dikali 2 sampai 30 s, jitter separuh atas; reset hanya setelah tersambung 10 s. Saat `navigator.onLine` false klien menunggu event `online` tanpa menghabiskan percobaan.
- Feed: jeda dari event tiba di browser sampai tampil di DOM median 1,7 ms, maks 2,1 ms (n = 8).
- Offline: muat ulang tanpa jaringan menampilkan shell dari cache dengan "Perangkat sedang offline" dan "Mode belum diketahui".
- Kontras: lihat `DESIGN.md` bagian Colors; semua pasangan teks di atas 4,5:1 di kedua tema.
- Area sentuh: semua tombol, tab, dan tautan setinggi minimal 44 px; kotak centang lapisan 20 px di dalam label setinggi 44 px.

## Belum terbukti

- iOS 16.4 atau lebih baru di perangkat nyata: pasang ke Layar Utama, izin push lewat tombol, notifikasi tampil. Layar Sistem menampilkan petunjuk Layar Utama saat dibuka dari Safari biasa, tetapi alur itu belum diuji di iPhone.
- Android dan desktop: dialog pasang dari Chrome atau Edge belum diklik oleh manusia; yang terbukti hanya syarat installability.
- Gateway nyata, jeda fill di Freqtrade sampai tampil di PWA, dan beban CPU gateway: gateway belum dibangun (ZHA-3764).
- Bentuk `/gw/v1/equity`, `/gw/v1/decisions`, `gw.decision`, dan `/gw/v1/push/*` masih rancangan (`docs/gateway-api.md` bagian 11).
- Pembaca layar: ARIA dan urutan fokus diperiksa di kode, belum diuji dengan VoiceOver atau TalkBack.
