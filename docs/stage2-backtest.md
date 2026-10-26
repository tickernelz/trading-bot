# Temuan Tahap 2e: backtest strategi aturan 3 tahun

Dokumen ini mencatat backtest strategi aturan bot A (`SwingEmaRsi`, candle 1 jam) pada data publik Indodax, dengan fee dan pajak. Sumber kebenaran tetap `docs/plan.md` revisi 11 pada ZHA-3760 (bagian 1 dan 8). Semua angka di bawah disalin dari laporan mentah `report.json` dan `report.md` yang dilampirkan pada ZHA-3778; tidak ada angka yang diketik tangan. Dokumen ini tidak menyimpulkan untung atau rugi di masa depan.

## Ringkasan

| Butir | Status | Bukti |
| --- | --- | --- |
| Riwayat 1h 3 tahun dari Indodax lewat CCXT | Terbukti | `history.json`: 26.904 candle per pair, 2023-10-01 00:00 sampai 2026-10-25 23:00 UTC, 0 candle hilang |
| Fee 0,2% dan pajak 0,21% per sisi | Diterapkan | `--fee 0.0041` di Freqtrade, tercatat di log dan di tiap trade (`fee_open`, `fee_close`) |
| Ekspektasi per trade, jumlah trade, drawdown, sebaran, in-sample dan out-of-sample terpisah | Terukur | Tabel di bawah |
| Syarat lolos tahap 2 plan bagian 8 (ekspektasi positif setelah fee dan pajak pada out-of-sample) | Tidak terpenuhi | Out-of-sample -0,832% per trade (limits_off) dan -1,388% (as_configured), CI 95% seluruhnya di bawah nol |
| Parameter disetel | Tidak | 1 set parameter strategi, matriks dikunci di commit `3d7a371` sebelum hasil pertama ada |

## Riwayat Indodax: koreksi temuan tahap 0a

Tahap 0a mencatat riwayat 1h Indodax hanya sekitar 649 candle (27 hari). Itu batas satu permintaan, bukan batas riwayat. Indodax (`tradingview/history_v2`) mengembalikan candle terbaru saja bila rentang `from`-`to` panjang, dan ccxt 4.5.84 mengisi `to` dengan waktu sekarang bila `params.until` tidak diberikan, sehingga `since` lama tetap menghasilkan 27 hari terakhir. ccxt untuk Indodax membaca `params.until` dalam detik (bukan milidetik seperti konvensi ccxt).

`engine/history.py` mengambil riwayat dalam jendela 500 candle (`since` dan `until` per jendela) lalu menyimpannya sebagai data feather Freqtrade. Hasil (`history.json`):

| Pair | Candle | Pertama (UTC) | Terakhir (UTC) | Hilang sebelum / di dalam / sesudah | Candle volume 0 | Permintaan |
| --- | --- | --- | --- | --- | --- | --- |
| BTC/IDR | 26904 | 2023-10-01 00:00 | 2026-10-25 23:00 | 0 / 0 / 0 | 92 | 54 |
| ETH/IDR | 26904 | 2023-10-01 00:00 | 2026-10-25 23:00 | 0 / 0 / 0 | 99 | 54 |
| SOL/IDR | 26904 | 2023-10-01 00:00 | 2026-10-25 23:00 | 0 / 0 / 0 | 102 | 54 |

"Sebelum" dan "sesudah" dihitung terhadap rentang yang diminta (`requested_since`, `requested_until`), "di dalam" di antara candle pertama dan terakhir; ketiganya dari `history.json` lari ulang di commit perbaikan review.

Riwayat lebih tua dari 2023-10-01 tidak diminta. Probe terpisah dengan jendela 500 candle mengembalikan 1h BTC/IDR penuh untuk 2023-10-22 dan 2024-08-17, sedangkan tanpa `until` setiap `since` (30 sampai 2000 hari) menghasilkan 649 candle yang sama.

## Rancangan (dikunci sebelum lari)

