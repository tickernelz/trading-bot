# Temuan Tahap 0b dan 0c

Dokumen ini mencatat apa yang sudah terbukti di Tahap 0b dan 0c, angka yang terukur, dan apa yang masih belum terbukti. Sumber kebenaran tetap `docs/plan.md` revisi 10 pada ZHA-3760.

Kode ada di `swarm/` (paket Python `tb_swarm`, `pyproject.toml` sendiri supaya tidak bertabrakan dengan `pyproject.toml` akar saat pekerjaan Tahap 0a berjalan). Vendor `vendor/freqtrade` tidak disentuh.

## Ringkasan bukti

| Butir | Status | Bukti |
| --- | --- | --- |
| 1. Antarmuka `DecisionProvider` tiga primitif + tiga adapter | Terbukti | `swarm/tb_swarm/providers/`, 18 tes wire |
| 2. Registri voter, kuorum 5/7, pengacakan opsi, median | Terbukti | `swarm/tb_swarm/{config,runner,shuffle,aggregate}.py`, 45 tes |
| 3. Semua adapter diuji ke server stub lokal | Terbukti | `swarm/tb_swarm/stub_server.py`, tanpa key dan tanpa jaringan |
| 4. Uji hidup `nutaraline/deepseek-v4.1-flash-1017` | Terbukti: 20/20 valid di setiap sel, dua kali (effort bawaan dan `high`) | `swarm/bench/live_nutaraline.py`, bagian Butir 4 |
| 5. Agen analis deepagents 0.7.32 + uji ulang ZHA-3610 | Terbukti, termasuk latensi dan token hidup | `swarm/tb_swarm/agents.py`, 21 tes, `bench/bench_voter_overhead.py` |
| 6. Kronos mini di CPU | Terbukti (waktu, memori, median antar jalur) | `swarm/bench/bench_kronos.py`, 10 konfigurasi |
| 7. Temuan dan angka di dokumen ini | Dokumen ini | - |
| 8. Tahap 0c: System One dan OpenAI Decisions hidup di Experiential Labs, adapter `openai_decisions` baru | Terbukti: 20/20 valid untuk `jev-latest`, `clef-flash`, `gpt-6-luna-decisions` | bagian "Tahap 0c", `swarm/bench/live_voters.py` |
| 9. Tahap 0c: tujuh voter `llm_structured` dari tujuh provider dan kuorum 5 dari 7 nyata | Terbukti: 20/20 valid per voter terpilih; kuorum 18 dari 20 dan 20 dari 20 keputusan lolos | bagian "Tahap 0c", Butir 3 dan 4 |
| 10. Tahap 0c: OpenRouter Decisions | Belum terbukti (tidak ada kunci) | bagian "Tahap 0c", Butir 2 |

Suite: `170 passed` pada Tahap 0c (`cd swarm && .venv/bin/python -m pytest`, dijalankan lewat `heavy` pada commit `8eeb4a6`, yang pohon kodenya identik dengan commit terakhir; sesudahnya hanya dokumen yang berubah), tanpa jaringan, tanpa key; 43,1 detik, RSS puncak 206 MB (`/usr/bin/time -v`). Tahap 0b: `161 passed`, 28,5 detik, RSS 203 MB. `tests/test_settings.py` di akar (21 tes, termasuk validasi `config.example.yaml` oleh skema mesin) lulus di venv swarm.

## Butir 1: antarmuka keputusan

`DecisionProvider` (`swarm/tb_swarm/providers/base.py`) punya satu metode abstrak `decide(request) -> DecisionResponse` plus tiga primitif tipis `noul()`, `choice()`, `score()` di atasnya. Pertanyaan bertipe pydantic: `NoulQuestion` (probabilitas 0..1), `ChoiceQuestion` (2 sampai 255 opsi, batas 255 dari dokumentasi Jev), `ScoreQuestion` (rubrik berurut, minimal 2 level).

Tiga adapter pada Tahap 0b; Tahap 0c menambah `openai_decisions` (`POST {base_url}/v1/decisions`, lihat bagian "Tahap 0c"):

- `llm_structured` untuk tipe API `openai-completions`, `openai-responses`, dan `anthropic-messages` lewat LangChain (`ChatOpenAI`, `ChatAnthropic`). Tiga tipe ini nyata dipakai, bukan sekadar antarmuka: ketiganya mengirim request ke wire masing-masing dan diuji ke stub (`/v1/chat/completions`, `/v1/responses`, `/v1/messages`).
- `systemone`: `POST {base_url}/v1/systemone`.
- `openrouter_decisions`: `POST {base_url}/api/alpha/decisions` dengan default `base_url` `https://openrouter.ai`.

Pertanyaan dan jawaban divalidasi ketat (`swarm/tb_swarm/validate.py`): nama jawaban harus persis sama dengan nama pertanyaan, `noul` di [0, 1], `choice` harus salah satu kunci opsi, `score` di [0, N-1], probabilitas harus memuat semua opsi. Jawaban yang menyimpang dianggap voter gagal, tidak pernah ditebak.

### Wire yang dikutip

OpenRouter Decisions (alpha), `POST /api/alpha/decisions`, https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request :

```yaml
model: typesafe/jev-1.13
state: {customer_tier: enterprise, ticket: '...'}
questions:
  is_bug:  {type: noul,   instructions: '...', criteria: {'false': '...', 'true': '...'}}
  team:    {type: choice, instructions: '...', criteria: {account: '...', frontend: '...', payments: '...'}}
  urgency: {type: score,  instructions: '...', criteria: ['Can wait for the next release', '...']}
```

Jawaban pada contoh resmi:

```yaml
answers:
  is_bug:  {noul: 0.96, type: noul}
  team:    {choice: payments, confidence: 0.75, probabilities: {account: 0, frontend: 0.16, payments: 0.84}, type: choice}
  urgency: {score: 1.99, confidence: 0.99, legend: {'0': '...', '1': '...', '2': '...'}, probabilities: {'0': 0, '1': 0.01, '2': 0.99}, type: score}
id: gen-dec-1789738314-X5e5eKGQdvR9rblyX250
model: typesafe/jev-1.13-20260917
provider: TypeSafe
usage: {cost: 0.000019992, input_tokens: 476, output_tokens: 70}
```

