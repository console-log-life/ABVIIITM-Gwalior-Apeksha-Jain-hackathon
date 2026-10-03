"""Sentiment (spec 6.2): FinBERT with automatic lexicon fallback.

- Model ProsusAI/finbert, loaded once (singleton). Label order is read from model.config.id2label.
- s = P(positive) - P(negative), rounded to 3 dp; confidence = max(probs).
- Long text: title (weight 2) + up to 8 sentences (weight 1); probabilities aggregated with a
  confidence-weighted mean; every segment truncated to 256 tokens. Batched inference.
- If the model cannot load (missing weights, offline without cache, OOM), the engine switches to
  lexicon_fallback (model="lexicon-fallback", confidence capped at 0.5) and status() reports why.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from risk_engine.logging_setup import get_logger
from risk_engine.sentiment import lexicon_fallback

log = get_logger(__name__)
MAX_SENTENCES = 8
MAX_TOKENS = 256
TITLE_WEIGHT = 2.0
BATCH_SIZE = 16
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
REQUIRED_LABELS = {"positive", "negative", "neutral"}


@dataclass(frozen=True)
class SentimentResult:
    score: float
    label: str  # Negative | Neutral | Positive
    probs: dict[str, float]
    confidence: float
    model: str  # finbert | lexicon-fallback


def label_for(score: float, settings: Settings) -> str:
    if score <= settings.sentiment_neg_threshold:
        return "Negative"
    if score >= settings.sentiment_pos_threshold:
        return "Positive"
    return "Neutral"


def map_logits_to_probs(probs_row: list[float], id2label: dict[int, str]) -> dict[str, float]:
    """Map a probability row to named labels using the model's own id2label (never a hard-coded order)."""
    labels = {int(k): str(v).lower() for k, v in id2label.items()}
    if set(labels.values()) != REQUIRED_LABELS:
        raise ValueError(f"unexpected sentiment labels {sorted(labels.values())}")
    return {labels[i]: float(p) for i, p in enumerate(probs_row)}


def segments_for(title: str, text: str | None) -> list[tuple[str, float]]:
    """(segment, weight) pairs: title x2 plus up to 8 body sentences that are not the title itself."""
    segs = [(title.strip(), TITLE_WEIGHT)] if title.strip() else []
    body = (text or "").strip()
    if body and body != title.strip():
        if body.startswith(title.strip()):
            body = body[len(title.strip()):].lstrip(" .:-")
        sentences = [s.strip() for s in _SENT_SPLIT.split(body) if len(s.strip()) > 3]
        segs += [(s, 1.0) for s in sentences[:MAX_SENTENCES]]
    return segs or [(body or title, 1.0)]


def aggregate(prob_rows: list[dict[str, float]], weights: list[float]) -> dict[str, float]:
    """Confidence-weighted mean of probability vectors (weight = segment weight x segment confidence)."""
    eff = [w * max(p.values()) for p, w in zip(prob_rows, weights, strict=True)]
    total = sum(eff) or 1.0
    return {k: sum(p[k] * e for p, e in zip(prob_rows, eff, strict=True)) / total for k in REQUIRED_LABELS}


class _FinBertModel:
    def __init__(self, settings: Settings):
        os.environ.setdefault("HF_HOME", str(settings.models_dir / ".hf_home"))
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        cache = str(settings.models_dir)
        name = settings.finbert_model
        try:  # local first: no network round-trip when weights are already cached
            self.tok = AutoTokenizer.from_pretrained(name, cache_dir=cache, local_files_only=True)
            self.model = AutoModelForSequenceClassification.from_pretrained(name, cache_dir=cache,
                                                                            local_files_only=True)
        except OSError:
            if os.environ.get("HF_HUB_OFFLINE") == "1" or os.environ.get("TRANSFORMERS_OFFLINE") == "1":
                raise
            self.tok = AutoTokenizer.from_pretrained(name, cache_dir=cache)
            self.model = AutoModelForSequenceClassification.from_pretrained(name, cache_dir=cache)
        self.model.eval()
        self.id2label = dict(self.model.config.id2label)
        map_logits_to_probs([0.0] * len(self.id2label), self.id2label)  # validate labels at load time
        self._torch = torch
        self._lock = threading.Lock()

    def predict(self, texts: list[str]) -> list[dict[str, float]]:
        # Batch similar-length segments together (padding to the longest item dominates CPU cost), then restore order.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out: list[dict[str, float] | None] = [None] * len(texts)
        with self._lock, self._torch.no_grad():
            for i in range(0, len(order), BATCH_SIZE):
                idx = order[i : i + BATCH_SIZE]
                enc = self.tok([texts[j] for j in idx], return_tensors="pt", truncation=True,
                               max_length=MAX_TOKENS, padding=True)
                probs = self._torch.softmax(self.model(**enc).logits, dim=-1).tolist()
                for j, row in zip(idx, probs, strict=True):
                    out[j] = map_logits_to_probs(row, self.id2label)
        return out  # type: ignore[return-value]


class SentimentEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.backend = lexicon_fallback.MODEL_NAME
        self.fallback_reason: str | None = None
        self._model: _FinBertModel | None = None
        choice = self.settings.sentiment_backend
        if choice == "lexicon":
            self.fallback_reason = "SENTIMENT_BACKEND=lexicon"
            return
        try:
            self._model = _FinBertModel(self.settings)
            self.backend = "finbert"
            log.info("FinBERT loaded (%s); labels %s", self.settings.finbert_model, self._model.id2label)
        except Exception as exc:
            if choice == "finbert":
                raise
            self.fallback_reason = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("FinBERT unavailable, using lexicon fallback: %s", self.fallback_reason)

    def status(self) -> dict:
        return {"backend": self.backend, "model": self.settings.finbert_model if self._model else None,
                "loaded": self._model is not None, "fallback_reason": self.fallback_reason}

    def _probs(self, texts: list[str]) -> list[dict[str, float]]:
        if self._model is not None:
            return self._model.predict(texts)
        return [lexicon_fallback.lexicon_probs(t) for t in texts]

    def analyze_many(self, items: list[tuple[str, str | None]]) -> list[SentimentResult]:
        seg_lists = [segments_for(t, x) for t, x in items]
        flat = [s for segs in seg_lists for s, _ in segs]
        probs = self._probs(flat) if flat else []
        results, k = [], 0
        for segs in seg_lists:
            rows = probs[k : k + len(segs)]
            k += len(segs)
            agg = aggregate(rows, [w for _, w in segs])
            score = round(agg["positive"] - agg["negative"], 3)
            conf = max(agg.values())
            if self._model is None:
                conf = min(conf, lexicon_fallback.CONFIDENCE_CAP)
            results.append(SentimentResult(
                score=score, label=label_for(score, self.settings),
                probs={k2: round(v, 4) for k2, v in agg.items()}, confidence=round(conf, 3), model=self.backend,
            ))
        return results

    def analyze(self, title: str, text: str | None = None) -> SentimentResult:
        return self.analyze_many([(title, text)])[0]


@lru_cache(maxsize=1)
def get_sentiment_engine() -> SentimentEngine:
    return SentimentEngine()
