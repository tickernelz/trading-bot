"""Download exchange OHLCV history in bounded windows and store it as Freqtrade candle data."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ccxt
from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.enums import CandleType
from pandas import DataFrame, to_datetime

from engine.settings import load_settings

WINDOW_CANDLES = 500
MAX_ATTEMPTS = 5
COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def windows(since_ms: int, until_ms: int, timeframe_ms: int, size: int = WINDOW_CANDLES) -> Iterator[tuple[int, int]]:
    """Yield [start, end) windows of at most size candles that cover [since_ms, until_ms)."""
    start = since_ms - since_ms % timeframe_ms
    while start < until_ms:
        end = min(start + size * timeframe_ms, until_ms)
        yield start, end
        start = end


def fetch_window(
    exchange: Any,
    pair: str,
    timeframe: str,
    start: int,
    end: int,
    size: int,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[list[float]], int]:
    """Fetch the candles opening in [start, end); Indodax reads params.until as seconds and caps long ranges."""
    attempt = 1
    while True:
        try:
            rows = exchange.fetch_ohlcv(pair, timeframe, since=start, limit=size, params={"until": (end - 1) // 1000})
            return [row for row in rows if start <= row[0] < end], attempt
        except ccxt.NetworkError:
            if attempt == MAX_ATTEMPTS:
                raise
            sleep(2**attempt)
            attempt += 1


def coverage(
    stamps_ms: list[int], volumes: list[float], timeframe_ms: int, since_ms: int, until_ms: int
) -> dict[str, Any]:
    """Describe sorted candles against the requested [since, until) range: span, missing and zero-volume candles."""
    expected_first = since_ms - since_ms % timeframe_ms
    expected_last = (until_ms - 1) // timeframe_ms * timeframe_ms
    if not stamps_ms:
        return {
            "candles": 0,
            "first": None,
            "last": None,
            "missing_before": (expected_last - expected_first) // timeframe_ms + 1,
            "missing_inside": 0,
            "missing_after": 0,
            "gaps": 0,
            "largest_gap_candles": 0,
            "zero_volume": 0,
        }
    missing = [(later - earlier) // timeframe_ms - 1 for earlier, later in zip(stamps_ms, stamps_ms[1:], strict=False)]
    holes = [count for count in missing if count > 0]
    return {
        "candles": len(stamps_ms),
        "first": _iso(stamps_ms[0]),
        "last": _iso(stamps_ms[-1]),
        "missing_before": (stamps_ms[0] - expected_first) // timeframe_ms,
        "missing_inside": sum(holes),
        "missing_after": (expected_last - stamps_ms[-1]) // timeframe_ms,
        "gaps": len(holes),
        "largest_gap_candles": max(holes, default=0),
        "zero_volume": sum(1 for volume in volumes if volume == 0),
    }


def collect(
    exchange: Any,
    pair: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    size: int = WINDOW_CANDLES,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[DataFrame, dict[str, Any]]:
    """Fetch every window for one pair, deduplicate by candle time, and report coverage and request counts."""
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    rows: dict[int, list[float]] = {}
    requests = 0
    for start, end in windows(since_ms, until_ms, timeframe_ms, size):
        batch, attempts = fetch_window(exchange, pair, timeframe, start, end, size, sleep)
        requests += attempts
        for row in batch:
            rows[int(row[0])] = row
    ordered = [rows[stamp] for stamp in sorted(rows)]
    frame = DataFrame(ordered, columns=COLUMNS)
    for column in COLUMNS[1:]:
        frame[column] = frame[column].astype(float)
    frame["date"] = to_datetime(frame["date"], unit="ms", utc=True)
    report = coverage(sorted(rows), frame["volume"].tolist(), timeframe_ms, since_ms, until_ms)
    report.update({"pair": pair, "timeframe": timeframe, "requests": requests})
    return frame, report


def _iso(stamp_ms: int) -> str:
    return datetime.fromtimestamp(stamp_ms / 1000, UTC).isoformat()


def _day(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.history", description=__doc__)
    parser.add_argument("--since", required=True, help="first UTC day to fetch, YYYY-MM-DD")
    parser.add_argument("--until", required=True, help="UTC day to stop before, YYYY-MM-DD")
    parser.add_argument("--datadir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--window", type=int, default=WINDOW_CANDLES)
    args = parser.parse_args(argv)

    settings = load_settings(os.environ.get("TRADING_BOT_CONFIG", "config/config.yaml"))
    exchange = getattr(ccxt, settings.exchange.name)({"enableRateLimit": True})
    exchange.load_markets()
    since_ms, until_ms = _day(args.since), _day(args.until)
    args.datadir.mkdir(parents=True, exist_ok=True)
    handler = get_datahandler(args.datadir, "feather")
    pairs = []
    for pair in settings.exchange.pairs:
        frame, report = collect(exchange, pair, settings.exchange.timeframe, since_ms, until_ms, args.window)
        handler.ohlcv_store(pair, settings.exchange.timeframe, frame, CandleType.SPOT)
        pairs.append(report)
        print(json.dumps(report), file=sys.stderr)
    manifest = {
        "exchange": settings.exchange.name,
        "ccxt": ccxt.__version__,
        "endpoint": "fetch_ohlcv (Indodax tradingview/history_v2)",
        "requested_since": _iso(since_ms),
        "requested_until": _iso(until_ms),
        "window_candles": args.window,
        "fetched_at": datetime.now(UTC).isoformat(),
        "pairs": pairs,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