TypeSafe System One, `POST /v1/systemone`, https://docs.typesafe.ai/api/system-one :

```yaml
model: jev-latest
state: 'teks bebas atau objek apa pun'
questions:
  billing: {type: noul,   instructions: '...'}
  tone:    {type: choice, instructions: '...', criteria: {angry: '...', calm: '...'}}
  urgency: {type: score,  instructions: '...', criteria: ['Can wait', '...']}
```

Jawaban: `model`, `answers` (kunci sama dengan nama pertanyaan), `usage: {input_tokens, output_tokens}`; `choice` dan `score` membawa `confidence` serta `probabilities`, `score` juga `legend`.

Yang belum terverifikasi dan karena itu ditandai:

- Skema autentikasi OpenRouter: dokumentasi hanya menyebut skema `apiKey`; implementasi mengirim `Authorization: Bearer <key>` (perilaku umum OpenRouter) tetapi belum diuji hidup.
- `base_url` OpenRouter di dokumentasi ditulis `https://openrouter.ai/api/v1` karena itu server default OpenAPI, sedangkan path endpoint-nya `/api/alpha/decisions` (bukan `/api/v1/...`). Adapter memakai base `https://openrouter.ai` + path tersebut; belum diuji hidup.
- Header `TypeSafe-Danger-Zone-Images` dan `TypeSafe-Danger-Zone-Long-Context` tidak dipakai (di luar lingkup Tahap 0b).
- Penamaan tipe API pada item provider (`openai-responses`, `anthropic-messages`) mengikuti konvensi OpenRouter/models.yml yang disebut plan, bukan spesifikasi resmi vendor.

## Butir 2: registri voter dan penggabungan

Konfigurasi (`swarm/tb_swarm/config.py`) menerima `providers` (daftar atau peta) dan `swarm.voters` (id, adapter, provider, model, variation, timeout_s, weight, enabled, temperature, structured_mode, backend, extra_body). Divalidasi saat muat: id voter unik, provider dikenal, adapter cocok dengan tipe provider, model termasuk daftar model provider, dan jumlah voter aktif harus sanggup mencapai kuorum. Contoh `config/config.example.yaml` di repo lolos apa adanya (7 voter, `min_voters_answered: 5`).

Aturan keputusan (`swarm/tb_swarm/runner.py`):

- Semua voter aktif dijalankan serentak, masing-masing dengan batas waktunya sendiri (`asyncio.wait_for`). Voter yang lewat batas, error HTTP, kunci salah, jawaban tidak valid, atau exception tak terduga dibuang dari keputusan itu dan dicatat alasannya (`timeout`, `failed`, `invalid`).
- Kuorum: kurang dari `min_voters_answered` (5) jawaban sah berarti hasil `skip` dengan alasan `quorum_not_met`. Fail-closed: tidak ada agregat, sehingga konsumen tidak bisa mengambil keputusan.
- Urutan opsi diacak per voter per keputusan dengan RNG ber-seed (`seed:decision_id:voter_id`), termasuk membalik rubrik `score`; jawaban dipulihkan ke urutan asli sebelum digabung. Voter tetap menjawab berdasarkan nama kunci, jadi pengacakan hanya menghapus bias posisi.
- Penggabungan: median berbobot (bobot voter) untuk `noul` dan `score`, plus sebaran kuartil (q25, q75, IQR, min, maks); untuk `choice` dipakai median probabilitas per opsi (distribusi ternormalisasi; satu-panas bila model tidak memberi probabilitas), pemenang, jumlah suara, dan tingkat kesepakatan berbobot. Seri (dua opsi atau lebih dengan median tertinggi sama, mis. tanpa mayoritas pada surat suara satu-panas) berarti voter tidak sepakat: hasil `skip` dengan alasan `choice_tie:<pertanyaan>`, dicek sebelum gerbang sebaran.
- `max_spread` opsional: bila IQR melebihi ambang, hasil `skip` dengan alasan `spread_exceeded:<pertanyaan>`. Ambang ini berlaku untuk `noul` dan untuk probabilitas pemenang `choice`; `score` tidak ikut diperiksa karena satuannya level rubrik, bukan probabilitas, sehingga satu angka ambang tidak bisa adil untuk keduanya.
- Setiap keputusan dapat dicatat ke JSONL (`swarm.log_path`): request, status, agregat, dan satu baris per voter (status, latency, model, usage, jawaban, urutan opsi yang disajikan, rubrik yang dibalik).

## Butir 3: uji ke stub lokal

`swarm/tb_swarm/stub_server.py` adalah server HTTP lokal (port acak) yang meniru lima wire: `/v1/systemone`, `/api/alpha/decisions`, `/v1/chat/completions`, `/v1/responses`, `/v1/messages`. Perilaku per model bisa diatur: kebijakan jawaban, delay, status gagal, keluaran rusak, jumlah token reasoning. Server menolak kunci salah dengan 401, sehingga tes bisa membuktikan jalur auth. Tidak ada jaringan keluar dan tidak ada key di tes: kunci yang dipakai hanya `stub-key-not-a-secret`.

Hasil stub bukan bukti kualitas model, hanya bukti bentuk wire, parsing, klasifikasi error, dan logika keputusan.

## Butir 4: uji hidup nutaraline

Dijalankan 2026-10-26 ke `https://nutaraline.co.uk/v1`, model `deepseek-v4.1-flash-1017`, tipe API `openai-completions`. Kunci diambil dari `NUTARALINE_API_KEY` di `.env` worktree yang di-gitignore (izin Zhafron lewat komentar Wira di ZHA-3763); nilai `apiKey` di `~/.omp/agent/models.yml` tidak dibaca. Pemeriksaan: nilai kunci tidak ada di berkas yang dilacak git, tidak ada di riwayat git, dan tidak ada di berkas keluaran.

`swarm/bench/live_nutaraline.py` mengirim 20 contoh keputusan trading (satu pertanyaan `choice`, satu `noul`, satu `score` per contoh), satu provider per sel dengan satu panggilan pemanasan yang tidak dihitung. Sel: backend `direct` x tiga mode (`prompt`, `json_object`, `json_schema`) dan backend `deepagents` x `prompt`.

### Dukungan structured output

