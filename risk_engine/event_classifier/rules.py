"""Rule-based event classification (spec 6.3) with evidence phrases and intensifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from risk_engine.logging_setup import get_logger
from risk_engine.schemas import EVENT_TYPES

log = get_logger(__name__)
TAXONOMY_YAML = Path(__file__).with_name("taxonomy.yaml")


def _wrap(p: str, case_sensitive: bool = False) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9])(?:{p})(?![A-Za-z0-9])", 0 if case_sensitive else re.I)


@dataclass
class EventResult:
    primary: str
    secondary: str | None
    evidence: list[str]
    scores: dict[str, float]
    intensifier_adj: float
    intensifier_terms: list[str] = field(default_factory=list)
    method: str = "rules"  # rules | rules+zero-shot


class RuleEventClassifier:
    def __init__(self, path: Path = TAXONOMY_YAML, zero_shot=None):
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        unknown = set(data["classes"]) - set(EVENT_TYPES)
        if unknown:
            raise ValueError(f"taxonomy.yaml has classes outside the spec taxonomy: {unknown}")
        self.order: list[str] = list(data["classes"])  # tie-break priority
        self.secondary_ratio = float(data.get("secondary_ratio", 0.6))
        self.patterns = {c: [(_wrap(i["p"]), float(i["w"])) for i in items] for c, items in data["classes"].items()}
        ints = data.get("intensifiers", {})
        self.int_clip = tuple(ints.get("clip", [-0.2, 0.25]))
        self.intensifiers = [(_wrap(i["p"], i.get("case_sensitive", False)), float(i["adj"]))
                             for i in (ints.get("up", []) + ints.get("down", []))]
        self.zero_shot = zero_shot

    def classify(self, text: str) -> EventResult:
        scores: dict[str, float] = {c: 0.0 for c in self.order}
        evidence_by_class: dict[str, list[str]] = {c: [] for c in self.order}
        for cls, pats in self.patterns.items():
            for rx, w in pats:
                m = rx.search(text)
                if m:
                    scores[cls] += w
                    evidence_by_class[cls].append(m.group(0).lower())

        ranked = sorted(self.order, key=lambda c: (-scores[c], self.order.index(c)))
        top = scores[ranked[0]]
        method = "rules"
        if top == 0:
            primary = "Other"
        else:
            primary = ranked[0]
            tied = [c for c in ranked if scores[c] == top]
            if len(tied) > 1 and self.zero_shot is not None:
                picked = self.zero_shot.pick(text, tied)
                if picked:
                    primary, method = picked, "rules+zero-shot"
        if top == 0 and self.zero_shot is not None:
            picked = self.zero_shot.pick(text, [c for c in EVENT_TYPES if c != "Other"], min_score=0.5)
            if picked:
                primary, method = picked, "zero-shot"

        secondary = None
        if primary != "Other" and scores.get(primary, 0) > 0:
            rest = [c for c in ranked if c != primary and scores[c] > 0]
            if rest and scores[rest[0]] >= self.secondary_ratio * scores[primary]:
                secondary = rest[0]

        evidence = list(dict.fromkeys(evidence_by_class.get(primary, []) +
                                      (evidence_by_class.get(secondary, []) if secondary else [])))
        adj, terms = 0.0, []
        for rx, a in self.intensifiers:
            m = rx.search(text)
            if m:
                adj += a
                terms.append(m.group(0))
        adj = max(self.int_clip[0], min(self.int_clip[1], adj))
        scores_out = {c: s for c, s in scores.items() if s > 0}
        return EventResult(primary, secondary, evidence, scores_out, round(adj, 3), terms, method)


@lru_cache(maxsize=1)
def get_event_classifier() -> RuleEventClassifier:
    zs = None
    if get_settings().enable_zero_shot:
        from risk_engine.event_classifier.zero_shot import get_zero_shot

        zs = get_zero_shot()
    return RuleEventClassifier(zero_shot=zs)
