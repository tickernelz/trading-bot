# PWA bot trading

Panel bot trading untuk ponsel dan desktop. Tahap 1: keadaan aman, ditahan, atau berhenti; jejak untung rugi hari ini; meter risiko; posisi dan order; grafik kandel per pair; feed aksi; keputusan swarm; kesehatan; notifikasi Web Push. Tahap 2: Kontrol (kill switch, exit paksa, kunci pair, blacklist, hentikan bot, dengan konfirmasi dua langkah dari gateway), Konfigurasi (editor per bot dengan validasi skema, tinjauan nilai lama dan baru, dua langkah bila menaikkan batas atau modal, voter, catatan perubahan), Provider dan key (sesi jarak jauh: status dan uji koneksi; sesi `control` dari PC bot: key, tambah, ubah, hapus, peran, impor models.yml), Swarm per keputusan dengan hasil sesudahnya, Riwayat dan statistik, Bot A vs B, dan Audit.

Gateway tiruan `mock-gateway/` menyajikan data contoh, dan PWA memberi label "contoh data" selama `/gw/v1/health` membawa `gateway.sample_data: true`. Endpoint yang dipakai: `docs/gateway-api.md` bagian 5, 7, 11 (tahap 1) dan 15 (tahap 2). Kontrol dan audit memakai kontrak ZHA-3774 (`feat/stage-2a-control`), konfigurasi, provider, key, voter, dan peran memakai kontrak ZHA-3775 (`feat/stage-2b-config`) apa adanya; keduanya belum di `main`. Swarm per keputusan, riwayat, dan A vs B masih rancangan (15.3) sampai ZHA-3776 ada.

Ponsel memakai tab Ringkas, Grafik, Aksi, Kontrol, Lainnya; Kontrol di tab utama supaya kill switch satu ketukan. Desktop memakai rel berkelompok Pantau, Kendali, Catatan, Sistem.

## Menjalankan

    cd pwa
    NODE_ENV=development npm install
    npm run mock-gateway
    npm run build && npm run preview

Buka http://localhost:4173, kata sandi gateway tiruan `contoh` (ubah lewat `MOCK_GATEWAY_PASSWORD`). `npm run dev` memakai port 5173. Vite meneruskan `/gw` (HTTP dan WebSocket) ke `GATEWAY_URL`, bawaan `http://127.0.0.1:8090`.

Gateway tiruan punya rute uji tanpa token, hanya untuk pengembangan:

- `POST /gw/v1/dev/scenario` body `{"name": "aman" | "ditahan" | "berhenti"}`
- `POST /gw/v1/dev/drop` body `{"seconds": 20}` memutus semua sambungan dan menolak sambungan baru selama itu
- `POST /gw/v1/dev/upstream` body `{"seconds": 30}` meniru Freqtrade mati: `gw.error` tiap 5 detik, `/health`, `/overview`, `/risk` membalas 503
- `POST /gw/v1/dev/fail` body `{"path": "/gw/v1/decisions", "status": 404}` memaksa satu endpoint gagal; `status: 0` memulihkannya
- `POST /gw/v1/dev/push` body `{"kind": "fill" | "risk_breach" | "kill_switch" | "heartbeat_lost" | "quorum_failed" | "daily_summary"}`
- `POST /gw/v1/dev/remote` body `{"remote": true}` membuat login berikutnya (dan sesi yang ada) berlingkup `read`, seperti login lewat tunnel; `false` mengembalikan `control`. `MOCK_REMOTE=1` memulai dalam keadaan itu.

Tes: `npm test`. Tahap 1: backoff, klien feed, kesegaran data, keadaan keselamatan, refresh inti vs panel, klien HTTP, format angka bertanda, teks feed. Tahap 2: `tests/settings.test.ts` (kunci yang boleh diubah lewat PATCH, badan `changes` bersarang, aturan dua langkah setara `raising_keys` 2b, pemetaan galat skema ke kolom, validasi setara `engine/settings.py`), `tests/control.test.ts` (dua langkah dengan kunci idempotensi yang sama, `confirmation_expired` dan `confirmation_invalid`), `tests/decisions.test.ts` (hasil sesudahnya, audit), dan `tests/contract.test.ts` yang menjalankan gateway tiruan dan memakai klien PWA: aturan 2a (lingkup, `Idempotency-Key` wajib, putar ulang termasuk hasil gagal 502, kunci tidak sah diaudit `rejected`, token untuk sasaran lain ditolak, exit-all, DELETE dengan confirm) dan 2b (PATCH bersarang, akar terkunci, dua langkah untuk batas dan modal, galat skema, sesi `read` ditolak dan diaudit `admin.denied`, voter per rute dengan kuorum, peran, key hanya lewat rute key dengan nilai penanda yang tidak muncul di respons mana pun, impor dengan key hanya bila dicentang), plus paging keputusan, trade, dan audit.

