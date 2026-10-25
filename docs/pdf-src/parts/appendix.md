
::: {.pb}
:::

# Lampiran: Arah visual dan mockup

Semua angka, saldo, nama posisi, dan hasil voter di mockup adalah contoh data, bukan hasil nyata; setiap layar membawa label itu. Tidak ada API key atau nilai rahasia di mockup. Nama provider dan model dari tabel 5.3 dan 5.4. Selama testing semua voter memakai deepseek-v4.1-flash-1017 di nutaraline (bab 5.4); daftar voter beragam di mockup menunjukkan konfigurasi setelah mesin lolos uji.

## A.1 Keputusan arah visual (plan bagian 12; PRODUCT.md dan DESIGN.md)

Arah visual adalah keputusan Wira yang masih terbuka untuk koreksi Zhafron. Zhafron mendelegasikan tema ke Wira dan tidak menjawab wawancara impeccable; PRODUCT.md dan DESIGN.md di repo (commit 54ed647) adalah sumbernya. Mockup memakai arah itu apa adanya dan belum diuji oleh Zhafron.

| Butir | Keputusan |
|---|---|
| Register dan pemakai | product; Zhafron saja, di PC (konfigurasi, analisa) dan di ponsel (sekilas, tengah malam) |
| Creative North Star | papan informasi stasiun bertemu strip kertas seismograf: satu jawaban besar (Aman, Ditahan, Berhenti) dan satu jejak garis tentang apa yang baru terjadi |
| Adegan fisik | ponsel di bawah matahari tropis untuk melihat apakah bot aman; PC di siang hari saat mengatur konfigurasi; ponsel lagi tengah malam di kamar gelap |
| Tema | terang sebagai bawaan (kontras tertinggi di bawah matahari); gelap mengikuti sistem; keduanya dirancang (Layar 1a terang, 1b dan 8a gelap) |
| Warna | strategi Restrained: netral murni, satu warna sinyal hangat oklch(0.673 0.217 38.6) (seed-041) hanya untuk rugi, batas, peringatan, dan kill switch; untung biru tua oklch(0.40 0.15 258); tombol utama tinta oklch(0.19 0.012 255) |
| Untung dan rugi | tidak hanya merah dan hijau: biru tua dan jingga, selalu dengan tanda plus atau minus, panah, dan kata untung atau rugi |
| Tipografi | satu keluarga sans, angka tabular wajib, skala tetap (A.2) |
| Bentuk | datar, tanpa bayangan lebar, tanpa kartu bersarang; tombol dan kolom radius 3 sampai 6 px |
| Gerak | hanya untuk perubahan keadaan, 150 sampai 250 ms, dengan versi prefers-reduced-motion (tidak tergambar di mockup statis) |
| Dilarang | gaya Binance atau Robinhood, gamifikasi, template hero-metric, dasbor AI generik, tampilan bawaan FreqUI dan Nuxt UI |

## A.2 Keluarga huruf dan bukti angka tabular

Keluarga yang dipilih: Inter versi 3.019 (terpasang di komputer pembuat PDF; yang tertanam di PDF ini Inter Regular dan Inter SemiBold, dicek dengan pdffonts). Tabel fitur OpenType font memuat tnum; dengan font-variant-numeric: tabular-nums semua angka berlebar sama.

Bukti di render Chrome (ukuran 40 px, lebar kotak teks):

| Cara angka | 1111 | 8888 |
|---|---|---|
| proporsional | 74,33 px | 98,64 px |
| tabular (tnum) | 103,64 px | 103,64 px |

Lebar angka proporsional berbeda; lebar angka tabular sama, jadi kolom harga, jumlah, dan persen sejajar. Satu keluarga untuk judul, label, tombol, dan data; skala tetap (11, 12,5, 32 px di ponsel).

## A.3 Kontras warna

Dihitung dari nilai OKLCH yang dipakai di mockup (rumus kontras WCAG). Target WCAG AA: teks minimal 4,5:1.

