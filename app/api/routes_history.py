"""REAL history + time machine: GET /history, POST /history/load, GET /overview (Home KPIs as of a time)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_runtime
from app.runtime import Runtime
from portfolio.watchlist import MONITOR, WATCH, WatchRules, build_watchlist
from risk_engine.history import history_path, is_fresh, read_meta

router = APIRouter(tags=["history"])

HISTORY_EXAMPLE = {"status": {"state": "ready", "loaded": {"signals": 1290, "stress_runs": 61}},
                   "fresh": True, "event_from": "2026-09-27T08:00:00+00:00", "event_to": "2026-10-05T20:10:00+00:00",
                   "meta": {"source": "local capture cache", "documents": 1325, "signals": 1290, "stress_runs": 61}}
OVERVIEW_EXAMPLE = {"as_of": "2026-10-05T20:13:49+00:00", "hours": 24,
                    "current": {"signals": 412, "critical": 9, "issuers_on_watch": 6, "sources_active": 4,
                                "social_pct": 38.1},
                    "previous": {"signals": 388, "critical": 5, "issuers_on_watch": 4, "sources_active": 4,
                                 "social_pct": 41.0}}


def parse_as_of(as_of: datetime | None) -> datetime:
    if as_of is None:
        return datetime.now(UTC)
    return as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of.astimezone(UTC)


@router.get("/history", summary="REAL history status, provenance and the known-time range for the time machine",
            responses={200: {"content": {"application/json": {"example": HISTORY_EXAMPLE}}}})
async def history(rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    lo, hi = await asyncio.to_thread(rt.store.event_time_range)
    path = history_path(rt.settings)
    return {"status": rt.history_status, "fresh": await asyncio.to_thread(is_fresh, rt.settings),
            "event_from": lo.isoformat() if lo else None, "event_to": hi.isoformat() if hi else None,
            "meta": read_meta(path), "note": "Signals with origin 'real' come from captured real documents "
            "(CACHED_REAL); the time machine replays them by publication (event) time, although they were collected at "
            "their capture times. Their stress runs are simulated (illustrative model, synthetic portfolio)."}


@router.post("/history/load", summary="Load the processed REAL history (build it first if missing or stale)",
             responses={200: {"content": {"application/json": {"example": {"state": "building",
                                                                           "progress": [320, 1325]}}}}})
async def history_load(rebuild: bool = Query(False, description="Rebuild even if the cache is fresh"),
                       rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return rt.start_history_load(rebuild)


def _kpis(rows: list[dict], wl: dict) -> dict[str, Any]:
    social = sum(1 for r in rows if r.get("source_type") == "social")
    return {"signals": len(rows), "critical": sum(1 for r in rows if r["risk_level"] == "Critical"),
            "high_or_critical": sum(1 for r in rows if r["risk_level"] in ("High", "Critical")),
            "issuers_on_watch": wl["counts"][WATCH] + wl["counts"][MONITOR],
            "watch_negative": wl["counts"][WATCH],
            "sources_active": len({r.get("imitated_source") or r["source"] for r in rows}),
            "social_pct": round(100 * social / len(rows), 1) if rows else 0.0}


@router.get("/overview", summary="Home KPIs over the window ending at as_of, and the previous window (trend)",
            responses={200: {"content": {"application/json": {"example": OVERVIEW_EXAMPLE}}}})
async def overview(as_of: datetime | None = Query(None, description="Event-time cut-off (default: now)"),
                   hours: int = Query(24, ge=1, le=720), rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    t = parse_as_of(as_of)
    rules = WatchRules.from_settings(rt.settings)
    out: dict[str, Any] = {"as_of": t.isoformat(), "hours": hours}
    for name, end in (("current", t), ("previous", t - timedelta(hours=hours))):
        rows = await asyncio.to_thread(rt.store.list_signals, since_ts=end - timedelta(hours=hours), until_ts=end,
                                       limit=50_000, ascending=True)
        wl = build_watchlist(rt.stress.portfolio, rows, rules, hours, end) if rt.stress else {
            "counts": {WATCH: 0, MONITOR: 0}}
        out[name] = _kpis(rows, wl)
    latest = await asyncio.to_thread(rt.store.latest_stress_run, t)
    out["latest_stress"] = {k: latest.get(k) for k in ("run_id", "scenario", "scenario_label", "loss_pct", "rag",
                                                       "created_at", "rule")} if latest else None
    return out
