"""Optional zero-shot tie-breaker (ENABLE_ZERO_SHOT=false by default).

Only consulted when rule scores tie or are all zero. It is enabled by default ONLY if src/scripts/evaluate.py shows
a macro-F1 gain on the eval set (see docs/evaluation.md). If the model cannot load, it is disabled with a
warning and classification stays purely rule-based.
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.config import Settings, get_settings
from risk_engine.logging_setup import get_logger

log = get_logger(__name__)
HYPOTHESIS = "This financial news is about {}."


class ZeroShotTieBreaker:
    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        os.environ.setdefault("HF_HOME", str(s.models_dir / ".hf_home"))
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

        kw = {"cache_dir": str(s.models_dir), "local_files_only": True}
        tok = AutoTokenizer.from_pretrained(s.zero_shot_model, **kw)
        model = AutoModelForSequenceClassification.from_pretrained(s.zero_shot_model, **kw)
        self.pipe = pipeline("zero-shot-classification", model=model, tokenizer=tok, device=-1)
        self.name = s.zero_shot_model

    def pick(self, text: str, candidates: list[str], min_score: float = 0.0) -> str | None:
        if not candidates:
            return None
        out = self.pipe(text[:1000], candidate_labels=candidates, hypothesis_template=HYPOTHESIS)
        label, score = out["labels"][0], float(out["scores"][0])
        return label if score >= min_score else None


@lru_cache(maxsize=1)
def get_zero_shot() -> ZeroShotTieBreaker | None:
    try:
        return ZeroShotTieBreaker()
    except Exception as exc:
        log.warning("zero-shot model unavailable (run src/scripts/setup_models.py --zero-shot): %s", exc)
        return None
