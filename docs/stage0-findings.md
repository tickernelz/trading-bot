# Temuan Tahap 0b

Dokumen ini mencatat apa yang sudah terbukti di Tahap 0b, angka yang terukur, dan apa yang masih belum terbukti. Sumber kebenaran tetap `docs/plan.md` revisi 10 pada ZHA-3760.

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

Suite: `161 passed` (`cd swarm && .venv/bin/python -m pytest`), tanpa jaringan, tanpa key; 28,5 detik, RSS puncak 203 MB (`/usr/bin/time -v`).

## Butir 1: antarmuka keputusan

`DecisionProvider` (`swarm/tb_swarm/providers/base.py`) punya satu metode abstrak `decide(request) -> DecisionResponse` plus tiga primitif tipis `noul()`, `choice()`, `score()` di atasnya. Pertanyaan bertipe pydantic: `NoulQuestion` (probabilitas 0..1), `ChoiceQuestion` (2 sampai 255 opsi, batas 255 dari dokumentasi Jev), `ScoreQuestion` (rubrik berurut, minimal 2 level).

Tiga adapter:

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

## Yang belum terbukti

1. Bahwa `json_object` dan `json_schema` ditegakkan di sisi server: pada 20 contoh mode `prompt` juga 20/20 valid, jadi tidak ada selisih yang bisa dikaitkan dengan penegakan.
2. Batas laju per kunci pada gateway nutaraline (angka pastinya dan pemicunya) dan perilaku tujuh voter paralel pada satu kunci: 429 teramati sekali pada putaran pertama (laporannya tidak disimpan) dan tidak muncul pada putaran ulang tanpa jeda.
3. Kualitas keputusan model: 20/20 valid berarti bentuk jawaban benar, bukan bahwa jawabannya tepat. Tidak ada label kebenaran.
4. Skema autentikasi dan path OpenRouter Decisions serta System One: baru dari dokumentasi, belum diuji hidup (tidak ada kunci untuk keduanya).
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
