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
- `POST /gw/v1/dev/upstream` body `{"seconds": 30}` meniru Freqtrade mati: `gw.error` tiap 5 detik, `/health`, `/overview`, `/risk` membalas 503
- `POST /gw/v1/dev/fail` body `{"path": "/gw/v1/decisions", "status": 404}` memaksa satu endpoint gagal; `status: 0` memulihkannya
- `POST /gw/v1/dev/push` body `{"kind": "fill" | "risk_breach" | "kill_switch" | "heartbeat_lost" | "quorum_failed" | "daily_summary"}`

Tes: `npm test` (backoff, klien feed, kesegaran data, keadaan keselamatan, refresh inti vs panel, klien HTTP, format angka bertanda, teks feed).

## Nice-to-have N2 (ZHA-3781)

- Mesin waktu (layar Grafik, tombol "Buka mesin waktu"): penggeser dan tombol panah melangkah per keputusan swarm untuk pair itu; keputusan terpilih tampil di atas grafik (hasil, kuorum, median, sebaran, titik tiap voter, jawaban tiap voter) dan ditandai di grafik pada kandelnya. Data dari `/gw/v1/decisions?pair=&limit=200` (`docs/gateway-api.md` 12.1), dimuat hanya saat mesin waktu dibuka. Keputusan yang lebih tua dari 300 kandel yang dimuat dihitung dan disebut, tidak ditampilkan.
- Lapisan berita dan sentimen (kotak centang di Lapisan, mati bawaan): judul RSS CoinDesk dan Cointelegraph yang menyebut aset pair ditandai per jam di grafik dan didaftar beserta sumber, jam ambil, dan galat per sumber; Fear & Greed alternative.me sebagai garis harian di panel bawah dengan atribusi dan tautan. Data dari `/gw/v1/news` dan `/gw/v1/sentiment` (12.2, 12.3); pengambil sungguhan di `engine/news.py`. Lapisan hanya tampilan, tidak mengubah keputusan bot.
- Tampilan terakhir saat offline: setiap refresh inti yang berhasil menyimpan keadaan (inti, posisi, ekuitas, keputusan, kandel maksimal 300 per pair, berita, sentimen) di `localStorage` `tb.lastView`. Saat offline tanpa sesi, layar masuk menawarkan "Buka tampilan terakhir", yang menampilkan semua layar hanya baca dengan jam simpan dan label "hanya baca". Keluar dari gateway menghapusnya. Manifest kini ikut di-cache supaya tidak ada galat jaringan saat offline.
- Lencana ikon aplikasi: service worker memasang `setAppBadge(n)` dengan jumlah notifikasi yang masih tampil bila tidak ada jendela aplikasi yang terlihat, dan `clearAppBadge()` saat jendela terlihat, notifikasi diklik, atau notifikasi terakhir ditutup. Halaman juga membersihkan lencana saat dibuka atau kembali terlihat.
- Dua bahasa: Indonesia bawaan, Inggris lewat pilihan di layar Sistem atau layar masuk (`localStorage` `tb.lang`, berganti memuat ulang aplikasi). Teks di `src/lib/locales/id.ts` dan `en.ts`; tes memastikan kedua kamus punya kunci dan placeholder yang sama. Angka, tanggal, dan sumbu grafik mengikuti bahasa (`id-ID` atau `en-GB`). Kode keadaan dari gateway (`izinkan`, `kecilkan`, `lewati`, kelas Fear & Greed) diterjemahkan di `src/lib/words.ts`.

Terukur (Chromium headless, gateway tiruan, 2026-10-26): bundel utama 128,58 kB (gzip 45,70 kB) sebelum, 158,05 kB (gzip 51,99 kB) sesudah; selisih +6,29 kB gzip, di antaranya kedua kamus (masing-masing sekitar 16,5 kB mentah, kamus Inggris 5,5 kB gzip). Kamus tidak dipecah per bahasa karena keduanya kecil dibanding modul grafik (57,44 kB gzip). Pengambil berita nyata: umpan dingin 0,28 s (dua RSS), dari cache 0,1 ms, Fear & Greed dingin 1,04 s.

Belum terbukti untuk N2: izin dan tampilan lencana di iOS 16.4 atau lebih baru (butuh perangkat; Chromium headless hanya membuktikan API ada dan push memunculkan notifikasi), lencana di Android dan desktop terlihat oleh manusia, rute `/gw/v1/news`, `/gw/v1/sentiment`, dan parameter `pair`/`before` di gateway nyata (gateway belum di main), dan kualitas terjemahan Inggris oleh penutur asli.

## Pilihan dan alasannya

- Kerangka: Svelte 5 dengan Vite 8, tanpa pustaka komponen. Runtime kecil (bundel utama 107,05 kB, gzip 38,08 kB; naik 4,62 kB dari 102,43 kB karena penanganan galat inti dan panel) dan reaktivitas rune cocok untuk aliran event WebSocket. Tidak memakai Vue atau Nuxt UI supaya tampilan bawaan FreqUI dan Nuxt UI tidak terbawa.
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
- Area sentuh: semua tombol, tab, dan tautan setinggi minimal 44 px; kotak centang lapisan 20 px di dalam label setinggi 44 px.

## Belum terbukti

- iOS 16.4 atau lebih baru di perangkat nyata: pasang ke Layar Utama, izin push lewat tombol, notifikasi tampil. Layar Sistem menampilkan petunjuk Layar Utama saat dibuka dari Safari biasa, tetapi alur itu belum diuji di iPhone.
- Android dan desktop: dialog pasang dari Chrome atau Edge belum diklik oleh manusia; yang terbukti hanya syarat installability.
- Gateway nyata, jeda fill di Freqtrade sampai tampil di PWA, dan beban CPU gateway: gateway belum dibangun (ZHA-3764).
- Bentuk `/gw/v1/equity`, `/gw/v1/decisions`, `gw.decision`, dan `/gw/v1/push/*` masih rancangan (`docs/gateway-api.md` bagian 11).
- Pembaca layar: ARIA dan urutan fokus diperiksa di kode, belum diuji dengan VoiceOver atau TalkBack.