Ketiga mode diterima server dan menghasilkan jawaban valid 20/20. `json_object` dan `json_schema` (strict) tidak ditolak oleh gateway. Catatan: ini membuktikan permintaan diterima dan jawabannya lolos validasi kita; belum membuktikan bahwa server benar-benar menegakkan skema (mode `prompt` juga 20/20, jadi pada 20 contoh ini tidak ada selisih yang bisa dikaitkan dengan penegakan).

### Reasoning

Tanpa parameter tambahan model menjawab tanpa reasoning (`reasoning_tokens` = 0 pada semua 80 panggilan). Reasoning baru aktif dengan `reasoning_effort: "high"` lewat `extra_body`: respons membawa `reasoning_content` dan `completion_tokens_details.reasoning_tokens`. Untuk tugas ini "reasoning aktif" di deskripsi butir 4 berarti harus dipilih lewat konfigurasi voter (`extra_body`), bukan bawaan model.

### Hasil 20 contoh per sel

Laporan mentah (JSON per sel dan per kasus, termasuk jawaban dan token) dilampirkan pada ZHA-3763 sebagai `live_default.json`, `live_high.json` dan `live_nopace.json`; tabel di bawah dihitung dari berkas itu. Putaran yang dilaporkan di sini adalah putaran ulang kedua (2026-10-26) dengan `--interval 3`; putaran pertama (angka serupa, berkasnya tidak disimpan) tidak dipakai sebagai bukti.

Effort bawaan (`live_default.json`, 0 percobaan ulang 429):

| Backend | Mode | Valid | Latensi median | p90 | Maks | Token masuk (median) | Token keluar (median) | Token reasoning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| direct | prompt | 20/20 | 1,36 s | 1,79 s | 6,14 s | 333 | 36 | 0 |
| direct | json_object | 20/20 | 1,40 s | 1,74 s | 2,10 s | 333 | 36 | 0 |
| direct | json_schema | 20/20 | 1,30 s | 1,50 s | 1,57 s | 654 | 36 | 0 |
| deepagents | prompt | 20/20 | 1,75 s | 3,48 s | 5,33 s | 333 | 36 | 0 |

`reasoning_effort: high` (`live_high.json`, 0 percobaan ulang 429):

| Backend | Mode | Valid | Latensi median | p90 | Maks | Token masuk (median) | Token keluar (median) | Token reasoning (median / total) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| direct | prompt | 20/20 | 4,38 s | 8,66 s | 10,28 s | 358 | 390 | 356 / 8.289 |
| direct | json_object | 20/20 | 5,26 s | 10,47 s | 10,51 s | 358 | 506 | 473 / 9.641 |
| direct | json_schema | 20/20 | 3,55 s | 5,20 s | 7,53 s | 679 | 267 | 234 / 5.607 |
| deepagents | prompt | 20/20 | 4,06 s | 7,47 s | 8,12 s | 358 | 375 | 345 / 8.545 |

Biaya moneter tidak diukur: respons tidak membawa `usage.cost`.

### Temuan operasional

- Mode `json_schema` hampir menggandakan token masuk (654 lawan 333) karena skema ikut dikirim; tanpa selisih kualitas yang terukur pada 20 contoh.
- Reasoning `high` menaikkan latensi median dari sekitar 1,36 s menjadi 3,55 s sampai 5,26 s dan token keluar dari 36 menjadi sekitar 267 sampai 506. Latensi satu panggilan terlama pada effort `high` 10,51 s, dan pada effort bawaan 6,14 s; putaran pertama mencatat satu panggilan 27,6 s, jadi `timeout_s: 30` di `config.example.yaml` tipis untuk effort `high`.
- Pembatasan laju per kunci terjadi tetapi tidak deterministik. Pada putaran pertama (empat sel berurutan tanpa jeda) tiga sel terakhir terkena HTTP 429 (`Laju request per key melebihi batas`), 19 dari 20 kasus gagal per sel; berkas laporan putaran itu tidak disimpan, jadi ini hanya catatan pengamatan, bukan data terlampir. Pada percobaan ulang dengan skrip yang sama tanpa jeda dan tanpa percobaan ulang (`--interval 0 --rate-limit-retries 0`, `live_nopace.json`) tidak ada satu pun 429 dan semua 80 panggilan valid. Jadi batas ada, pemicunya belum diketahui (kemungkinan bergantung pada beban gateway atau jendela waktu), dan tujuh voter paralel pada satu kunci belum diuji. Risiko kuorum 5 dari 7 tetap nyata tetapi belum terukur.
- Skrip uji hidup kini memberi jeda `--interval` (bawaan 3 detik) setelah setiap panggilan selesai, sukses maupun gagal, dan mengulang hanya HTTP 429 (`--rate-limit-retries`, `--rate-limit-wait`).

Cara menjalankan ulang:

```sh
cd swarm
set -a && . ../.env && set +a
.venv/bin/python bench/live_nutaraline.py --base-url https://nutaraline.co.uk/v1 --interval 3 --out <berkas keluaran>
.venv/bin/python bench/live_nutaraline.py --base-url https://nutaraline.co.uk/v1 --interval 3 \
  --extra-body '{"reasoning_effort":"high"}' --out <berkas keluaran>
```

## Butir 5: deepagents 0.7.32

Versi terpasang: `deepagents==0.7.32`, `langchain==1.4.7`, `langgraph==1.2.17`.

### Agen analis

`swarm/tb_swarm/agents.py` membangun analis dengan tiga tool baca saja: `get_metrics`, `get_trade_history`, `get_voter_log`. Tidak ada argumen path: berkas yang dibaca tetap (`metrics.json`, `trades.jsonl`, `voter_decisions.jsonl`) di dalam direktori data, baris dibatasi 200, keluaran dipotong 20.000 karakter. Tidak ada tool order, tidak ada tool ubah konfigurasi, dan berkas konfigurasi atau `.env` tidak pernah dibuka.

Batas itu ditegakkan dua lapis oleh `ToolAllowlist`, sebuah `AgentMiddleware`: daftar tool yang dikirim ke model disaring, dan setiap pemanggilan tool di luar daftar ditolak dengan `ToolMessage(status="error")` sebelum dieksekusi. Berlaku untuk jalur sinkron dan asinkron (dua tes terpisah). Tes mencoba `write_file`, `edit_file`, `delete`, `execute`, `task`, dan satu tool order palsu: keenamnya ditolak, tidak ada berkas berubah, dan direktori data tetap byte-identik.