- Strategi: `engine/strategies/swing_ema_rsi.py` apa adanya di main, termasuk lapisan risiko (ukuran posisi 0,5% risiko per trade, batas rugi harian 1%, batas drawdown total 10%, maksimal 3 posisi). Konfigurasi `config/config.example.yaml`: modal Rp 2.000.000, compounding aktif, BTC/IDR, ETH/IDR, SOL/IDR.
- Parameter strategi: 13 (EMA 20 dan 50, RSI 14, RSI masuk 45-70, RSI keluar 78, stoploss -3%, tabel ROI tiga langkah 0 menit 5%, 480 menit 2,5%, 1440 menit 1,2%). Parameter risiko: 4 (0,5%, 1%, 10%, 3 posisi). Semuanya dipilih di tahap 0a sebelum data ini diunduh; tidak ada yang diubah di tahap ini.
- Variasi yang dicoba: 1 set parameter strategi. Matriks: 2 periode × (as_configured dengan fee dan pajak, limits_off dengan tiga tingkat biaya) = 8 backtest. Matriks, periode, dan seed bootstrap ada di `engine/backtest_suite.py` pada commit `3d7a371`, sebelum backtest pertama.
- Periode: in-sample 2023-10-26 sampai 2025-10-26 (2 tahun), out-of-sample 2025-10-26 sampai 2026-10-26 (1 tahun). Karena tidak ada penyetelan, in-sample di sini adalah bagian yang boleh dipakai bila kelak ada penyetelan; out-of-sample tidak boleh disentuh untuk itu.
- Biaya per sisi: fee_and_tax 0,41% (fee 0,2% dari API publik ditambah pajak 0,21% dari sumber sekunder, belum diverifikasi dari dokumen resmi), fee_only 0,2%, no_cost 0% (pembanding kotor).
- Mode risiko: as_configured memakai batas apa adanya; begitu drawdown total menembus 10%, entry baru berhenti sampai akhir periode (on_breach: stop_new_entries). limits_off menaikkan batas rugi harian dan drawdown total ke 100% (ukuran posisi tetap 0,5% risiko), supaya ekspektasi aturan diukur pada seluruh periode, bukan hanya sampai kill switch.
- Sebaran: kuantil per trade dan interval bootstrap persentil 95% untuk rata-rata (10.000 sampel ulang, seed 3778).

Empat percobaan lari terjadi: tiga pertama berhenti karena cacat skrip (direktori data belum dibuat, kontainer tanpa jaringan sehingga Freqtrade tidak bisa memuat metadata pasar, tanggal `backtest_end` tanpa zona waktu). Lari ketiga sempat menyelesaikan in_sample-as_configured-fee_and_tax (104 trade, -7,85%, sama dengan lari keempat) sebelum gagal di peringkasan. Tidak ada parameter strategi, matriks, atau periode yang berubah di antaranya; hasil di bawah dari lari keempat.

## Hasil

Ekspektasi per trade adalah rata-rata `profit_ratio` Freqtrade, yang sudah dikurangi biaya kedua sisi pada tingkat biaya run tersebut. Drawdown maks dihitung dari saldo setelah tiap trade tertutup dan sama dengan `max_drawdown_account` Freqtrade di kedelapan run. "Hari tanpa entry di akhir" adalah jarak entry terakhir ke akhir periode.

| Run | Periode | Biaya per sisi | Mode risiko | Trade | Ekspektasi per trade | CI 95% | Median | Win rate | Drawdown maks | Hasil total | Hari tanpa entry di akhir |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample-as_configured-fee_and_tax | in_sample | 0.41% | as_configured | 104 | -0.590% | -1.092% .. -0.092% | -1.447% | 44.2% | 10.06% | -7.85% | 545.6 |
| in_sample-limits_off-fee_and_tax | in_sample | 0.41% | limits_off | 447 | -0.818% | -1.044% .. -0.594% | -1.524% | 38.3% | 40.06% | -38.48% | 1.8 |
| in_sample-limits_off-fee_only | in_sample | 0.20% | limits_off | 447 | -0.428% | -0.643% .. -0.218% | -0.964% | 40.5% | 28.63% | -24.90% | 1.8 |
| in_sample-limits_off-no_cost | in_sample | 0.00% | limits_off | 447 | -0.058% | -0.263% .. +0.143% | -0.508% | 43.6% | 12.77% | -4.61% | 1.8 |
| out_of_sample-as_configured-fee_and_tax | out_of_sample | 0.41% | as_configured | 59 | -1.388% | -1.913% .. -0.868% | -1.758% | 28.8% | 10.27% | -10.27% | 250.8 |
| out_of_sample-limits_off-fee_and_tax | out_of_sample | 0.41% | limits_off | 221 | -0.832% | -1.098% .. -0.561% | -1.521% | 34.4% | 22.17% | -21.63% | 5.3 |
| out_of_sample-limits_off-fee_only | out_of_sample | 0.20% | limits_off | 221 | -0.451% | -0.707% .. -0.194% | -1.097% | 37.1% | 14.55% | -13.81% | 5.3 |
| out_of_sample-limits_off-no_cost | out_of_sample | 0.00% | limits_off | 221 | -0.077% | -0.317% .. +0.171% | -0.675% | 38.9% | 6.89% | -2.95% | 5.3 |

