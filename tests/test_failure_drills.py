"""Failure drills (spec 11 / M6): a source dies mid-run -> health shows it, the other source keeps feeding
signals through the same pipeline, nothing crashes; the model fallback is reported by /health."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.runtime import Runtime
from risk_engine.ingestion.base import HealthRegistry, SourceStatus
from risk_engine.ingestion.google_news import GoogleNewsAdapter
from risk_engine.ingestion.reddit_rss import RedditRSSAdapter
from risk_engine.ingestion.scheduler import IngestionScheduler

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>{title} - Reuters</title><link>https://news.google.com/rss/articles/{n}</link>
<pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>{title}</title><link href="https://www.reddit.com/r/stocks/comments/{n}"/>
<updated>2026-10-03T09:00:00+00:00</updated></entry></feed>"""


REDDIT_TITLES = ["HDFC Bank shares jump after strong quarterly results",
                 "Infosys wins large outsourcing deal in Europe",
                 "Tesla recalls vehicles over braking software defect", "Adani Group faces fresh regulatory probe",
                 "Reliance Industries profit beats analyst estimates", "Boeing halts 737 deliveries after inspection",
                 "JPMorgan raises dividend after stress test", "Intel delays new foundry plant opening"]


@pytest.fixture
def runtime(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "drill.db", cache_dir=tmp_path, sentiment_backend="lexicon",
                 log_dir=tmp_path / "logs")
    return Runtime(s)


async def test_source_killed_mid_run_shows_fallback_and_keeps_running(runtime, monkeypatch):
    import app.runtime as rt_mod

    health = HealthRegistry()
    monkeypatch.setattr(rt_mod, "HEALTH", health)
    state = {"google_dead": False, "n": 0}

    def respond(r: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if "news.google.com" in str(r.url):
            if state["google_dead"]:
                raise httpx.ConnectError("connection refused (drill: source killed)")
            return httpx.Response(200, text=RSS.format(title=f"Fed signals rate cut number {state['n']}",
                                                       n=state["n"]))
        title = REDDIT_TITLES[state["n"] % len(REDDIT_TITLES)]  # distinct stories, so dedup keeps them
        return httpx.Response(200, text=ATOM.format(title=title, n=state["n"]))

    s = runtime.settings
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gn = GoogleNewsAdapter(client, s, {"interval_s": 1, "capacity": 5, "min_gap_s": 0,
                                           "editions": {"US": "x=1"}, "queries": [{"q": "fed", "edition": "US"}]},
                               health=health)
        rd = RedditRSSAdapter(client, s, {"interval_s": 1, "capacity": 5, "min_gap_s": 0, "subreddits": ["stocks"]},
                              health=health)

        async def sink(docs):
            await runtime.ingest(docs, "live")

        sched = IngestionScheduler([gn, rd], sink)
        first = {r.source: r.status for r in await sched.run_once()}
        assert first == {"google_news": SourceStatus.OK, "reddit": SourceStatus.OK}
        stored_before = runtime.store.count_signals()

        state["google_dead"] = True  # kill one source mid-run
        statuses = []
        for _ in range(3):
            statuses.append({r.source: r.status for r in await sched.run_once()})

    assert [x["google_news"] for x in statuses] == [SourceStatus.DEGRADED, SourceStatus.DEGRADED, SourceStatus.DOWN]
    assert all(x["reddit"] is SourceStatus.OK for x in statuses)  # the surviving source keeps feeding
    assert runtime.store.count_signals() > stored_before
    h = runtime.health()
    by = {x["source"]: x for x in h["sources"]}
    assert by["google_news"]["status"] == "DOWN" and "ConnectError" in by["google_news"]["last_error"]
    assert by["reddit"]["status"] == "OK"
    assert h["db_ok"] is True


def test_model_fallback_is_reported(runtime):
    h = runtime.health()  # pipeline not built yet -> "loading"
    assert h["model"]["backend"] == "loading"
    _ = runtime.pipeline
    h = runtime.health()
    assert h["model"]["backend"] == "lexicon-fallback" and h["status"] == "degraded"