## Nice-to-have N2 (ZHA-3781)

- Mesin waktu (layar Grafik, tombol "Buka mesin waktu"): penggeser dan tombol panah melangkah per keputusan swarm untuk pair itu; keputusan terpilih tampil di atas grafik (hasil, kuorum, median, sebaran, titik tiap voter, jawaban tiap voter) dan ditandai di grafik pada kandelnya. Data dari `/gw/v1/decisions?pair=&limit=200` (`docs/gateway-api.md` 12.1), dimuat hanya saat mesin waktu dibuka. Keputusan yang lebih tua dari 300 kandel yang dimuat dihitung dan disebut, tidak ditampilkan.
- Lapisan berita dan sentimen (kotak centang di Lapisan, mati bawaan): judul RSS CoinDesk dan Cointelegraph yang menyebut aset pair ditandai per jam di grafik dan didaftar beserta sumber, jam ambil, dan galat per sumber; Fear & Greed alternative.me sebagai garis harian di panel bawah dengan atribusi dan tautan. Data dari `/gw/v1/news` dan `/gw/v1/sentiment` (12.2, 12.3); pengambil sungguhan di `engine/news.py`. Lapisan hanya tampilan, tidak mengubah keputusan bot.
- Tampilan terakhir saat offline: setiap refresh inti yang berhasil menyimpan keadaan (inti, posisi, ekuitas, keputusan, kandel maksimal 300 per pair, berita, sentimen) di `localStorage` `tb.lastView`. Saat offline tanpa sesi, layar masuk menawarkan "Buka tampilan terakhir", yang menampilkan semua layar hanya baca dengan jam simpan dan label "hanya baca". Keluar dari gateway menghapusnya. Manifest kini ikut di-cache supaya tidak ada galat jaringan saat offline.
- Lencana ikon aplikasi: service worker memasang `setAppBadge(n)` dengan jumlah notifikasi yang masih tampil bila tidak ada jendela aplikasi yang terlihat, dan `clearAppBadge()` saat jendela terlihat, notifikasi diklik, atau notifikasi terakhir ditutup. Halaman juga membersihkan lencana saat dibuka atau kembali terlihat.
- Dua bahasa: Indonesia bawaan, Inggris lewat pilihan di layar Sistem atau layar masuk (`localStorage` `tb.lang`, berganti memuat ulang aplikasi). Teks di `src/lib/locales/id.ts` dan `en.ts`; tes memastikan kedua kamus punya kunci dan placeholder yang sama. Angka, tanggal, dan sumbu grafik mengikuti bahasa (`id-ID` atau `en-GB`). Kode keadaan dari gateway (`izinkan`, `kecilkan`, `lewati`, kelas Fear & Greed) diterjemahkan di `src/lib/words.ts`.

Terukur (Chromium headless, gateway tiruan, 2026-10-26): bundel utama 128,58 kB (gzip 45,70 kB) sebelum, 158,05 kB (gzip 51,99 kB) sesudah; selisih +6,29 kB gzip, di antaranya kedua kamus (masing-masing sekitar 16,5 kB mentah, kamus Inggris 5,5 kB gzip). Kamus tidak dipecah per bahasa karena keduanya kecil dibanding modul grafik (57,44 kB gzip). Pengambil berita nyata: umpan dingin 0,28 s (dua RSS), dari cache 0,1 ms, Fear & Greed dingin 1,04 s.

