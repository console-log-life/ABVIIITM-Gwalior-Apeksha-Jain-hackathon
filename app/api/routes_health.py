from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.runtime import Runtime

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


@router.get("/health", summary="Service status: model/fallback, DB, mode, per-source health",
            responses={200: {"content": {"application/json": {"example": HEALTH_EXAMPLE}}}})
async def health(rt: Runtime = Depends(get_runtime)) -> dict:
    return await asyncio.to_thread(rt.health)
