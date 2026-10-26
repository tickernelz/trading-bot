"""Record the Freqtrade answers and swarm decisions of a dry-run so gateway tests replay real data."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import yaml

from engine.launch import DRY_RUN_DB

CONFIG_FIELDS = ("dry_run", "state", "exchange", "stake_currency", "tradable_balance_ratio", "timeframe")
PLAIN = ("/health", "/status", "/profit", "/stats", "/performance", "/entries", "/exits", "/mix_tags", "/whitelist")
CANDLE_MARGIN = timedelta(hours=6)


def env_file(path: Path) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def record_bot(client: httpx.Client, base: str, pairs: list[str], since: datetime) -> dict[str, object]:
    answers: dict[str, object] = {}
    for path in PLAIN:
        answers[path] = client.get(base + path).json()
    config = client.get(base + "/show_config").json()
    answers["/show_config"] = {key: config.get(key) for key in CONFIG_FIELDS}
    answers["/trades"] = client.get(base + "/trades", params={"limit": 500, "offset": 0, "order_by_id": True}).json()
    for unit in ("daily", "weekly", "monthly"):
        answers[f"/{unit}"] = client.get(base + f"/{unit}", params={"timescale": 3}).json()
    for pair in pairs:
        frame = client.get(base + "/pair_candles", params={"pair": pair, "timeframe": "1h", "limit": 1500}).json()
        dates = frame["columns"].index("__date_ts")
        frame["data"] = [row for row in frame["data"] if row[dates] >= since.timestamp() * 1000]
        frame["length"] = len(frame["data"])
        answers[f"/pair_candles?pair={pair}"] = frame
    return answers


def table(path: Path, query: str) -> list[dict[str, object]]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in db.execute(query)]
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    env = env_file(args.run_dir / "secrets" / "ft.env")
    auth = (env["FT_API_USERNAME"], env["FT_API_PASSWORD"])
    started = datetime.fromisoformat((args.run_dir / "RUN_STARTED_AT").read_text().strip())
    recorded = {"recorded_at": datetime.now(UTC).isoformat(timespec="seconds"), "run_started_at": started.isoformat()}
    args.out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(auth=auth, timeout=20.0) as client:
        for name in ("bot-a", "bot-b"):
            settings = yaml.safe_load((args.run_dir / "config" / f"{name}.yaml").read_text(encoding="utf-8"))
            base = f"http://127.0.0.1:{settings['api']['port']}/api/v1"
            answers = record_bot(client, base, settings["exchange"]["pairs"], started - CANDLE_MARGIN)
            userdir = args.run_dir / name
            links = table(
                userdir / DRY_RUN_DB,
                "SELECT ft_trade_id, cd_key, cd_type, cd_value FROM trade_custom_data ORDER BY id",
            )
            trades = table(userdir / DRY_RUN_DB, "SELECT id, is_open, close_profit_abs, close_profit FROM trades")
            decisions_db = userdir / "swarm_decisions.sqlite"
            decisions = table(decisions_db, "SELECT * FROM decisions ORDER BY ts") if decisions_db.exists() else []
            for decision in decisions:
                voters = json.loads(decision["voters"] or "[]")
                for voter in voters:
                    voter.pop("error", None)
                decision["voters"] = json.dumps(voters)
            bot = {"id": settings["bot_id"], "answers": answers, "custom_data": links, "trades": trades}
            bot["decisions"] = decisions
            (args.out / f"{name}.json").write_text(json.dumps(bot, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "run.json").write_text(json.dumps(recorded, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