Belum terbukti untuk N2: izin dan tampilan lencana di iOS 16.4 atau lebih baru (butuh perangkat; Chromium headless hanya membuktikan API ada dan push memunculkan notifikasi), lencana di Android dan desktop terlihat oleh manusia, rute `/gw/v1/news`, `/gw/v1/sentiment`, dan parameter `pair`/`before` di gateway nyata (gateway belum di main), dan kualitas terjemahan Inggris oleh penutur asli.

## Pilihan dan alasannya

- Kerangka: Svelte 5 dengan Vite 8, tanpa pustaka komponen. Reaktivitas rune cocok untuk aliran event WebSocket. Tahap 2 memuat malas tujuh layar baru beserta Swarm dan Sistem, dan kamus Inggris kini dimuat hanya saat bahasa Inggris dipilih (top-level `await import`). Muatan awal (skrip utama, CSS, dan modul yang dipreload) 205,6 kB, gzip 70,0 kB, terhadap 202,9 kB, gzip 65,0 kB di `main` 3cd1e8a (`vite build` yang sama): naik 2,7 kB mentah dan 5,0 kB gzip, karena ratusan kunci teks tahap 2 masuk kamus Indonesia yang selalu dimuat dan pecahan modul bersama ikut dipreload. Sebelum kamus Inggris dipisah, skrip utama dan modul bersama saja sudah 220,6 kB, gzip 74,3 kB (angka Vite: 82,3 kB dan 138,3 kB). Layar terbesar Konfigurasi 39 kB, gzip 11,9 kB, hanya saat dibuka. Tidak memakai Vue atau Nuxt UI supaya tampilan bawaan FreqUI dan Nuxt UI tidak terbawa.
- Grafik: TradingView Lightweight Charts 5.2.1 (Apache-2.0, atribusi ada di layar Sistem). Canvas, kandel, penanda masuk dan keluar, garis harga untuk stop loss, panel kedua untuk RSI. Dimuat malas hanya di layar Grafik (176,63 kB, gzip 57,44 kB). ECharts tidak dipakai karena itu pustaka FreqUI. Jejak harian dan sebaran voter digambar sendiri dengan SVG.
- Huruf: Atkinson Hyperlegible Next. Bukti angka tabular dan alasan penolakan Inter ada di `DESIGN.md` bagian Typography. Hanya subset latin dan latin-ext yang dimuat (34 kB dan 19 kB woff2).
- Service worker tulisan tangan (`sw/sw.js`), tanpa Workbox. Plugin kecil di `vite.config.ts` menulis `dist/sw.js` dengan nama cache dari hash daftar aset dan daftar aset itu untuk precache, jadi tiap build punya cache sendiri dan cache lama dihapus saat activate. `/gw/` tidak pernah di-cache, halaman navigasi hanya disimpan bila respons `ok`, URL dari push dibatasi ke origin sendiri, dan push selalu tampil sebagai notifikasi terlihat. Hanya didaftarkan di build produksi.

## Terukur (Chromium headless, gateway tiruan di localhost, 2026-10-26)

