# swarm

Lapisan keputusan Tahap 0b: adapter `DecisionProvider`, registri voter, agen analis baca-saja, dan alat ukur. Rincian angka dan status tiap butir ada di `../docs/stage0-findings.md`.

## Pasang

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python pytest pytest-asyncio ruff
```

## Pakai dari kode

```python
from tb_swarm.config import load_config
from tb_swarm.models import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion
from tb_swarm.runner import SwarmRunner, VoterLog

config = load_config("../config/config.yaml")
runner = SwarmRunner.from_config(config, os.environ, log=VoterLog("../logs/voter_decisions.jsonl"))
outcome = await runner.decide(
    DecisionRequest(
        state={"pair": "BTC/IDR", "rsi": 41, "ema20": 100_000_000, "ema50": 99_000_000},
        questions={
            "take": NoulQuestion(instructions="Is there a reason to take an entry now?"),
            "size": ChoiceQuestion(instructions="Size?", criteria={"full": "...", "half": "...", "skip": "..."}),
            "risk": ScoreQuestion(instructions="Event risk?", criteria=["low", "medium", "high"]),
        },
    )
)
if outcome.proceed:
    ...
```

`outcome.proceed` hanya benar bila jumlah voter sah mencapai `swarm.min_voters_answered` dan sebaran tidak melewati `swarm.max_spread`. Selain itu hasilnya `skip` dengan alasan yang bisa dicatat, dan konsumen tidak boleh entry.

## Adapter

| Adapter | Tipe provider | Wire |
| --- | --- | --- |
| `llm_structured` | `openai-completions`, `openai-responses`, `anthropic-messages` | chat model + JSON tervalidasi |
| `systemone` | `systemone` | `POST {base_url}/v1/systemone` |
| `openai_decisions` | `openai-decisions` | `POST {base_url}/v1/decisions` |
| `openrouter_decisions` | `openrouter-decisions` | `POST {base_url}/api/alpha/decisions` |

Kunci API diambil dari variabel lingkungan (`api_key_env`) atau `api_key` di konfigurasi lokal yang di-gitignore. Kunci yang tidak ada membuat voter itu gagal dengan jenis error `auth`, dan kuorum memutuskan apakah keputusan tetap boleh jalan.

## Agen analis

`build_analyst(model, data_dir)` membuat agen deepagents dengan tiga tool baca (`get_metrics`, `get_trade_history`, `get_voter_log`). `ToolAllowlist` menyaring daftar tool ke model dan menolak panggilan tool lain, termasuk `task`, `write_file`, `edit_file`, `delete`, dan `execute`.

## Menjalankan tes dan alat ukur

```sh
.venv/bin/python -m pytest
.venv/bin/python bench/bench_voter_overhead.py --samples 30
.venv/bin/python bench/live_nutaraline.py --base-url <base URL berakhiran /v1> --out /tmp/nutaraline-live.json
```

`bench/live_nutaraline.py` butuh `NUTARALINE_API_KEY` dan `--base-url`; tanpa itu skrip berhenti dengan status `not_run` dan tidak menghubungi jaringan.
