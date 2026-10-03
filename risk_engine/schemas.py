"""Data contracts (spec section 5). These are the only shapes that cross module boundaries."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Source(str, Enum):
    GOOGLE_NEWS = "google_news"
    FINNHUB = "finnhub"
    GDELT = "gdelt"
    STOCKTWITS = "stocktwits"
    REDDIT = "reddit"
    MANUAL = "manual"
    SCENARIO = "scenario"


class SourceType(str, Enum):
    NEWS = "news"
    SOCIAL = "social"


class Provenance(str, Enum):
    LIVE = "LIVE"
    CACHED_REAL = "CACHED_REAL"
    SYNTHETIC = "SYNTHETIC"


class SentimentLabel(str, Enum):
    NEGATIVE = "Negative"
    NEUTRAL = "Neutral"
    POSITIVE = "Positive"


class RiskLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


EventType = Literal[
    "Geopolitical",
    "Macroeconomic",
    "Credit Event",
    "M&A",
    "Product Launch",
    "Regulatory",
    "Earnings",
    "Supply Chain",
    "Litigation",
    "Management",
    "Other",
]
EVENT_TYPES: tuple[str, ...] = EventType.__args__  # type: ignore[attr-defined]

# Default source_type per source; scenario/manual documents declare theirs explicitly.
SOURCE_TYPE_OF: dict[Source, SourceType] = {
    Source.GOOGLE_NEWS: SourceType.NEWS,
    Source.FINNHUB: SourceType.NEWS,
    Source.GDELT: SourceType.NEWS,
    Source.STOCKTWITS: SourceType.SOCIAL,
    Source.REDDIT: SourceType.SOCIAL,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _to_utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def make_doc_id(source: str, url: str | None, title: str) -> str:
    """doc_id = sha1(source + url + title) — stable across runs, used for exact dedup."""
    raw = f"{source}|{url or ''}|{title.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)


class RawDocument(_Strict):
    doc_id: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
    source: Source
    source_type: SourceType
    provenance: Provenance
    captured_at: datetime
    published_at: datetime | None = None
    title: str = Field(min_length=1, max_length=1000)
    text: str = Field(min_length=1)
    url: str | None = None
    publisher: str | None = None
    hint_ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9.\-]{1,12}$")
    user_sentiment_tag: Literal["Bullish", "Bearish"] | None = None
    # Extension (documented): the real source a SCENARIO doc imitates, for its credibility prior.
    imitated_source: Source | None = None

    @field_validator("captured_at", "published_at")
    @classmethod
    def normalise_utc(cls, v: datetime | None) -> datetime | None:
        return _to_utc(v)

    @model_validator(mode="after")
    def _consistency(self) -> RawDocument:
        if self.source == Source.SCENARIO and self.provenance != Provenance.SYNTHETIC:
            raise ValueError("scenario documents must have provenance SYNTHETIC")
        if self.imitated_source is not None and self.source != Source.SCENARIO:
            raise ValueError("imitated_source is only allowed for source='scenario'")
        if self.imitated_source == Source.SCENARIO:
            raise ValueError("imitated_source cannot be 'scenario'")
        return self

    @classmethod
    def build(cls, *, source: Source, title: str, text: str | None = None, url: str | None = None,
              provenance: Provenance, source_type: SourceType | None = None,
              captured_at: datetime | None = None, **kwargs: object) -> RawDocument:
        """Convenience constructor that computes doc_id and default source_type."""
        st = source_type or SOURCE_TYPE_OF.get(source)
        if st is None:
            raise ValueError(f"source_type must be given for source {source.value!r}")
        return cls(
            doc_id=make_doc_id(source.value, url, title),
            source=source,
            source_type=st,
            provenance=provenance,
            captured_at=captured_at or utcnow(),
            title=title,
            text=text or title,
            url=url,
            **kwargs,
        )


class SentimentProbs(_Strict):
    positive: float = Field(ge=0, le=1)
    negative: float = Field(ge=0, le=1)
    neutral: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sums_to_one(self) -> SentimentProbs:
        total = self.positive + self.negative + self.neutral
        if abs(total - 1.0) > 0.02:
            raise ValueError(f"sentiment probabilities must sum to 1 (got {total:.3f})")
        return self


class ImpactFactors(_Strict):
    E: float = Field(ge=0, le=1, description="Event severity")
    M: float = Field(ge=0, le=1, description="Sentiment magnitude")
    X: float = Field(ge=0, le=1, description="Exposure / breadth")
    R: float = Field(ge=0, le=1, description="Source credibility")
    Q: float = Field(ge=0, le=1, description="Confidence shrinkage")


class RiskSignal(_Strict):
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str
    company: str = Field(min_length=1, description="Issuer name, 'MARKET' or 'UNRESOLVED'")
    ticker: str | None = None
    issuer_id: str | None = None
    sector: str | None = None
    country: str | None = None
    source: Source
    source_type: SourceType
    provenance: Provenance
    timestamp: datetime
    text_excerpt: str = Field(max_length=280)
    sentiment_score: float = Field(ge=-1, le=1)
    sentiment_label: SentimentLabel
    sentiment_probs: SentimentProbs
    event_type: EventType
    secondary_event_type: EventType | None = None
    event_evidence: list[str] = Field(default_factory=list)
    impact_score: float = Field(ge=1, le=10)
    impact_factors: ImpactFactors
    risk_level: RiskLevel
    confidence: float = Field(ge=0, le=1)
    corroborating_sources: int = Field(ge=1, description="Distinct sources incl. this one")
    model: Literal["finbert", "lexicon-fallback"]
    reason: str = Field(min_length=1)
    business_implication: str = Field(min_length=1)

    @field_validator("timestamp")
    @classmethod
    def normalise_utc(cls, v: datetime) -> datetime:
        return _to_utc(v)

    @field_validator("sentiment_score", "confidence")
    @classmethod
    def round_3dp(cls, v: float) -> float:
        return round(v, 3)

    @field_validator("impact_score")
    @classmethod
    def round_1dp(cls, v: float) -> float:
        return round(v, 1)

    @model_validator(mode="after")
    def _consistency(self) -> RiskSignal:
        if self.secondary_event_type is not None and self.secondary_event_type == self.event_type:
            raise ValueError("secondary_event_type must differ from event_type")
        if self.company in ("MARKET", "UNRESOLVED") and self.ticker is not None:
            raise ValueError(f"company={self.company} must not carry a ticker")
        return self
