"""Learned event classifier (fine-tuned distilroberta from src/notebooks/train_models.ipynb) and the HYBRID decision.

The model's labels are mapped to our taxonomy with `risk_engine_labels.json` (written by the notebook): either our
classes directly, or the 20 public topics, whose probabilities are summed per mapped class.

Hybrid decision (thresholds in config, documented in docs/methodology.md):
  1. the rules found Credit Event, Supply Chain or Litigation with a rule score >= EVENT_RULES_AUTHORITATIVE_MIN_SCORE
     -> the rules win (no clean public labels exist for these classes);
  2. else the model's top class if its probability >= EVENT_MODEL_MIN_CONFIDENCE -> the model wins;
  3. else the rules.
Rule evidence and intensifiers are always computed, so explainability shows both the model probabilities and the
evidence phrases. The stress triggers still count rule evidence, so a model-only call cannot start systemic stress.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path

from app.config import Settings
from risk_engine.event_classifier.rules import EventResult, RuleEventClassifier
from risk_engine.logging_setup import get_logger
from risk_engine.model_paths import finetuned_dir, quantize_int8, read_labels
from risk_engine.schemas import EVENT_TYPES

log = get_logger(__name__)
MAX_TOKENS = 64  # trained with max_len 64 (headline/tweet length)


class LearnedEventModel:
    def __init__(self, model_dir: Path, settings: Settings):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(settings.torch_threads)
        self._torch = torch
        self.path = str(model_dir)
        self.tok = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(model_dir), local_files_only=True, low_cpu_mem_usage=True).eval()
        self.quantized = bool(settings.model_quantize_int8)
        if self.quantized:
            self.model = quantize_int8(self.model)
        self.meta = read_labels(model_dir)
        id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        to_ours = self.meta.get("to_ours") or {v: v for v in id2label.values()}
        self.index_to_class = [to_ours.get(id2label[i]) for i in range(len(id2label))]
        bad = sorted({c for c in self.index_to_class if c not in EVENT_TYPES}, key=str)
        if bad:
            raise ValueError(f"event model labels do not map to our taxonomy: {bad}")
        self.classes = sorted(set(self.index_to_class))
        self._lock = threading.Lock()

    def predict_many(self, texts: list[str]) -> list[dict[str, float]]:
        out = []
        with self._lock, self._torch.no_grad():
            for i in range(0, len(texts), 16):
                enc = self.tok(texts[i:i + 16], return_tensors="pt", truncation=True, max_length=MAX_TOKENS,
                               padding=True)
                for row in self._torch.softmax(self.model(**enc).logits, dim=-1).tolist():
                    probs = dict.fromkeys(self.classes, 0.0)
                    for j, p in enumerate(row):
                        probs[self.index_to_class[j]] += p
                    out.append(probs)
        return out

    def predict(self, text: str) -> dict[str, float]:
        return self.predict_many([text])[0]


def decide(r: EventResult, probs: dict[str, float], settings: Settings) -> EventResult:
    """Combine a rule result with model class probabilities (see module docstring)."""
    top = max(probs, key=lambda c: (probs[c], -EVENT_TYPES.index(c)))
    conf = probs[top]
    rule_score = r.scores.get(r.primary, 0.0)
    if r.primary in settings.event_rules_authoritative and rule_score >= settings.event_rules_authoritative_min_score:
        primary, how = r.primary, "hybrid:rules-authoritative"
    elif conf >= settings.event_model_min_confidence:
        primary, how = top, "hybrid:model"
    else:
        primary, how = r.primary, "hybrid:rules"
    if primary == r.primary:
        secondary = r.secondary
    else:
        secondary = r.primary if r.primary not in ("Other", primary) else None
    ev = r.evidence_by_class
    evidence = list(dict.fromkeys(ev.get(primary, []) + (ev.get(secondary, []) if secondary else [])))
    return dataclasses.replace(r, primary=primary, secondary=secondary, evidence=evidence, method=how,
                               model_probs={c: round(p, 4) for c, p in sorted(probs.items(), key=lambda x: -x[1])},
                               model_label=top, model_confidence=round(conf, 4))


class HybridEventClassifier:
    """Drop-in for RuleEventClassifier (same classify() result type; other attributes come from the rules)."""

    def __init__(self, rules: RuleEventClassifier, model: LearnedEventModel, settings: Settings):
        self.rules, self.model, self.settings = rules, model, settings

    def __getattr__(self, name):  # patterns, market_min_patterns, class_evidence_count, ... (used by the triggers)
        return getattr(self.rules, name)

    def classify(self, text: str) -> EventResult:
        return decide(self.rules.classify(text), self.model.predict(text), self.settings)


_CACHE: dict[tuple, LearnedEventModel | None] = {}
_ERRORS: dict[tuple, str] = {}
_LOCK = threading.Lock()


def load_event_model(settings: Settings) -> LearnedEventModel | None:
    """Process-wide singleton. None when no fine-tuned folder exists or it fails to load (logged, see status)."""
    d = finetuned_dir(settings.model_event_path, settings)
    key = (str(d), settings.model_quantize_int8)
    with _LOCK:
        if key not in _CACHE:
            if d is None:
                _CACHE[key] = None
            else:
                t0 = time.perf_counter()
                try:
                    _CACHE[key] = LearnedEventModel(d, settings)
                    log.info("event model %s ready in %.1f s", d, time.perf_counter() - t0)
                except Exception as exc:
                    _CACHE[key] = None
                    _ERRORS[key] = f"{type(exc).__name__}: {exc}"[:300]
                    log.warning("event model at %s could not be loaded, rules only: %s", d, _ERRORS[key])
        return _CACHE[key]


def event_status(settings: Settings) -> dict:
    d = finetuned_dir(settings.model_event_path, settings)
    key = (str(d), settings.model_quantize_int8)
    m = _CACHE.get(key)
    return {"backend": "hybrid" if m else "rules", "model": m.path if m else None,
            "label_space": (m.meta.get("label_space") if m else None), "quantized_int8": m.quantized if m else False,
            "error": _ERRORS.get(key), "configured_path": settings.model_event_path or None}
