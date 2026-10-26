from __future__ import annotations

import json

import pytest

from engine import news
from engine.settings import ConfigError, load_settings

COINDESK = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>CoinDesk</title>
<item><title>Bitcoin  slips below $60K</title><link>https://www.coindesk.com/markets/btc-slips</link>
<pubDate>Sun, 25 Oct 2026 15:00:00 +0000</pubDate><category>Markets</category>
<description>&lt;img src=x onerror=alert(1)&gt;</description></item>
<item><title>Latvia targets tokenization rules</title><link>https://www.coindesk.com/policy/latvia</link>
<pubDate>Sun, 25 Oct 2026 13:00:00 +0000</pubDate><category>Policy</category></item>
<item><title>Scripted link</title><link>javascript:alert(1)</link><pubDate>Sun, 25 Oct 2026 12:00:00 +0000</pubDate></item>
<item><title>No date</title><link>https://www.coindesk.com/no-date</link></item>
</channel></rss>"""

COINTELEGRAPH = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>AI agents help rescue ETH\xe2\x80\x99s Glamsterdam fork</title>
<link>https://cointelegraph.com/magazine/eth-fork</link><pubDate>Mon, 26 Oct 2026 07:13:29 +0700</pubDate>
<category>Magazine</category></item>
<item><title>Solana validators vote</title><link>https://cointelegraph.com/news/solana</link>
<pubDate>Sun, 25 Oct 2026 16:00:00 +0000</pubDate></item>
<item><title>Solstice consolidation is not a solar story</title><link>https://cointelegraph.com/news/solstice</link>
<pubDate>Sun, 25 Oct 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""

FNG = {
    "name": "Fear and Greed Index",
    "data": [
        {"value": "50", "value_classification": "Neutral", "timestamp": "1792972800"},
        {"value": "24", "value_classification": "Extreme Fear", "timestamp": "1792886400"},
    ],
    "metadata": {"error": None},
}


class FakeWeb:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failing: set[str] = set()
        self.now = 1_792_990_000.0

    def fetch(self, url: str) -> bytes:
        self.calls.append(url)
        if any(part in url for part in self.failing):
            raise OSError("network down")
        if "coindesk" in url:
            return COINDESK
        if "cointelegraph" in url:
            return COINTELEGRAPH
        return json.dumps(FNG).encode()


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def feeds(web):
    return news.Feeds(["coindesk", "cointelegraph"], ["BTC", "ETH", "SOL"], fetch=web.fetch, clock=lambda: web.now)


def test_items_are_merged_newest_first_with_asset_tags(feeds):
    payload = feeds.news()
    titles = [(item["title"], item["source"], item["assets"]) for item in payload["items"]]
    assert titles == [
        ("AI agents help rescue ETH\u2019s Glamsterdam fork", "cointelegraph", ["ETH"]),
        ("Solana validators vote", "cointelegraph", ["SOL"]),
        ("Bitcoin slips below $60K", "coindesk", ["BTC"]),
        ("Latvia targets tokenization rules", "coindesk", []),
        ("Solstice consolidation is not a solar story", "cointelegraph", []),
    ]
    assert payload["items"][0]["published"] == "2026-10-26T00:13:29Z"
    assert [source["id"] for source in payload["sources"]] == ["coindesk", "cointelegraph"]
    assert all(source["ok"] and source["url"].startswith("https://") for source in payload["sources"])


def test_untrusted_fields_are_not_served(feeds):
    served = json.dumps(feeds.news())
    assert "javascript:" not in served
    assert "onerror" not in served
    assert "No date" not in served


@pytest.mark.parametrize(("limit", "served"), [(0, 1), (-3, 1), (2, 2), (500, 5)])
def test_limit_is_clamped(feeds, limit, served):
    assert len(feeds.news(limit=limit)["items"]) == served


def test_asset_filter_keeps_only_tagged_items(feeds):
    assert [item["assets"] for item in feeds.news(asset="BTC")["items"]] == [["BTC"]]


def test_sources_are_fetched_once_per_ttl(feeds, web):
    feeds.news()
    feeds.news(asset="ETH")
    assert len(web.calls) == 2
    web.now += news.NEWS_TTL_S
    feeds.news()
    assert len(web.calls) == 4


def test_failed_source_keeps_last_items_and_reports_error(feeds, web):
    feeds.news()
    web.failing.add("cointelegraph")
    web.now += news.NEWS_TTL_S
    payload = feeds.news()
    status = {source["id"]: source for source in payload["sources"]}
    assert status["coindesk"]["ok"] is True
    assert status["cointelegraph"]["ok"] is False
    assert "network down" in status["cointelegraph"]["error"]
    assert status["cointelegraph"]["fetched_at"] == "2026-10-26T04:46:40Z"
    assert len(payload["items"]) == 5


def test_first_failure_serves_no_items_but_names_the_source(web):
    web.failing.add("coindesk")
    payload = news.Feeds(["coindesk"], ["BTC"], fetch=web.fetch, clock=lambda: web.now).news()
    assert payload["items"] == []
    assert payload["sources"][0]["ok"] is False
    assert payload["sources"][0]["fetched_at"] is None


def test_sentiment_is_daily_oldest_first_with_attribution(feeds, web):
    payload = feeds.sentiment(days=30)
    assert payload["points"] == [
        {"date": "2026-10-25", "value": 24, "classification": "Extreme Fear"},
        {"date": "2026-10-26", "value": 50, "classification": "Neutral"},
    ]
    assert payload["source"]["provider"] == "alternative.me"
    assert payload["source"]["url"] == "https://alternative.me/crypto/fear-and-greed-index/"
    assert feeds.sentiment(days=1)["points"] == [payload["points"][-1]]
    assert len(web.calls) == 1


@pytest.mark.parametrize(
    "row",
    [
        {"value": "101", "value_classification": "Greed", "timestamp": "1792972800"},
        {"value": "50", "value_classification": "Panic", "timestamp": "1792972800"},
    ],
)
def test_sentiment_rejects_out_of_contract_rows(row):
    with pytest.raises(ValueError):
        news.parse_fear_greed(json.dumps({"data": [row], "metadata": {"error": None}}).encode())


def test_disabled_layers_fetch_nothing(web):
    feeds = news.Feeds([], ["BTC"], fear_greed=False, fetch=web.fetch, clock=lambda: web.now)
    assert feeds.news() == {"as_of": "2026-10-26T04:46:40Z", "enabled": False, "sources": [], "items": []}
    sentiment = feeds.sentiment()
    assert sentiment["enabled"] is False
    assert sentiment["points"] == []
    assert sentiment["source"]["provider"] == "alternative.me"
    assert web.calls == []


def test_unknown_news_source_is_a_config_error(example_raw, write_config):
    example_raw["data"]["news_rss"] = ["coindesk", "rumors"]
    with pytest.raises(ConfigError, match="news_rss"):
        load_settings(write_config(example_raw))
