import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tb_swarm.agents import DEFAULT_TIMEZONE, METRICS_FILE, TRADES_FILE, VOTER_LOG_FILE

TRADE_FIELDS = (
    "trade_id",
    "pair",
    "is_open",
    "enter_tag",
    "exit_reason",
    "open_date",
    "close_date",
    "open_rate",
    "close_rate",
    "amount",
    "stake_amount",
    "profit_abs",
    "close_profit_abs",
    "strategy",
    "stop_loss_pct",
)
DECISION_FIELDS = (
    "decision_id",
    "ts",
    "bot",
    "pair",
    "timeframe",
    "candle",
    "mode",
    "status",
    "reason",
    "required",
    "answered",
    "verdict",
    "iqr_limit",
    "aggregate",
    "usage",
)
SKIPS_LISTED = 30
DAYS_KEPT = 14
VOTER_FIELDS = ("voter_id", "provider", "model", "status", "latency_s", "error_kind", "answers")


def _iso(milliseconds: float) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def trade_row(trade: Mapping[str, Any]) -> dict[str, Any]:
    """One Freqtrade trade as an analyst row: allowlisted fields plus ts, the close time or else the open time."""
    stamp = trade.get("open_timestamp")
    if not trade.get("is_open") and trade.get("close_timestamp"):
        stamp = trade["close_timestamp"]
    if not isinstance(stamp, (int, float)):
        raise ValueError(f"trade {trade.get('trade_id')!r} has no timestamp")
    row = {name: trade[name] for name in TRADE_FIELDS if trade.get(name) is not None}
    row["ts"] = _iso(stamp)
    return row


def decision_row(decision: Mapping[str, Any]) -> dict[str, Any]:
    """One stored swarm decision as an analyst row; the request state and voter error text stay out."""
    row = {name: decision[name] for name in DECISION_FIELDS if decision.get(name) is not None}
    row["voters"] = [{name: voter.get(name) for name in VOTER_FIELDS} for voter in decision.get("voters") or []]
    return row


def swarm_by_day(decisions: Iterable[Mapping[str, Any]], timezone: str = DEFAULT_TIMEZONE) -> dict[str, Any]:
    """Per local day counts the analyst reads first, so a busy day never has to be paged through row by row."""
    zone = ZoneInfo(timezone)
    days: dict[str, dict[str, Any]] = {}
    for decision in sorted(decisions, key=lambda row: row["ts"]):
        local = datetime.fromisoformat(decision["ts"]).astimezone(zone)
        day = days.setdefault(
            local.date().isoformat(),
            {"decisions": 0, "by_status": Counter(), "by_verdict": Counter(), "by_pair": {}, "voters": {}, "skips": []},
        )
        day["decisions"] += 1
        day["by_status"][decision.get("status")] += 1
        day["by_verdict"][decision.get("verdict")] += 1
        pair = day["by_pair"].setdefault(decision.get("pair"), {"decisions": 0, "verdicts": Counter()})
        pair["decisions"] += 1
        pair["verdicts"][decision.get("verdict")] += 1
        for voter in decision.get("voters") or []:
            seen = day["voters"].setdefault(voter.get("voter_id"), {"calls": 0, "not_ok": 0})
            seen["calls"] += 1
            seen["not_ok"] += voter.get("status") != "ok"
        if decision.get("status") != "ok" and len(day["skips"]) < SKIPS_LISTED:
            day["skips"].append(
                {
                    "decision_id": decision.get("decision_id"),
                    "pair": decision.get("pair"),
                    "ts_local": local.isoformat(timespec="seconds"),
                    "status": decision.get("status"),
                    "reason": decision.get("reason"),
                    "answered": decision.get("answered"),
                    "required": decision.get("required"),
                }
            )
    newest = sorted(days)[-DAYS_KEPT:]
    return json.loads(json.dumps({day: days[day] for day in newest}))


def _replace(path: Path, text: str) -> None:
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=".snapshot-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _lines(rows: Iterable[Mapping[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: row["ts"])
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered)


def write_snapshot(
    directory: str | os.PathLike[str],
    *,
    metrics: Mapping[str, Any],
    trades: Iterable[Mapping[str, Any]],
    decisions: Iterable[Mapping[str, Any]],
    timezone: str = DEFAULT_TIMEZONE,
) -> None:
    """Replace the three files the analyst tools read, each atomically and oldest row first."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    rows = [decision_row(decision) for decision in decisions]
    full = {**metrics, "swarm_by_day": swarm_by_day(rows, timezone)}
    _replace(root / TRADES_FILE, _lines(trade_row(trade) for trade in trades))
    _replace(root / VOTER_LOG_FILE, _lines(rows))
    _replace(root / METRICS_FILE, json.dumps(full, ensure_ascii=False, indent=2))
