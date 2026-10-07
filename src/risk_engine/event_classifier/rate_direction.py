"""Policy-rate direction for Macroeconomic signals: "cut", "hike", or None (unclear).

Used by the stress triggers: cuts map to the macro_rate_cut scenario, hikes to the rate-shock scenarios, and an
unclear direction (no rate verb, a hold, or both directions in one text) starts no systemic rate scenario at all.
Rule-based and headline-level, so it has known limits: "little chance of a rate hike" reads as a hike, and
"investors cut bets on rate rises" reads as a hike.
"""

from __future__ import annotations

import re

_RATE = (r"(?:the |its |a |key |policy |benchmark |repo |interest |lending |borrowing |\d+ ?(?:bps?|basis points) )*"
         r"(?:rates?|repo)")
_FLAGS = re.IGNORECASE

CUT = re.compile(
    rf"(?<![A-Za-z])(?:rate cuts?|rate reductions?|cuts? {_RATE}|lower(?:s|ed|ing)? {_RATE}|reduc(?:e|es|ed|ing) "
    rf"{_RATE}|(?:monetary|policy) easing|easing cycle|eas(?:e|es|ed|ing) (?:monetary )?policy|dovish pivot)"
    r"(?![A-Za-z])", _FLAGS)
HIKE = re.compile(
    rf"(?<![A-Za-z])(?:rate (?:hikes?|rises?|increases?)|hik(?:e|es|ed|ing) {_RATE}|rais(?:e|es|ed|ing) {_RATE}|"
    rf"increas(?:e|es|ed|ing) {_RATE}|lift(?:s|ed|ing)? {_RATE}|tighten(?:s|ed|ing)?(?: monetary)?(?: policy)?|"
    r"monetary tightening|hawkish)(?![A-Za-z])", _FLAGS)
HOLD = re.compile(
    rf"(?<![A-Za-z])(?:{_RATE} (?:unchanged|on hold|steady)|(?:keeps|holds|leaves|kept|held) {_RATE}"
    r"(?: unchanged| steady| on hold)?|pause[sd]?)(?![A-Za-z])", _FLAGS)


def rate_direction(text: str) -> str | None:
    """'cut', 'hike' or None. A hold, no rate verb, or both directions -> None (unclear)."""
    cut, hike = bool(CUT.search(text)), bool(HIKE.search(text))
    if cut == hike:  # neither, or contradictory
        return None
    if HOLD.search(text):
        return None
    return "cut" if cut else "hike"
