"""Corroboration (spec 4): same entity + same primary event from >= 2 DISTINCT sources within a 6 h window.

- Entity key = issuer_id, external ticker, or MARKET. UNRESOLVED signals are never corroborated (too generic).
- MARKET is very broad (any two geopolitical headlines would match), so MARKET observations additionally need
  at least one shared evidence phrase (e.g. both mention "sanctions").
- Scenario documents count as the source they imitate.
- Corroboration is computed when a signal arrives, against earlier observations; earlier signals are not
  rewritten (signals are immutable once published).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Observation:
    entity_key: str
    event_type: str
    source: str
    timestamp: datetime
    evidence: frozenset[str]


class CorroborationTracker:
    def __init__(self, window_hours: float = 6.0, max_items: int = 50_000):
        self.window = timedelta(hours=window_hours)
        self._obs: deque[Observation] = deque(maxlen=max_items)
        self._lock = threading.Lock()

    @staticmethod
    def entity_key(kind: str, issuer_id: str | None, ticker: str | None) -> str | None:
        if kind == "MARKET":
            return "MARKET"
        if kind == "ISSUER" and issuer_id:
            return issuer_id
        if kind == "EXTERNAL_TICKER" and ticker:
            return f"TICKER:{ticker}"
        return None

    def _matches(self, o: Observation, key: str, event: str, ts: datetime, evidence: frozenset[str]) -> bool:
        if o.entity_key != key or o.event_type != event or abs(ts - o.timestamp) > self.window:
            return False
        return key != "MARKET" or bool(o.evidence & evidence)

    def count_and_add(self, key: str | None, event_type: str, source: str, timestamp: datetime,
                      evidence: list[str]) -> int:
        """Return distinct sources (including this one) for this entity+event in the window; then record it."""
        if key is None or event_type == "Other":
            return 1
        ev = frozenset(e.lower() for e in evidence)
        with self._lock:
            sources = {o.source for o in self._obs if self._matches(o, key, event_type, timestamp, ev)}
            sources.add(source)
            self._obs.append(Observation(key, event_type, source, timestamp, ev))
        return len(sources)

    def seed(self, observations: list[Observation]) -> None:
        with self._lock:
            self._obs.extend(observations)

    def clear(self) -> None:
        with self._lock:
            self._obs.clear()