### Uji ulang ZHA-3610

Temuan ZHA-3610 (deepagents 0.7.13) berulang di 0.7.32 pada dua bentuk subagen:

| Bentuk subagen | Tool induk ikut? | Baris safety di prompt? |
| --- | --- | --- |
| Default `general-purpose` (dibuat otomatis) | Ya, `place_order` ikut | Tidak |
| `SubAgent` tanpa kunci `tools` | Ya, `place_order` ikut | Tidak |
| `SubAgent` dengan `tools=[]` | Tidak | Hanya bila prompt subagen sendiri memuatnya |

Kesimpulan: batas keamanan tidak boleh ditaruh di prompt induk, dan pembatasan harus eksplisit per subagen (`tools=[]` atau middleware penyaring). Analis di repo ini memakai jalur yang lebih keras: `ToolAllowlist` juga menyaring `task` dari induk, jadi subagen tidak bisa dipanggil sama sekali (diuji: panggilan `task` ditolak).

### Biaya deepagents dibanding panggilan langsung

`swarm/bench/bench_voter_overhead.py`, 30 sampel per jalur, dua voter identik (model yang sama, prompt yang sama) terhadap stub lokal, CPU sama:

| Delay stub | Langsung (median) | Lewat deepagents (median) | Selisih |
| --- | --- | --- | --- |
| 0 ms | 4,0 ms (maks 5,6) | 9,9 ms (maks 19,5) | +5,9 ms |
| 500 ms | 504,0 ms | 508,8 ms | +4,8 ms |

Panjang prompt yang dikirim identik (selisih 0 karakter pada stub, karena profil default deepagents tidak menambah system prompt dan `ToolAllowlist` mengosongkan daftar tool). Artinya overhead deepagents di sini murni latency kerangka, sekitar 5-10 ms per pemanggilan, sementara latensi provider nyata berada di kisaran ratusan sampai ribuan milidetik. Angka provider nyata ada di bagian "Hidup: deepagents lawan panggilan langsung" di bawah.

### Hidup: deepagents lawan panggilan langsung

Sel yang sama (`prompt`), model nutaraline, 20 contoh, dari laporan yang dilampirkan:

| Effort | Jalur | Latensi median | p90 | Token masuk | Token keluar |
| --- | --- | --- | --- | --- | --- |
| bawaan | direct | 1,36 s | 1,79 s | 333 | 36 |
| bawaan | deepagents | 1,75 s | 3,48 s | 333 | 36 |
| high | direct | 4,38 s | 8,66 s | 358 | 390 |
| high | deepagents | 4,06 s | 7,47 s | 358 | 375 |

Token masuk identik pada kedua jalur (333 dan 358): deepagents tidak menambah prompt. Latensi median pada effort bawaan: deepagents 1,75 s lawan direct 1,36 s (p90 3,48 s lawan 1,79 s); pada effort `high`: 4,06 s lawan 4,38 s (p90 7,47 s lawan 8,66 s). Arah selisihnya tidak konsisten antar effort dan antar putaran (putaran pertama menunjukkan deepagents sama pada effort bawaan, sekarang lebih lambat), jadi satu putaran 20 contoh tidak cukup untuk menyimpulkan keuntungan atau kerugian latensi. Overhead kerangka yang terukur pada stub (5-10 ms) jauh di bawah derau itu.

Keputusan: voter cepat tidak perlu deepagents (tidak ada manfaat terukur, dan satu lapisan lebih banyak yang harus dijaga batasnya); deepagents dipakai untuk agen analis yang memang butuh tool.

### Agen voter

`build_voter_agent` membuat agen tanpa tool sama sekali (`tools=[]` plus `ToolAllowlist(())`) dan dengan system prompt voter yang sama seperti jalur langsung, sehingga perbandingan langsung vs deepagents adil. Tes membuktikan tidak ada tool yang ditawarkan ke model dan jawaban yang dihasilkan identik dengan jalur langsung.

## Butir 6: Kronos mini di CPU

Model: `NeoQuasar/Kronos-mini` (4.108.032 parameter model + 3.958.042 parameter tokenizer, lisensi MIT, commit sumber `shiyu-coder/Kronos` 67b630e), tokenizer `NeoQuasar/Kronos-Tokenizer-2k`, `max_context` 2048, `torch==2.14.1+cu130` dipakai di CPU, data sintetis 512 lilin 1 jam (bukan data pasar nyata, karena akurasi tidak diuji di sini).

Mesin: Intel i5-12600K, 16 CPU logis, semua job lewat antrean `heavy` (kuota 400% CPU, nice 19). `T=1.0`, `top_p=0.9`.

| Konfigurasi | Prediksi | Jalur | Thread | Median | p90 | RSS puncak |
| --- | --- | --- | --- | --- | --- | --- |
| lookback 512 | 1 jam | 1 | 4 | 48 ms | 75 ms | 677 MB |
| lookback 512 | 1 jam | 4 | 4 | 185 ms | 223 ms | 704 MB |
| lookback 512 | 1 jam | 8 | 4 | 342 ms | 411 ms | 765 MB |
| lookback 512 | 1 jam | 16 | 4 | 718 ms | 804 ms | 851 MB |
| lookback 512 | 1 jam | 32 | 4 | 1.448 ms | 1.555 ms | 1.068 MB (naik dari 677 MB) |
| lookback 512 | 1 jam | 8 | 1 | 903 ms | 965 ms | 751 MB |
| lookback 512 | 1 jam | 8 | 2 | 517 ms | 545 ms | 758 MB |
| lookback 512 | 1 jam | 8 | 8 | 649 ms | 696 ms | 773 MB |
| lookback 512 | 24 jam | 8 | 4 | 4.000 ms | 4.439 ms | 786 MB |
| lookback 2048 | 1 jam | 8 | 4 | 1.684 ms | 1.703 ms | 1.065 MB |

Bacaan angka:

