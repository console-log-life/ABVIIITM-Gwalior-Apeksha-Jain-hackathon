"""API tests (TestClient, temp SQLite DB, lexicon sentiment backend, no network)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from risk_engine.ingestion.replay import captures_dir
from risk_engine.schemas import Provenance, RawDocument, Source


def _story(path: Path) -> Path:
    path.write_text(json.dumps({"name": "test_story", "steps": [
        {"imitates": "google_news", "title": "Apple unveils new iPhone lineup", "hint_ticker": "AAPL"},
        {"imitates": "google_news", "title": "Moody's downgrades Tata Motors to junk as regulators open probe"},
        {"imitates": "gdelt", "title": "Russia launches invasion as war escalates; sanctions imposed"},
    ]}), encoding="utf-8")
    return path


def _cache(cache_dir: Path) -> None:
    d = captures_dir(cache_dir)
    d.mkdir(parents=True)
    docs = [RawDocument.build(source=Source.GOOGLE_NEWS, title=t, url=f"u/{i}", provenance=Provenance.CACHED_REAL,
                              captured_at="2026-10-03T17:22:21Z")
            for i, t in enumerate(["Fed signals rate cuts as inflation cools", "HDFC Bank profit beats estimates",
                                   "Adani Group shares slump after fraud allegations"])]
    (d / "capture_20261003T172221Z.jsonl").write_text("".join(x.model_dump_json() + "\n" for x in docs),
                                                      encoding="utf-8")


@pytest.fixture
def client(tmp_path):
    cache = tmp_path / "cache"
    _cache(cache)
    s = Settings(_env_file=None, db_path=tmp_path / "test.db", cache_dir=cache, sentiment_backend="lexicon",
                 app_mode="SCENARIO", demo_story_path=_story(tmp_path / "story.json"), demo_step_seconds=0,
                 replay_delay_s=0, log_dir=tmp_path / "logs")
    with TestClient(create_app(s)) as c:
        yield c


def _wait_demo(client, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get("/demo/status").json()
        if not st.get("running"):
            return st
        time.sleep(0.1)
    raise AssertionError("demo did not finish")


# ---------------------------------------------------------------- health

def test_health(client):
    h = client.get("/health").json()
    assert h["db_ok"] is True and h["mode"] == "SCENARIO"
    assert h["model"]["backend"] == "lexicon-fallback" and h["status"] == "degraded"  # fallback is reported
    assert "sources" in h


# ---------------------------------------------------------------- analyze

def test_analyze_persists_and_dedups(client):
    body = {"text": "Moody's downgrades Tata Motors to junk as SEBI opens probe", "source": "manual"}
    r1 = client.post("/analyze", json=body)
    assert r1.status_code == 200 and r1.headers["X-Duplicate"] == "false"
    s1 = r1.json()
    assert s1["event_type"] == "Credit Event" and s1["provenance"] == "SYNTHETIC" and 1 <= s1["impact_score"] <= 10
    assert -1 <= s1["sentiment_score"] <= 1 and s1["company"] == "Tata Motors Ltd."
    r2 = client.post("/analyze", json=body)
    assert r2.headers["X-Duplicate"] == "true" and r2.json()["signal_id"] == s1["signal_id"]
    assert len(client.get("/signals").json()) == 1


@pytest.mark.parametrize("body", [
    {"text": ""}, {"text": "   "}, {}, {"text": "<p>  </p>"}, {"text": "x", "unexpected": 1},
    {"text": "ok text", "ticker": "BAD TICKER!"}, {"text": "ok text", "source": "scenario"},
    {"text": "ok text", "source": "nope"}, {"text": "Die Europäische Zentralbank hat die Leitzinsen angehoben."},
])
def test_analyze_rejects_malformed(client, body):
    r = client.post("/analyze", json=body)
    assert r.status_code == 422 and r.json()["detail"]


def test_company_hint_and_ticker(client):
    s = client.post("/analyze", json={"text": "Holiday outlook improves", "company": "Apple Inc"}).json()
    assert s["ticker"] == "AAPL"


def test_batch(client):
    items = [{"text": "Apple unveils new iPhone lineup"}, {"text": "Fed signals rate cuts as inflation cools"}]
    r = client.post("/analyze/batch", json={"items": items})
    assert r.status_code == 200 and len(r.json()) == 2
    assert client.post("/analyze/batch", json={"items": [{"text": "a b c"}] * 101}).status_code == 422
    assert client.post("/analyze/batch", json={"items": []}).status_code == 422


# ---------------------------------------------------------------- queries

def test_filters_since_id_ticker_and_export(client):
    texts = ["Apple shares plunge after iPhone recall", "Fed signals rate cuts as inflation cools",
             "Russia launches invasion as war escalates; markets plunge on sanctions fears"]
    ids = [client.post("/analyze", json={"text": t}).json()["signal_id"] for t in texts]
    assert {s["event_type"] for s in client.get("/signals", params={"event_type": "Geopolitical"}).json()} == \
        {"Geopolitical"}
    assert all(s["impact_score"] >= 7 for s in client.get("/signals", params={"min_impact": 7}).json())
    assert len(client.get("/signals", params={"provenance": "CACHED_REAL"}).json()) == 0
    after = client.get("/signals", params={"since_id": ids[0]}).json()
    assert [s["signal_id"] for s in after] == ids[1:]
    assert client.get("/signals", params={"event_type": "Weather"}).status_code == 422
    assert client.get("/signals", params={"since_id": "nope"}).status_code == 404
    agg = client.get("/signals/AAPL").json()
    assert agg["count"] == 1 and agg["max_impact"] == agg["signals"][0]["impact_score"]
    lines = client.get("/signals/export.jsonl").text.strip().splitlines()
    assert len(lines) == 3 and all(json.loads(x)["provenance"] == "SYNTHETIC" for x in lines)


# ---------------------------------------------------------------- SSE

def test_sse_replays_stored_signal(client):
    client.post("/analyze", json={"text": "Apple unveils new iPhone lineup"})
    with client.stream("GET", "/signals/stream", params={"replay_last": 1, "max_events": 1}) as r:
        body = "".join(r.iter_text())
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: signal" in body and '"event_type"' in body


def test_sse_emits_new_signal(client):
    received: list[str] = []

    def listen():
        with client.stream("GET", "/signals/stream", params={"max_events": 1}) as r:
            received.append("".join(r.iter_text()))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    posted = []
    for i in range(20):  # keep publishing until the (possibly late-subscribing) stream has received one event
        time.sleep(0.3)
        posted.append(client.post("/analyze", json={"text": f"Fed signals rate cut number {i} as inflation cools"})
                      .json()["signal_id"])
        if not t.is_alive():
            break
    t.join(timeout=10)
    assert received and any(sid in received[0] for sid in posted)


# ---------------------------------------------------------------- demo / replay / reset

def test_scenario_demo_and_reset(client):
    assert client.post("/demo/start", json={"mode": "SCENARIO", "step_seconds": 0}).status_code == 200
    st = _wait_demo(client)
    assert st.get("documents") == 3
    sigs = client.get("/signals").json()
    assert len(sigs) == 3 and all(s["provenance"] == "SYNTHETIC" and s["source"] == "scenario" for s in sigs)
    assert {s["imitated_source"] for s in sigs} == {"google_news", "gdelt"}
    reset = client.post("/demo/reset").json()
    assert reset["signals_deleted"] == 3 and client.get("/signals").json() == []


def test_replay_mode_streams_cached_real(client):
    assert client.post("/mode", json={"mode": "REPLAY"}).status_code == 200
    _wait_demo(client)
    sigs = client.get("/signals").json()
    assert len(sigs) == 3 and all(s["provenance"] == "CACHED_REAL" for s in sigs)
    assert all(s["captured_at"].startswith("2026-10-03T17:22:21") for s in sigs)
    assert client.get("/health").json()["mode"] == "REPLAY"


def test_demo_start_rejects_live(client):
    assert client.post("/demo/start", json={"mode": "LIVE"}).status_code == 422


# ---------------------------------------------------------------- swagger

def test_every_endpoint_has_an_example(client):
    spec = client.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert "example" in json.dumps(op), f"{method.upper()} {path} has no example"
