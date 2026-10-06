"""Early-warning watchlist: status rules, aggregation/ranking, GET /watchlist, and the demo-story guarantee."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, Settings
from app.main import create_app
from portfolio.loader import Portfolio, default_portfolio, issuer_exposures
from portfolio.watchlist import MONITOR, STABLE, WATCH, WatchRules, build_watchlist, watch_status
from risk_engine.ingestion.scenario import load_opening, load_scenario, run_scenario, step_to_document
from risk_engine.schemas import Provenance, RawDocument, Source

RULES = WatchRules()  # defaults = config defaults
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def sig(impact: float, sentiment: float, issuer: str | None = "IN-TATAMOTORS", minutes_ago: int = 10,
        event: str = "Credit Event", source: str = "google_news", n: int = 0, corr: int = 1) -> dict:
    return {"signal_id": f"s-{issuer}-{impact}-{sentiment}-{minutes_ago}-{n}", "issuer_id": issuer,
            "ticker": "TATAMOTORS.NS" if issuer == "IN-TATAMOTORS" else None,
            "timestamp": (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z"),
            "impact_score": impact, "risk_level": "High", "sentiment_score": sentiment, "event_type": event,
            "reason": f"reason {impact}", "text_excerpt": "x", "provenance": "SYNTHETIC", "source": source,
            "corroborating_sources": corr}


# ---------------------------------------------------------------- status rules

@pytest.mark.parametrize("signals, expected", [
    ([], STABLE),
    ([sig(7.0, -0.25)], WATCH),                      # both boundaries are inclusive
    ([sig(9.5, -0.24)], STABLE),                     # strong but not negative enough → not even MONITOR
    ([sig(6.9, -0.9)], MONITOR),                     # just below the WATCH impact
    ([sig(5.0, -0.5), sig(5.2, -0.3, n=1)], WATCH),  # two negative signals >= 5
    ([sig(5.0, -0.5), sig(4.9, -0.3, n=1)], MONITOR),  # only one of them >= 5
    ([sig(4.0, -0.3)], MONITOR),
    ([sig(3.9, -0.9)], STABLE),
    ([sig(9.0, 0.8)], STABLE),                       # strong POSITIVE news is not an early warning
])
def test_watch_status_rules(signals, expected):
    assert watch_status(signals, RULES)[0] == expected


def test_watch_status_reason_names_the_rule():
    status, why = watch_status([sig(8.7, -0.903)], RULES)
    assert status == WATCH and "8.7" in why and ">= 7" in why
    assert "2 negative signals" in watch_status([sig(5.5, -0.5), sig(6.0, -0.4, n=1)], RULES)[1]


def test_rules_come_from_settings():
    s = Settings(_env_file=None, watchlist_watch_impact=9.0, watchlist_monitor_impact=8.0)
    rules = WatchRules.from_settings(s)
    assert watch_status([sig(8.5, -0.9)], rules)[0] == MONITOR
    assert watch_status([sig(8.5, -0.9)], RULES)[0] == WATCH


# ---------------------------------------------------------------- aggregation

def _portfolio() -> Portfolio:
    rows = [
        ("L1", "Loan", "IN-TATAMOTORS", "Tata Motors Ltd.", "BB", 60.0, 60.0, "long"),
        ("C1", "CDS", "IN-TATAMOTORS", "Tata Motors Ltd.", "BB", 10.0, 0.0, "protection_bought"),
        ("B1", "Bond", "US-AAPL", "Apple Inc.", "AAAA", 30.0, 30.0, "long"),
        ("E1", "Equity", "US-NVDA", "Nvidia Corp.", "A", 10.0, 10.0, "long"),
        ("I1", "IRS", "", "", "AAA-AA", 50.0, 0.0, "pay_fixed"),
    ]
    df = pd.DataFrame([{"asset_id": a, "asset_type": t, "issuer_id": i, "issuer_name": n, "sector": "S",
                        "country": "IN", "rating_bucket": r if r != "AAAA" else "AAA-AA", "notional": no,
                        "market_value": mv, "side": side} for a, t, i, n, r, no, mv, side in rows])
    return Portfolio(df, "SYNTHETIC (test)", "SYNTHETIC", "test")


def test_build_watchlist_ranks_and_aggregates():
    sigs = [sig(8.7, -0.9, minutes_ago=5, corr=2), sig(4.0, -0.1, minutes_ago=60, event="Earnings", source="reddit"),
            sig(6.0, 0.5, minutes_ago=30, event="Earnings"), sig(4.5, -0.6, issuer="US-NVDA"),
            sig(9.9, -0.99, issuer="US-UNHELD"), sig(9.9, -0.99, issuer=None)]
    w = build_watchlist(_portfolio(), sigs, RULES, 24, NOW)
    assert [r["issuer_id"] for r in w["issuers"]] == ["IN-TATAMOTORS", "US-NVDA", "US-AAPL"]  # only held issuers
    assert w["counts"] == {WATCH: 1, MONITOR: 1, STABLE: 1} and w["signals_in_window"] == 4
    tata = w["issuers"][0]
    assert tata["rank"] == 1 and tata["status"] == WATCH
    assert tata["signal_count"] == 3 and tata["negative_count"] == 1 and tata["worst_impact"] == 8.7
    assert tata["mean_sentiment"] == round((-0.9 - 0.1 + 0.5) / 3, 3)
    assert tata["event_types"] == {"Earnings": 2, "Credit Event": 1}
    assert tata["sources"] == ["google_news", "reddit"] and tata["max_corroborating_sources"] == 2
    assert tata["exposure_mv"] == 60.0 and tata["exposure_pct"] == 60.0  # funded book = 60 + 30 + 10
    assert tata["rating_bucket"] == "BB" and tata["cds_protection_notional"] == 10.0
    assert [t["impact_score"] for t in tata["top_signals"]] == [8.7, 6.0, 4.0]
    assert all(t["reason"] for t in tata["top_signals"])
    assert [p["impact_score"] for p in tata["impact_series"]] == [4.0, 6.0, 8.7]  # oldest first (sparkline)
    apple = w["issuers"][2]
    assert apple["status"] == STABLE and apple["signal_count"] == 0 and apple["mean_sentiment"] is None


# ---------------------------------------------------------------- endpoint

@pytest.fixture
def client(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "w.db", cache_dir=tmp_path / "cache", sentiment_backend="lexicon",
                 app_mode="SCENARIO", log_dir=tmp_path / "logs")
    with TestClient(create_app(s)) as c:
        yield c


def test_watchlist_endpoint_covers_every_held_issuer(client):
    held = set(issuer_exposures(default_portfolio())) | set(
        default_portfolio().df.loc[default_portfolio().df["issuer_id"] != "", "issuer_id"])
    w = client.get("/watchlist").json()
    assert w["window_hours"] == 24 and {r["issuer_id"] for r in w["issuers"]} == held
    assert all(r["status"] == STABLE and r["signal_count"] == 0 for r in w["issuers"])
    assert w["portfolio_source"].startswith("SYNTHETIC") and "not a credit rating" in w["note"]
    assert abs(sum(r["exposure_pct"] for r in w["issuers"]) - 100) < 0.5


def test_watchlist_endpoint_status_window_and_click_through(client):
    a = client.post("/analyze", json={"text": "Moody's downgrades Tata Motors to junk as SEBI opens fraud probe",
                                      "ticker": "TATAMOTORS.NS"}).json()
    b = client.post("/analyze", json={"text": "Tata Motors faces default fears after rating cut",
                                      "ticker": "TATAMOTORS.NS"}).json()
    tata = next(r for r in client.get("/watchlist").json()["issuers"] if r["issuer_id"] == "IN-TATAMOTORS")
    assert tata["signal_count"] == 2 and {t["signal_id"] for t in tata["top_signals"]} == {a["signal_id"],
                                                                                            b["signal_id"]}
    assert tata["status"] == watch_status([a, b], RULES)[0]  # endpoint applies exactly the configured rules
    # time machine: as of one hour ago nothing was known yet (window = known/capture time)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    then = next(r for r in client.get("/watchlist", params={"as_of": past}).json()["issuers"]
                if r["issuer_id"] == "IN-TATAMOTORS")
    assert then["signal_count"] == 0 and then["status"] == STABLE
    assert client.get(f"/signals/by-id/{a['signal_id']}").json()["reason"] == a["reason"]
    assert client.get("/signals/by-id/nope").status_code == 404


@pytest.mark.parametrize("hours", [0, 721, "x"])
def test_watchlist_rejects_bad_window(client, hours):
    assert client.get("/watchlist", params={"hours": hours}).status_code == 422


# ---------------------------------------------------------------- demo story: real opening + hold

SAMPLE = PROJECT_ROOT / "data" / "cache" / "sample" / "sample_google_news.jsonl"


def test_demo_story_real_opening_uses_published_cached_real_sample():
    sc = load_scenario(PROJECT_ROOT / "data" / "scenarios" / "demo_story.json")
    assert sc.real_opening is not None and 3 <= len(sc.real_opening.doc_ids) <= 5
    docs = load_opening(sc.real_opening, PROJECT_ROOT)
    assert [d.doc_id for d in docs] == sc.real_opening.doc_ids  # every listed id exists in the committed sample
    assert all(d.provenance is Provenance.CACHED_REAL and d.captured_at for d in docs)
    assert sc.steps[1].hold_after_s >= 20 and "Tata Motors" in sc.steps[1].title


async def test_run_scenario_emits_real_opening_first_and_skips_missing(tmp_path: Path):
    real = RawDocument.build(source=Source.GOOGLE_NEWS, title="Real headline", url="u/1",
                             provenance=Provenance.CACHED_REAL, captured_at="2026-10-03T17:22:21Z")
    (tmp_path / "s.jsonl").write_text(real.model_dump_json() + "\n", encoding="utf-8")
    story = tmp_path / "story.json"
    story.write_text(json.dumps({"name": "t", "real_opening": {"path": "s.jsonl", "doc_ids": [real.doc_id, "missing"]},
                                 "steps": [{"imitates": "google_news", "title": "Synthetic one"}]}), encoding="utf-8")
    seen: list[RawDocument] = []

    async def sink(docs):
        seen.extend(docs)

    assert await run_scenario(story, sink, step_seconds=0, root=tmp_path) == 2
    assert [d.provenance for d in seen] == [Provenance.CACHED_REAL, Provenance.SYNTHETIC]
    assert seen[0].doc_id == real.doc_id and seen[0].source is Source.GOOGLE_NEWS  # replayed unchanged


@pytest.mark.model
def test_demo_story_step2_puts_tata_motors_on_watch(finbert_engine, settings):
    """With the REAL model: after story steps 1-2, Tata Motors is WATCH-NEGATIVE and ranked first."""
    from risk_engine.impact_scoring.corroboration import CorroborationTracker
    from risk_engine.impact_scoring.scorer import ImpactScorer
    from risk_engine.pipeline import RiskPipeline

    port = default_portfolio()
    p = RiskPipeline(sentiment=finbert_engine, scorer=ImpactScorer(exposures=issuer_exposures(port)),
                     corroboration=CorroborationTracker(6), settings=settings)
    sc = load_scenario(PROJECT_ROOT / "data" / "scenarios" / "demo_story.json")
    rows = [p.process(step_to_document(st, sc.name, i)).model_dump(mode="json") for i, st in enumerate(sc.steps[:2])]
    w = build_watchlist(port, rows, WatchRules.from_settings(settings), 24, datetime.now(UTC))
    top = w["issuers"][0]
    assert top["issuer_id"] == "IN-TATAMOTORS" and top["status"] == WATCH
    assert w["counts"][WATCH] == 1
