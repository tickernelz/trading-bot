"""News headlines and the Fear and Greed index for the chart overlay, fetched on demand and cached."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) trading-bot/0.1"
MAX_BYTES = 2_000_000
NEWS_TTL_S = 900
SENTIMENT_TTL_S = 3600


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    feed: str


SOURCES = {
    "coindesk": Source(
        "coindesk", "CoinDesk", "https://www.coindesk.com/", "https://www.coindesk.com/arc/outboundfeeds/rss/"
    ),
    "cointelegraph": Source(
        "cointelegraph", "Cointelegraph", "https://cointelegraph.com/", "https://cointelegraph.com/rss"
    ),
}
FEAR_GREED = {
    "name": "Fear & Greed Index",
    "provider": "alternative.me",
    "url": "https://alternative.me/crypto/fear-and-greed-index/",
}
FEAR_GREED_API = "https://api.alternative.me/fng/?limit={days}&format=json"
ASSET_NAMES = {"BTC": ("bitcoin",), "ETH": ("ethereum", "ether"), "SOL": ("solana",)}
CLASSIFICATIONS = {"Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"}

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class NewsItem:
    id: str
    source: str
    title: str
    url: str
    published: str
    assets: tuple[str, ...]


@dataclass(frozen=True)
class SentimentPoint:
    date: str
    value: int
    classification: str


def http_get(url: str, timeout: float = 15) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"response larger than {MAX_BYTES} bytes")
    return body


def asset_patterns(assets: Iterable[str]) -> dict[str, re.Pattern[str]]:
    patterns = {}
    for asset in assets:
        words = (asset.lower(), *ASSET_NAMES.get(asset, ()))
        patterns[asset] = re.compile(r"\b(" + "|".join(re.escape(word) for word in words) + r")\b", re.IGNORECASE)
    return patterns


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rss(source: str, raw: bytes, patterns: dict[str, re.Pattern[str]]) -> list[NewsItem]:
    """Keep title, http(s) link, publish time and asset tags; descriptions are dropped as untrusted HTML."""
    items = []
    for node in ET.fromstring(raw).findall("./channel/item"):
        title = " ".join((node.findtext("title") or "").split())
        link = (node.findtext("link") or "").strip()
        stamp = node.findtext("pubDate")
        if not title or not link.startswith(("https://", "http://")) or not stamp:
            continue
        try:
            published = parsedate_to_datetime(stamp)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        text = " ".join([title, *(category.text or "" for category in node.findall("category"))])
        assets = tuple(asset for asset, pattern in patterns.items() if pattern.search(text))
        digest = hashlib.sha1(link.encode()).hexdigest()[:16]
        items.append(NewsItem(f"n_{digest}", source, title, link, iso(published), assets))
    return items


def parse_fear_greed(raw: bytes) -> list[SentimentPoint]:
    payload = json.loads(raw)
    if (payload.get("metadata") or {}).get("error"):
        raise ValueError(f"alternative.me error: {payload['metadata']['error']}")
    points = []
    for row in payload.get("data") or []:
        value = int(row["value"])
        classification = row["value_classification"]
        if not 0 <= value <= 100 or classification not in CLASSIFICATIONS:
            raise ValueError(f"unexpected Fear and Greed row {row!r}")
        day = datetime.fromtimestamp(int(row["timestamp"]), UTC).strftime("%Y-%m-%d")
        points.append(SentimentPoint(day, value, classification))
    return sorted(points, key=lambda point: point.date)


@dataclass
class _Cached:
    fetched_at: float = 0.0
    value: object = None
    error: str | None = None
    ok_at: float | None = None


class Feeds:
    """On-demand cache: a source is fetched only when asked and its TTL has passed; failures keep the last good data."""

    def __init__(
        self,
        sources: Iterable[str],
        assets: Iterable[str],
        fear_greed: bool = True,
        fetch: Fetch = http_get,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sources = [SOURCES[source] for source in sources]
        self._patterns = asset_patterns(assets)
        self._fear_greed = fear_greed
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._news: dict[str, _Cached] = {source.id: _Cached() for source in self._sources}
        self._sentiment = _Cached()

    def _refresh(self, entry: _Cached, ttl: float, load: Callable[[], object]) -> None:
        now = self._clock()
        if entry.fetched_at and now - entry.fetched_at < ttl:
            return
        entry.fetched_at = now
        try:
            entry.value = load()
            entry.error = None
            entry.ok_at = now
        except Exception as exc:
            entry.error = f"{type(exc).__name__}: {exc}"[:200]

    def news(self, asset: str | None = None, limit: int = 50) -> dict:
        limit = max(1, min(limit, 100))
        with self._lock:
            sources, items = [], []
            for source in self._sources:
                entry = self._news[source.id]
                self._refresh(entry, NEWS_TTL_S, lambda s=source: parse_rss(s.id, self._fetch(s.feed), self._patterns))
                sources.append(
                    {
                        **asdict(source),
                        "ok": entry.error is None,
                        "error": entry.error,
                        "fetched_at": iso(datetime.fromtimestamp(entry.ok_at, UTC)) if entry.ok_at else None,
                    }
                )
                items.extend(entry.value or [])
        if asset:
            items = [item for item in items if asset in item.assets]
        unique = {item.id: item for item in items}.values()
        ordered = sorted(unique, key=lambda item: item.published, reverse=True)[:limit]
        return {
            "as_of": iso(datetime.fromtimestamp(self._clock(), UTC)),
            "enabled": bool(self._sources),
            "sources": sources,
            "items": [{**asdict(item), "assets": list(item.assets)} for item in ordered],
        }

    def sentiment(self, days: int = 30) -> dict:
        days = max(1, min(days, 365))
        with self._lock:
            entry = self._sentiment
            if not self._fear_greed:
                return {
                    "as_of": iso(datetime.fromtimestamp(self._clock(), UTC)),
                    "enabled": False,
                    "source": FEAR_GREED,
                    "points": [],
                }
            self._refresh(
                entry, SENTIMENT_TTL_S, lambda: parse_fear_greed(self._fetch(FEAR_GREED_API.format(days=365)))
            )
            points = list(entry.value or [])[-days:]
            return {
                "as_of": iso(datetime.fromtimestamp(self._clock(), UTC)),
                "enabled": True,
                "source": {
                    **FEAR_GREED,
                    "ok": entry.error is None,
                    "error": entry.error,
                    "fetched_at": iso(datetime.fromtimestamp(entry.ok_at, UTC)) if entry.ok_at else None,
                },
                "points": [asdict(point) for point in points],
            }
