"""API request/response models and the Swagger examples shown at /docs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import AppMode
from risk_engine.schemas import Provenance, RiskSignal, Source

EXAMPLE_SIGNAL: dict[str, Any] = {
    "signal_id": "0b9d3c55-7f0e-4a51-9a39-5a3f3b1b6c2e",
    "doc_id": "c8a1c0d25b6d0a9e0ca68d28beabd83578dfb237",
    "company": "Tata Motors Ltd.", "ticker": "TATAMOTORS.NS", "issuer_id": "IN-TATAMOTORS",
    "sector": "Consumer Discretionary", "country": "IN", "source": "manual", "source_type": "news",
    "provenance": "SYNTHETIC", "timestamp": "2026-10-03T17:49:30Z",
    "text_excerpt": "Moody's downgrades Tata Motors to junk as SEBI opens probe into accounting",
    "sentiment_score": -0.903, "sentiment_label": "Negative",
    "sentiment_probs": {"positive": 0.0128, "negative": 0.9161, "neutral": 0.0711},
    "event_type": "Credit Event", "secondary_event_type": "Regulatory",
    "event_evidence": ["downgrades", "junk", "moody's", "probe", "sebi"], "impact_score": 7.4,
    "impact_factors": {"E": 0.9, "M": 0.903, "X": 0.3, "R": 0.6, "Q": 0.966}, "risk_level": "High",
    "confidence": 0.916, "corroborating_sources": 1, "model": "finbert",
    "reason": "Impact 7.4 (High) driven mainly by Credit Event severity (E = 0.90) and strongly negative "
              "sentiment (s = -0.90).",
    "business_implication": "Credit stress at a non-held name (Tata Motors Ltd.); monitor for contagion to the "
                            "same sector and rating bucket.",
}


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "source": "manual", "text": "Moody's downgrades Tata Motors to junk as SEBI opens probe into accounting",
        "ticker": "TATAMOTORS.NS",
    }, {
        "source": "google_news", "provenance": "LIVE", "timestamp": "2026-10-03T09:15:00Z",
        "text": "Russia launches invasion as war escalates; markets plunge on sanctions fears",
    }]})

    source: Source = Field(default=Source.MANUAL, description="Origin of the text; 'scenario' is reserved")
    text: str = Field(min_length=1, max_length=20_000, description="Headline or post text (required, non-empty)")
    title: str | None = Field(default=None, max_length=1000, description="Optional headline if text is a body")
    timestamp: datetime | None = Field(default=None, description="Publication time (UTC); defaults to now")
    company: str | None = Field(default=None, max_length=120, description="Optional company-name hint")
    ticker: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.\-]{1,15}$", description="Optional ticker hint")
    provenance: Provenance = Field(default=Provenance.SYNTHETIC,
                                   description="User-supplied text defaults to SYNTHETIC (not fetched from a source)")
    url: str | None = Field(default=None, max_length=2000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be empty or whitespace")
        return v

    @field_validator("source")
    @classmethod
    def _no_scenario(cls, v: Source) -> Source:
        if v is Source.SCENARIO:
            raise ValueError("source 'scenario' is reserved for the scripted demo")
        return v


class AnalyzeBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"items": [
        {"text": "Apple unveils new iPhone lineup", "source": "manual"},
        {"text": "Fed signals two more rate cuts as inflation cools", "source": "manual"},
    ]}]})
    items: list[AnalyzeRequest] = Field(min_length=1, max_length=100)


class SignalView(RiskSignal):
    """RiskSignal plus storage/display fields (capture time for CACHED_REAL badges, URL, title)."""
    seq: int | None = None
    origin: str | None = None
    title: str | None = None
    url: str | None = None
    publisher: str | None = None
    captured_at: datetime | None = None
    imitated_source: str | None = None
    duplicate: bool = False


class TickerSignals(BaseModel):
    ticker: str
    count: int
    mean_sentiment: float | None
    max_impact: float | None
    signals: list[SignalView]


class ModeRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"mode": "SCENARIO"}, {"mode": "LIVE"}]})
    mode: AppMode


class DemoStartRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"mode": "SCENARIO", "step_seconds": 10}, {"mode": "REPLAY", "limit": 60, "step_seconds": 0.5}]})
    mode: AppMode = AppMode.SCENARIO
    step_seconds: float | None = Field(default=None, ge=0, le=120)
    limit: int | None = Field(default=None, ge=1, le=5000, description="REPLAY only: most recent N cached docs")