| Run | p05 | p25 | p75 | p95 | Simpangan baku | Min | Maks | Median lama pegang (jam) | Penolakan gerbang risiko |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample-as_configured-fee_and_tax | -3.792% | -3.299% | +1.744% | +2.573% | 2.649% | -3.792% | +5.000% | 13.0 | daily_loss 2, total_drawdown 341 |
| in_sample-limits_off-fee_and_tax | -3.792% | -2.776% | +1.200% | +2.500% | 2.395% | -3.792% | +5.000% | 15.0 | 0 |
| in_sample-limits_off-fee_only | -3.387% | -2.251% | +1.200% | +2.500% | 2.285% | -3.387% | +5.000% | 14.0 | 0 |
| in_sample-limits_off-no_cost | -3.000% | -1.850% | +2.036% | +2.874% | 2.196% | -3.000% | +5.000% | 13.0 | 0 |
| out_of_sample-as_configured-fee_and_tax | -3.792% | -2.862% | +1.200% | +2.123% | 2.036% | -3.792% | +2.500% | 15.0 | total_drawdown 162 |
| out_of_sample-limits_off-fee_and_tax | -3.792% | -2.248% | +1.200% | +2.500% | 2.044% | -3.792% | +5.000% | 18.0 | 0 |
| out_of_sample-limits_off-fee_only | -3.387% | -1.837% | +1.200% | +2.500% | 1.953% | -3.387% | +5.000% | 17.0 | 0 |
| out_of_sample-limits_off-no_cost | -3.000% | -1.417% | +1.200% | +2.500% | 1.866% | -3.000% | +5.000% | 16.0 | 0 |

| Run | Pair | Trade | Ekspektasi per trade |
| --- | --- | --- | --- |
| in_sample-as_configured-fee_and_tax | BTC/IDR | 33 | -1.103% |
| in_sample-as_configured-fee_and_tax | ETH/IDR | 34 | -0.526% |
| in_sample-as_configured-fee_and_tax | SOL/IDR | 37 | -0.191% |
| in_sample-limits_off-fee_and_tax | BTC/IDR | 146 | -0.979% |
| in_sample-limits_off-fee_and_tax | ETH/IDR | 152 | -0.825% |
| in_sample-limits_off-fee_and_tax | SOL/IDR | 149 | -0.654% |
| in_sample-limits_off-fee_only | BTC/IDR | 146 | -0.565% |
| in_sample-limits_off-fee_only | ETH/IDR | 152 | -0.438% |
| in_sample-limits_off-fee_only | SOL/IDR | 149 | -0.284% |
| in_sample-limits_off-no_cost | BTC/IDR | 146 | -0.170% |
| in_sample-limits_off-no_cost | ETH/IDR | 152 | -0.066% |
| in_sample-limits_off-no_cost | SOL/IDR | 149 | +0.060% |
| out_of_sample-as_configured-fee_and_tax | BTC/IDR | 22 | -1.369% |
| out_of_sample-as_configured-fee_and_tax | ETH/IDR | 17 | -0.921% |
| out_of_sample-as_configured-fee_and_tax | SOL/IDR | 20 | -1.806% |
| out_of_sample-limits_off-fee_and_tax | BTC/IDR | 71 | -0.859% |
| out_of_sample-limits_off-fee_and_tax | ETH/IDR | 75 | -0.638% |
| out_of_sample-limits_off-fee_and_tax | SOL/IDR | 75 | -1.000% |
| out_of_sample-limits_off-fee_only | BTC/IDR | 71 | -0.453% |
| out_of_sample-limits_off-fee_only | ETH/IDR | 75 | -0.310% |
| out_of_sample-limits_off-fee_only | SOL/IDR | 75 | -0.591% |
| out_of_sample-limits_off-no_cost | BTC/IDR | 71 | -0.048% |
| out_of_sample-limits_off-no_cost | ETH/IDR | 75 | +0.034% |
| out_of_sample-limits_off-no_cost | SOL/IDR | 75 | -0.215% |

