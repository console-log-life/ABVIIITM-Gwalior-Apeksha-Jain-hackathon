"""Risk propagation view: GET /propagation (direct vs propagated exposure + the exposure graph around an issuer)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_runtime
from app.runtime import Runtime
from portfolio.propagation import load_links, propagated_exposure, reach
from portfolio.watchlist import WatchRules, build_watchlist, issuer_table

router = APIRouter(tags=["propagation"])

PROP_EXAMPLE = {
    "issuer_id": "IN-TATAMOTORS", "direct_exposure": 41013632.09, "direct_pct": 4.94, "propagated_exposure": 21534071.6,
    "propagated_pct": 2.59, "total_pct": 7.53,
    "contributions": [{"issuer_id": "US-F", "relation": "peer_of", "weight": 0.3, "exposure": 38150000.0,
                       "weighted": 11445000.0, "note": "automakers (incl. JLR / Ford premium segments)"}],
    "graph": {"nodes": [{"id": "IN-TATAMOTORS", "kind": "issuer", "status": "WATCH-NEGATIVE", "hop": 0}],
              "edges": [{"a": "IN-TATAMOTORS", "b": "US-F", "relation": "peer_of", "weight": 0.3}]},
    "note": "Curated links (universe.yaml), not inferred; illustrative exposure map, not a contagion model.",
}


@router.get("/propagation", summary="Direct vs propagated (second-order) exposure and the exposure graph of an issuer",
            responses={200: {"content": {"application/json": {"example": PROP_EXAMPLE}}},
                       404: {"description": "Issuer not held"}})
async def propagation(issuer_id: str = Query(..., examples=["IN-TATAMOTORS"]),
                      as_of: datetime | None = Query(None, description="Time machine: watch statuses as of this time"),
                      hours: int | None = Query(None, ge=1, le=720),
                      rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    if rt.stress is None:
        raise HTTPException(503, "portfolio unavailable (see /health)")
    port = rt.stress.portfolio
    table = issuer_table(port)
    if issuer_id not in table:
        raise HTTPException(404, f"issuer {issuer_id} is not held")
    s = rt.settings
    exposures = {k: v["exposure_mv"] for k, v in table.items()}
    out = propagated_exposure(issuer_id, exposures, port.funded_mv, s)

    now = datetime.now(UTC) if as_of is None else (as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of)
    hours = hours or s.watchlist_window_h
    rows = await asyncio.to_thread(rt.store.list_signals, since_ts=now - timedelta(hours=hours), until_ts=now,
                                   limit=50_000, ascending=True)
    wl = build_watchlist(port, rows, WatchRules.from_settings(s), hours, now, s)
    status = {r["issuer_id"]: (r["status"], r["status_reason"]) for r in wl["issuers"]}

    links = load_links()
    shown = {issuer_id: {"weight": 1.0, "path": [], "hop": 0}}
    for other, h in reach(issuer_id, links, s.propagation_decay, max(2, s.propagation_max_hops)).items():
        shown[other] = {**h, "hop": len(h["path"])}
    df = port.df
    nodes, edges = [], []
    for iid, h in shown.items():
        meta = table.get(iid)
        pos = df[df["issuer_id"] == iid]
        nodes.append({"id": iid, "kind": "issuer", "name": meta["issuer_name"] if meta else iid,
                      "sector": meta["sector"] if meta else None,
                      "rating_bucket": meta["rating_bucket"] if meta else None,
                      "exposure": exposures.get(iid, 0.0), "exposure_pct": meta["exposure_pct"] if meta else 0.0,
                      "status": status.get(iid, ("STABLE", ""))[0], "status_reason": status.get(iid, ("", ""))[1],
                      "hop": h["hop"], "weight": h["weight"], "held": meta is not None,
                      "positions": [{k: r[k] for k in ("asset_id", "asset_type", "side", "market_value",
                                                         "notional", "rating_bucket", "currency")}
                                    for r in pos.to_dict("records")]})
        if meta:
            edges.append({"a": iid, "b": f"sector:{meta['sector']}", "relation": "sector", "weight": None})
    for sec in sorted({n["sector"] for n in nodes if n["sector"]}):
        nodes.append({"id": f"sector:{sec}", "kind": "sector", "name": sec})
    for ln in links:
        if ln.a in shown and ln.b in shown:
            edges.append({"a": ln.a, "b": ln.b, "relation": ln.relation, "note": ln.note,
                          "weight": s.propagation_decay.get(ln.relation)})
    out.update(graph={"nodes": nodes, "edges": edges}, as_of=now.isoformat(), window_hours=hours,
               note="Curated links (universe.yaml), not inferred from data; illustrative exposure map for analyst "
                    "attention, not a correlation or default-contagion model.")
    return out
