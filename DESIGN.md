<!-- SEED: re-run $impeccable document once there's code to capture the actual tokens and components. -->
---
name: trading-bot
description: Panel kontrol bot trading otonom yang tenang, jujur, dan terbaca sekilas; risiko lebih dulu daripada keuntungan.
---

## Overview

Creative North Star: papan informasi stasiun bertemu strip kertas seismograf. Satu jawaban besar yang terbaca dari jauh, dan satu jejak garis yang menunjukkan apa yang baru saja terjadi.

Adegan fisik: Zhafron memegang ponsel di bawah matahari tropis yang terang untuk melihat apakah bot aman, atau menatap PC di siang hari saat mengatur konfigurasi, lalu melirik ponsel lagi tengah malam di kamar gelap. Karena itu tema terang adalah bawaan (kontras tertinggi di bawah sinar matahari), dan tema gelap mengikuti pengaturan sistem untuk malam hari. Dua-duanya dirancang, bukan salah satunya sekadar dibalik.

**The Quiet Win Rule.** Keuntungan tampil tenang; kerugian dan batas tampil tegas. Warna sinyal dicadangkan untuk risiko, bukan untuk tombol atau hiasan.

Referensi (pilihan Wira, bisa dikoreksi): papan keberangkatan dan tipografi jadwal SBB; strip kertas helikorder seismograf; kerapatan tenang Linear. Anti-referensi: dasbor trading gelap bergaya Binance dengan hijau dan merah neon (disebut di PRODUCT.md).

Gerak: restrained. Hanya untuk menyampaikan perubahan keadaan (fill, batas tercapai, koneksi putus), 150 sampai 250 ms, tanpa koreografi saat memuat, dan wajib ada versi prefers-reduced-motion.

## Colors

Strategi: Restrained. Netral murni atau dengan tint sangat tipis, satu warna sinyal tidak lebih dari sepuluh persen permukaan.

**The Risk Signal Rule.** Satu warna sinyal hangat (jangkar: coral atau jingga terbakar, oklch(0.673 0.217 38.6), benih seed-041 dari palette.mjs untuk kunci trading-bot) hanya untuk kerugian, batas risiko, peringatan, dan kill switch. Tidak untuk tombol utama, tautan, atau dekorasi.

**The Not-Red-Not-Green Rule.** Untung memakai biru tua, rugi memakai warna sinyal hangat; keduanya selalu disertai tanda plus atau minus dan arah. Pasangan biru dan jingga dipilih karena tetap terbedakan bagi buta warna merah-hijau. Tombol utama memakai tinta (hampir hitam), bukan warna sinyal.

Nilai: [to be resolved during implementation]. Permukaan terang memakai putih murni; permukaan gelap hampir hitam tanpa tint; lapisan netral kedua untuk panel sedikit lebih dingin. Hindari pita krem, pasir, dan kertas.

## Typography

Arah: satu keluarga sans yang teknis dan mudah dibaca, dengan angka tabular wajib (kolom harga, jumlah, dan persen sejajar). Keluarga huruf konkret dipilih saat implementasi setelah dipastikan mendukung angka tabular dan aksara Indonesia: [font to be chosen at implementation]. Skala tetap, bukan fluid. Judul tidak memakai huruf tampilan; label dan tombol memakai keluarga yang sama.

## Elevation

Datar secara bawaan. Lapisan dibedakan oleh nada permukaan, bukan bayangan. Tidak ada bayangan lebar dan tidak ada kartu bersarang.

## Do's and Don'ts

Do:
- Tampilkan satu keadaan besar (aman, ditahan, berhenti) sebelum detail apa pun.
- Selalu tampilkan penanda mode dry-run atau live dan usia data terakhir.
- Beri tanda plus atau minus, arah, dan teks pada setiap angka untung dan rugi.

Don't:
- Dasbor trading bergaya Binance atau Robinhood: gelap, hijau dan merah neon, candlestick sebagai pusat segalanya.
- Aplikasi broker yang digamifikasi: konfeti, runtun kemenangan, angka profit besar yang dirayakan.
- Template SaaS hero-metric: angka raksasa, label kecil, gradient, kartu statistik identik berulang.
- Dasbor AI generik: gradient ungu, kartu kaca, ikon bulat berwarna.
- Tampilan bawaan FreqUI dan Nuxt UI.
- Warna sinyal untuk tombol atau hiasan; merah dan hijau sebagai satu-satunya pembeda untung dan rugi.

Uji cepat: bila seseorang melihat layar dan langsung menebak "dasbor trading" dari warna dan bentuknya saja, arah visualnya gagal.
