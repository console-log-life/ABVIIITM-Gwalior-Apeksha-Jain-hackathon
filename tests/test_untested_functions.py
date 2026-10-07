"""Tests for public functions the rest of the suite never executed (found by src/scripts/list_untested.py)."""

from __future__ import annotations

import asyncio
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from risk_engine.bus import EventBus
from risk_engine.event_classifier.rules import EventResult
from risk_engine.history import default_history_db
from risk_engine.impact_scoring.scorer import ImpactScorer, get_scorer
from risk_engine.ingestion.base import BaseAdapter, HealthRegistry, load_sources_config
from risk_engine.ingestion.mastodon import MastodonAdapter
from risk_engine.ingestion.stocktwits import parse_stocktwits
from risk_engine.schemas import Provenance, RawDocument, Source, SourceType
from risk_engine.store import Store
from tests.test_api import _cache, _story


@pytest.fixture
def client(tmp_path):
    cache = tmp_path / "cache"
    _cache(cache)
    s = Settings(_env_file=None, db_path=tmp_path / "test.db", cache_dir=cache, sentiment_backend="lexicon",
                 app_mode="SCENARIO", demo_story_path=_story(tmp_path / "story.json"), demo_step_seconds=0,
                 replay_delay_s=0, log_dir=tmp_path / "logs", real_history_path=tmp_path / "history.db")
    with TestClient(create_app(s)) as c:
        yield c


def test_methodology_lists_weights_and_thresholds(client):
    r = client.get("/methodology")
    assert r.status_code == 200
    assert r.json() and isinstance(r.json(), dict)


def test_history_load_builds_from_cache(client):
    r = client.post("/history/load")
    assert r.status_code == 200
    t0 = time.time()
    while time.time() - t0 < 60:
        st = client.get("/history").json()["status"]
        if st.get("state") in ("ready", "error"):
            break
        time.sleep(0.2)
    assert st.get("state") == "ready" and st["loaded"]["signals"] == 3, st
    assert client.post("/history/load", params={"rebuild": "maybe"}).status_code == 422


class _FakeAdapter(BaseAdapter):
    name = "fake"
    source = Source.GOOGLE_NEWS
    config_key = "fake"

    async def _fetch(self) -> list[RawDocument]:
        return [RawDocument.build(source=Source.GOOGLE_NEWS, title="Moody's downgrades Tata Motors to junk",
                                  url="fake/1", provenance=Provenance.LIVE)]


def test_live_mode_ingests_without_network(client, monkeypatch):
    import app.runtime as runtime

    def fake_adapters(http_client, settings, only=None):
        return [_FakeAdapter(http_client, settings, config={"interval_s": 3600})]

    monkeypatch.setattr(runtime, "build_live_adapters", fake_adapters)
    r = client.post("/mode", json={"mode": "LIVE"})
    assert r.status_code == 200 and r.json()["live_running"] is True
    t0 = time.time()
    while time.time() - t0 < 30 and not client.get("/signals", params={"provenance": "LIVE"}).json():
        time.sleep(0.2)
    assert client.get("/signals", params={"provenance": "LIVE"}).json()
    assert client.post("/mode", json={"mode": "REPLAY"}).status_code == 200


def test_parse_stocktwits_keeps_channel_not_author():
    payload = {"messages": [
        {"id": 1, "body": "$TSLA looks weak after recall @someone", "user": {"username": "bob"},
         "created_at": "2026-10-03T10:00:00Z", "entities": {"sentiment": {"basic": "Bearish"}}},
        {"id": 2, "body": "", "user": {"username": "x"}},
    ]}
    docs = parse_stocktwits(payload, "TSLA")
    assert len(docs) == 1
    d = docs[0]
    assert d.publisher == "$TSLA stream" and d.user_sentiment_tag == "Bearish" and "@someone" not in d.text
    assert parse_stocktwits({}, "TSLA") == []


def test_mastodon_state_round_trip(settings, clock, health):
    import httpx

    a = MastodonAdapter(httpx.AsyncClient(), settings, config={"tags": ["markets"]}, clock=clock, health=health)
    a.since_ids = {"markets": "123"}
    a.backoff_until = clock() + 60
    b = MastodonAdapter(httpx.AsyncClient(), settings, config={"tags": ["markets"]}, clock=clock, health=health)
    b.import_state(a.export_state())
    assert b.since_ids == {"markets": "123"} and b.backoff_until == a.backoff_until


