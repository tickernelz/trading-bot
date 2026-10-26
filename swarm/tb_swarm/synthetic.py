import random
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tb_swarm.agents import DEFAULT_TIMEZONE

PAIRS = ("BTC/IDR", "ETH/IDR", "SOL/IDR")
VOTERS = 7
ORIGIN = "synthetic test data from tb_swarm.synthetic, not a bot run"


def _voter(index: int, skipped: bool, rng: random.Random) -> dict[str, Any]:
    timed_out = skipped and index > 2
    if timed_out:
        return {
            "voter_id": f"v{index}",
            "provider": "nutaraline" if index % 2 else "experientiallabs",
            "model": "deepseek-v4.1-flash-1017",
            "status": "timeout",
            "latency_s": 30.0,
            "error_kind": "timeout",
            "answers": None,
        }
    lean = rng.random()
    options = {"izinkan": round(lean, 3), "kecilkan": round((1 - lean) / 3, 3), "lewati": round(2 * (1 - lean) / 3, 3)}
    return {
        "voter_id": f"v{index}",
        "provider": "nutaraline" if index % 2 else "experientiallabs",
        "model": "deepseek-v4.1-flash-1017",
        "status": "ok",
        "latency_s": round(1.5 + rng.random() * 3, 2),
        "error_kind": None,
        "answers": {"verdict": {"type": "choice", "choice": max(options, key=options.get), "probabilities": options}},
    }


def synthetic_decisions(
    end_day: date, days: int, skip_rate: float, seed: int = 7, timezone: str = DEFAULT_TIMEZONE
) -> list[dict[str, Any]]:
    """Hourly decisions per pair for days local days ending on end_day; skip_rate of them miss quorum."""
    rng = random.Random(seed)
    zone = ZoneInfo(timezone)
    rows = []
    for offset in range(days - 1, -1, -1):
        day = end_day - timedelta(days=offset)
        for hour in range(24):
            for pair in PAIRS:
                moment = datetime(day.year, day.month, day.day, hour, 2, tzinfo=zone).astimezone(UTC)
                skipped = rng.random() < skip_rate
                voters = [_voter(index, skipped, rng) for index in range(1, VOTERS + 1)]
                answered = sum(1 for voter in voters if voter["status"] == "ok")
                verdict = "lewati" if skipped else rng.choice(("izinkan", "izinkan", "kecilkan", "lewati"))
                rows.append(
                    {
                        "decision_id": f"dec_{day:%m%d}_{hour:02d}_{pair[:3].lower()}",
                        "ts": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
                        "bot": "B",
                        "pair": pair,
                        "timeframe": "1h",
                        "candle": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
                        "mode": "shadow",
                        "status": "skip" if skipped else "ok",
                        "reason": "quorum_not_met" if skipped else None,
                        "required": 5,
                        "answered": answered,
                        "verdict": verdict,
                        "iqr_limit": None,
                        "aggregate": None,
                        "usage": {"input_tokens": 300 * VOTERS, "output_tokens": 40 * VOTERS, "cost": None},
                        "voters": voters,
                    }
                )
    return rows


def synthetic_trades(
    end_day: date, days: int, seed: int = 11, timezone: str = DEFAULT_TIMEZONE
) -> list[dict[str, Any]]:
    """One to three closed trades a day with fixed ids, exit reasons and profits."""
    rng = random.Random(seed)
    zone = ZoneInfo(timezone)
    trades = []
    trade_id = 0
    for offset in range(days - 1, -1, -1):
        day = end_day - timedelta(days=offset)
        for slot in range(rng.randint(1, 3)):
            trade_id += 1
            opened = datetime(day.year, day.month, day.day, 3 + slot * 5, 30, tzinfo=zone)
            closed = opened + timedelta(hours=rng.randint(2, 9))
            profit = round(rng.uniform(-9000, 7000), 2)
            trades.append(
                {
                    "trade_id": trade_id,
                    "pair": rng.choice(PAIRS),
                    "is_open": False,
                    "open_timestamp": int(opened.timestamp() * 1000),
                    "close_timestamp": int(closed.timestamp() * 1000),
                    "exit_reason": rng.choice(("roi", "stoploss", "exit_signal")),
                    "close_profit_abs": profit,
                    "profit_abs": profit,
                }
            )
    return trades