- Biaya naik hampir linear terhadap `sample_count` dan terhadap panjang prediksi; 24 langkah 1 jam (sekitar 3-4 detik) sudah di batas praktis untuk voter bayangan tiap jam di CPU ini.
- 8 thread lebih lambat dari 4 thread karena job berjalan di bawah kuota 400% CPU; angka thread 4 adalah yang relevan untuk kotak ini.
- Memori dasar sekitar 680 MB (impor torch ikut terhitung) dan naik sekitar 12 MB per jalur tambahan pada 32 jalur.
- Waktu muat bobot 1,1-1,3 detik setelah cache Hugging Face terisi (7,4 detik pada unduhan pertama).

### Median antar jalur

Fungsi `auto_regressive_inference` di vendor merata-ratakan semua jalur (`np.mean(preds, axis=1)`) sebelum mengembalikan hasil, jadi `predict()` tidak pernah memperlihatkan jalur individual. Median antar jalur tetap mungkin tanpa menyentuh vendor: `swarm/bench/bench_kronos.py` mengganti nama `np` di dalam modul vendor dengan proksi yang menangkap array 4 dimensi tepat sebelum perataan, lalu memulihkannya ke skala harga asli. Verifikasi: rata-rata jalur yang ditangkap sama dengan keluaran `predict()` (`rtol=1e-4`, cocok pada 10 dari 10 konfigurasi), jadi yang ditangkap memang jalur yang sebenarnya.

Dengan 8 jalur, sebaran hasil (perubahan harga close pada langkah terakhir, persen, data sintetis):

| Horizon | p10 | median | p90 |
| --- | --- | --- | --- |
| 1 jam | -0,71% | -0,71% | -0,13% |
| 24 jam | -2,05% | +0,62% | +2,18% |

Median antar jalur karena itu bisa dibuat dan masuk akal sebagai voter bayangan: untuk horizon 1 jam sebarannya sangat sempit (median praktis sama dengan rata-rata), dan melebar di horizon 24 jam. Ini bukan klaim akurasi; yang diuji hanya waktu, memori, dan kelayakan agregasi.

## Tahap 0c: uji hidup decision dan voter lintas provider (ZHA-3772)

Dijalankan 2026-10-26 dari host dengan `swarm/bench/live_voters.py` dan `swarm/bench/probe_decision_wires.py`. Kunci dibaca dari `NUTARALINE_API_KEY` dan saudaranya di `.env` worktree yang di-gitignore; `~/.omp/agent/models.yml` hanya dibaca untuk daftar provider, base URL, dan tipe API, bukan kunci. Id model diambil dari `GET {base_url}/models` tiap provider, tidak ditebak. Klien memakai httpx dan header `User-Agent: curl/8.5.0` pada probe mentah. Laporan mentah (JSON per sel dan per kasus, termasuk jawaban, token, dan latensi) dilampirkan pada ZHA-3772: `wire_probe.json`, `single_1.json`, `single_2.json`, `cand.json`, `cand2.json`, `quorum_1.json`, `quorum_1.voters.jsonl`, `quorum_2.json`, `quorum_2.voters.jsonl`, `burst_1.json`, `local_host.json`, `local_container_hostnet.json`, `local_container_bridge.json`. Semua tabel di bagian ini dihitung dari berkas itu. Dua puluh kasus yang sama dengan Butir 4 (`CASES`, tiga pertanyaan `choice`, `noul`, `score` per kasus), satu panggilan pemanasan tidak dihitung, jeda 3 detik setelah tiap panggilan.

### Butir 1: adapter decision Experiential Labs

Probe adapter terhadap `https://api.experientiallabs.ai` (`wire_probe.json`, payload dibangun oleh adapter, pertanyaan yang sama untuk setiap model):

| Jalur | jev-latest | clef | clef-flash | gpt-6-luna-decisions |
| --- | --- | --- | --- | --- |
| `POST /v1/systemone` (adapter `systemone`) | 200, 0,62 s, jawaban lolos validasi | 200, 1,08 s, lolos | 200, 1,42 s, lolos | 400 `unsupported_capability` |
| `POST /v1/decisions` (adapter `openai_decisions`) | 400 `unsupported_capability` | 400 `unsupported_capability` | 400 `unsupported_capability` | 200, 0,67 s, lolos |
| `POST /v1/responses/decisions` | 404 | 404 | 404 | 404 |

Satu probe awal mencatat `clef` 6,9 s pada panggilan dingin pertama; probe berikutnya 1,08 s. Tiga model System One tidak melayani `/v1/decisions`, dan `gpt-6-luna-decisions` tidak melayani `/v1/systemone`: pesan galat meminta mengirim ulang ke jalur yang sesuai. `/v1/responses/decisions` tidak ada.

**System One (`/v1/systemone`) cocok dengan adapter yang sudah ada.** Permintaan nyata `{model, state, questions: {nama: {type, instructions, criteria}}}` diterima apa adanya. Jawaban nyata:

```yaml
id: decision_cd6f41269b093975f160f63a9c5dcb73
model: jev-latest
answers:
  direction: {type: choice, choice: flat, confidence: 0.69, probabilities: {long: 0.04, flat: 0.79, short: 0.17}}
  entry_reason: {type: noul, noul: 0.4}
  risk: {type: score, score: 1.95, confidence: 0.94, legend: {'0': low, '1': medium, '2': high}, probabilities: {'0': 0.0, '1': 0.04, '2': 0.96}}
usage: {input_tokens: 409, output_tokens: 69, cost: 0.0, is_byok: false}
provider: typesafe
```

Beda dengan dokumen yang dikutip di Butir 1: jawaban membawa `id`, `provider`, `usage.cost`, `usage.is_byok`, dan `legend` pada `score`; `noul` tidak membawa `confidence`. Semuanya aman diabaikan oleh `parse_answers`. `clef` dan `clef-flash` mengembalikan probabilitas pecahan (misalnya `0.4576796777173158`) dan `output_tokens: 0`; yang melayani adalah `experiential_cloud`, bukan `typesafe`. Biaya terlapor per panggilan 0,0 untuk `jev-latest`, `clef-flash`, dan `gpt-6-luna-decisions`.

