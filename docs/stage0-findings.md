# Temuan Tahap 0b

Dokumen ini mencatat apa yang sudah terbukti di Tahap 0b, angka yang terukur, dan apa yang masih belum terbukti. Sumber kebenaran tetap `docs/plan.md` revisi 10 pada ZHA-3760.

Kode ada di `swarm/` (paket Python `tb_swarm`, `pyproject.toml` sendiri supaya tidak bertabrakan dengan `pyproject.toml` akar saat pekerjaan Tahap 0a berjalan). Vendor `vendor/freqtrade` tidak disentuh.

## Ringkasan bukti

| Butir | Status | Bukti |
| --- | --- | --- |
| 1. Antarmuka `DecisionProvider` tiga primitif + tiga adapter | Terbukti | `swarm/tb_swarm/providers/`, 18 tes wire |
| 2. Registri voter, kuorum 5/7, pengacakan opsi, median | Terbukti | `swarm/tb_swarm/{config,runner,shuffle,aggregate}.py`, 45 tes |
| 3. Semua adapter diuji ke server stub lokal | Terbukti | `swarm/tb_swarm/stub_server.py`, tanpa key dan tanpa jaringan |
| 4. Uji hidup `nutaraline/deepseek-v4.1-flash-1017` | **Belum terbukti, menunggu `NUTARALINE_API_KEY`** | Skrip siap: `swarm/bench/live_nutaraline.py` |
| 5. Agen analis deepagents 0.7.32 + uji ulang ZHA-3610 | Terbukti; angka token hidup menunggu key | `swarm/tb_swarm/agents.py`, 21 tes, `bench/bench_voter_overhead.py` |
| 6. Kronos mini di CPU | Terbukti (waktu, memori, median antar jalur) | `swarm/bench/bench_kronos.py`, 10 konfigurasi |
| 7. Temuan dan angka di dokumen ini | Dokumen ini | - |

Suite: `142 passed` (`cd swarm && .venv/bin/python -m pytest`), tanpa jaringan, tanpa key; 26,9 detik, RSS puncak 203 MB (`/usr/bin/time -v`).

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

## Butir 4: uji hidup nutaraline (menunggu key)

Belum dijalankan: `NUTARALINE_API_KEY` tidak ada di lingkungan maupun `.env` worktree saat pekerjaan ini dikerjakan. Nilai `apiKey` di `~/.omp/agent/models.yml` tidak dibaca dan tidak disalin.

Skrip siap: `swarm/bench/live_nutaraline.py`, 20 contoh keputusan trading (RSI, breakdown, funding crowded, depeg, outage API, dan seterusnya) x tiga mode structured output (`prompt`, `json_object`, `json_schema`) untuk backend `direct`, dan mode `prompt` saja untuk backend `deepagents` (backend itu tidak meneruskan `response_format`, jadi kombinasi lain ditolak saat konfigurasi dimuat). Perbandingan deepagents vs langsung dilakukan pada sel yang sama, `prompt`. Satu provider per sel (mode, backend) dan satu panggilan pemanasan yang tidak dihitung, jadi median latensi adalah keadaan tunak. Yang diukur per sel: tingkat jawaban valid, latensi median/p90, token input/output/reasoning, dan model yang benar-benar melayani. Perbandingan latensi dan token deepagents vs langsung pada provider nyata (butir 5) keluar dari skrip yang sama: sel `direct x prompt` melawan `deepagents x prompt`.

Cara jalan setelah key terpasang:

```sh
cd swarm
NUTARALINE_API_KEY=... .venv/bin/python bench/live_nutaraline.py \
  --base-url <base URL berakhiran /v1> --out /tmp/nutaraline-live.json
```

Base URL wajib diberikan lewat `--base-url` atau `NUTARALINE_BASE_URL` (berakhiran `/v1`); skrip tidak membuka `~/.omp/agent/models.yml`. Mekanisme jalur sukses dan jalur gagal sudah diuji ke stub.

Dukungan structured output, latensi nyata, dan token reasoning pada model ini tetap **belum terbukti** sampai skrip di atas dijalankan dengan key.

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

Panjang prompt yang dikirim identik (selisih 0 karakter pada stub, karena profil default deepagents tidak menambah system prompt dan `ToolAllowlist` mengosongkan daftar tool). Artinya overhead deepagents di sini murni latency kerangka, sekitar 5-10 ms per pemanggilan, sementara latensi provider nyata berada di kisaran ratusan sampai ribuan milidetik. Selisih token pada provider nyata belum terukur: stub mengembalikan `usage` tetap, jadi angka token hidup menunggu butir 4.

Keputusan sementara: voter cepat tidak perlu deepagents; deepagents dipakai untuk agen analis yang memang butuh tool, bukan untuk voter.

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

1. Dukungan structured output `deepseek-v4.1-flash-1017` di `nutaraline` (tiga mode) dan perilaku `reasoning` yang aktif: butuh key.
2. Latensi, token reasoning, dan tingkat jawaban valid model itu: butuh key.
3. Selisih token deepagents vs panggilan langsung pada provider nyata: butuh key.
4. Skema autentikasi dan path OpenRouter Decisions: baru dari dokumentasi, belum diuji hidup.
5. Akurasi Kronos: sengaja tidak disimpulkan, dan datanya sintetis.
6. Biaya harian swarm: belum ada angka karena semua panggilan model masih ke stub.

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
