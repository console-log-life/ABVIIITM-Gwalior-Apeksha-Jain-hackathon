"""Signal endpoints: /analyze, /analyze/batch, /signals (+ /stream, /export.jsonl, /{ticker})."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.deps import get_runtime
from app.api.models import EXAMPLE_SIGNAL, AnalyzeBatchRequest, AnalyzeRequest, SignalView, TickerSignals
from app.runtime import Runtime
from risk_engine.bus import SIGNAL_CREATED
from risk_engine.pipeline import DocumentRejected
from risk_engine.schemas import EVENT_TYPES, Provenance, RawDocument, Source, SourceType, utcnow

router = APIRouter(tags=["signals"])
SIG_RESPONSE = {200: {"content": {"application/json": {"example": EXAMPLE_SIGNAL}}},
                422: {"description": "Malformed, empty or non-English input",
                      "content": {"application/json": {"example": {"detail": "text must not be empty"}}}}}
LIST_RESPONSE = {200: {"content": {"application/json": {"example": [EXAMPLE_SIGNAL]}}}}


def _to_doc(req: AnalyzeRequest, rt: Runtime) -> RawDocument:
    hint = req.ticker.upper() if req.ticker else None
    if hint is None and req.company:
        res = rt.pipeline.resolver.resolve(req.company)
        hint = res.ticker if res.kind == "ISSUER" else None
    title = req.title or req.text.strip().split("\n", 1)[0][:300]
    return RawDocument.build(
        source=req.source, title=title, text=req.text, url=req.url, provenance=req.provenance,
        source_type=SourceType.NEWS if req.source is Source.MANUAL else None, captured_at=utcnow(),
        published_at=req.timestamp, hint_ticker=hint,
    )


@router.post("/analyze", response_model=SignalView, responses=SIG_RESPONSE,
             summary="Analyse one text → RiskSignal (stored and published)")
async def analyze(req: AnalyzeRequest, response: Response, rt: Runtime = Depends(get_runtime)) -> SignalView:
    try:
        row, dup = await rt.analyze(_to_doc(req, rt))
    except DocumentRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["X-Duplicate"] = str(dup).lower()
    return SignalView(**row, duplicate=dup)


@router.post("/analyze/batch", response_model=list[SignalView], responses=LIST_RESPONSE,
             summary="Analyse up to 100 texts (all-or-nothing validation)")
async def analyze_batch(req: AnalyzeBatchRequest, rt: Runtime = Depends(get_runtime)) -> list[SignalView]:
    out = []
    for i, item in enumerate(req.items):
        try:
            row, dup = await rt.analyze(_to_doc(item, rt))
        except DocumentRejected as exc:
            raise HTTPException(status_code=422, detail=f"items[{i}]: {exc}") from exc
        out.append(SignalView(**row, duplicate=dup))
    return out


def _filters(ticker, event_type, min_impact, provenance) -> dict:
    if event_type is not None and event_type not in EVENT_TYPES:
        raise HTTPException(422, f"event_type must be one of {list(EVENT_TYPES)}")
    return {"ticker": ticker, "event_type": event_type, "min_impact": min_impact,
            "provenance": provenance.value if provenance else None}


@router.get("/signals", response_model=list[SignalView], responses=LIST_RESPONSE,
            summary="List signals, newest first, with filters")
async def list_signals(
    ticker: str | None = Query(None, examples=["AAPL"]),
    event_type: str | None = Query(None, examples=["Credit Event"]),
    min_impact: float | None = Query(None, ge=1, le=10, examples=[7.0]),
    provenance: Provenance | None = Query(None, examples=["CACHED_REAL"]),
    since_id: str | None = Query(None, description="Only signals created after this signal_id"),
    as_of: datetime | None = Query(None, description="Time machine: only signals with event time up to this time"),
    hours: int | None = Query(None, ge=1, le=720, description="Only the last N hours of event time before as_of"),
    limit: int = Query(50, ge=1, le=500),
    rt: Runtime = Depends(get_runtime),
) -> list[SignalView]:
    since_seq = None
    if since_id:
        since_seq = await asyncio.to_thread(rt.store.seq_of, since_id)
        if since_seq is None:
            raise HTTPException(404, f"unknown since_id {since_id}")
    rows = await asyncio.to_thread(rt.store.list_signals, since_seq=since_seq, limit=limit,
                                   ascending=since_seq is not None, until_ts=as_of,
                                   since_ts=(as_of or datetime.now(UTC)) - timedelta(hours=hours) if hours else None,
                                   **_filters(ticker, event_type, min_impact, provenance))
    return [SignalView(**r) for r in rows]


@router.get("/signals/stream", summary="Server-Sent Events: one `signal` event per new RiskSignal",
            responses={200: {"content": {"text/event-stream": {"example":
                       "event: signal\nid: 0b9d3c55-...\ndata: {\"signal_id\": \"0b9d3c55-...\", ...}\n\n"}}}})
async def stream(request: Request, replay_last: int = Query(0, ge=0, le=200, description="Send N stored first"),
                 max_events: int | None = Query(None, ge=1, description="Close after N events (clients/tests)"),
                 rt: Runtime = Depends(get_runtime)) -> StreamingResponse:
    queue = rt.bus.open_queue(SIGNAL_CREATED)

    async def gen() -> AsyncIterator[str]:
        sent = 0
        try:
            if replay_last:
                rows = await asyncio.to_thread(rt.store.list_signals, limit=replay_last)
                for r in reversed(rows):
                    yield f"event: signal\nid: {r['signal_id']}\ndata: {json.dumps(r, default=str)}\n\n"
                    sent += 1
                    if max_events and sent >= max_events:
                        return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    sig = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: signal\nid: {sig.signal_id}\ndata: {sig.model_dump_json()}\n\n"
                sent += 1
                if max_events and sent >= max_events:
                    return
        finally:
            rt.bus.close_queue(SIGNAL_CREATED, queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/signals/export.jsonl", summary="Machine-readable export: one RiskSignal JSON per line",
            responses={200: {"content": {"application/x-ndjson": {"example": json.dumps(EXAMPLE_SIGNAL) + "\n"}}}})
async def export_jsonl(
    ticker: str | None = Query(None), event_type: str | None = Query(None),
    min_impact: float | None = Query(None, ge=1, le=10), provenance: Provenance | None = Query(None),
    rt: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    filters = _filters(ticker, event_type, min_impact, provenance)
    rows = await asyncio.to_thread(lambda: list(rt.store.iter_signals(**filters)))
    keys = set(EXAMPLE_SIGNAL)

    def gen():
        for r in rows:
            yield json.dumps({k: v for k, v in r.items() if k in keys or k == "captured_at"}, default=str) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=signals.jsonl"})


@router.get("/signals/by-id/{signal_id}", response_model=SignalView, responses={
            200: {"content": {"application/json": {"example": EXAMPLE_SIGNAL}}}, 404: {"description": "Unknown id"}},
            summary="One stored signal by signal_id (dashboard click-through)")
async def signal_by_id(signal_id: str, rt: Runtime = Depends(get_runtime)) -> SignalView:
    row = await asyncio.to_thread(rt.store.get_signal, signal_id)
    if row is None:
        raise HTTPException(404, f"unknown signal_id {signal_id}")
    return SignalView(**row)


@router.get("/signals/{ticker}", response_model=TickerSignals,
            responses={200: {"content": {"application/json": {"example": {
                "ticker": "TATAMOTORS.NS", "count": 1, "mean_sentiment": -0.903, "max_impact": 7.4,
                "signals": [EXAMPLE_SIGNAL]}}}}},
            summary="Signals for one ticker + aggregate (mean sentiment, max impact)")
async def signals_for_ticker(ticker: str, limit: int = Query(100, ge=1, le=500),
                             rt: Runtime = Depends(get_runtime)) -> TickerSignals:
    rows = await asyncio.to_thread(rt.store.list_signals, ticker=ticker, limit=limit)
    sents = [r["sentiment_score"] for r in rows]
    return TickerSignals(ticker=ticker.upper(), count=len(rows),
                         mean_sentiment=round(sum(sents) / len(sents), 3) if sents else None,
                         max_impact=max((r["impact_score"] for r in rows), default=None),
                         signals=[SignalView(**r) for r in rows])