**OpenAI Decisions (`/v1/decisions`) memakai wire yang berbeda, dan adapter lama tidak cocok.** Spesifikasi OpenAPI gateway (`/openapi.json`) hanya menyebut "Relay the OpenAI Decisions API wire" tanpa skema; bentuknya ditemukan dengan probe, dan galat 400 `invalid_parameter` menyebut `predicate`, `choice (with choices)`, `score (with levels)`. Bentuk yang diterima (200) dan yang ditolak (400) pada `gpt-6-luna-decisions`:

| Elemen | Diterima | Ditolak |
| --- | --- | --- |
| Badan | `{model, input, questions}` | `state`, `questions` berupa peta nama ke objek |
| `input` | teks, atau daftar pesan pengguna dengan bagian `input_text` | objek JSON |
| Pertanyaan `noul` | `{type: predicate, name, instructions}` | `criteria`, `true`, `false` |
| Pertanyaan `choice` | `{type: choice, name, instructions, choices: [{value, description?}]}` | `choices` berupa daftar string, `{id}`, `{label}`, `{name}`, peta, `criteria` |
| Pertanyaan `score` | `{type: score, name, instructions, levels: [{label, description?}]}` | `levels` berupa daftar string, `{value}`, `{name}`, `{description}` saja |
| `name` | opsional, unik | duplikat |

Jawaban nyata berupa daftar bernama, bukan peta:

```yaml
model: gpt-6-luna-decisions
answers:
  - {type: choice, name: d, choice: long, probabilities: [{value: long, probability: 0.94}, {value: short, probability: 0.06}], confidence: 0.88}
  - {type: score, name: r, score: 0.95, probabilities: [{value: 0, label: low, probability: 0.05}, {value: 1, label: high, probability: 0.95}], confidence: 0.9}
  - {type: predicate, name: p, probability: 0.53}
usage: {input_tokens: 124, input_tokens_details: {cached_tokens: 0, cache_write_tokens: 0}, output_tokens: 0, output_tokens_details: {reasoning_tokens: 0}, total_tokens: 124, cost: 0.0, is_byok: false}
provider: openai
```

Perbaikan: adapter baru `openai_decisions` (`swarm/tb_swarm/providers/openai_decisions.py`, tipe provider `openai-decisions`, `POST {base_url}/v1/decisions`). Pemetaan: `noul` ke `predicate` (kriteria `true`/`false` dipindah ke teks instruksi karena wire tidak menerimanya), `choice.criteria` ke `choices`, `score.criteria` ke `levels[].label`, status keadaan berupa objek diserialisasi ke teks JSON, jawaban daftar dipetakan kembali ke peta nama, probabilitas daftar ke peta, `reasoning_tokens` dibaca dari `output_tokens_details`. Stub (`swarm/tb_swarm/stub_server.py`) dikoreksi sesuai kenyataan: route `/v1/decisions` menolak dengan 400 persis seperti pesan nyata bila bentuk badan menyimpang, dan respons System One kini membawa `id`, `provider`, `usage.cost`, `usage.is_byok`, dan `legend`. Tes baru di `swarm/tests/test_wire_adapters.py` dan `test_config.py` memakai jawaban nyata di atas sebagai fixture. `engine/settings.py` ikut menerima tipe provider `systemone`, `openai-decisions`, dan `openrouter-decisions` supaya `config/config.example.yaml` yang sama divalidasi oleh mesin dan oleh swarm.

Hasil 20 kasus per voter keputusan (baris d1 sampai d3 pada tabel Butir 3): 20/20 valid, tanpa 429, biaya terlapor 0,0 untuk ketiganya.

### Butir 2: OpenRouter Decisions

Tidak ada kunci OpenRouter di `models.yml` maupun `.env`, jadi adapter `openrouter_decisions` tetap belum terbukti hidup: skema auth dan path `/api/alpha/decisions` hanya dari dokumentasi. Hanya stub yang menguji bentuk wire dan parsing. Wire OpenRouter (state dan questions berkunci nama) sama dengan System One yang kini terbukti, tetapi itu bukan bukti untuk OpenRouter.

### Butir 3: voter `llm_structured` lintas keluarga dan provider

Tujuh voter, tujuh keluarga model, tujuh provider dengan tujuh kunci berbeda (`config/config.example.yaml`), ditambah tiga voter keputusan dari satu provider (kunci yang sama, dijalankan berurutan). Tiap voter sendirian, 20 kasus, `--interval 3`, tanpa percobaan ulang 429 yang terpakai (`single_1.json`, `single_2.json`):

| Voter | Provider | Model | Valid | Latensi median | p90 | Maks | Token masuk / keluar (median) | Token reasoning (total) | 429 | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v1 | nutaraline | deepseek-v4.1-flash-1017 | 20/20 | 1,47 s | 1,94 s | 2,19 s | 333 / 36 | 0 | 0 | - |
| v2 | modelrouter | glm-5.3-flash:mr | 20/20 | 1,69 s | 2,66 s | 5,55 s | 338 / 43 | 238 | 0 | - |
| v3 | xai-hm | cx/gpt-6-luna | 20/20 | 2,84 s | 3,54 s | 4,31 s | 348 / 105 | 1423 | 0 | - |
| v4 | sub2api-claude | claude-haiku-5-5 | 20/20 | 2,54 s | 3,77 s | 4,20 s | 972 / 305 | 4966 | 0 | - |
| v5 | omniroute | agy/gemini-3.8-flash-medium | 20/20 | 6,79 s | 8,36 s | 11,69 s | 401 / 518 | 10487 | 0 | - |
| d1 | experientiallabs-systemone | jev-latest | 20/20 | 0,43 s | 0,98 s | 1,97 s | 416 / 69 | 0 | 0 | - |
| d2 | experientiallabs-systemone | clef-flash | 20/20 | 0,81 s | 2,25 s | 5,85 s | 350 / 0 | 0 | 0 | - |
| d3 | experientiallabs-decisions | gpt-6-luna-decisions | 20/20 | 1,02 s | 2,55 s | 4,48 s | 419 / 0 | 0 | 0 | - |
| v6 | experientiallabs | llama-4-maverick | 20/20 | 2,21 s | 3,97 s | 5,64 s | 343 / 41 | 0 | 0 | - |
| v7 | sub2api-agy | gpt-oss-120b-medium | 20/20 | 2,21 s | 4,66 s | 6,49 s | 0 / 0 | 0 | 0 | - |

