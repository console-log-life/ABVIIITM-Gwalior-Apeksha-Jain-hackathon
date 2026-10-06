"""What-if scenario builder: monotonic responses of the pricers and an endpoint that never saves a run."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from portfolio.stress_engine import StressEngine

BASE = {"rates_bp": 0, "ig_spread_bp": 0, "hy_spread_bp": 0, "equity_pct": 0, "em_fx_pct": 0, "pd_multiplier": 1}


@pytest.fixture(scope="module")
def engine() -> StressEngine:
    return StressEngine(Settings(_env_file=None))


def asset_pnl(engine: StressEngine, **shocks) -> dict[str, float]:
    summary, positions = engine.run(custom_shocks={**BASE, **shocks})
    out: dict[str, float] = {}
    for p in positions:
        key = "CDS_bought" if p["asset_type"] == "CDS" and p["side"] == "protection_bought" else p["asset_type"]
        out[key] = out.get(key, 0.0) + p["pnl"]
    out["total"] = summary["pnl"]
    return out


def test_zero_shock_is_flat(engine):
    assert abs(asset_pnl(engine)["total"]) < 1e-6


@pytest.mark.parametrize("field", ["ig_spread_bp", "hy_spread_bp"])
def test_wider_spreads_hurt_bonds_and_loans_and_help_bought_protection(engine, field):
    steps = [asset_pnl(engine, **{field: bp}) for bp in (0, 50, 150, 300)]
    for a, b in zip(steps, steps[1:], strict=False):
        assert b["Bond"] < a["Bond"]
        assert b["Loan"] <= a["Loan"]  # floating loans move only through spread duration
        assert b["Bond"] + b["Loan"] < a["Bond"] + a["Loan"]
        assert b["CDS_bought"] > a["CDS_bought"]


def test_higher_pd_multiplier_increases_credit_losses(engine):
    lo, hi = asset_pnl(engine, pd_multiplier=1.0), asset_pnl(engine, pd_multiplier=3.0)
    assert hi["Bond"] + hi["Loan"] < lo["Bond"] + lo["Loan"]


def test_rates_up_hurts_bonds_and_equity_down_hurts_equity(engine):
    assert asset_pnl(engine, rates_bp=200)["Bond"] < asset_pnl(engine, rates_bp=50)["Bond"] < 0
    assert asset_pnl(engine, equity_pct=-0.3)["Equity"] < asset_pnl(engine, equity_pct=-0.1)["Equity"] < 0


def test_rag_follows_loss(engine):
    small, _ = engine.run(custom_shocks={**BASE, "ig_spread_bp": 5})
    big, _ = engine.run(custom_shocks={**BASE, "ig_spread_bp": 300, "hy_spread_bp": 900, "equity_pct": -0.4,
                                       "pd_multiplier": 4})
    assert small["rag"] == "GREEN" and big["rag"] == "RED" and big["loss_pct"] > 2


@pytest.fixture
def client(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "w.db", sentiment_backend="lexicon", log_dir=tmp_path / "logs")
    with TestClient(create_app(s, warm=False)) as c:
        yield c


def test_what_if_endpoint_prices_without_saving(client):
    r = client.post("/portfolio/what-if", json={"shocks": {"ig_spread_bp": 100, "hy_spread_bp": 300,
                                                          "equity_pct": -0.1, "pd_multiplier": 1.5}})
    assert r.status_code == 200
    body = r.json()
    assert body["scenario"] == "what_if" and body["loss_pct"] > 0 and body["positions"]
    assert client.get("/stress-runs").json()["runs"] == []  # nothing in the audit log
    assert client.get("/portfolio/stress-test").status_code == 404  # no "latest run" either
    issuer = client.post("/portfolio/what-if", json={"shocks": {"pd_multiplier": 3}, "issuer_id": "IN-TATAMOTORS"})
    assert issuer.status_code == 200 and set(issuer.json()["by_issuer"]) >= {"IN-TATAMOTORS"}
    assert client.post("/portfolio/what-if", json={"shocks": {}, "issuer_id": "XX-NOPE"}).status_code == 422
    assert client.post("/portfolio/what-if", json={"shocks": {"equity_pct": -5}}).status_code == 422