| Pasangan | Tema terang | Tema gelap |
|---|---|---|
| teks utama pada latar | 18,46 | 17,51 |
| teks sekunder pada latar | 8,45 | 9,17 |
| teks sekunder pada panel | 7,64 | 8,43 |
| biru untung pada latar | 9,41 | 9,86 |
| biru untung pada panel | 8,51 | 9,07 |
| jingga rugi (teks) pada latar | 6,53 | 7,19 |
| jingga rugi (teks) pada panel | 5,90 | 6,62 |
| teks tinta pada warna sinyal | 5,69 | 6,07 |

Semua pasangan di atas 4,5:1.

## A.4 Uji AI slop dan category-reflex (plan bagian 12)

| Larangan atau uji | Cara mockup menghindarinya |
|---|---|
| Template hero-metric (angka besar, label kecil, gradient) | tidak ada angka raksasa; satu kata keadaan (Aman, Ditahan, Berhenti) sebelum detail; angka lain berukuran biasa dalam baris tabular |
| Grid kartu identik, kartu bersarang | tidak ada kartu; bagian dipisah garis tipis dan jarak, judul bagian kalimat biasa |
| Glassmorphism, gradient, gradient text | tidak ada blur, gradient, atau gradient text |
| Eyebrow kapital kecil di tiap bagian | tidak ada teks kapital kecil berjarak; judul bagian memakai huruf biasa |
| Penomoran 01, 02, 03 sebagai perancah | angka urut hanya di langkah pasang iOS (1 sampai 4), yang memang berurutan; nomor layar hanya label gambar |
| Border bersama bayangan lebar | tidak ada bayangan dengan blur; hanya garis 1 sampai 2 px |
| Radius kartu di atas 16 px | radius terbesar 16 px (bingkai perangkat); tombol dan kolom 3 sampai 6 px; saklar berbentuk pil |
| Ilustrasi SVG sketsa | tidak ada; SVG hanya grafik data dan ikon aplikasi geometris |
| Untung dan rugi hanya merah dan hijau | biru tua dan jingga, plus tanda plus atau minus, panah, dan kata untung atau rugi pada setiap angka |
| Category-reflex tingkat satu (gelap, hijau dan merah neon, candlestick di pusat) | terang sebagai bawaan, tanpa neon; candlestick hanya di Layar 2, kecil, tanpa hijau dan merah |
| Category-reflex tingkat dua (mode gelap ala terminal) | papan stasiun terang berbasis tipografi; gelap hanya sebagai tema pilihan |
| Uji cepat DESIGN.md: langsung ditebak sebagai dasbor trading dari warna dan bentuk | penilaian akhir ada pada Zhafron; arah ini terbuka untuk koreksi |

Detektor pola bawaan skill (detect.mjs, lokal) dijalankan pada HTML 11 gambar mockup: 7 temuan, tidak ada yang berat. Enam peringatan overused-font menunjuk Inter. reference/product.md mengizinkan Inter untuk register product dan DESIGN.md hanya mensyaratkan angka tabular (terbukti di A.2), jadi Inter dipertahankan dan tetap bisa diganti bila Zhafron memilih keluarga lain. Satu saran numbered-section-markers (deretan 02, 03, 04, 06, 08, 09) dinilai false positive: mockup tidak punya penanda bagian bernomor, dan deretan itu tampaknya berasal dari label jam di sumbu grafik dan feed (dugaan, tidak ditelusuri per angka).

## A.5 Layar 1: Dasbor (ponsel)

@@MOCKg1@@

- Satu keadaan besar lebih dulu (Aman atau Ditahan), lalu jejak per jam terhadap batas harian, profit dengan tanda dan kata, meter rugi harian dan total, posisi terbuka, status bot A dan bot B (dry-run), biaya LLM sebagai informasi.
- Penanda mode (Dry-run) dan usia data ada di bilah atas semua layar; tombol Hentikan selalu terjangkau.
- Sumber fitur: plan bagian 13 (posisi dan order live, meter risiko, bot A vs bot B).

