"""Adapter behaviour with mocked HTTP (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from risk_engine.ingestion.base import SourceStatus, TokenBucket
from risk_engine.ingestion.bluesky import BlueskyAdapter
from risk_engine.ingestion.finnhub import FinnhubAdapter
from risk_engine.ingestion.gdelt import GdeltAdapter
from risk_engine.ingestion.google_news import GoogleNewsAdapter
from risk_engine.ingestion.mastodon import MastodonAdapter
from risk_engine.ingestion.reddit_rss import RedditRSSAdapter
from risk_engine.ingestion.stocktwits import StockTwitsAdapter
from risk_engine.schemas import Provenance, Source, SourceType

GOOGLE_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Moody's downgrades Example Corp to junk - Reuters</title>
<link>https://news.google.com/rss/articles/abc</link>
<pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Apple unveils new iPhone lineup - The Verge</title>
<link>https://news.google.com/rss/articles/def</link>
<pubDate>Fri, 02 Oct 2026 11:00:00 GMT</pubDate><source url="https://theverge.com">The Verge</source></item>
</channel></rss>"""

REDDIT_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>HDFC Bank results beat estimates</title><link href="https://www.reddit.com/r/stocks/comments/1"/>
<updated>2026-10-03T09:00:00+00:00</updated>
<content type="html">&lt;p&gt;Strong quarter.&lt;/p&gt; submitted by /u/someone [link] [comments]</content></entry>
</feed>"""


def _cfg(**kw):
    base = {"interval_s": 600, "capacity": 1, "min_gap_s": 0.0, "backoff_429_s": 900, "backoff_403_s": 3600}
    return {**base, **kw}


# ---------------------------------------------------------------- token bucket

def test_token_bucket_enforces_gap(clock):
    b = TokenBucket(capacity=1, min_gap_s=120, clock=clock)
    assert b.try_acquire()
    assert not b.try_acquire()
    assert b.wait_time() == pytest.approx(120)
    clock.advance(119)
    assert not b.try_acquire()
    clock.advance(1)
    assert b.try_acquire()


def test_token_bucket_restore_across_processes(clock):
    b = TokenBucket(capacity=1, min_gap_s=120, clock=clock)
    b.restore(clock() - 30)
    assert b.wait_time() == pytest.approx(90)


async def test_more_requests_than_capacity_wait_instead_of_failing(recorder_factory, settings, health):
    """Regression: 4 Mastodon tags with capacity 2 must all be fetched (real clock, short gap)."""
    rec = recorder_factory(lambda r: httpx.Response(200, json=[]))
    cfg = _cfg(capacity=2, min_gap_s=0.2, instance="m.example", tags=["a", "b", "c", "d"], limit=5)
    async with rec.client() as c:
        res = await MastodonAdapter(c, settings, cfg, health=health).fetch()
    assert res.status is SourceStatus.EMPTY and len(rec.requests) == 4


# ---------------------------------------------------------------- google news

async def test_google_news_parses_feed(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(200, content=GOOGLE_RSS))
    cfg = _cfg(editions={"US": "hl=en-US&gl=US&ceid=US:en"}, queries=[{"q": "Apple stock", "edition": "US",
                                                                          "ticker": "AAPL"}])
    async with rec.client() as c:
        res = await GoogleNewsAdapter(c, settings, cfg, clock, health).fetch()
    assert res.status is SourceStatus.OK and len(res.docs) == 2
    d = res.docs[0]
    assert d.source is Source.GOOGLE_NEWS and d.source_type is SourceType.NEWS
    assert d.provenance is Provenance.LIVE and d.publisher == "Reuters" and d.hint_ticker == "AAPL"
    assert d.published_at is not None and d.published_at.tzinfo is not None
    assert "q=Apple+stock" in str(rec.requests[0].url)


async def test_google_news_partial_failure_keeps_other_queries(recorder_factory, settings, clock, health):
    def respond(r):
        return httpx.Response(404) if "bad" in str(r.url) else httpx.Response(200, content=GOOGLE_RSS)

    rec = recorder_factory(respond)
    cfg = _cfg(editions={"US": "x=1"}, queries=[{"q": "bad", "edition": "US"}, {"q": "good", "edition": "US"}])
    async with rec.client() as c:
        res = await GoogleNewsAdapter(c, settings, cfg, clock, health).fetch()
    assert res.status is SourceStatus.OK and len(res.docs) == 2


# ---------------------------------------------------------------- reddit

async def test_reddit_rotates_one_subreddit_per_cycle_with_gap(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(200, content=REDDIT_ATOM))
    cfg = _cfg(min_gap_s=120, subreddits=["stocks", "investing", "wallstreetbets", "IndianStockMarket"])
    async with rec.client() as c:
        a = RedditRSSAdapter(c, settings, cfg, clock, health)
        r1 = await a.fetch()
        r2 = await a.fetch()  # immediately again -> must NOT hit the network
        clock.advance(120)
        r3 = await a.fetch()
    assert r1.status is SourceStatus.OK and r1.docs[0].publisher == "r/stocks"
    assert "submitted by" not in r1.docs[0].text
    assert r2.status is SourceStatus.RATE_LIMITED
    assert r3.status is SourceStatus.OK and r3.docs[0].publisher == "r/investing"
    assert [str(r.url).split("/r/")[1].split("/")[0] for r in rec.requests] == ["stocks", "investing"]


async def test_reddit_429_parks_for_15_minutes(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(429))
    async with rec.client() as c:
        a = RedditRSSAdapter(c, settings, _cfg(min_gap_s=120, subreddits=["stocks", "investing"]), clock, health)
        r1 = await a.fetch()
        clock.advance(600)
        r2 = await a.fetch()
        clock.advance(301)
        await a.fetch()
    assert r1.status is SourceStatus.BACKOFF and r2.status is SourceStatus.BACKOFF
    assert len(rec.requests) == 2  # nothing during the 900 s backoff; retried after it
    assert health.get("reddit").status is SourceStatus.BACKOFF


async def test_reddit_state_roundtrip(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(200, content=REDDIT_ATOM))
    cfg = _cfg(min_gap_s=120, subreddits=["a", "b", "c"])
    async with rec.client() as c:
        a = RedditRSSAdapter(c, settings, cfg, clock, health)
        await a.fetch()
        state = a.export_state()
        b = RedditRSSAdapter(c, settings, cfg, clock, health)
        b.import_state(state)
        assert (await b.fetch()).status is SourceStatus.RATE_LIMITED  # gap survives a "new process"
        clock.advance(120)
        res = await b.fetch()
    assert res.docs[0].publisher == "r/b"


# ---------------------------------------------------------------- mastodon

async def test_mastodon_parses_and_tracks_since_id(recorder_factory, settings, clock, health):
    statuses = [
        {"id": "105", "created_at": "2026-10-03T10:00:00.000Z", "language": "en", "reblog": None,
         "url": "https://m.s/@a/105", "account": {"acct": "a"},
         "content": '<p>Fed holds rates <a class="hashtag">#<span>stocks</span></a></p>'},
        {"id": "104", "language": "en", "reblog": {"id": "1"}, "content": "<p>boost</p>", "account": {}},
        {"id": "103", "language": "de", "reblog": None, "content": "<p>Die Aktien fallen</p>", "account": {}},
    ]
    rec = recorder_factory(lambda r: httpx.Response(200, json=statuses))
    async with rec.client() as c:
        a = MastodonAdapter(c, settings, _cfg(instance="mastodon.social", tags=["stocks"], limit=40),
                            clock, health)
        res = await a.fetch()
        await a.fetch()
    assert len(res.docs) == 1 and res.docs[0].text == "Fed holds rates #stocks"
    assert res.docs[0].source_type is SourceType.SOCIAL
    assert "since_id=105" in str(rec.requests[1].url)


# ---------------------------------------------------------------- bluesky

async def test_bluesky_skips_without_credentials(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(500))
    async with rec.client() as c:
        res = await BlueskyAdapter(c, settings, _cfg(queries=[{"q": "$AAPL"}]), clock, health).fetch()
    assert res.status is SourceStatus.DISABLED and rec.requests == []


async def test_bluesky_authenticates_and_refreshes(recorder_factory, settings, clock, health):
    s = settings.model_copy(update={"bluesky_handle": "me.bsky.social", "bluesky_app_password": "app-pw"})
    calls = {"search": 0}
    post = {"uri": "at://did:plc:x/app.bsky.feed.post/3abc", "author": {"handle": "trader.bsky.social"},
            "record": {"text": "$AAPL looks weak after downgrade", "createdAt": "2026-10-03T10:00:00Z"}}

    def respond(r: httpx.Request) -> httpx.Response:
        path = r.url.path
        if path.endswith("createSession"):
            assert json.loads(r.content)["password"] == "app-pw"
            return httpx.Response(200, json={"accessJwt": "A1", "refreshJwt": "R1", "handle": "me"})
        if path.endswith("refreshSession"):
            assert r.headers["Authorization"] == "Bearer R1"
            return httpx.Response(200, json={"accessJwt": "A2", "refreshJwt": "R2"})
        calls["search"] += 1
        if r.headers["Authorization"] == "Bearer A1" and calls["search"] > 1:
            return httpx.Response(400, json={"error": "ExpiredToken", "message": "Token has expired"})
        return httpx.Response(200, json={"posts": [post]})

    rec = recorder_factory(respond)
    async with rec.client() as c:
        a = BlueskyAdapter(c, s, _cfg(queries=[{"q": "$AAPL", "ticker": "AAPL"}], limit=25), clock, health)
        r1 = await a.fetch()
        r2 = await a.fetch()
    assert r1.status is SourceStatus.OK and r2.status is SourceStatus.OK
    d = r1.docs[0]
    assert d.source is Source.BLUESKY and d.hint_ticker == "AAPL"
    assert d.url == "https://bsky.app/profile/trader.bsky.social/post/3abc"
    paths = [r.url.path.rsplit(".", 1)[-1] for r in rec.requests]
    assert paths.count("createSession") == 1 and paths.count("refreshSession") == 1


# ---------------------------------------------------------------- best-effort sources

async def test_gdelt_plain_text_200_is_a_failure_not_a_crash(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(200, text="Please limit requests to one every 5 seconds"))
    async with rec.client() as c:
        res = await GdeltAdapter(c, settings, _cfg(query="x", max_records=5), clock, health).fetch()
    assert res.status is SourceStatus.DEGRADED and "non-JSON" in res.detail and res.docs == []


async def test_stocktwits_403_backs_off(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(403))
    async with rec.client() as c:
        a = StockTwitsAdapter(c, settings, _cfg(symbols=["AAPL"]), clock, health)
        assert (await a.fetch()).status is SourceStatus.BACKOFF
        assert (await a.fetch()).status is SourceStatus.BACKOFF
    assert len(rec.requests) == 1


async def test_finnhub_disabled_without_key_and_uses_header(recorder_factory, settings, clock, health):
    rec = recorder_factory(lambda r: httpx.Response(200, json=[
        {"headline": "Apple beats earnings", "summary": "Strong quarter", "url": "u", "datetime": 1791000000,
         "source": "Reuters"}]))
    async with rec.client() as c:
        assert (await FinnhubAdapter(c, settings, _cfg(symbols=["AAPL"]), clock, health).fetch()).status \
            is SourceStatus.DISABLED
        keyed = settings.model_copy(update={"finnhub_api_key": "secret-key"})
        res = await FinnhubAdapter(c, keyed, _cfg(symbols=["AAPL"], lookback_days=2), clock, health).fetch()
    assert res.status is SourceStatus.OK and res.docs[0].hint_ticker == "AAPL"
    assert rec.requests[0].headers["X-Finnhub-Token"] == "secret-key"
    assert "secret-key" not in str(rec.requests[0].url)


async def test_transport_errors_retry_max_two_then_degrade_then_down(recorder_factory, settings, clock, health):
    def boom(r):
        raise httpx.ConnectError("network unreachable")

    rec = recorder_factory(boom)
    async with rec.client() as c:
        a = GdeltAdapter(c, settings, _cfg(query="x", max_records=5), clock, health)
        r1 = await a.fetch()
        assert len(rec.requests) == 3  # 1 attempt + 2 retries
        await a.fetch()
        r3 = await a.fetch()
    assert r1.status is SourceStatus.DEGRADED and r3.status is SourceStatus.DOWN
    assert "ConnectError" in health.get("gdelt").last_error
