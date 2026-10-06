"""Credit brief: builds for EVERY held issuer (JSON, HTML, PDF), template text from data, PDF-safe text."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from portfolio.credit_brief import _latin, file_name, summary_lines
from portfolio.loader import default_portfolio


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("brief")
    s = Settings(_env_file=None, db_path=tmp / "b.db", sentiment_backend="lexicon", log_dir=tmp / "logs",
                 real_history_autoload=False, real_history_path=tmp / "hist.db")
    with TestClient(create_app(s, warm=False)) as c:
        c.post("/analyze", json={"text": "Moody's downgrades Tata Motors to junk as SEBI opens fraud probe",
                                 "ticker": "TATAMOTORS.NS"})
        c.post("/portfolio/stress-test", json={"scenario": "geopolitical_severe"})
        yield c


HELD = sorted(set(default_portfolio().df.query("issuer_id != ''")["issuer_id"]))


@pytest.mark.parametrize("issuer_id", HELD)
def test_brief_builds_for_every_held_issuer(client, issuer_id):
    r = client.get(f"/credit-brief/{issuer_id}")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["issuer_id"] == issuer_id and b["status"] in ("WATCH-NEGATIVE", "MONITOR", "STABLE")
    assert b["exposure"]["direct"] >= 0 and b["stress"]["positions"] and b["summary"]
    assert b["file_name"].startswith("credit_brief_") and b["file_name"].endswith(".pdf")
    assert b["disclaimer"] and "not a credit rating" in b["note"]
    html = client.get(f"/credit-brief/{issuer_id}", params={"format": "html"})
    assert html.status_code == 200 and b["issuer_name"].split()[0] in html.text
    pdf = client.get(f"/credit-brief/{issuer_id}", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert pdf.headers["content-disposition"].endswith(f'filename="{b["file_name"]}"')


def test_tata_brief_content(client):
    b = client.get("/credit-brief/IN-TATAMOTORS").json()
    assert b["file_name"].startswith("credit_brief_TATAMOTORS_NS_")
    assert b["signals"] and b["signals"][0]["reason"]
    assert b["hedges"]["cds_protection_notional"] > 0 and b["stress"]["issuer_shock"]["hedge_pnl"] > 0
    assert b["stress"]["latest_systemic"]["scenario_label"].startswith("Geopolitical")
    text = " ".join(b["summary"])
    assert "Tata Motors" in text and "CDS hedges offsetting" in text and "rating bucket BB" in text
    assert {c["issuer_id"] for c in b["exposure"]["linked"]} >= {"US-F", "US-TSLA"}


def test_brief_errors_and_helpers(client):
    assert client.get("/credit-brief/XX-NOPE").status_code == 404
    assert client.get("/credit-brief/US-AAPL", params={"format": "docx"}).status_code == 422
    assert _latin("impact ≥ 7 → watch · ₹10 − 2 × 3 “q”") == 'impact >= 7 -> watch | Rs 10 - 2 x 3 "q"'
    assert file_name({"ticker": None, "issuer_id": "SOV-IN", "as_of": "2026-10-06T09:00"}) == \
        "credit_brief_SOV-IN_2026-10-06.pdf"
    b = {"issuer_name": "X", "status": "STABLE", "signals_in_window": 0, "window_hours": 24,
         "as_of": "2026-10-06T09:00", "status_reason": "no signals in the window", "rating_bucket": "A",
         "exposure": {"direct": 1e6, "direct_pct": 0.1, "positions": 1, "propagated": 0, "propagated_pct": 0,
                      "total_pct": 0.1},
         "stress": {"issuer_shock": {"scenario_label": "S", "issuer_pnl": -1e5, "hedge_pnl": 0, "net_pnl": -1e5,
                                     "loss_pct_book": 0.01}, "latest_systemic": None}}
    assert "no CDS protection" in " ".join(summary_lines(b))
