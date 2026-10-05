"""The ONE NLP pipeline. LIVE, REPLAY, SCENARIO and /analyze all call process() / process_batch().

RawDocument -> clean -> entity resolution -> FinBERT sentiment -> rule event classification
            -> corroboration -> impact score -> RiskSignal

CLI:  python -m risk_engine.pipeline "Moody's downgrades Tata Motors to junk" [--source google_news]
"""

from __future__ import annotations

import argparse
import sys
import threading
from functools import lru_cache

from app.config import Settings, get_settings
from risk_engine.entity_resolution.resolver import EntityResolver, Resolution, get_resolver
from risk_engine.event_classifier.rules import EventResult, RuleEventClassifier, get_event_classifier
from risk_engine.impact_scoring.corroboration import CorroborationTracker
from risk_engine.impact_scoring.scorer import ImpactInput, ImpactScorer
from risk_engine.logging_setup import get_logger
from risk_engine.preprocessing.clean import clean_text, is_english
from risk_engine.schemas import (
    Provenance,
    RawDocument,
    RiskSignal,
    SentimentProbs,
    Source,
    SourceType,
    utcnow,
)
from risk_engine.sentiment.finbert import SentimentEngine, get_sentiment_engine

log = get_logger(__name__)
EXCERPT_CHARS = 280


class DocumentRejected(ValueError):
    """Document cannot be analysed (empty after cleaning, or not English)."""


def _excerpt(doc: RawDocument) -> str:
    body = doc.text if len(doc.text) > len(doc.title) else doc.title
    return body if len(body) <= EXCERPT_CHARS else body[: EXCERPT_CHARS - 1].rstrip() + "…"


def _prepare(doc: RawDocument) -> RawDocument:
    """Idempotent cleaning so manual/API input gets the same treatment as ingested documents."""
    title = clean_text(doc.title)
    text = clean_text(doc.text) or title
    if not title and not text:
        raise DocumentRejected("text is empty after cleaning")
    if not is_english(title if text == title else f"{title}. {text}"):
        raise DocumentRejected("text does not appear to be English")
    return doc.model_copy(update={"title": title or text[:200], "text": text})


def classify_and_resolve(classifier: RuleEventClassifier, resolver: EntityResolver, title: str, text: str | None,
                         hint_ticker: str | None = None) -> tuple[EventResult, Resolution]:
    """Event classification + entity resolution (unresolved + Geopolitical/Macroeconomic -> MARKET).
    Shared by the pipeline and scripts/evaluate.py so the evaluation measures exactly what runs.
    The market evidence rule (>= 2 distinct cues) is applied only by the stress triggers, not here."""
    full = title if not text or text == title else f"{title}. {text}"
    event = classifier.classify(full)
    return event, resolver.resolve(title, text, hint_ticker).finalize(event.primary)


def default_exposures() -> dict[str, float]:
    """issuer_id -> gross exposure from the portfolio (Module B). Empty if no portfolio is available."""
    try:
        from portfolio.loader import issuer_exposures
    except ImportError:
        return {}
    try:
        return issuer_exposures()
    except Exception as exc:  # portfolio file missing/invalid: score without holdings, but say so
        log.warning("portfolio exposures unavailable, X factor treats all issuers as non-held: %s", exc)
        return {}


class RiskPipeline:
    def __init__(self, resolver: EntityResolver | None = None, sentiment: SentimentEngine | None = None,
                 classifier: RuleEventClassifier | None = None, scorer: ImpactScorer | None = None,
                 corroboration: CorroborationTracker | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.resolver = resolver or get_resolver()
        self.sentiment = sentiment or get_sentiment_engine()
        self.classifier = classifier or get_event_classifier()
        self.scorer = scorer or ImpactScorer(exposures=default_exposures())
        self.corroboration = corroboration or CorroborationTracker(self.settings.corroboration_window_h)
        self._lock = threading.Lock()

    def process_batch(self, docs: list[RawDocument], skip_rejected: bool = False) -> list[RiskSignal]:
        """Analyse documents in input order. With skip_rejected, unusable docs are logged and omitted
        (ingestion); otherwise the first DocumentRejected is raised (API input -> HTTP 422)."""
        prepared = []
        for d in docs:
            try:
                prepared.append(_prepare(d))
            except DocumentRejected as exc:
                if not skip_rejected:
                    raise
                log.info("pipeline: skipping %s (%s)", d.doc_id, exc)
        if not prepared:
            return []
        sentiments = self.sentiment.analyze_many([(d.title, d.text) for d in prepared])
        out = []
        with self._lock:  # corroboration order must follow input order
            for doc, sent in zip(prepared, sentiments, strict=True):
                out.append(self._finish(doc, sent))
        return out

    def process(self, doc: RawDocument) -> RiskSignal:
        return self.process_batch([doc])[0]

    def _finish(self, doc: RawDocument, sent) -> RiskSignal:
        event, res = classify_and_resolve(self.classifier, self.resolver, doc.title, doc.text, doc.hint_ticker)
        eff_source = (doc.imitated_source or doc.source).value
        ts = doc.published_at or doc.captured_at
        key = self.corroboration.entity_key(res.kind, res.issuer_id, res.ticker)
        n_sources = self.corroboration.count_and_add(key, event.primary, eff_source, ts, event.evidence)
        impact = self.scorer.score(ImpactInput(
            event_type=event.primary, intensifier_adj=event.intensifier_adj, sentiment_score=sent.score,
            confidence=sent.confidence, entity_kind=res.kind, issuer_id=res.issuer_id, company=res.company,
            source=eff_source, corroborating_sources=n_sources, relation=res.relation,
        ))
        iss = res.issuer
        return RiskSignal(
            doc_id=doc.doc_id, company=res.company, ticker=res.ticker, issuer_id=res.issuer_id,
            sector=iss.sector if iss else None, country=iss.country if iss else None,
            source=doc.source, source_type=doc.source_type, provenance=doc.provenance, timestamp=ts,
            text_excerpt=_excerpt(doc), sentiment_score=sent.score, sentiment_label=sent.label,
            sentiment_probs=SentimentProbs(**sent.probs), event_type=event.primary,
            secondary_event_type=event.secondary, event_evidence=event.evidence, impact_score=impact.score,
            impact_factors=impact.factors, risk_level=impact.risk_level, confidence=sent.confidence,
            corroborating_sources=n_sources, model=sent.model, reason=impact.reason,
            business_implication=impact.business_implication,
        )


@lru_cache(maxsize=1)
def get_pipeline() -> RiskPipeline:
    return RiskPipeline()


def process(doc: RawDocument) -> RiskSignal:
    """Spec entry point: risk_engine.pipeline.process()."""
    return get_pipeline().process(doc)


def process_batch(docs: list[RawDocument]) -> list[RiskSignal]:
    return get_pipeline().process_batch(docs)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Analyse one text and print the RiskSignal JSON")
    ap.add_argument("text")
    ap.add_argument("--source", default="manual", choices=[s.value for s in Source if s is not Source.SCENARIO])
    ap.add_argument("--ticker", default=None, help="optional ticker hint")
    args = ap.parse_args()
    src = Source(args.source)
    doc = RawDocument.build(source=src, title=args.text, provenance=Provenance.SYNTHETIC,
                            source_type=SourceType.NEWS if src is Source.MANUAL else None,
                            captured_at=utcnow(), hint_ticker=args.ticker)
    try:
        sig = process(doc)
    except DocumentRejected as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2
    print(sig.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