- Installable: `Page.getInstallabilityErrors` kosong, manifest tanpa galat, service worker `activated` dan mengendalikan halaman.
- Web Push: langganan FCM dibuat lewat tombol; enam jenis push dikirim (masing-masing `sent: 1`), enam notifikasi tampil; `risk_breach`, `kill_switch`, `heartbeat_lost` dengan `requireInteraction`.
- Sambung ulang: gateway diputus 25 detik; percobaan pada 0; 1,0; 2,5; 6,6; 11,2; 23,4 detik, tersambung lagi pada 44,1 detik dan papan kembali dari mode basi ke "Aman". Jeda backoff 1 s dikali 2 sampai 30 s, jitter separuh atas; reset hanya setelah tersambung 10 s. Saat `navigator.onLine` false klien menunggu event `online` tanpa menghabiskan percobaan.
- Feed: jeda dari event tiba di browser sampai tampil di DOM median 1,7 ms, maks 2,1 ms (n = 8).
- Offline: muat ulang tanpa jaringan menampilkan shell dari cache dengan "Perangkat sedang offline"; bila keadaan belum pernah dimuat, bar atas menampilkan "Mode ?" (label aksesibel "Mode belum diketahui").
- Kontras: lihat `DESIGN.md` bagian Colors; semua pasangan teks di atas 4,5:1 di kedua tema.
- Area sentuh: semua tombol, tab, dan tautan setinggi minimal 44 px; kotak centang lapisan 20 px di dalam label setinggi 44 px. Tahap 2 diukur ulang di 390 px pada delapan layar: nol elemen interaktif di bawah 44 px.
- Tahap 2, tanpa gulir samping di 360 px pada 12 layar (`scrollWidth` = 360). Batas kolom isian 3,93:1 (terang) dan 3,29:1 (gelap) terhadap latar; placeholder 8,41:1 dan 9,14:1. `prefers-reduced-motion: reduce`: animasi panel konfirmasi 0 s.
- Tahap 2, klien PWA (`createApi`, `send`, `patchBody`, `schemaErrors`, label audit) dijalankan terhadap gateway 2b nyata (`feat/stage-2b-config` b7a801d, yang memuat 2a dbc3b9f) di image `trading-bot/engine:test-zha3775` dengan Freqtrade palsu `CountingFreqtrade`: kontrol dua langkah, exit-all, DELETE blacklist dengan body confirm, token aksi lain `confirmation_invalid`, sesi `read` 403; PATCH bersarang (menurunkan batas, menaikkan modal dengan langkah 2, akar `api` 400, galat skema terpetakan ke `risk.max_open_trades`, sesi `read` 403), `settings/changes`, bentuk `providers`, uji koneksi dari sesi `read` lalu `429` dalam 5 detik, key lewat `/key`, `api_key` di badan provider 400, rute `/state` 404, voter PUT/DELETE, peran, pratinjau dan impor (key berupa perintah 400); semua aksi dan hasil audit nyata punya label PWA; nilai key literal tidak muncul di pratinjau atau audit.
- Tahap 2, dijalankan di Chromium terhadap gateway tiruan: exit paksa dua langkah (fokus pindah ke panel, trade tertutup setelah langkah 2), kill switch satu langkah, sesi `read` dengan semua tombol kontrol nonaktif dan tanpa kolom key, simpan konfigurasi yang menaikkan batas dengan langkah 2 lalu catatan muncul di log, key provider disimpan lalu hanya "berakhiran ABCD" yang tampil, dan galat 502 di tujuh endpoint tampil per bagian dengan Coba lagi.

## Belum terbukti

- iOS 16.4 atau lebih baru di perangkat nyata: pasang ke Layar Utama, izin push lewat tombol, notifikasi tampil. Layar Sistem menampilkan petunjuk Layar Utama saat dibuka dari Safari biasa, tetapi alur itu belum diuji di iPhone.
- Android dan desktop: dialog pasang dari Chrome atau Edge belum diklik oleh manusia; yang terbukti hanya syarat installability.
- Layar PWA di browser terhadap gateway nyata: klien PWA diuji terhadap gateway 2b nyata dengan Freqtrade palsu, layar di Chromium hanya terhadap gateway tiruan; Freqtrade dry-run sungguhan belum dipakai untuk layar tahap 2.
- Bagian 15.3 masih rancangan (menunggu ZHA-3776): `outcome` keputusan, `status` dan `bot` di `/gw/v1/decisions`, `offset` dan `state=closed` trade, `window=total` ekuitas, `overview.state` per bot.
- Mengaktifkan atau menonaktifkan provider dari jarak jauh tidak dibangun (2b membatasi sesi `read` ke baca dan uji); keputusan ada di ZHA-3796.
- Pembaca layar: ARIA dan urutan fokus diperiksa di kode, belum diuji dengan VoiceOver atau TalkBack.

## Audit teknis tahap 2 (impeccable audit, 2026-10-26)

| # | Dimensi | Skor | Temuan utama |
| --- | --- | --- | --- |
| 1 | Aksesibilitas | 3 | Semua isian berlabel, tombol bernama, fokus 2 px; pembaca layar belum diuji |
| 2 | Performa | 4 | Tujuh layar baru dan Swarm, Sistem dimuat malas; muatan awal turun |
| 3 | Responsif | 3 | Tanpa gulir samping di 360 px pada 12 layar; Konfigurasi ponsel panjang |
| 4 | Tema | 4 | Semua warna dari token; gelap dan terang diukur |
| 5 | Anti-pattern | 4 | Detector `[]` dengan kontrol negatif |
| **Total** | | **18/20** | P0 0, P1 0 |
