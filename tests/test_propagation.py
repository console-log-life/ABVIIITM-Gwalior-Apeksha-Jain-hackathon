"""Risk propagation: decay maths, no double counting, cycles, curated links valid, watchlist rule, endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from portfolio.loader import default_portfolio
from portfolio.propagation import Link, load_links, propagated_exposure, propagation_monitor, reach
from portfolio.watchlist import MONITOR, STABLE, WATCH, WatchRules, build_watchlist
from risk_engine.entity_resolution.resolver import UNIVERSE_YAML

DECAY = {"supplier_of": 0.5, "parent_of": 0.5, "peer_of": 0.3}
TRIANGLE = (Link("A", "B", "supplier_of"), Link("B", "C", "peer_of"), Link("A", "C", "peer_of"))
EXPOSURE = {"A": 100.0, "B": 200.0, "C": 300.0, "D": 50.0}


def S(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_second_order_decay_math():
    p = propagated_exposure("A", EXPOSURE, 1000.0, S(), TRIANGLE)
    assert p["direct_exposure"] == 100 and p["direct_pct"] == 10.0
    # B via supplier 0.5 x 200 = 100; C via peer 0.3 x 300 = 90
    assert {c["issuer_id"]: c["weighted"] for c in p["contributions"]} == {"B": 100.0, "C": 90.0}
    assert p["propagated_exposure"] == 190.0 and p["propagated_pct"] == 19.0 and p["total_pct"] == 29.0


def test_each_issuer_counted_once_at_its_strongest_path_and_cycles_terminate():
    # with 2 hops, C is reachable directly (0.3) and via B (0.5 x 0.3 = 0.15): counted once, at 0.3
    hits = reach("A", TRIANGLE, DECAY, max_hops=2)
    assert set(hits) == {"B", "C"} and hits["C"]["weight"] == 0.3 and hits["B"]["weight"] == 0.5
    assert "A" not in hits  # the start issuer is never propagated back to itself through the cycle
    p = propagated_exposure("A", EXPOSURE, 1000.0, S(propagation_max_hops=3), TRIANGLE)
    assert p["propagated_exposure"] == 190.0  # identical to 1 hop here: no double counting


def test_multi_hop_multiplies_decays_and_unknown_relations_do_not_propagate():
    chain = (Link("A", "B", "parent_of"), Link("B", "D", "peer_of"), Link("A", "X", "mystery"))
    assert reach("A", chain, DECAY, 1) == {"B": {"weight": 0.5, "path": ["parent_of"], "via": ["B"], "note": ""}}
    two = reach("A", chain, DECAY, 2)
    assert two["D"]["weight"] == pytest.approx(0.15) and two["D"]["path"] == ["parent_of", "peer_of"]
    assert "X" not in two


def test_curated_links_reference_universe_issuers_with_known_relations():
    data = yaml.safe_load(UNIVERSE_YAML.read_text(encoding="utf-8"))
    ids = {i["issuer_id"] for i in data["issuers"]}
    links = load_links()
    assert len(links) >= 15
    for ln in links:
        assert ln.a in ids and ln.b in ids and ln.a != ln.b
        assert ln.relation in DECAY and ln.note
    assert len({frozenset((ln.a, ln.b)) for ln in links}) == len(links)  # no duplicate pairs


def test_propagation_monitor_rule():
    statuses = {"A": WATCH, "B": STABLE, "C": STABLE, "D": STABLE}
    out = propagation_monitor(statuses, S(), TRIANGLE)
    assert set(out) == {"B", "C"} and "linked to A" in out["B"]
    assert set(propagation_monitor(statuses, S(watchlist_propagation_min_weight=0.4), TRIANGLE)) == {"B"}
    assert propagation_monitor(statuses, S(watchlist_propagation_min_weight=0), TRIANGLE) == {}


def tata_signal() -> dict:
    return {"signal_id": "s1", "issuer_id": "IN-TATAMOTORS", "ticker": "TATAMOTORS.NS",
            "timestamp": "2026-10-06T08:00:00Z", "impact_score": 8.7, "risk_level": "Critical",
            "sentiment_score": -0.9, "event_type": "Credit Event", "reason": "r", "text_excerpt": "x",
            "provenance": "SYNTHETIC", "source": "google_news", "corroborating_sources": 1}


def test_watchlist_peers_of_a_watched_issuer_become_monitor_with_propagated_exposure():
    port = default_portfolio()
    w = build_watchlist(port, [tata_signal()], WatchRules(), 24, datetime(2026, 10, 6, 9, tzinfo=UTC), S())
    rows = {r["issuer_id"]: r for r in w["issuers"]}
    assert rows["IN-TATAMOTORS"]["status"] == WATCH
    for peer in ("US-F", "US-TSLA"):  # curated peer_of links of Tata Motors
        assert rows[peer]["status"] == MONITOR and rows[peer]["via_propagation"]
        assert "IN-TATAMOTORS" in rows[peer]["status_reason"]
    assert rows["US-AAPL"]["status"] == STABLE  # not linked
    assert rows["IN-TATAMOTORS"]["propagated_exposure"] > 0
    without = build_watchlist(port, [tata_signal()], WatchRules(), 24, datetime(2026, 10, 6, 9, tzinfo=UTC))
    assert {r["issuer_id"]: r["status"] for r in without["issuers"]}["US-F"] == STABLE  # rule needs settings


@pytest.fixture
def client(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "p.db", sentiment_backend="lexicon", log_dir=tmp_path / "logs")
    with TestClient(create_app(s, warm=False)) as c:
        yield c


def test_propagation_endpoint(client):
    r = client.get("/propagation", params={"issuer_id": "IN-TATAMOTORS"})
    assert r.status_code == 200
    p = r.json()
    assert p["direct_exposure"] > 0 and p["propagated_exposure"] > 0
    assert {c["issuer_id"] for c in p["contributions"]} >= {"US-F", "US-TSLA"}
    kinds = {n["kind"] for n in p["graph"]["nodes"]}
    assert kinds == {"issuer", "sector"} and any(n["positions"] for n in p["graph"]["nodes"] if n["kind"] == "issuer")
    assert any(e["relation"] == "peer_of" for e in p["graph"]["edges"]) and "curated" in p["note"].lower()
    assert client.get("/propagation", params={"issuer_id": "XX-NOPE"}).status_code == 404
