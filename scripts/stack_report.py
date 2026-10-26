"""Summarise a stack run: uptime, restarts, orders, decisions, tokens, fill latency."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from engine.decisions import DecisionStore

GAP_S = 180


def heartbeat_times(unit: str, since: str) -> list[datetime]:
    output = subprocess.run(
        [
            "journalctl",
            "--user",
            "-u",
            unit,
            "--since",
            since,
            "--no-pager",
            "-o",
            "short-iso-precise",
            "--grep",
            "Bot heartbeat",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    times = []
    for line in output.splitlines():
        stamp = line.split(" ", 1)[0]
        try:
            times.append(datetime.fromisoformat(stamp).astimezone(UTC))
        except ValueError:
            continue
    return times


def error_lines(unit: str, since: str) -> list[str]:
    output = subprocess.run(
        ["journalctl", "--user", "-u", unit, "--since", since, "--no-pager", "-o", "cat", "--grep", " - ERROR - "],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line[:200] for line in output.splitlines()]


def uptime(started: datetime, now: datetime, beats: list[datetime]) -> dict:
    edges = [started, *beats, now]
    down = sum(
        (later - earlier).total_seconds() - GAP_S
        for earlier, later in pairwise(edges)
        if (later - earlier).total_seconds() > GAP_S
    )
    span = (now - started).total_seconds()
    return {"span_h": round(span / 3600, 2), "down_s": round(down), "uptime_pct": round(100 * (span - down) / span, 3)}


def orders(trades_db: Path) -> dict:
    if not trades_db.exists():
        return {}
    db = sqlite3.connect(f"file:{trades_db}?mode=ro", uri=True)
    try:
        statuses = dict(db.execute("SELECT COALESCE(status, 'none'), COUNT(*) FROM orders GROUP BY status"))
        trades = dict(db.execute("SELECT is_open, COUNT(*) FROM trades GROUP BY is_open"))
    finally:
        db.close()
    return {"orders_by_status": statuses, "trades_open": trades.get(1, 0), "trades_closed": trades.get(0, 0)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--unit-prefix", default="trading-bot-stack")
    args = parser.parse_args()
    started = datetime.fromisoformat((args.run_dir / "RUN_STARTED_AT").read_text().strip())
    since = started.strftime("%Y-%m-%d %H:%M:%S UTC")
    now = datetime.now(UTC)
    report: dict = {"run_started_at": started.isoformat(), "as_of": now.isoformat(timespec="seconds"), "bots": {}}
    for bot in ("bot-a", "bot-b"):
        userdir = args.run_dir / bot
        starts_file = userdir / "starts.jsonl"
        starts = len(starts_file.read_text().splitlines()) if starts_file.exists() else 0
        unit = f"{args.unit_prefix}-{bot}"
        errors = error_lines(unit, since)
        report["bots"][bot] = {
            "starts": starts,
            "restarts": max(0, starts - 1),
            **uptime(started, now, heartbeat_times(unit, since)),
            **orders(userdir / "tradesv3.dryrun.sqlite"),
            "error_lines": len(errors),
            "error_samples": errors[:5],
        }
    decisions_db = args.run_dir / "bot-b" / "swarm_decisions.sqlite"
    if decisions_db.exists():
        store = DecisionStore(decisions_db, readonly=True)
        first = store.first_real_answer_at()
        outcomes = store.outcomes(args.run_dir / "bot-b" / "tradesv3.dryrun.sqlite")
        report["shadow"] = {
            "first_real_answer_at": first,
            "clock_h": round((now - datetime.fromisoformat(first)).total_seconds() / 3600, 2) if first else None,
            "decisions_by_status": store.counts(),
            "usage_total": store.usage(),
            "outcomes": [outcome.__dict__ for outcome in outcomes],
        }
        store.close()
    gateway_db = args.run_dir / "gateway" / "gateway.sqlite"
    if gateway_db.exists():
        db = sqlite3.connect(f"file:{gateway_db}?mode=ro", uri=True)
        latencies = sorted(row[0] for row in db.execute("SELECT latency_ms FROM fills"))
        db.close()
        report["fill_latency_ms"] = (
            {"n": len(latencies), "p50": latencies[len(latencies) // 2], "max": latencies[-1]}
            if latencies
            else {"n": 0}
        )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
