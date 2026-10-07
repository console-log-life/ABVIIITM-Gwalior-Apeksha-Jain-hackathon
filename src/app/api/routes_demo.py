"""Demo control: /demo/start, /demo/reset, plus /mode (dashboard mode switch) and /demo/status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_runtime
from app.api.models import DemoStartRequest, ModeRequest
from app.config import AppMode
from app.runtime import Runtime

router = APIRouter(tags=["demo"])


@router.post("/demo/start", summary="Start the scripted SCENARIO story or a REPLAY of cached real data",
             responses={200: {"content": {"application/json": {"example": {
                 "running": True, "mode": "SCENARIO", "started_at": "2026-10-03T18:00:00+00:00"}}}},
                 404: {"description": "Demo story file missing"}})
async def demo_start(req: DemoStartRequest, rt: Runtime = Depends(get_runtime)) -> dict:
    if req.mode is AppMode.LIVE:
        raise HTTPException(422, "mode must be SCENARIO or REPLAY (use POST /mode for LIVE)")
    try:
        return await rt.start_demo(req.mode, req.step_seconds, req.limit)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/demo/reset", summary="Delete demo/replay/API signals and all stress runs; LIVE signals are kept",
             responses={200: {"content": {"application/json": {"example": {
                 "signals_deleted": 3, "documents_deleted": 3, "stress_runs_deleted": 2}}}}})
async def demo_reset(rt: Runtime = Depends(get_runtime)) -> dict:
    return await rt.reset_demo()


@router.get("/demo/status", summary="Progress of the running demo",
            responses={200: {"content": {"application/json": {"example": {
                "running": False, "mode": "SCENARIO", "documents": 4}}}}})
async def demo_status(rt: Runtime = Depends(get_runtime)) -> dict:
    return {**rt.demo_status, "mode_current": rt.mode.value}


@router.post("/mode", summary="Switch mode: LIVE starts ingestion; REPLAY/SCENARIO stop it and start playback",
             responses={200: {"content": {"application/json": {"example": {"mode": "LIVE", "live_running": True}}}}})
async def set_mode(req: ModeRequest, rt: Runtime = Depends(get_runtime)) -> dict:
    try:
        return await rt.set_mode(req.mode)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
