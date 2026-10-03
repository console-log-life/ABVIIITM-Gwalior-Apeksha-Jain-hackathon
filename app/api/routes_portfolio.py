"""Module B endpoints: /portfolio, /portfolio/stress-test (GET latest, POST manual), /stress-runs (audit log)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.deps import get_runtime
from app.config import STRESS_DISCLAIMER
from app.runtime import Runtime
from portfolio.loader import FUNDED_TYPES
from risk_engine.bus import STRESS_COMPLETED

router = APIRouter(tags=["portfolio"])

STRESS_EXAMPLE = {
    "run_id": "5f1c2b9e-7a1d-4c55-9a77-2b8f1e0c3d11", "scenario": "geopolitical_severe",
    "scenario_label": "Geopolitical shock (severe)", "trigger_signal_id": "0b9d3c55-7f0e-4a51-9a39-5a3f3b1b6c2e",
    "rule": "Systemic: Geopolitical with entity MARKET and impact 9.1 >= 7.0 → severe (severe at >= 8.5)",
    "before_value": 920000000.0, "after_value": 897000000.0, "loss": 23000000.0, "loss_pct": 2.5, "rag": "RED",
    "hedge_offset": 6100000.0, "by_asset_class": {"Bond": -15000000.0, "Equity": -9000000.0, "CDS": 2000000.0},
    "hhi_sector": 0.14, "hhi_issuer": 0.06, "disclaimer": STRESS_DISCLAIMER,
}


class CustomShocks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rates_bp: float = Field(0, ge=-500, le=500)
    ig_spread_bp: float = Field(0, ge=-200, le=1000)
    hy_spread_bp: float = Field(0, ge=-500, le=2000)
    equity_pct: float = Field(0, ge=-0.9, le=0.5)
    em_fx_pct: float = Field(0, ge=-0.5, le=0.5)
    pd_multiplier: float = Field(1, ge=0.5, le=10)


class StressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"scenario": "geopolitical_severe"},
        {"scenario": "idiosyncratic_credit", "issuer_id": "IN-TATAMOTORS"},
        {"custom": {"rates_bp": 150, "ig_spread_bp": 60, "hy_spread_bp": 200, "equity_pct": -0.08,
                    "em_fx_pct": -0.03, "pd_multiplier": 1.4}},
    ]})
    scenario: str | None = None
    issuer_id: str | None = None
    custom: CustomShocks | None = None

    @model_validator(mode="after")
    def _one_of(self) -> StressRequest:
        if (self.scenario is None) == (self.custom is None):
            raise ValueError("provide exactly one of 'scenario' or 'custom'")
        return self


def _engine(rt: Runtime):
    if rt.stress is None:
        raise HTTPException(503, "stress engine unavailable (portfolio could not be loaded; see /health)")
    return rt.stress


@router.get("/portfolio", summary="Positions + composition summary (SYNTHETIC unless provided data is configured)",
            responses={200: {"content": {"application/json": {"example": {
                "source": "SYNTHETIC (generated, seed 42)", "positions_count": 51, "funded_mv": 920000000.0,
                "by_asset_class_gross": {"Loan": 0.4, "Bond": 0.35, "IRS": 0.08, "Equity": 0.08},
                "positions": [{"asset_id": "LOA-001", "asset_type": "Loan",
                               "issuer_name": "JPMorgan Chase & Co."}]}}}}})
async def get_portfolio(rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    eng = _engine(rt)
    df = eng.portfolio.df
    gross = df["market_value"].where(df["asset_type"].isin(FUNDED_TYPES), df["notional"])
    funded = df[df["asset_type"].isin(FUNDED_TYPES)]

    def share(series, by) -> dict[str, float]:
        g = series.groupby(by).sum()
        return {k: round(float(v / g.sum()), 4) for k, v in g.sort_values(ascending=False).items()}

    return {
        "source": eng.portfolio.source_label, "provenance": eng.portfolio.provenance,
        "positions_count": int(len(df)), "funded_mv": round(eng.portfolio.funded_mv, 2),
        "gross_exposure": round(float(gross.sum()), 2),
        "by_asset_class_gross": share(gross, df["asset_type"]),
        "by_sector_funded": share(funded["market_value"], funded["sector"]),
        "by_rating_funded": share(funded["market_value"], funded["rating_bucket"]),
        "by_country_funded": share(funded["market_value"], funded["country"]),
        "note": "Mix measured on gross exposure: market value for loans/bonds/equity, notional for derivative "
                "overlays (IRS, CDS, FX forwards). Loss % is measured against funded market value.",
        "positions": eng.portfolio.positions(),
    }


@router.get("/portfolio/scenarios", summary="Available named stress scenarios (illustrative)",
            responses={200: {"content": {"application/json": {"example": {"geopolitical_severe": {
                "label": "Geopolitical shock (severe)", "shocks": {"rates_bp": -25}}}}}}})
async def scenarios(rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return _engine(rt).scenarios


@router.get("/portfolio/stress-test", summary="Latest stress run (full result incl. per-position P&L)",
            responses={200: {"content": {"application/json": {"example": STRESS_EXAMPLE}}},
                       404: {"description": "No stress run yet"}})
async def latest_stress(rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    latest = await asyncio.to_thread(rt.store.latest_stress_run)
    if latest is None:
        raise HTTPException(404, "no stress run yet")
    latest["positions"] = await asyncio.to_thread(rt.store.stress_positions, latest["run_id"])
    return latest


@router.post("/portfolio/stress-test", summary="Run a named scenario or a custom shock vector manually",
             responses={200: {"content": {"application/json": {"example": STRESS_EXAMPLE}}},
                        422: {"description": "Unknown scenario / issuer, or invalid shocks"}})
async def run_stress(req: StressRequest, rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    eng = _engine(rt)
    try:
        summary, positions = await asyncio.to_thread(
            eng.run, req.scenario, req.issuer_id, None, "manual run via API",
            req.custom.model_dump() if req.custom else None)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc).strip("'\"")) from exc
    await asyncio.to_thread(rt.store.save_stress_run, summary, positions, True)
    await rt.bus.publish(STRESS_COMPLETED, summary)
    return {**summary, "positions": positions}


@router.get("/stress-runs", summary="Audit log: run_id, triggering signal_id, scenario, loss",
            responses={200: {"content": {"application/json": {"example": {"runs": [{
                "run_id": "5f1c2b9e-...", "trigger_signal_id": "0b9d3c55-...", "scenario": "geopolitical_severe",
                "loss": 23000000.0, "loss_pct": 2.5, "rag": "RED"}], "suppressed": []}}}}})
async def stress_runs(limit: int = Query(50, ge=1, le=500), rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    runs = await asyncio.to_thread(rt.store.list_stress_runs, limit)
    suppressed = list(rt.stress.triggers.suppressed) if rt.stress is not None else []
    return {"runs": runs, "suppressed": suppressed, "disclaimer": STRESS_DISCLAIMER}


@router.get("/stress-runs/{run_id}", summary="One stress run with per-position results",
            responses={200: {"content": {"application/json": {"example": STRESS_EXAMPLE}}}, 404: {"description": "x"}})
async def stress_run(run_id: str, rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    run = await asyncio.to_thread(rt.store.get_stress_run, run_id)
    if run is None:
        raise HTTPException(404, f"unknown run_id {run_id}")
    run["positions"] = await asyncio.to_thread(rt.store.stress_positions, run_id)
    return run
