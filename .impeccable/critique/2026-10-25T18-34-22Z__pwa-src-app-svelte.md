---
target: PWA tahap 1 (5 layar)
total_score: 29
p0_count: 0
p1_count: 0
timestamp: 2026-10-25T18-34-22Z
slug: pwa-src-app-svelte
---
## Critique impeccable: pwa/src/App.svelte (5 layar, ponsel 390 px dan desktop 1440 px, terang dan gelap)

### Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4 | Mode, tersambung, usia data, dan keadaan besar selalu di layar; basi mengubah papan jadi abu dengan jam data terakhir |
| 2 | Match System / Real World | 3 | Istilah swarm (median, selisih kuartil, kuorum) dijelaskan satu kalimat, tetap teknis |
| 3 | User Control and Freedom | 3 | Baca-saja; filter feed, pilih pair, lapisan grafik, keputusan lama bisa dipilih |
| 4 | Consistency and Standards | 3 | Satu kosakata baris, tabel, tab; Swarm menyorot pilihan dengan kotak, Grafik dengan garis bawah |
| 5 | Error Prevention | 3 | Tidak ada aksi berisiko; tombol notifikasi mati saat izin ditolak |
| 6 | Recognition Rather Than Recall | 3 | Legenda grafik ditulis di bawah grafik, bukan di atas |
| 7 | Flexibility and Efficiency | 2 | Tidak ada pintasan papan ketik di desktop; tidak ada tautan langsung ke satu trade |
| 8 | Aesthetic and Minimalist Design | 3 | Ringkas di ponsel panjang (sekitar 2.400 px) karena kolom samping desktop ditumpuk di bawah |
| 9 | Error Recovery | 3 | Terputus: alasan, jam, hitung mundur, tombol Coba sekarang; galat REST hanya disimpan, belum tampil |
| 10 | Help and Documentation | 2 | Petunjuk iOS dan catatan per bagian ada; tidak ada glosarium |
| **Total** | | **29/40** | **Good** |

### Anti-Patterns Verdict

LLM: tidak terbaca sebagai AI. Uji cepat DESIGN.md: tema terang putih, satu warna jingga hanya untuk batas dan peringatan, untung biru tua, kandel abu tanpa hijau merah; dari warna dan bentuk saja layar Ringkas terbaca sebagai papan stasiun (satu kata besar di bidang tinta) dan strip seismograf (jejak satu garis dengan garis batas putus), bukan dasbor trading. Tidak ada hero-metric (yang besar adalah kata keadaan, bukan angka profit), tidak ada kartu, tidak ada gradient, eyebrow, atau penomoran. Grafik kandel di layar Grafik tetap mirip alat charting umum; itu wajar karena memang alat charting, dan tidak menjadi pusat aplikasi.

Detector: sumber (`pwa/src`, `index.html`, `public`) 0 temuan. HTML yang dirender dari 5 layar plus CSS hasil build: 2 temuan `side-tab` pada `border-left: 1px solid var(--rule)` (pembatas kolom samping Ringkas) dan `border-right: 1px solid var(--rule)` (pembatas rel navigasi desktop). Keduanya positif palsu: larangan skill adalah aksen berwarna lebih dari 1 px di sisi kartu; ini garis netral 1 px pembatas kolom, bukan kartu dan bukan aksen. Run sebelumnya juga melaporkan `numbered-section-markers` dari jam di feed (01, 02, 06); temuan itu hilang setelah data contoh diperbarui dan memang jam, bukan perancah. Font Inter ditandai `overused-font` dan diganti Atkinson Hyperlegible Next.

### Overall Impression

Tenang dan terbaca dalam dua detik: kata Aman, Ditahan, atau Berhenti di atas, kalimat yang menyebut angka dan batasnya, lalu jejak hari ini dengan garis batas. Peluang terbesar: ponsel Ringkas terlalu panjang.

### What's Working

- Papan keadaan memakai bidang tinta untuk aman dan bidang sinyal untuk ditahan atau berhenti, dengan kalimat yang menyebut batas; saat basi papan berubah abu dengan jam data terakhir, jadi warna tidak pernah mengklaim keadaan yang tidak diketahui.
- Setiap untung rugi membawa tanda (+ atau U+2212), segitiga arah, dan kata untung, rugi, atau impas; biru tua dan jingga hanya penguat.
- Meter risiko menyebut sisa dalam persen sebelum entry ditahan, dan berubah jadi "Batas tercapai" saat terlewati.

### Priority Issues

- [P2] Ringkas ponsel panjang. Kolom samping desktop (keputusan swarm, kesehatan, aksi terakhir) ditumpuk di bawah; di 390 px halaman sekitar 2.400 px. Fix: di ponsel ganti jadi satu baris ringkas per bagian dengan tautan ke layar penuhnya. Command: $impeccable distill.
- [P2] Galat REST tidak terlihat. `gateway.error` diisi saat fetch gagal tetapi tidak ditampilkan; pengguna hanya melihat usia data menua. Fix: tampilkan di StaleBanner bila galat lebih baru dari data terakhir. Command: $impeccable harden.
- [P2] Feed kosong setelah masuk ulang. Feed hanya berisi event sejak tersambung; resume tidak berlaku untuk sesi baru. Fix: gateway nyata mengirim 50 event terakhir di `gw.hello`. Command: $impeccable onboard.
- [P3] Label harga di sumbu grafik ponsel memakan sekitar seperempat lebar (1.463.933.000). Fix: format ringkas (1,464 M) di sumbu, angka penuh di crosshair. Command: $impeccable adapt.

### Persona Red Flags

- Casey (pengguna ponsel yang terganggu): dari notifikasi ke jawaban butuh satu ketukan dan satu lirikan; aman. Posisi terbuka berada di bawah lipatan pertama setelah papan, jejak, dan dua meter.
- Alex (pengguna mahir di desktop): tidak ada pintasan papan ketik untuk berpindah layar atau pair; tidak ada URL per pair (`#grafik` selalu mulai dari pair pertama).
- Zhafron (pemilik, tengah malam, tema gelap): tema gelap dirancang terpisah, sinyal tetap jingga, kontras teks kedua 9,14:1; tidak ada warna menyilaukan selain papan Ditahan.

### Minor Observations

- Di desktop Swarm, label v6 bisa menempel garis median bila nilainya hampir sama.
- Kandel berongga untuk naik dan penuh untuk turun mengikuti konvensi charting, dijelaskan di catatan bawah grafik.

### Questions to Consider

- Haruskah Ringkas ponsel berhenti setelah posisi terbuka dan memindahkan sisanya ke layar masing-masing? (Opsi: ya, ringkas; tidak, satu gulir lengkap.)
- Perlukah sesi PWA bertahan setelah aplikasi ditutup (sekarang token di sessionStorage, masuk ulang tiap buka)? (Opsi: tetap; simpan di IndexedDB dengan masa berlaku pendek.)

Questions skipped dari kartu: mode full otonom; keputusan diambil sebagai "Keputusan otonom" di komentar penutup, Zhafron mengoreksi sambil jalan.
