"""Module B: portfolio, pricers (sign conventions), scenarios (sanity band), triggers (cooldown), API slice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import STRESS_DISCLAIMER, Settings
from app.main import create_app
from portfolio.generate_portfolio import generate
from portfolio.loader import FUNDED_TYPES, issuer_exposures, load_portfolio
from portfolio.pricers import (
    Shock,
    price_bond,
    price_cds,
    price_equity,
    price_fx_forward,
    price_irs,
    price_loan,
)
from portfolio.stress_engine import StressEngine, hhi
from portfolio.triggers import TriggerEngine
from risk_engine.schemas import RiskSignal
from tests.conftest import FakeClock

FIX = Path(__file__).parent / "fixtures" / "sample_risk_signal.json"


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture(scope="module")
def engine(settings) -> StressEngine:
    return StressEngine(settings)


# ---------------------------------------------------------------- portfolio

def test_portfolio_is_deterministic_and_well_formed():
    a, b = generate(42), generate(42)
    assert a.equals(b) and 40 <= len(a) <= 60
    gross = a["market_value"].where(a["asset_type"].isin(FUNDED_TYPES), a["notional"])
    mix = gross.groupby(a["asset_type"]).sum() / gross.sum()
    assert mix["Loan"] == pytest.approx(0.40, abs=0.02) and mix["Bond"] == pytest.approx(0.35, abs=0.02)
    assert mix["Equity"] <= 0.10
    held = set(issuer_exposures(load_portfolio(Settings(_env_file=None))))
    cds = a[(a["asset_type"] == "CDS") & (a["side"] == "protection_bought")]
    assert len(cds) >= 2 and set(cds["issuer_id"]) <= held
    assert {"IRS", "CDS", "FXForward", "Loan", "Bond", "Equity"} <= set(a["asset_type"])
    assert "US-WMT" not in held and "US-AAPL" in held


# ---------------------------------------------------------------- pricers (sign conventions)

def test_irs_sign_convention():
    up, down = Shock(rates_bp=100), Shock(rates_bp=-100)
    assert price_irs(5_000, "pay_fixed", up) == pytest.approx(500_000)  # pay-fixed gains when rates rise
    assert price_irs(5_000, "pay_fixed", down) < 0
    assert price_irs(5_000, "receive_fixed", up) == pytest.approx(-500_000)


def test_cds_sign_convention():
    assert price_cds(10e6, 4.5, "protection_bought", Shock(spread_bp=100)) == pytest.approx(450_000)
    assert price_cds(10e6, 4.5, "protection_bought", Shock(spread_bp=-50)) < 0
    assert price_cds(10e6, 4.5, "protection_sold", Shock(spread_bp=100)) == pytest.approx(-450_000)


def test_bond_loan_fx_equity():
    assert price_bond(100e6, 5, 30, 5, Shock(rates_bp=100)) < 0
    assert price_bond(100e6, 5, 30, 0, Shock(spread_bp=100)) == 0  # treasury: no spread shock
    assert price_bond(100e6, 5, 30, 5, Shock(rates_bp=-100)) > 0
    assert price_loan(100e6, 0.4, 0.01, True, 0.25, 100e6, Shock(pd_multiplier=2)) == pytest.approx(-400_000)
    assert price_loan(100e6, 0.4, 0.01, True, 0.25, 100e6, Shock(rates_bp=100)) == 0  # floating: no rate effect
    assert price_loan(100e6, 0.4, 0.01, False, 3, 100e6, Shock(rates_bp=100)) == pytest.approx(-3e6)
    assert price_loan(1e6, 0.5, 0.5, True, 0, 1e6, Shock(pd_multiplier=5)) == pytest.approx(-250_000)  # PD capped at 1
    assert price_fx_forward(10e6, "short", Shock(em_fx_pct=-0.05)) == pytest.approx(500_000)
    assert price_fx_forward(10e6, "long", Shock(em_fx_pct=-0.05)) == pytest.approx(-500_000)
    assert price_equity(10e6, 1.2, "long", Shock(equity_pct=-0.1)) == pytest.approx(-1.2e6)


# ---------------------------------------------------------------- scenarios

@pytest.mark.parametrize("scenario", ["geopolitical_severe", "macro_rate_shock_severe", "systemic_credit_severe"])
def test_severe_scenarios_in_sanity_band(engine, scenario):
    summary, _ = engine.run(scenario)
    assert 0.5 <= summary["loss_pct"] <= 15.0, summary["loss_pct"]


def test_outputs_complete_and_consistent(engine):
    s, positions = engine.run("geopolitical_severe", trigger_signal_id="sig-1", rule="test")
    for key in ("before_value", "after_value", "loss", "loss_pct", "by_asset_class", "by_sector", "by_issuer",
                "by_country", "top_contributors", "hedge_offset", "hhi_sector", "hhi_issuer", "rag", "heatmap"):
        assert key in s
    assert s["after_value"] == pytest.approx(s["before_value"] - s["loss"], abs=1)
    assert s["loss"] == pytest.approx(-sum(p["pnl"] for p in positions), abs=1)
    assert len(s["top_contributors"]) == 10 and s["hedge_offset"] > 0
    assert 0 < s["hhi_sector"] <= 1 and 0 < s["hhi_issuer"] <= 1
    assert s["disclaimer"] == STRESS_DISCLAIMER and s["trigger_signal_id"] == "sig-1"
    assert s["rag"] == ("GREEN" if s["loss_pct"] < 1 else "AMBER" if s["loss_pct"] <= 2 else "RED")


def test_idiosyncratic_only_moves_the_issuer(engine):
    s, positions = engine.run("idiosyncratic_credit", "IN-TATAMOTORS")
    moved = {p["issuer_id"] for p in positions if p["pnl"] != 0}
    assert moved == {"IN-TATAMOTORS"}
    cds = [p for p in positions if p["asset_type"] == "CDS" and p["issuer_id"] == "IN-TATAMOTORS"]
    assert cds and cds[0]["pnl"] > 0 and cds[0]["is_hedge"]
    with pytest.raises(ValueError):
        engine.run("idiosyncratic_credit")
    with pytest.raises(ValueError):
        engine.run("idiosyncratic_credit", "US-WMT")  # not held


def test_custom_shocks_and_unknown_scenario(engine):
    s, _ = engine.run(custom_shocks={"rates_bp": 100})
    assert s["scenario"] == "custom" and s["shocks"]["pd_multiplier"] == 1.0
    with pytest.raises(KeyError):
        engine.run("martian_invasion")


def test_hhi():
    assert hhi({"a": 1}) == 1.0 and hhi({"a": 1, "b": 1}) == 0.5 and hhi({}) == 0.0


# ---------------------------------------------------------------- triggers

def _sig(**kw) -> RiskSignal:
    base = json.loads(FIX.read_text(encoding="utf-8"))
    return RiskSignal.model_validate({**base, **kw})


MARKET = {"company": "MARKET", "ticker": None, "issuer_id": None, "sector": None, "country": None}


@pytest.fixture
def trig(settings):
    clock = FakeClock()
    fam = {"Geopolitical": "geopolitical", "Macroeconomic": "macro_rate_shock", "Credit Event": "systemic_credit"}
    return TriggerEngine(settings, {"US-AAPL", "IN-TATAMOTORS"}, fam, clock), clock


def test_systemic_trigger_severity(trig):
    t, _ = trig
    sev = t.candidates(_sig(**MARKET, event_type="Geopolitical", secondary_event_type=None, impact_score=9.0))
    mod = t.candidates(_sig(**MARKET, event_type="Geopolitical", secondary_event_type=None, impact_score=7.5))
    none = t.candidates(_sig(**MARKET, event_type="Geopolitical", secondary_event_type=None, impact_score=6.9))
    assert [d.scenario for d in sev] == ["geopolitical_severe"]
    assert [d.scenario for d in mod] == ["geopolitical_moderate"]
    assert none == []
    macro = t.candidates(_sig(**MARKET, event_type="Macroeconomic", secondary_event_type=None, impact_score=8.6))
    assert macro[0].scenario == "macro_rate_shock_severe" and "MARKET" in macro[0].rule


def test_corroborated_issuer_credit_event_triggers_both(trig):
    t, _ = trig
    ds = t.candidates(_sig(event_type="Credit Event", impact_score=8.0, corroborating_sources=2))
    assert {d.scenario for d in ds} == {"systemic_credit_moderate", "idiosyncratic_credit"}


def test_idiosyncratic_requires_held_issuer_and_threshold(trig):
    t, _ = trig
    held = t.candidates(_sig(event_type="Regulatory", secondary_event_type=None, impact_score=6.2,
                             corroborating_sources=1))
    assert [(d.scenario, d.scope_issuer_id) for d in held] == [("idiosyncratic_credit", "US-AAPL")]
    low = t.candidates(_sig(event_type="Regulatory", secondary_event_type=None, impact_score=5.9,
                            corroborating_sources=1))
    other = t.candidates(_sig(event_type="Regulatory", secondary_event_type=None, impact_score=7.0,
                              corroborating_sources=1, company="Walmart Inc.", ticker="WMT", issuer_id="US-WMT"))
    earnings = t.candidates(_sig(event_type="Earnings", secondary_event_type=None, impact_score=9.0,
                                 corroborating_sources=1))
    assert low == [] and other == [] and earnings == []


def test_cooldown_suppresses_and_expires(trig):
    t, clock = trig
    sig = _sig(**MARKET, event_type="Geopolitical", secondary_event_type=None, impact_score=9.0)
    assert len(t.evaluate(sig)) == 1
    clock.advance(10 * 60)
    assert t.evaluate(sig) == [] and t.suppressed[0]["suppressed"] is True
    clock.advance(21 * 60)
    assert len(t.evaluate(sig)) == 1
    t.reset()
    assert len(t.evaluate(sig)) == 1 and not t.suppressed


# ---------------------------------------------------------------- API end-to-end slice

@pytest.fixture
def client(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "s.db", cache_dir=tmp_path, sentiment_backend="lexicon",
                 log_dir=tmp_path / "logs")
    with TestClient(create_app(s)) as c:
        yield c


def test_headline_to_signal_to_trigger_to_stress(client):
    sig = client.post("/analyze", json={
        "text": "Russia launches invasion as war escalates; markets plunge on sweeping sanctions"}).json()
    assert sig["company"] == "MARKET" and sig["event_type"] == "Geopolitical" and sig["impact_score"] >= 7
    runs = client.get("/stress-runs").json()["runs"]
    assert len(runs) == 1 and runs[0]["trigger_signal_id"] == sig["signal_id"]
    assert runs[0]["scenario"].startswith("geopolitical_")
    latest = client.get("/portfolio/stress-test").json()
    assert latest["run_id"] == runs[0]["run_id"] and len(latest["positions"]) == 49
    assert latest["disclaimer"] == STRESS_DISCLAIMER and 0.5 <= latest["loss_pct"] <= 15
    assert client.get("/health").json()["bus"]["stress.completed"] == 1
    # same headline again: duplicate -> no new signal, no new run
    again = client.post("/analyze", json={
        "text": "Russia launches invasion as war escalates; markets plunge on sweeping sanctions"})
    assert again.headers["X-Duplicate"] == "true"
    assert len(client.get("/stress-runs").json()["runs"]) == 1


def test_low_impact_headline_does_not_trigger(client):
    client.post("/analyze", json={"text": "Apple unveils new iPhone lineup"})
    assert client.get("/stress-runs").json()["runs"] == []
    assert client.get("/portfolio/stress-test").status_code == 404


def test_portfolio_and_manual_runs(client):
    p = client.get("/portfolio").json()
    assert p["provenance"] == "SYNTHETIC" and p["positions_count"] == 49 and "SYNTHETIC" in p["source"]
    assert "geopolitical_severe" in client.get("/portfolio/scenarios").json()
    r = client.post("/portfolio/stress-test", json={"scenario": "idiosyncratic_credit", "issuer_id": "IN-TATAMOTORS"})
    assert r.status_code == 200 and r.json()["scope_issuer_id"] == "IN-TATAMOTORS"
    c = client.post("/portfolio/stress-test", json={"custom": {"rates_bp": 150, "equity_pct": -0.1}})
    assert c.status_code == 200 and c.json()["scenario"] == "custom"
    assert client.post("/portfolio/stress-test", json={"scenario": "nope"}).status_code == 422
    assert client.post("/portfolio/stress-test", json={}).status_code == 422
    runs = client.get("/stress-runs").json()["runs"]
    assert len(runs) == 2 and all(r["trigger_signal_id"] is None for r in runs)
    one = client.get(f"/stress-runs/{runs[0]['run_id']}").json()
    assert one["run_id"] == runs[0]["run_id"] and one["positions"]
    assert client.post("/demo/reset").json()["stress_runs_deleted"] == 2