## A.6 Layar 2: Grafik live (ponsel dan desktop)

@@MOCKg2a@@

@@MOCKg2b@@

- Kandel per pair dengan penanda masuk dan keluar, indikator (EMA), garis stop loss, sumbu persen dari harga masuk; kandel kosong naik dan penuh turun, tanpa hijau dan merah.
- Dasar: /pair_candles, WebSocket analyzed_df, /plot_config (plan bagian 13). Lapisan berita dan sentimen: nice-to-have, mati.

## A.7 Layar 3 dan 4: Aksi live dan Pratinjau kandidat entry

@@MOCKg3@@

- Aksi live: fill, jawaban voter, median, sebaran, kuorum, gerbang risiko, peringatan, heartbeat, dalam waktu nyata; sambungan putus ditandai data basi.
- Pratinjau: kandidat entry beserta jawaban voter sebelum order dikirim; di mode shadow menampilkan apa yang akan terjadi (plan bagian 13).

## A.8 Layar 5 dan 6: Swarm per keputusan dan Konfigurasi

@@MOCKg4@@

- Swarm: sebaran jawaban voter pada satu garis, median, selisih kuartil, kuorum, keputusan, dan hasil sesudahnya (apakah entry yang dilewati ternyata rugi).
- Konfigurasi: batas rugi (turun langsung, naik dua langkah), voter (model, adapter, aktif), backend LLM, dan batas biaya harian sebagai saklar mati secara default; biaya dan token hanya informasi, bukan meter batas (plan revisi 5).

## A.9 Layar 7: Provider dan key

@@MOCKg5a@@

@@MOCKg5b@@

- Di PC: kolom key sekali tulis (hanya 4 karakter terakhir tampil, tanpa tombol lihat), uji koneksi, pilih model per peran. Di ponsel: tanpa kolom key; hanya status, aktif atau nonaktif, dan uji koneksi (plan bagian 4.5).

## A.10 Layar 8: Kill switch dan konfirmasi dua langkah

@@MOCKg6a@@

@@MOCKg6b@@

- Kill switch menjalankan stop_new_entries tanpa konfirmasi; posisi terbuka tetap dijaga stop loss di sisi bot. Naikkan batas, tutup semua posisi, dan pindah ke live butuh dua langkah dengan akibat dalam rupiah.

## A.11 Layar 9: Dasbor desktop (lebar)

@@MOCKg7@@

- Satu keadaan besar, ekuitas bot A dan bot B bersama batas harian, meter, posisi, keputusan swarm terakhir, kesehatan provider, dan aksi terakhir. Beban CPU gateway dan jeda fill ke PWA belum diukur (tahap 1).

## A.12 Layar 10: Pasang PWA di iOS

@@MOCKg8@@

- iOS 16.4 atau lebih baru; harus ditambahkan ke Home Screen; izin notifikasi diminta lewat ketukan tombol; notifikasi harus terlihat (Safari tidak mendukung push tak terlihat). WebSocket hanya hidup saat aplikasi terbuka di depan; di latar belakang kabar datang lewat Web Push (plan bagian 13).

## A.13 Daftar mockup

| No | Layar | Perangkat | Tema |
|---|---|---|---|
| 1 | Dasbor | ponsel | terang (aman) dan gelap (ditahan) |
| 2 | Grafik live | ponsel dan desktop | terang |
| 3 | Aksi live (feed waktu nyata) | ponsel | terang |
| 4 | Pratinjau kandidat entry beserta jawaban voter | ponsel | terang |
| 5 | Swarm per keputusan | ponsel | terang |
| 6 | Konfigurasi, batas biaya saklar mati bawaan | ponsel | terang |
| 7 | Provider dan key | desktop (PC) dan ponsel | terang |
| 8 | Kill switch dan konfirmasi dua langkah | ponsel (tiga layar) | gelap dan terang |
| 9 | Dasbor desktop lebar | desktop | terang |
| 10 | Langkah pasang PWA di iOS | ponsel (empat langkah) | terang |
