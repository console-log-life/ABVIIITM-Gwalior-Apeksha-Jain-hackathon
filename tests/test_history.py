"""REAL history: build from a capture cache, freshness fingerprint, load into the live store, time machine (as_of)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from risk_engine import history
from risk_engine.ingestion.replay import captures_dir
from risk_engine.schemas import Provenance, RawDocument, Source
from risk_engine.store import Store

T0 = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
HEADLINES = [  # (hours after T0, source, title)
    (0, Source.GOOGLE_NEWS, "Moody's downgrades Tata Motors to junk as SEBI opens fraud probe; default fears grow"),
    (1, Source.GOOGLE_NEWS, "HDFC Bank profit beats estimates"),
    (5, Source.REDDIT, "Russia invades neighbour; war and sanctions crash markets"),
    (30, Source.GOOGLE_NEWS, "Apple unveils new iPhone lineup"),
]


def write_cache(cache: Path, rows=HEADLINES, name="capture_20261003T170000Z.jsonl") -> None:
    d = captures_dir(cache)
    d.mkdir(parents=True, exist_ok=True)
    docs = [RawDocument.build(source=src, title=t, url=f"u/{i}-{name}", provenance=Provenance.CACHED_REAL,
                              captured_at=(T0 + timedelta(hours=h)).isoformat(),
                              published_at=(T0 + timedelta(hours=h - 2)).isoformat())
            for i, (h, src, t) in enumerate(rows)]
    (d / name).write_text("".join(x.model_dump_json() + "\n" for x in docs), encoding="utf-8")


@pytest.fixture
def s(tmp_path) -> Settings:
    write_cache(tmp_path / "cache")
    return Settings(_env_file=None, cache_dir=tmp_path / "cache", real_history_path=tmp_path / "hist.db",
                    db_path=tmp_path / "live.db", sentiment_backend="lexicon", log_dir=tmp_path / "logs",
                    real_history_autoload=False)


def test_build_is_fresh_until_inputs_change(s, tmp_path):
    assert not history.is_fresh(s)
    meta = history.build_history(s)
    assert meta["documents"] == 4 and meta["signals"] == 4 and meta["source"] == "local capture cache"
    assert meta["first_capture"].startswith("2026-10-03T17:00") and history.is_fresh(s)
    write_cache(tmp_path / "cache", HEADLINES[:1], name="capture_20261004T170000Z.jsonl")
    assert not history.is_fresh(s)  # a new capture file makes the cache stale


def test_history_runs_use_event_time_and_real_prefix(s):
    meta = history.build_history(s)
    st = Store(history.history_path(s))
    runs = st.list_stress_runs(100)
    assert len(runs) == meta["stress_runs"]
    known = {(T0 + timedelta(hours=h - 2)).isoformat() for h, _, _ in HEADLINES}  # event (publication) times
    for r in runs:
        assert r["run_id"].startswith("real-") and r["created_at"] in known
    st.engine.dispose()


def test_load_into_store_is_idempotent_and_survives_demo_reset(s):
    history.build_history(s)
    live = Store(s.db_file)
    assert history.load_into(live, history.history_path(s))["signals"] == 4
    assert history.load_into(live, history.history_path(s))["signals"] == 4  # reload replaces, never duplicates
    sigs = live.list_signals(limit=100)
    assert len(sigs) == 4 and {r["origin"] for r in sigs} == {"real"}
    assert {r["provenance"] for r in sigs} == {"CACHED_REAL"}
    live.reset_demo()
    assert len(live.list_signals(limit=100)) == 4  # history is kept by /demo/reset
    lo, hi = live.event_time_range()
    assert lo == T0 - timedelta(hours=2) and hi == T0 + timedelta(hours=28)
    # time machine: signals published up to T0
    assert len(live.list_signals(limit=100, until_ts=T0)) == 2
    live.engine.dispose()


def test_api_time_machine_overview_and_watchlist(s, monkeypatch):
    monkeypatch.setenv("REAL_HISTORY_AUTOLOAD", "true")
    s = s.model_copy(update={"real_history_autoload": True})
    with TestClient(create_app(s)) as c:
        t0 = time.time()
        while c.get("/history").json()["status"].get("state") not in ("ready", "error") and time.time() - t0 < 60:
            time.sleep(0.2)
        h = c.get("/history").json()
        assert h["status"]["state"] == "ready" and h["fresh"] and h["meta"]["signals"] == 4
        assert h["event_from"].startswith("2026-10-03T15:00") and h["event_to"].startswith("2026-10-04T21:00")
        as_of = (T0 + timedelta(hours=6)).isoformat()
        assert len(c.get("/signals", params={"as_of": as_of, "limit": 100}).json()) == 3
        ov = c.get("/overview", params={"as_of": as_of, "hours": 24}).json()
        assert ov["current"]["signals"] == 3 and ov["previous"]["signals"] == 0
        assert ov["current"]["social_pct"] == round(100 / 3, 1)
        wl = c.get("/watchlist", params={"as_of": as_of}).json()
        assert wl["signals_in_window"] >= 1  # Tata Motors / HDFC are held issuers
        later = c.get("/watchlist", params={"as_of": (T0 + timedelta(hours=40)).isoformat(), "hours": 6}).json()
        assert later["signals_in_window"] == 0  # window is relative to as_of
        assert c.post("/demo/reset").status_code == 200 and len(c.get("/signals", params={"limit": 100}).json()) == 4
