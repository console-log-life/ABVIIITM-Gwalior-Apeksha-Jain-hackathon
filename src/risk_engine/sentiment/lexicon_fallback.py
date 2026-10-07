"""Lexicon sentiment fallback (used when FinBERT cannot load, or SENTIMENT_BACKEND=lexicon).

Small curated finance lexicon with negation handling: a negator ("not", "no", "never", "fails to", ...)
within 3 tokens before a sentiment term flips its polarity. Confidence is capped at 0.5 so downstream impact
scoring (Q factor) treats lexicon output as low-confidence.
"""

from __future__ import annotations

import re

MODEL_NAME = "lexicon-fallback"
CONFIDENCE_CAP = 0.5
NEGATION_WINDOW = 3

POSITIVE: dict[str, float] = {
    "beat": 1.5, "beats": 1.5, "surge": 1.5, "surges": 1.5, "soar": 1.5, "soars": 1.5, "jump": 1.2, "jumps": 1.2,
    "rally": 1.2, "rallies": 1.2, "gain": 1.0, "gains": 1.0, "rise": 0.8, "rises": 0.8, "climb": 0.8,
    "climbs": 0.8, "record high": 1.5, "upgrade": 1.5, "upgrades": 1.5, "upgraded": 1.5, "outperform": 1.2,
    "growth": 0.8, "profit": 0.6, "profits": 0.6, "strong": 1.0, "robust": 1.0, "boost": 1.0, "boosts": 1.0,
    "expands": 0.8, "expansion": 0.8, "wins": 1.0, "win": 0.8, "approval": 1.0, "approved": 1.0,
    "recovery": 1.0, "rebound": 1.0, "rebounds": 1.0, "optimism": 1.0, "bullish": 1.5, "buy": 0.6,
    "dividend hike": 1.5, "buyback": 1.0, "exceeds": 1.2, "tops": 1.0, "raises guidance": 2.0,
    "raises forecast": 2.0, "positive": 0.8, "improves": 0.8, "improved": 0.8, "launch": 0.4, "unveils": 0.4,
}

NEGATIVE: dict[str, float] = {
    "miss": 1.5, "misses": 1.5, "missed": 1.5, "plunge": 2.0, "plunges": 2.0, "plummet": 2.0, "plummets": 2.0,
    "crash": 2.0, "crashes": 2.0, "tumble": 1.5, "tumbles": 1.5, "slump": 1.5, "slumps": 1.5, "fall": 1.0,
    "falls": 1.0, "drop": 1.0, "drops": 1.0, "decline": 1.0, "declines": 1.0, "slide": 1.0, "slides": 1.0,
    "loss": 1.2, "losses": 1.2, "downgrade": 2.0, "downgrades": 2.0, "downgraded": 2.0, "default": 2.5,
    "defaults": 2.5, "bankruptcy": 2.5, "bankrupt": 2.5, "insolvency": 2.5, "fraud": 2.5, "probe": 1.5,
    "investigation": 1.5, "lawsuit": 1.5, "sued": 1.5, "fined": 1.5, "penalty": 1.5,
    "recall": 1.2, "layoffs": 1.5, "lays off": 1.5, "job cuts": 1.5, "warning": 1.2, "warns": 1.2,
    "weak": 1.0, "weaker": 1.0, "slowdown": 1.2, "recession": 2.0, "crisis": 2.0, "collapse": 2.5,
    "war": 2.0, "invasion": 2.5, "sanctions": 1.5, "tariffs": 1.0, "selloff": 1.5, "sell-off": 1.5,
    "bearish": 1.5, "risk": 0.6, "risks": 0.6, "concern": 0.8, "concerns": 0.8, "fears": 1.0, "uncertainty": 0.8,
    "cuts guidance": 2.0, "cuts forecast": 2.0, "halts": 1.5, "halt": 1.2, "shortage": 1.2, "disruption": 1.2,
    "volatile": 0.8, "negative": 0.8, "worst": 1.5, "lowest": 1.0, "52-week low": 1.5, "resigns": 1.0,
}

NEGATORS = ("not", "no", "never", "without", "neither", "nor", "isn't", "wasn't", "aren't", "don't",
            "doesn't", "didn't", "won't", "cannot", "can't", "fails to", "failed to", "fail to")

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _phrase_positions(tokens: list[str], phrase: str) -> list[int]:
    parts = phrase.split()
    n = len(parts)
    return [i for i in range(len(tokens) - n + 1) if tokens[i : i + n] == parts]


def _negated(tokens: list[str], idx: int) -> bool:
    window = tokens[max(0, idx - NEGATION_WINDOW) : idx]
    joined = " ".join(window)
    return any((neg in window) if " " not in neg else (neg in joined) for neg in NEGATORS)


def lexicon_probs(text: str) -> dict[str, float]:
    """Return {'positive','negative','neutral'} probabilities consistent with s = P(pos) - P(neg)."""
    toks = _tokens(text)
    pos_mass = neg_mass = 0.0
    used: set[int] = set()
    # longer phrases first so "raises guidance" wins over nothing / "cuts guidance" over "cuts"
    for lex, sign in ((POSITIVE, 1), (NEGATIVE, -1)):
        for phrase in sorted(lex, key=lambda p: -len(p.split())):
            for i in _phrase_positions(toks, phrase):
                span = set(range(i, i + len(phrase.split())))
                if span & used:
                    continue
                used |= span
                polarity = -sign if _negated(toks, i) else sign
                if polarity > 0:
                    pos_mass += lex[phrase]
                else:
                    neg_mass += lex[phrase]
    s = (pos_mass - neg_mass) / (pos_mass + neg_mass + 1.0)
    s = max(-1.0, min(1.0, s))
    p_pos, p_neg = max(s, 0.0), max(-s, 0.0)
    return {"positive": p_pos, "negative": p_neg, "neutral": 1.0 - p_pos - p_neg}
