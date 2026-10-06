"""Application runtime: owns the store, bus, pipeline, LIVE scheduler and demo playback.

Every path into the system (LIVE scheduler, REPLAY, SCENARIO, POST /analyze) goes through Runtime.ingest()
or Runtime.analyze(), which call the single risk_engine.pipeline (spec rule 5).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import AppMode, Settings
from risk_engine.bus import SIGNAL_CREATED, EventBus
from risk_engine.impact_scoring.corroboration import CorroborationTracker, Observation
from risk_engine.impact_scoring.scorer import ImpactScorer
from risk_engine.ingestion.base import HEALTH
from risk_engine.ingestion.replay import run_replay
from risk_engine.ingestion.scenario import run_scenario
from risk_engine.ingestion.scheduler import IngestionScheduler, build_live_adapters, make_http_client
from risk_engine.ingestion.state import apply_state, last_capture_health, save_state
from risk_engine.logging_setup import get_logger
from risk_engine.pipeline import RiskPipeline, default_exposures
from risk_engine.preprocessing.dedup import Deduplicator
from risk_engine.schemas import RawDocument, RiskSignal
from risk_engine.sentiment.finbert import SentimentEngine
from risk_engine.store import Store

log = get_logger(__name__)
INGEST_CHUNK = 32
HEALTH_PERSIST_S = 30.0
WARMUP_TEXT = "Warm-up: markets steady ahead of central bank meeting"


class Runtime:
    def __init__(self, settings: Settings, store: Store | None = None, pipeline: RiskPipeline | None = None,
                 bus: EventBus | None = None):
        self.settings = settings
        self.store = store or Store(settings.db_file)
        self.bus = bus or EventBus()
        self._pipeline = pipeline
        self._pipeline_error: str | None = None
        self.mode: AppMode = settings.app_mode
        self.started_at = time.time()
        self.dedup = Deduplicator(settings.near_dup_threshold)
        self._live_task: asyncio.Task | None = None
        self._live_stop: asyncio.Event | None = None
        self._live_adapters: list = []
        self._live_client = None
        self._demo_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self.demo_status: dict[str, Any] = {"running": False}
        self.stress = None  # set by attach_stress_engine (Module B)
        self.exposures: dict[str, float] | None = None  # issuer_id -> funded exposure, set with the stress engine

    # ------------------------------------------------------------------ pipeline
    @property
    def pipeline(self) -> RiskPipeline:
        if self._pipeline is None:
            scorer = ImpactScorer(exposures=self.exposures if self.exposures is not None else default_exposures())
            self._pipeline = RiskPipeline(settings=self.settings, sentiment=SentimentEngine(self.settings),
                                          scorer=scorer,
                                          corroboration=CorroborationTracker(self.settings.corroboration_window_h))
            self.seed_corroboration()
        return self._pipeline

    def pipeline_ready(self) -> bool:
        return self._pipeline is not None

    def seed_corroboration(self) -> int:
        """Rebuild the corroboration window from stored signals (restart-safe)."""
        tracker = self.pipeline.corroboration
        tracker.clear()
        since = datetime.now(UTC) - timedelta(hours=self.settings.corroboration_window_h)
        obs = []
        for r in self.store.recent_for_corroboration(since):
            kind = "MARKET" if r["company"] == "MARKET" else ("ISSUER" if r.get("issuer_id") else
                                                               ("EXTERNAL_TICKER" if r.get("ticker") else "UNRESOLVED"))
            key = tracker.entity_key(kind, r.get("issuer_id"), r.get("ticker"))
            if key and r["event_type"] != "Other":
                obs.append(Observation(key, r["event_type"], r.get("imitated_source") or r["source"],
                                       datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")),
                                       frozenset(e.lower() for e in r.get("event_evidence", []))))
        tracker.seed(obs)
        return len(obs)

    async def warm_up(self) -> None:
        """Load models off the event loop so startup stays responsive."""
        try:
            await asyncio.to_thread(lambda: self.pipeline)
            t0 = time.perf_counter()  # warm-up inference: the first real request should not pay the JIT/alloc cost
            await asyncio.to_thread(self.pipeline.sentiment.analyze, WARMUP_TEXT)
            log.info("pipeline warm-up inference done in %.2f s (backend=%s)", time.perf_counter() - t0,
                     self.pipeline.sentiment.backend)
        except Exception as exc:  # never crash the API; /health reports it
            self._pipeline_error = f"{type(exc).__name__}: {exc}"
            log.exception("pipeline warm-up failed")

    # ------------------------------------------------------------------ ingestion
    async def ingest(self, docs: list[RawDocument], origin: str) -> list[RiskSignal]:
        """Store + publish signals for documents not seen before. Returns the newly created signals."""
        fresh = [d for d in docs if not await asyncio.to_thread(self.store.has_document, d.doc_id)]
        created: list[RiskSignal] = []
        by_id = {d.doc_id: d for d in fresh}
        for i in range(0, len(fresh), INGEST_CHUNK):
            chunk = fresh[i : i + INGEST_CHUNK]
            sigs = await asyncio.to_thread(self.pipeline.process_batch, chunk, True)
            for sig in sigs:
                if await asyncio.to_thread(self.store.save_signal, by_id[sig.doc_id], sig, origin):
                    created.append(sig)
                    await self.bus.publish(SIGNAL_CREATED, sig)
        return created

    async def analyze(self, doc: RawDocument) -> tuple[dict[str, Any], bool]:
        """Analyse one API document. Returns (signal row, duplicate?). Raises DocumentRejected."""
        existing = await asyncio.to_thread(self.store.get_signal_by_doc, doc.doc_id)
        if existing:
            return existing, True
        sig = (await asyncio.to_thread(self.pipeline.process_batch, [doc], False))[0]
        if await asyncio.to_thread(self.store.save_signal, doc, sig, "api"):
            await self.bus.publish(SIGNAL_CREATED, sig)
        return await asyncio.to_thread(self.store.get_signal_by_doc, doc.doc_id), False

    # ------------------------------------------------------------------ LIVE mode
    @property
    def live_running(self) -> bool:
        return self._live_task is not None and not self._live_task.done()

    async def start_live(self) -> None:
        if self.live_running:
            return
        self._live_client = make_http_client(self.settings)
        self._live_adapters = build_live_adapters(self._live_client, self.settings)
        apply_state(self._live_adapters, self.settings.cache_path)  # respect capture-run rate limits/backoffs

        async def sink(docs: list[RawDocument]) -> None:
            await self.ingest(docs, "live")

        sched = IngestionScheduler(self._live_adapters, sink, self.dedup)
        self._live_stop = asyncio.Event()
        self._live_task = asyncio.create_task(sched.run_forever(self._live_stop), name="live-ingestion")
        log.info("LIVE mode started with %d adapters", len(self._live_adapters))

    async def stop_live(self) -> None:
        if self._live_stop is not None:
            self._live_stop.set()
        if self._live_task is not None:
            try:
                await asyncio.wait_for(self._live_task, timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                self._live_task.cancel()
        if self._live_adapters:
            save_state(self.settings.cache_path, self._live_adapters)
        if self._live_client is not None:
            await self._live_client.aclose()
        self._live_task = self._live_stop = self._live_client = None
        self._live_adapters = []

    # ------------------------------------------------------------------ demo / modes
    @property
    def demo_running(self) -> bool:
        return self._demo_task is not None and not self._demo_task.done()

    async def start_demo(self, mode: AppMode, step_seconds: float | None = None, limit: int | None = None) -> dict:
        if mode is AppMode.LIVE:
            raise ValueError("use set_mode(LIVE) to start live ingestion")
        if self.demo_running:
            self._demo_task.cancel()
        if mode is AppMode.SCENARIO:
            path = self.settings.resolve(self.settings.demo_story_path)
            if not path.exists():
                raise FileNotFoundError(f"demo story not found: {path}")

            async def sink(docs):
                await self.ingest(docs, "scenario")

            step = self.settings.demo_step_seconds if step_seconds is None else step_seconds
            coro = run_scenario(path, sink, step_seconds=step, root=self.settings.resolve(Path('.')))
        else:
            async def sink(docs):
                await self.ingest(docs, "replay")

            delay = self.settings.replay_delay_s if step_seconds is None else step_seconds
            coro = run_replay(self.settings.cache_path, sink, delay_s=delay, limit=limit or self.settings.replay_limit,
                              batch_size=4)
        self.mode = mode
        self.demo_status = {"running": True, "mode": mode.value, "started_at": datetime.now(UTC).isoformat()}

        async def runner():
            try:
                n = await coro
                self.demo_status.update(running=False, documents=n, finished_at=datetime.now(UTC).isoformat())
            except asyncio.CancelledError:
                self.demo_status.update(running=False, cancelled=True)
                raise
            except Exception as exc:
                log.exception("demo run failed")
                self.demo_status.update(running=False, error=f"{type(exc).__name__}: {exc}")

        self._demo_task = asyncio.create_task(runner(), name=f"demo-{mode.value}")
        return self.demo_status

    async def set_mode(self, mode: AppMode) -> dict:
        if mode is AppMode.LIVE:
            if self.demo_running:
                self._demo_task.cancel()
            await self.start_live()
            self.mode = mode
            return {"mode": mode.value, "live_running": True}
        await self.stop_live()
        return {"mode": mode.value, **(await self.start_demo(mode))}

    async def reset_demo(self) -> dict:
        if self.demo_running:
            self._demo_task.cancel()
            try:
                await self._demo_task
            except (asyncio.CancelledError, Exception):
                pass
        counts = await asyncio.to_thread(self.store.reset_demo)
        self.dedup = Deduplicator(self.settings.near_dup_threshold)
        if self._pipeline is not None:
            self.seed_corroboration()
        if self.stress is not None:
            self.stress.reset()
        self.demo_status = {"running": False}
        return counts

    # ------------------------------------------------------------------ health
    async def _persist_health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_PERSIST_S)
            snap = HEALTH.snapshot()
            if snap:
                await asyncio.to_thread(self.store.upsert_source_health, snap)

    def health(self) -> dict[str, Any]:
        # live polling in this session > persisted DB rows > last capture_cache.py run (labelled as such)
        sources = HEALTH.snapshot() or self.store.source_health_rows() or last_capture_health(self.settings.cache_path)
        if self._pipeline is not None:
            model = self._pipeline.sentiment.status()
            from risk_engine.event_classifier.learned import event_status

            model["event"] = event_status(self.settings)
        else:
            model = {"backend": "loading" if not self._pipeline_error else "error", "error": self._pipeline_error}
        db_ok = self.store.ping()
        degraded = (not db_ok) or model.get("backend") != "finbert"
        return {
            "status": "degraded" if degraded else "ok",
            "mode": self.mode.value,
            "uptime_s": round(time.time() - self.started_at, 1),
            "db_ok": db_ok,
            "signals_stored": self.store.count_signals() if db_ok else None,
            "model": model,
            "live_running": self.live_running,
            "demo": self.demo_status,
            "sources": sources,
            "bus": {"signal.created": self.bus.published.get("signal.created", 0),
                    "stress.completed": self.bus.published.get("stress.completed", 0)},
            "portfolio": self.stress.portfolio_info() if self.stress is not None else None,
        }

    # ------------------------------------------------------------------ lifecycle
    async def startup(self, warm: bool = True) -> None:
        self._health_task = asyncio.create_task(self._persist_health_loop(), name="health-persist")
        if warm:
            await self.warm_up()
        if self.mode is AppMode.LIVE:
            await self.start_live()

    async def shutdown(self) -> None:
        await self.stop_live()
        for t in (self._demo_task, self._health_task):
            if t is not None and not t.done():
                t.cancel()
        snap = HEALTH.snapshot()
        if snap:
            self.store.upsert_source_health(snap)