Keluarga: deepseek (nutaraline), glm (modelrouter), openai gpt-6 (xai-hm, tipe `openai-responses`), anthropic (sub2api-claude, tipe `anthropic-messages`, base URL tanpa `/v1` karena SDK menambahkannya), gemini (omniroute), llama (experientiallabs), gpt-oss (sub2api-agy). Dua provider terakhir adalah host lokal. Baris v7 melaporkan token 0 karena sub2api-agy tidak membawa `usage` untuk model ini; biaya moneter tidak dilaporkan oleh satu pun provider LLM (hanya ketiga voter keputusan yang membawa `usage.cost`).

Pilihan model yang gagal diuji dan diganti (`single_1.json` untuk dua baris pertama, `cand.json` dan `cand2.json` untuk sisanya; id voter di berkas itu `c1` sampai `c8`, `e1`, `e2`):

| Voter | Provider | Model | Valid | Latensi median | p90 | Maks | Token masuk / keluar (median) | Token reasoning (total) | 429 | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v6 | experientiallabs | kimi-k2.6 | 15/20 | 25,51 s | 27,29 s | 28,37 s | 335 / 1835 | 28683 | 0 | timeout |
| v7 | sub2api-mimo | mimo-v2.6-flash | 0/20 | - | - | - | - / - | 0 | 0 | http |
| c1 | experientiallabs | llama-4-maverick | 3/3 | 1,54 s | 1,54 s | 1,70 s | 365 / 41 | 0 | 0 | - |
| c2 | experientiallabs | grok-4.20-non-reasoning | 3/3 | 2,86 s | 2,86 s | 3,22 s | 524 / 34 | 0 | 0 | - |
| c3 | experientiallabs | gpt-oss-120b | 2/3 | 20,67 s | 14,78 s | 26,55 s | 416 / 314 | 565 | 0 | invalid |
| c8 | experientiallabs | deepseek-v4-flash | 3/3 | 2,21 s | 2,21 s | 3,72 s | 349 / 36 | 0 | 0 | - |
| c4 | lucif | lucif | 2/3 | 29,87 s | 5,65 s | 54,09 s | 393 / 858 | 0 | 0 | timeout |
| c5 | tiprouter | gemini-3.8-flash | 0/3 | - | - | - | - / - | 0 | 0 | http |
| c6 | sub2api-mimo | mimo-v2.5 | 0/3 | - | - | - | - / - | 0 | 0 | http |
| c7 | sub2api-codex | glm-5.2 | 0/3 | - | - | - | - / - | 0 | 12 | rate_limit |
| e1 | sub2api-agy | gpt-oss-120b-medium | 6/6 | 2,17 s | 2,25 s | 2,40 s | 0 / 0 | 0 | 0 | - |
| e2 | sub2api-agy | tab_flash_lite_preview | 0/6 | - | - | - | - / - | 0 | 0 | invalid |

Alasan penggantian: `kimi-k2.6` adalah model reasoning (28.683 token reasoning, median 25,5 s, 5 dari 20 melewati `timeout_s: 30`); `mimo-v2.6-flash` dan `mimo-v2.5` di sub2api-mimo menjawab 502 "Upstream authentication failed" lalu 503; tiprouter 503 `platform_unavailable` (juga `GET /models`); sub2api-codex 429 "Upstream rate limit exceeded" pada `glm-5.2` (12 kejadian 429 termasuk percobaan ulang, tidak pernah berhasil); lucif satu dari tiga panggilan timeout (54 s); `gpt-oss-120b` di experientiallabs lambat dan sekali mengembalikan `noul` bukan angka; `tab_flash_lite_preview` tidak menghasilkan JSON. Pada baris ini kasus cuma 3 atau 6, jadi hanya menunjukkan layak atau tidak layak, bukan tingkat validitas.

### Butir 4: kuorum nyata

Agregator nyata (`SwarmRunner`, median berbobot, sebaran kuartil, kuorum 5 dari 7, urutan opsi diacak) dengan voter nyata, 20 keputusan, jeda 3 detik antar keputusan, semua voter aktif dijalankan serentak dan tiap voter ada pada kuncinya sendiri (`quorum_1.json`, `quorum_2.json`, log per voter `*.voters.jsonl`).

| Putaran | Voter | Keputusan lolos | Voter dibuang | Latensi keputusan (median / p90) |
| --- | --- | --- | --- | --- |
| 1: tujuh voter `llm_structured` dari tujuh provider | v1 sampai v7 | 18 dari 20 | 1 jawaban (v3 pada kasus `api-outage`: "model output is not valid JSON"); keputusan itu tetap lolos dengan 6 dari 7 | 6,91 s / 9,21 s |
| 2: tiga voter keputusan + empat `llm_structured` | d1, d2, d3, v1, v2, v4, v5 | 20 dari 20 | 0 | 6,69 s / 10,13 s |

Dua keputusan pada putaran 1 berstatus `skip` dengan alasan `choice_tie:direction` (kasus `funding-flip` dan `week-open`): ketujuh voter menjawab, tetapi suara terpecah 3/2/2 dan median surat suara satu-panas tidak menghasilkan satu pemenang. Itu perilaku agregator yang dirancang pada Butir 2 (fail-closed), bukan kegagalan voter. Pada putaran 2 tidak ada seri karena voter keputusan mengirim probabilitas, sehingga median per opsi berbeda. Latensi keputusan ditentukan voter paling lambat: v5 (gemini lewat omniroute, median 6,7 s sampai 6,8 s).

### Jeda dan batas laju yang terukur

- Satu voter per kunci dengan jeda 3 detik setelah tiap panggilan: 0 kejadian 429 pada 7 voter dan 3 voter keputusan, 20 kasus masing-masing (satu-satunya 429 di seluruh uji datang dari sub2api-codex `glm-5.2` yang memang ditolak hulu).
- Tujuh voter dari tujuh kunci serentak tiap 3 detik selama 20 keputusan: 0 kejadian 429 (`quorum_1.json`, `quorum_2.json`).
- Uji beban tujuh panggilan paralel pada satu kunci, tiga putaran, jeda 5 detik antar putaran (`burst_1.json`):

