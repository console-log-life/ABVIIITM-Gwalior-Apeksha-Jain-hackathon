import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from risk_engine.schemas import (
    EVENT_TYPES,
    Provenance,
    RawDocument,
    RiskSignal,
    Source,
    SourceType,
    make_doc_id,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_sample_raw_document_validates():
    doc = RawDocument.model_validate(_load("sample_raw_document.json"))
    assert doc.provenance is Provenance.CACHED_REAL
    assert doc.captured_at.tzinfo is not None


def test_sample_risk_signal_validates_and_roundtrips():
    sig = RiskSignal.model_validate(_load("sample_risk_signal.json"))
    again = RiskSignal.model_validate_json(sig.model_dump_json())
    assert again == sig
    assert sig.impact_factors.E == 0.90


def test_taxonomy_is_exact():
    assert EVENT_TYPES == (
        "Geopolitical", "Macroeconomic", "Credit Event", "M&A", "Product Launch", "Regulatory",
        "Earnings", "Supply Chain", "Litigation", "Management", "Other",
    )


def test_build_computes_doc_id_and_source_type():
    doc = RawDocument.build(source=Source.STOCKTWITS, title="$AAPL to the moon", provenance=Provenance.LIVE)
    assert doc.source_type is SourceType.SOCIAL
    assert doc.doc_id == make_doc_id("stocktwits", None, "$AAPL to the moon")
    assert doc.text == doc.title


def test_doc_id_is_deterministic():
    assert make_doc_id("google_news", "u", "t") == make_doc_id("google_news", "u", " t ")


@pytest.mark.parametrize(
    "patch",
    [
        {"sentiment_score": -1.5},
        {"impact_score": 0.5},
        {"impact_score": 10.5},
        {"event_type": "Weather"},
        {"provenance": "MAYBE"},
        {"text_excerpt": "x" * 281},
        {"sentiment_probs": {"positive": 0.5, "negative": 0.5, "neutral": 0.5}},
        {"impact_factors": {"E": 1.2, "M": 0.8, "X": 0.6, "R": 0.85, "Q": 0.94}},
        {"secondary_event_type": "Credit Event"},
        {"company": "MARKET"},  # MARKET with a ticker is inconsistent
        {"unexpected_field": 1},
    ],
)
def test_malformed_signal_rejected(patch):
    data = {**_load("sample_risk_signal.json"), **patch}
    with pytest.raises(ValidationError):
        RiskSignal.model_validate(data)


def test_scenario_doc_must_be_synthetic():
    with pytest.raises(ValidationError):
        RawDocument.build(source=Source.SCENARIO, source_type=SourceType.NEWS, title="t",
                          provenance=Provenance.LIVE, imitated_source=Source.GOOGLE_NEWS)
    ok = RawDocument.build(source=Source.SCENARIO, source_type=SourceType.NEWS, title="t",
                           provenance=Provenance.SYNTHETIC, imitated_source=Source.GOOGLE_NEWS)
    assert ok.imitated_source is Source.GOOGLE_NEWS


def test_empty_title_rejected():
    with pytest.raises(ValidationError):
        RawDocument.build(source=Source.MANUAL, source_type=SourceType.NEWS, title="   ",
                          provenance=Provenance.LIVE)


def test_settings_run_with_zero_keys(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert not s.has_finnhub
    assert s.http_timeout_s <= 10 and s.gdelt_timeout_s <= 20 and s.http_max_retries <= 2
    assert s.transaction_data_path is None


def test_settings_reject_excessive_timeouts():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, http_timeout_s=30)
