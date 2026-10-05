"""Stress triggers (spec 8.4). Thresholds come from config (TRIGGER_* settings).

Systemic:      event in {Geopolitical, Macroeconomic, Credit Event} AND (entity MARKET OR >= 2 corroborating
               sources) AND impact >= 7.0 AND the triggering signal comes from a NEWS source
               (SYSTEMIC_TRIGGER_SOURCES, default google_news/finnhub/gdelt; scenario docs count as the source they
               imitate)  ->  <family>_moderate if impact < 8.5, else <family>_severe.
               Social posts can never trigger systemic stress on their own; they only add corroboration.
Idiosyncratic: event in {Credit Event, Regulatory, Litigation} on a HELD issuer AND impact >= 6.0
               ->  idiosyncratic_credit for that issuer only.
Cooldown:      the same scenario + same scope (issuer or MARKET) is not re-run within TRIGGER_COOLDOWN_MIN minutes;
               suppressed triggers are logged and kept for display.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass

from app.config import Settings
from risk_engine.logging_setup import get_logger
from risk_engine.schemas import RiskSignal

log = get_logger(__name__)
SYSTEMIC_EVENTS = {"Geopolitical", "Macroeconomic", "Credit Event"}
IDIOSYNCRATIC_EVENTS = {"Credit Event", "Regulatory", "Litigation"}


@dataclass(frozen=True)
class TriggerDecision:
    scenario: str
    scope_issuer_id: str | None
    rule: str
    signal_id: str
    kind: str  # systemic | idiosyncratic
    suppressed: bool = False
    suppressed_reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class TriggerEngine:
    def __init__(self, settings: Settings, held_issuers: set[str], systemic_family: dict[str, str],
                 clock: Callable[[], float] = time.time):
        self.s = settings
        self.held = set(held_issuers)
        self.family = systemic_family
        self.clock = clock
        self._last_run: dict[tuple[str, str], float] = {}
        self.suppressed: deque[dict] = deque(maxlen=200)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._last_run.clear()
            self.suppressed.clear()

    def candidates(self, sig: RiskSignal, source: str | None = None) -> list[TriggerDecision]:
        """Pure rule evaluation (no cooldown). `source` = effective source (imitated source for scenario docs)."""
        out: list[TriggerDecision] = []
        s = self.s
        src = source or sig.source.value
        market_wide = sig.company == "MARKET" or sig.corroborating_sources >= 2
        news = src in s.systemic_trigger_sources
        if (sig.event_type in SYSTEMIC_EVENTS and market_wide and news
                and sig.impact_score >= s.trigger_systemic_min_impact):
            severity = "severe" if sig.impact_score >= s.trigger_systemic_severe_impact else "moderate"
            why = "entity MARKET" if sig.company == "MARKET" else f"{sig.corroborating_sources} corroborating sources"
            out.append(TriggerDecision(
                scenario=f"{self.family[sig.event_type]}_{severity}", scope_issuer_id=None, signal_id=sig.signal_id,
                kind="systemic",
                rule=(f"Systemic: {sig.event_type} from news source {src} with {why} and impact {sig.impact_score} >= "
                      f"{s.trigger_systemic_min_impact} → {severity} "
                      f"(severe at >= {s.trigger_systemic_severe_impact})"),
            ))
        if (sig.event_type in IDIOSYNCRATIC_EVENTS and sig.issuer_id in self.held
                and sig.impact_score >= s.trigger_idiosyncratic_min_impact):
            out.append(TriggerDecision(
                scenario="idiosyncratic_credit", scope_issuer_id=sig.issuer_id, signal_id=sig.signal_id,
                kind="idiosyncratic",
                rule=(f"Idiosyncratic: {sig.event_type} on held issuer {sig.company} with impact "
                      f"{sig.impact_score} >= {s.trigger_idiosyncratic_min_impact}"),
            ))
        return out

    def evaluate(self, sig: RiskSignal, source: str | None = None) -> list[TriggerDecision]:
        """Apply cooldown. Returns decisions to run; suppressed ones are recorded in self.suppressed."""
        now = self.clock()
        cooldown = self.s.trigger_cooldown_min * 60
        run: list[TriggerDecision] = []
        with self._lock:
            for d in self.candidates(sig, source):
                key = (d.scenario, d.scope_issuer_id or "MARKET")
                last = self._last_run.get(key)
                if last is not None and now - last < cooldown:
                    reason = f"cooldown: {key[0]} for {key[1]} ran {int(now - last)} s ago (< {cooldown} s)"
                    sup = TriggerDecision(**{**d.as_dict(), "suppressed": True, "suppressed_reason": reason})
                    self.suppressed.appendleft({**sup.as_dict(), "at": now})
                    log.info("trigger suppressed for signal %s: %s", sig.signal_id, reason)
                    continue
                self._last_run[key] = now
                run.append(d)
        return run