| Voter | Provider | Putaran 1 | Putaran 2 | Putaran 3 |
| --- | --- | --- | --- | --- |
| d1 | experientiallabs-systemone | 7 ok, 3,64 s | 7 ok, 1,77 s | 7 ok, 1,05 s |
| d3 | experientiallabs-decisions | 7 ok, 1,54 s | 7 ok, 2,73 s | 7 ok, 1,54 s |
| v6 | experientiallabs (`llama-4-maverick`) | 7 ok, 3,47 s | 6 ok 1 invalid, 4,59 s | 7 ok, 2,79 s |
| v2 | modelrouter | 7 ok, 3,66 s | 7 ok, 3,81 s | 7 ok, 3,40 s |
| v1 | nutaraline | 7 ok, 7,00 s | 7 ok, 3,05 s | 4 ok 3 `rate_limit`, 4,00 s |

Hanya nutaraline membalas 429, pada putaran ke-3 setelah 14 permintaan selesai dalam sekitar 20 detik. Ambang pastinya belum ditentukan; dua putaran tujuh paralel diterima. Kesimpulan operasional: jangan menjalankan lebih dari satu voter pada kunci nutaraline per keputusan, dan bila perlu beberapa voter per kunci pakai provider selain nutaraline atau jeda 3 detik. Satu jawaban llama tidak valid pada putaran 2 uji beban v6 (alasannya tidak disimpan di laporan beban).

### Butir 5: provider localhost dari host dan dari kontainer

`GET /v1/models` lima kali dan satu panggilan kecil (`max_tokens: 16`) lima kali per provider dengan urllib (`local_host.json`, `local_container_hostnet.json`, `local_container_bridge.json`); kontainer memakai image `trading-bot/engine:dev` dengan batas memori 512 MB:

| Provider | Dari host (median POST) | Kontainer `--network host`, 127.0.0.1 | Kontainer bridge, `host.docker.internal` (host-gateway) |
| --- | --- | --- | --- |
| sub2api-claude :62173 | 5/5 ok, 1,49 s | 5/5 ok, 1,61 s | 0/5, URLError |
| sub2api-agy :62173 | 5/5 ok, 0,90 s | 5/5 ok, 0,48 s | 0/5, URLError |
| omniroute :20128 | 5/5 ok, 2,26 s | 5/5 ok, 2,54 s | 0/5, URLError |

Selisih host dan kontainer `--network host` ada dalam rentang variasi hulu (satu panggilan pertama tiap provider lebih lambat, misalnya 4,76 s pada sub2api-agy dari kontainer). Jalur bridge dengan `host.docker.internal` tidak menjangkau layanan yang hanya listen di 127.0.0.1 host, sama dengan catatan README; jadi bot di Docker memakai `network_mode: host`. Jalur Docker Desktop di Windows tetap belum diuji.

### Konfigurasi contoh

`config/config.example.yaml` sekarang berisi sembilan provider dan sepuluh voter: tujuh voter `llm_structured` aktif (v1 sampai v7, tujuh provider dan tujuh keluarga model, kuorum 5 dari 7) dan tiga voter keputusan nonaktif (d1 `jev-latest`, d2 `clef-flash`, d3 `gpt-6-luna-decisions`) yang bisa dipilih lewat `enabled: true` atau `--voters`. Base URL ditulis langsung (bukan lagi `from_import`) karena semuanya sudah terukur; `timeout_s: 30` cukup untuk seluruh voter aktif (maksimum terukur 11,7 s, v5). Model reasoning seperti `kimi-k2.6` butuh `timeout_s` jauh lebih besar dan tidak dipakai.

### Cara menjalankan ulang Tahap 0c

```sh
cd swarm
.venv/bin/python bench/probe_decision_wires.py --out /tmp/wire_probe.json
.venv/bin/python bench/live_voters.py single --voters v1,v2,v3,v4,v5,v6,v7,d1,d2,d3 --interval 3 --out /tmp/single.json
.venv/bin/python bench/live_voters.py quorum --cases 20 --interval 3 --log /tmp/quorum.voters.jsonl --out /tmp/quorum.json
.venv/bin/python bench/live_voters.py quorum --voters d1,d2,d3,v1,v2,v4,v5 --min-voters 5 --out /tmp/quorum_decisions.json
.venv/bin/python bench/live_voters.py burst --voters d1,d3,v1,v2,v6 --parallel 7 --rounds 3 --interval 5 --out /tmp/burst.json
```

`.env` di akar repo dibaca otomatis; skrip tidak mencetak kunci.

## Yang belum terbukti

1. Bahwa `json_object` dan `json_schema` ditegakkan di sisi server: pada 20 contoh mode `prompt` juga 20/20 valid, jadi tidak ada selisih yang bisa dikaitkan dengan penegakan.
2. Ambang pasti batas laju per kunci pada gateway nutaraline. Tahap 0c mengukur bahwa tujuh panggilan paralel pada satu kunci nutaraline diterima dua putaran lalu menghasilkan 3 dari 7 respons 429 pada putaran ketiga; angka ambangnya (permintaan per detik atau per menit) tetap belum diketahui.
3. Kualitas keputusan model: 20/20 valid berarti bentuk jawaban benar, bukan bahwa jawabannya tepat. Tidak ada label kebenaran.
4. Skema autentikasi dan path OpenRouter Decisions: baru dari dokumentasi, belum diuji hidup (tidak ada kunci OpenRouter). System One dan OpenAI Decisions sudah terbukti hidup di Experiential Labs pada Tahap 0c (Bearer, `/v1/systemone`, `/v1/decisions`); keduanya belum diuji ke TypeSafe langsung.
5. Akurasi Kronos: sengaja tidak disimpulkan, dan datanya sintetis.
6. Biaya harian swarm: respons nutaraline tidak membawa `usage.cost`, jadi belum ada angka moneter.

## Cara menjalankan ulang

```sh
cd swarm
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . --group dev
.venv/bin/python -m pytest
.venv/bin/python bench/bench_voter_overhead.py --samples 30
heavy --kind other --label <label> -- <venv kronos>/bin/python bench/bench_kronos.py \
  --kronos-src <checkout Kronos> --sample-count 8 --repeats 10
```
