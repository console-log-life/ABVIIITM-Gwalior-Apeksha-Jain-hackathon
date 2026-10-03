"""Transparent impact score (spec 6.4). All weights/priors/templates come from weights.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

WEIGHTS_YAML = Path(__file__).with_name("weights.yaml")


@dataclass(frozen=True)
class ImpactInput:
    event_type: str
    intensifier_adj: float
    sentiment_score: float
    confidence: float
    entity_kind: str  # ISSUER | EXTERNAL_TICKER | MARKET | UNRESOLVED
    issuer_id: str | None
    company: str
    source: str  # effective source for the credibility prior (imitated source for scenarios)
    corroborating_sources: int
    relation: str | None = None


@dataclass(frozen=True)
class ImpactResult:
    score: float
    factors: dict[str, float]  # E, M, X, R, Q
    contributions: dict[str, float]  # w_k * factor_k (before Q and the 1 + 9x mapping)
    risk_level: str
    reason: str
    business_implication: str
    held: bool


class ImpactScorer:
    def __init__(self, path: Path = WEIGHTS_YAML, exposures: dict[str, float] | None = None):
        self.cfg: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.w = self.cfg["weights"]
        self.exposures: dict[str, float] = {}
        self.set_exposures(exposures or {})

    def set_exposures(self, exposures: dict[str, float]) -> None:
        """issuer_id -> gross exposure (any currency unit). Held issuers are those with exposure > 0."""
        self.exposures = {k: float(v) for k, v in exposures.items() if float(v) > 0}
        self._max_exp = max(self.exposures.values(), default=0.0)

    def is_held(self, issuer_id: str | None) -> bool:
        return bool(issuer_id) and issuer_id in self.exposures

    # ---------------------------------------------------------------- factors
    def factor_e(self, event_type: str, adj: float) -> float:
        base = float(self.cfg["event_severity"].get(event_type, self.cfg["event_severity"]["Other"]))
        return min(1.0, max(0.0, base + adj))

    def factor_m(self, s: float) -> float:
        c = self.cfg["sentiment_magnitude"]
        return min(1.0, abs(s) * (c["negative_multiplier"] if s < 0 else c["positive_multiplier"]))

    def factor_x(self, kind: str, issuer_id: str | None) -> float:
        c = self.cfg["exposure"]
        if kind == "MARKET":
            return float(c["market"])
        if kind in ("ISSUER", "EXTERNAL_TICKER"):
            if self.is_held(issuer_id) and self._max_exp > 0:
                return float(c["held_base"]) + float(c["held_scale"]) * self.exposures[issuer_id] / self._max_exp
            return float(c["non_held_resolved"])
        return float(c["unresolved"])

    def factor_r(self, source: str, corroborating: int) -> float:
        c = self.cfg["credibility"]
        prior = float(c["source_prior"].get(source, c["source_prior"]["manual"]))
        return min(float(c["cap"]), prior + float(c["per_corroborating_source"]) * max(0, corroborating - 1))

    def factor_q(self, confidence: float) -> float:
        c = self.cfg["confidence_shrinkage"]
        return float(c["base"]) + float(c["scale"]) * max(0.0, min(1.0, confidence))

    def risk_level(self, score: float) -> str:
        for level, lower in sorted(self.cfg["risk_levels"].items(), key=lambda kv: -kv[1]):
            if score >= lower:
                return level
        return "Low"

    @staticmethod
    def combine(factors: dict[str, float], weights: dict[str, float]) -> float:
        raw = 1 + 9 * factors["Q"] * sum(weights[k] * factors[k] for k in ("E", "M", "X", "R"))
        return round(min(10.0, max(1.0, raw)), 1)

    # ---------------------------------------------------------------- text
    def _phrase(self, key: str, inp: ImpactInput, f: dict[str, float]) -> str:
        p = self.cfg["factor_phrases"]
        if key == "E":
            return p["E"].format(event=inp.event_type, E=f["E"])
        if key == "M":
            return p["M_neg" if inp.sentiment_score < 0 else "M_pos"].format(s=inp.sentiment_score)
        if key == "X":
            if inp.entity_kind == "MARKET":
                return p["X_market"]
            return p["X_held" if self.is_held(inp.issuer_id) else "X_other"].format(company=inp.company)
        n = inp.corroborating_sources
        return p["R"].format(source=inp.source, n=n, plural="" if n == 1 else "s")

    def implication(self, inp: ImpactInput) -> str:
        imp = self.cfg["implications"]
        kind = "market" if inp.entity_kind == "MARKET" else ("held" if self.is_held(inp.issuer_id) else "other")
        by_event = imp.get(inp.event_type, {})
        template = by_event.get(kind) or by_event.get("default") or imp["default"]
        relation = " via its supplier" if inp.relation == "supplier" else ""
        return template.format(company=inp.company, relation=relation)

    # ---------------------------------------------------------------- public
    def score(self, inp: ImpactInput) -> ImpactResult:
        f = {
            "E": self.factor_e(inp.event_type, inp.intensifier_adj),
            "M": self.factor_m(inp.sentiment_score),
            "X": self.factor_x(inp.entity_kind, inp.issuer_id),
            "R": self.factor_r(inp.source, inp.corroborating_sources),
            "Q": self.factor_q(inp.confidence),
        }
        f = {k: round(v, 3) for k, v in f.items()}
        contrib = {k: round(self.w[k] * f[k], 4) for k in ("E", "M", "X", "R")}
        score = self.combine(f, self.w)
        level = self.risk_level(score)
        top2 = sorted(contrib, key=lambda k: -contrib[k])[:2]
        reason = (f"Impact {score} ({level}) driven mainly by {self._phrase(top2[0], inp, f)} "
                  f"and {self._phrase(top2[1], inp, f)}.")
        return ImpactResult(score, f, contrib, level, reason, self.implication(inp), self.is_held(inp.issuer_id))


@lru_cache(maxsize=1)
def get_scorer() -> ImpactScorer:
    return ImpactScorer()
