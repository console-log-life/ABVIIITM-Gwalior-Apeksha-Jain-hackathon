"""Early-warning watchlist: GET /watchlist (credit-risk view of recent signals per held issuer)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_runtime
from app.runtime import Runtime
from portfolio.watchlist import NOTE, WatchRules, build_watchlist

router = APIRouter(tags=["watchlist"])

WATCHLIST_EXAMPLE = {
    "as_of": "2026-10-06T09:00:00+00:00", "window_hours": 24,
    "counts": {"WATCH-NEGATIVE": 1, "MONITOR": 0, "STABLE": 30},
    "rules": {"WATCH-NEGATIVE": "any negative signal (sentiment <= -0.25) with impact >= 7, or >= 2 negative "
                                "signals with impact >= 5",
              "MONITOR": "any negative signal (sentiment <= -0.25) with impact >= 4", "STABLE": "otherwise"},
    "portfolio_source": "SYNTHETIC (generated, seed 42)", "signals_in_window": 1, "note": NOTE,
    "issuers": [{
        "rank": 1, "issuer_id": "IN-TATAMOTORS", "issuer_name": "Tata Motors Ltd.", "ticker": "TATAMOTORS.NS",
        "sector": "Consumer Discretionary", "country": "IN", "rating_bucket": "BB", "exposure_mv": 41013632.09,
        "exposure_pct": 4.94, "positions": 3, "cds_protection_notional": 7727587.04, "status": "WATCH-NEGATIVE",
        "status_reason": "negative signal with impact 8.7 >= 7 (sentiment -0.90)", "signal_count": 1,
        "negative_count": 1, "worst_impact": 8.7, "mean_sentiment": -0.903, "event_types": {"Credit Event": 1},
        "sources": ["google_news"], "max_corroborating_sources": 1,
        "top_signals": [{"signal_id": "0b9d3c55-7f0e-4a51-9a39-5a3f3b1b6c2e", "impact_score": 8.7,
                         "event_type": "Credit Event", "sentiment_score": -0.903,
                         "reason": "Credit Event at Tata Motors Ltd. (negative sentiment -0.90) ...",
                         "provenance": "SYNTHETIC", "source": "google_news"}],
        "impact_series": [{"timestamp": "2026-10-06T08:59:10Z", "impact_score": 8.7}],
    }],
}


@router.get("/watchlist", summary="Early-warning watchlist: watch status per HELD issuer from recent signals",
            responses={200: {"content": {"application/json": {"example": WATCHLIST_EXAMPLE}}},
                       503: {"description": "Portfolio unavailable"}})
async def watchlist(hours: int | None = Query(None, ge=1, le=720, description="Window by event time (default "
                                              "WATCHLIST_WINDOW_H = 24)", examples=[24]),
                    as_of: datetime | None = Query(None, description="Time machine: window ends at this event time"),
                    rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    if rt.stress is None:
        raise HTTPException(503, "watchlist unavailable (portfolio could not be loaded; see /health)")
    hours = hours or rt.settings.watchlist_window_h
    now = datetime.now(UTC) if as_of is None else (as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of)
    rows = await asyncio.to_thread(rt.store.list_signals, since_ts=now - timedelta(hours=hours), until_ts=now,
                                   limit=50_000, ascending=True)
    return build_watchlist(rt.stress.portfolio, rows, WatchRules.from_settings(rt.settings), hours, now, rt.settings)