| Run | Alasan exit |
| --- | --- |
| in_sample-as_configured-fee_and_tax | ema_cross_down_or_rsi 47, roi 33, stop_loss 24 |
| in_sample-limits_off-fee_and_tax | ema_cross_down_or_rsi 218, force_exit 1, roi 147, stop_loss 81 |
| in_sample-limits_off-fee_only | ema_cross_down_or_rsi 210, force_exit 1, roi 160, stop_loss 76 |
| in_sample-limits_off-no_cost | ema_cross_down_or_rsi 193, force_exit 1, roi 179, stop_loss 74 |
| out_of_sample-as_configured-fee_and_tax | ema_cross_down_or_rsi 31, roi 15, stop_loss 13 |
| out_of_sample-limits_off-fee_and_tax | ema_cross_down_or_rsi 136, roi 63, stop_loss 22 |
| out_of_sample-limits_off-fee_only | ema_cross_down_or_rsi 129, roi 70, stop_loss 22 |
| out_of_sample-limits_off-no_cost | ema_cross_down_or_rsi 126, roi 75, stop_loss 20 |

## Bacaan

- Setelah fee dan pajak, ekspektasi per trade negatif di kedua periode: in-sample -0,818% (447 trade) dan out-of-sample -0,832% (221 trade) pada limits_off; batas atas CI 95% masing-masing -0,594% dan -0,561%.
- Tanpa biaya (no_cost) ekspektasi -0,058% in-sample dan -0,077% out-of-sample dengan CI 95% yang memuat nol: data ini tidak menunjukkan keunggulan aturan sebelum biaya. Biaya 0,41% per sisi menurunkan ekspektasi sekitar 0,76 poin persen per trade (in-sample -0,818 lawan -0,058; out-of-sample -0,832 lawan -0,077); median lama pegang 13 sampai 18 jam.
- Dengan konfigurasi apa adanya, batas drawdown total 10% tercapai dan menghentikan entry: entry terakhir 2024-04-28 di in-sample (545,6 hari tanpa entry, 341 penolakan total_drawdown) dan 2026-02-17 di out-of-sample (250,8 hari, 162 penolakan). Gerbang risiko bekerja sesuai rancangan dan membatasi rugi ke sekitar 10%, tetapi juga berarti bot A dengan strategi ini berhenti membuka posisi dalam beberapa bulan.
- Syarat lolos tahap 2 di plan bagian 8 tidak terpenuhi oleh strategi ini. Tidak ada penyetelan yang dilakukan untuk mengubahnya.

## Belum terbukti dan batasan

- Pajak 0,21% per sisi berasal dari sumber sekunder (plan bagian 1). Plan menyebut satu siklus 0,61-0,82%; backtest memakai batas atas 0,82%. Skenario 0,61% (pajak hanya satu sisi) tidak dijalankan; fee_only (0,4% per siklus) adalah batas bawahnya.
- Model pengisian Freqtrade: order terisi di harga buka candle berikutnya atau di harga stoploss/ROI, tanpa spread, slippage, kedalaman buku order, atau order limit yang tidak terisi. Spread Indodax belum diukur.
- Metadata pasar (presisi, minimal order) diambil dari Indodax saat lari (2026-10-26) dan diberlakukan ke seluruh riwayat.
- Interval bootstrap menganggap trade saling bebas. Trade pada tiga pair sering bersamaan dan berkorelasi, jadi interval sebenarnya kemungkinan lebih lebar.
- Satu jalur sejarah dan satu set parameter; tidak ada walk-forward. Strategi dengan timeframe 4 jam atau parameter lain tidak diuji (setiap variasi tambahan menaikkan risiko overfit dan harus dicatat).
- Data dari endpoint TradingView Indodax yang tidak terdokumentasi resmi; kelengkapan diperiksa (0 candle hilang), kebenaran harga tidak dibandingkan dengan sumber kedua.
- Swarm, sinyal berita, dan bot B tidak termasuk; plan menetapkan evaluasinya lewat forward test.

## Menjalankan ulang

    docker compose --profile build build freqtrade-base
    docker build -f docker/Dockerfile --target engine --build-context freqtrade-base=docker-image://trading-bot/freqtrade:2026.9 -t trading-bot/engine:stage2 .
    IMAGE=trading-bot/engine:stage2 scripts/stage2_backtest.sh user_data/stage2

Skrip mengunduh riwayat bila `history.json` belum ada, lalu menjalankan delapan backtest dan menulis `plan.json`, `report.json`, `report.md`, serta hasil Freqtrade per run di `runs/<run>/`. Delapan backtest memakan 54 detik (termasuk start kontainer) di PC Zhafron. Pengunduhan memakai jaringan; backtest juga memakai jaringan untuk metadata pasar, tanpa key.
