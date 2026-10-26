from __future__ import annotations

import ccxt
import pytest

from engine.history import MAX_ATTEMPTS, collect, coverage, fetch_window, windows

HOUR = 3_600_000
START = 1_700_000_000_000 - 1_700_000_000_000 % HOUR


class IndodaxLike:
    """Serves the newest cap candles inside [from, to], then filters like ccxt parse_ohlcvs."""

    def __init__(self, stamps: list[int], cap: int, failures: int = 0):
        self.stamps = stamps
        self.cap = cap
        self.failures = failures
        self.calls = 0

    @staticmethod
    def parse_timeframe(timeframe: str) -> int:
        return {"1h": 3600}[timeframe]

    def fetch_ohlcv(self, pair, timeframe, since, limit, params):
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise ccxt.RequestTimeout("slow")
        upper = params["until"] * 1000
        served = [stamp for stamp in self.stamps if since // 1000 * 1000 <= stamp <= upper][-self.cap :]
        rows = [[stamp, 100.0, 101.0, 99.0, 100.5, 0.0 if stamp % (7 * HOUR) == 0 else 1.0] for stamp in served]
        return [row for row in rows if row[0] >= since][:limit]


def test_windows_tile_the_range_without_overlap():
    spans = list(windows(START + 5, START + 1201 * HOUR, HOUR, size=500))
    assert spans[0][0] == START
    assert spans[-1][1] == START + 1201 * HOUR
    assert all(left[1] == right[0] for left, right in zip(spans, spans[1:], strict=False))
    assert all(end - start <= 500 * HOUR for start, end in spans)


def test_collect_reaches_old_candles_when_windows_stay_under_the_server_cap():
    stamps = [START + index * HOUR for index in range(2000) if index not in (700, 701, 1500)]
    frame, report = collect(IndodaxLike(stamps, cap=649), "BTC/IDR", "1h", START, START + 2000 * HOUR, size=500)
    assert len(frame) == len(stamps)
    assert frame["date"].is_monotonic_increasing
    assert report["first"] == frame["date"].iloc[0].isoformat()
    assert (report["candles"], report["missing_inside"], report["gaps"], report["largest_gap_candles"]) == (
        1997,
        3,
        2,
        2,
    )
    assert (report["missing_before"], report["missing_after"]) == (0, 0)
    assert report["requests"] == 4


def test_coverage_exposes_a_window_larger_than_the_server_cap():
    stamps = [START + index * HOUR for index in range(2000)]
    _, report = collect(IndodaxLike(stamps, cap=649), "BTC/IDR", "1h", START, START + 2000 * HOUR, size=1000)
    assert report["candles"] == 2 * 649
    assert report["missing_before"] == 1000 - 649
    assert report["missing_inside"] == 1000 - 649
    assert report["missing_after"] == 0


def test_coverage_counts_candles_missing_at_both_edges_of_the_request():
    report = coverage([START + 2 * HOUR, START + 3 * HOUR], [1.0, 1.0], HOUR, START + 5, START + 7 * HOUR)
    assert (report["missing_before"], report["missing_inside"], report["missing_after"]) == (2, 0, 3)


def test_coverage_of_an_empty_series_counts_every_requested_candle_missing():
    report = coverage([], [], HOUR, START, START + 24 * HOUR)
    assert (report["candles"], report["missing_before"], report["missing_after"]) == (0, 24, 0)


def test_coverage_counts_zero_volume_candles():
    report = coverage([START, START + HOUR, START + 3 * HOUR], [0.0, 2.0, 0.0], HOUR, START, START + 4 * HOUR)
    assert report["zero_volume"] == 2
    assert report["missing_inside"] == 1


def test_fetch_window_retries_network_errors_then_returns():
    exchange = IndodaxLike([START], cap=649, failures=2)
    waits: list[float] = []
    rows, attempts = fetch_window(exchange, "BTC/IDR", "1h", START, START + HOUR, 500, waits.append)
    assert [row[0] for row in rows] == [START]
    assert attempts == 3
    assert waits == [2, 4]


def test_fetch_window_gives_up_after_the_last_attempt():
    exchange = IndodaxLike([START], cap=649, failures=MAX_ATTEMPTS)
    with pytest.raises(ccxt.NetworkError):
        fetch_window(exchange, "BTC/IDR", "1h", START, START + HOUR, 500, lambda _: None)
    assert exchange.calls == MAX_ATTEMPTS
