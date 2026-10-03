from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.config import STRESS_DISCLAIMER
from app.runtime import Runtime
from risk_engine.impact_scoring.scorer import get_scorer

router = APIRouter(tags=["health"])

HEALTH_EXAMPLE = {
    "status": "ok", "mode": "SCENARIO", "uptime_s": 12.3, "db_ok": True, "signals_stored": 42,
    "model": {"backend": "finbert", "model": "ProsusAI/finbert", "loaded": True, "fallback_reason": None},
    "live_running": False, "demo": {"running": False},
    "sources": [{"source": "google_news", "status": "OK", "last_count": 581, "last_error": None},
                {"source": "stocktwits", "status": "BACKOFF", "last_error": "HTTP 403 — blocked by source"}],
    "bus": {"signal.created": 42, "stress.completed": 3},
    "portfolio": {"source": "SYNTHETIC (generated, seed 42)", "positions": 50},
}


@router.get("/methodology", summary="Impact weights, priors and trigger thresholds in use (transparency)",
            responses={200: {"content": {"application/json": {"example": {
                "formula": "Impact = clip(1 + 9 × Q × (wE·E + wM·M + wX·X + wR·R), 1, 10)",
                "weights": {"E": 0.4, "M": 0.25, "X": 0.2, "R": 0.15}, "calibrated": False}}}}})
async def methodology(rt: Runtime = Depends(get_runtime)) -> dict:
    cfg = get_scorer().cfg
    s = rt.settings
    return {
        "formula": "Impact = clip(1 + 9 × Q × (wE·E + wM·M + wX·X + wR·R), 1, 10), rounded to 1 dp",
        "calibrated": False,
        "note": "All weights are expert-set priors, not learned or calibrated against market reactions.",
        "weights": cfg["weights"], "event_severity": cfg["event_severity"],
        "sentiment_magnitude": cfg["sentiment_magnitude"], "exposure": cfg["exposure"],
        "credibility": cfg["credibility"], "confidence_shrinkage": cfg["confidence_shrinkage"],
        "risk_levels": cfg["risk_levels"],
        "sentiment_thresholds": {"negative_at_or_below": s.sentiment_neg_threshold,
                                 "positive_at_or_above": s.sentiment_pos_threshold},
        "triggers": {"systemic_min_impact": s.trigger_systemic_min_impact,
                     "systemic_severe_impact": s.trigger_systemic_severe_impact,
                     "idiosyncratic_min_impact": s.trigger_idiosyncratic_min_impact,
                     "cooldown_min": s.trigger_cooldown_min, "risk_appetite_loss_pct": s.risk_appetite_loss_pct},
        "stress_disclaimer": STRESS_DISCLAIMER,
    }


@router.get("/health", summary="Service status: model/fallback, DB, mode, per-source health",
            responses={200: {"content": {"application/json": {"example": HEALTH_EXAMPLE}}}})
async def health(rt: Runtime = Depends(get_runtime)) -> dict:
    return await asyncio.to_thread(rt.health)