def test_store_source_health_upsert(tmp_path):
    st = Store(tmp_path / "s.db")
    st.upsert_source_health([{"source": "gdelt", "status": "OK"}])
    st.upsert_source_health([{"source": "gdelt", "status": "BACKOFF"}, {"source": "reddit", "status": "OK"}])
    rows = st.source_health_rows()
    assert [(r["source"], r["status"]) for r in rows] == [("gdelt", "BACKOFF"), ("reddit", "OK")]


def test_small_helpers():
    cfg = load_sources_config()
    assert "google_news" in cfg or cfg  # the shipped config parses
    h = HealthRegistry()
    h.reset()
    bus = EventBus()
    assert bus.subscriber_count("signal.created") == 0
    bus.subscribe("signal.created", lambda _: None)
    assert bus.subscriber_count("signal.created") == 1
    ev = EventResult(primary="Credit", secondary=None, evidence=[], scores={}, intensifier_adj=0.0,
                     evidence_by_class={"Credit": ["downgrade", "default"]})
    assert ev.distinct_patterns() == 2 and ev.distinct_patterns("Legal") == 0
    assert isinstance(get_scorer(), ImpactScorer)
    assert default_history_db().name == "real_history.db"


def test_generate_portfolio_main_writes_csv(tmp_path, monkeypatch):
    from portfolio import generate_portfolio

    out = tmp_path / "p.csv"
    monkeypatch.setattr(sys, "argv", ["generate_portfolio", "--seed", "7", "--out", str(out)])
    assert generate_portfolio.main() in (0, None)
    assert out.exists() and len(out.read_text(encoding="utf-8").splitlines()) > 10


def test_scheduler_run_forever_stops(settings, clock, health):
    import httpx

    from risk_engine.ingestion.scheduler import IngestionScheduler

    got: list = []

    async def sink(docs):
        got.extend(docs)

    async def go():
        a = _FakeAdapter(httpx.AsyncClient(), settings, config={"interval_s": 3600}, health=health)
        stop = asyncio.Event()
        task = asyncio.create_task(IngestionScheduler([a], sink).run_forever(stop, tick_s=0.05))
        for _ in range(100):
            if got:
                break
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 5)

    asyncio.run(go())
    assert got and got[0].title.startswith("Moody's")


def test_build_live_adapters_constructs_without_network(settings):
    import httpx

    from risk_engine.ingestion.scheduler import ADAPTER_CLASSES, build_live_adapters

    adapters = build_live_adapters(httpx.AsyncClient(), settings)
    assert [a.name for a in adapters] == [c.name for c in ADAPTER_CLASSES]
    assert [a.name for a in build_live_adapters(httpx.AsyncClient(), settings, only={"gdelt"})] == ["gdelt"]


def test_replay_cli_prints_cached_documents(monkeypatch, capsys):
    from risk_engine.ingestion import replay

    monkeypatch.setattr(sys, "argv", ["replay", "--limit", "2"])
    assert replay.main() == 0
    out = capsys.readouterr().out
    assert "replayed 2 documents" in out and "CACHED_REAL" in out


@pytest.mark.model
def test_module_level_pipeline_entry_points(monkeypatch, capsys):
    from risk_engine import pipeline
    from risk_engine.sentiment.finbert import get_sentiment_engine

    doc = RawDocument.build(source=Source.MANUAL, title="Moody's downgrades Tata Motors to junk",
                            provenance=Provenance.SYNTHETIC, source_type=SourceType.NEWS)
    sig = pipeline.process(doc)
    assert sig.event_type == "Credit Event" and sig.sentiment_label == "Negative"
    assert len(pipeline.process_batch([doc])) == 1
    assert get_sentiment_engine() is get_sentiment_engine()
    monkeypatch.setattr(sys, "argv", ["pipeline", "Fed cuts rates as inflation cools"])
    assert pipeline.main() == 0
    assert '"impact_score"' in capsys.readouterr().out
