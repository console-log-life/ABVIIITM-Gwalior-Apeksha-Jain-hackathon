"""LIVE ingestion: poll every adapter on its own interval, clean + dedup, hand new docs to a sink.

The sink is the single entry point into the NLP pipeline (wired in M3). Adapter failures are already
converted to statuses by BaseAdapter.fetch(); this loop additionally guards against hangs with a timeout.

CLI (one cycle, prints a report; PYTHONPATH=src):  python -m risk_engine.ingestion.scheduler --once
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from app.config import Settings, get_settings
from risk_engine.ingestion.base import HEALTH, BaseAdapter, FetchResult, SourceStatus
from risk_engine.ingestion.bluesky import BlueskyAdapter
from risk_engine.ingestion.finnhub import FinnhubAdapter
from risk_engine.ingestion.gdelt import GdeltAdapter
from risk_engine.ingestion.google_news import GoogleNewsAdapter
from risk_engine.ingestion.mastodon import MastodonAdapter
from risk_engine.ingestion.reddit_rss import RedditRSSAdapter
from risk_engine.ingestion.stocktwits import StockTwitsAdapter
from risk_engine.logging_setup import get_logger, setup_logging
from risk_engine.preprocessing.clean import clean_document
from risk_engine.preprocessing.dedup import Deduplicator
from risk_engine.schemas import RawDocument

log = get_logger(__name__)
Sink = Callable[[list[RawDocument]], Awaitable[None]]
ADAPTER_CLASSES: list[type[BaseAdapter]] = [
    GoogleNewsAdapter, FinnhubAdapter, GdeltAdapter, RedditRSSAdapter, MastodonAdapter, BlueskyAdapter,
    StockTwitsAdapter,
]
CYCLE_TIMEOUT_S = 180.0  # hard cap for one adapter's whole cycle (many queries x <=10 s each)


def make_http_client(settings: Settings | None = None) -> httpx.AsyncClient:
    s = settings or get_settings()
    return httpx.AsyncClient(headers={"User-Agent": s.user_agent, "Accept": "*/*"},
                             timeout=s.http_timeout_s, follow_redirects=True)


def build_live_adapters(client: httpx.AsyncClient, settings: Settings | None = None,
                        only: set[str] | None = None) -> list[BaseAdapter]:
    return [cls(client, settings) for cls in ADAPTER_CLASSES if only is None or cls.name in only]


@dataclass
class CycleReport:
    source: str
    status: SourceStatus
    fetched: int = 0
    after_clean: int = 0
    new: int = 0
    dedup: dict[str, int] = field(default_factory=dict)
    detail: str = ""
    elapsed_s: float = 0.0
    docs: list[RawDocument] = field(default_factory=list)


async def fetch_with_timeout(adapter: BaseAdapter) -> FetchResult:
    try:
        return await asyncio.wait_for(adapter.fetch(), timeout=CYCLE_TIMEOUT_S)
    except TimeoutError:
        h = HEALTH.get(adapter.name)
        h.status, h.last_error = SourceStatus.DEGRADED, f"cycle exceeded {CYCLE_TIMEOUT_S:.0f}s"
        log.warning("source %s: %s", adapter.name, h.last_error)
        return FetchResult(adapter.name, SourceStatus.DEGRADED, detail=h.last_error)


def process_result(result: FetchResult, dedup: Deduplicator) -> CycleReport:
    cleaned = [c for c in (clean_document(d) for d in result.docs) if c is not None]
    kept, counts = dedup.filter(cleaned)
    return CycleReport(result.source, result.status, len(result.docs), len(cleaned), len(kept), counts,
                       result.detail, result.elapsed_s, kept)


class IngestionScheduler:
    def __init__(self, adapters: list[BaseAdapter], sink: Sink, dedup: Deduplicator | None = None):
        self.adapters = adapters
        self.sink = sink
        self.dedup = dedup or Deduplicator(get_settings().near_dup_threshold)
        self._next_due: dict[str, float] = {a.name: 0.0 for a in adapters}

    async def run_adapter(self, adapter: BaseAdapter) -> CycleReport:
        report = process_result(await fetch_with_timeout(adapter), self.dedup)
        if report.docs:
            try:
                await self.sink(report.docs)
            except Exception:  # a sink failure must not stop ingestion
                log.exception("sink failed for %d docs from %s", len(report.docs), adapter.name)
        return report

    async def run_once(self) -> list[CycleReport]:
        return list(await asyncio.gather(*(self.run_adapter(a) for a in self.adapters)))

    async def run_forever(self, stop: asyncio.Event, tick_s: float = 5.0) -> None:
        log.info("LIVE ingestion started with %d adapters", len(self.adapters))
        running: dict[str, asyncio.Task] = {}
        while not stop.is_set():
            now = time.monotonic()
            for a in self.adapters:
                if now >= self._next_due[a.name] and a.name not in running:
                    self._next_due[a.name] = now + a.interval_s
                    running[a.name] = asyncio.create_task(self.run_adapter(a))
            for name, task in list(running.items()):
                if task.done():
                    running.pop(name)
            try:
                await asyncio.wait_for(stop.wait(), timeout=tick_s)
            except TimeoutError:
                pass
        for task in running.values():
            task.cancel()
        log.info("LIVE ingestion stopped")


def print_reports(reports: list[CycleReport], show: int = 0) -> None:
    hdr = f"{'SOURCE':<12} {'STATUS':<13} {'FETCHED':>7} {'CLEAN':>6} {'NEW':>5} {'SECS':>6}  DETAIL"
    print(hdr)
    print("-" * (len(hdr) + 30))
    for r in reports:
        print(f"{r.source:<12} {r.status.value:<13} {r.fetched:>7} {r.after_clean:>6} {r.new:>5} "
              f"{r.elapsed_s:>6.1f}  {r.detail[:70]}")
        for d in r.docs[:show]:
            print(f"{'':<12}   [{d.provenance.value}] {d.title[:95]}")


async def _cli(once: bool, only: set[str] | None, show: int) -> int:
    async def log_sink(docs: list[RawDocument]) -> None:
        log.info("sink received %d docs", len(docs))

    async with make_http_client() as client:
        sched = IngestionScheduler(build_live_adapters(client, only=only), log_sink)
        if once:
            print_reports(await sched.run_once(), show)
            return 0
        stop = asyncio.Event()
        try:
            await sched.run_forever(stop)
        except (KeyboardInterrupt, asyncio.CancelledError):
            stop.set()
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="LIVE ingestion scheduler")
    ap.add_argument("--once", action="store_true", help="run one cycle of every adapter and print a report")
    ap.add_argument("--sources", help="comma-separated subset, e.g. google_news,mastodon")
    ap.add_argument("--show", type=int, default=2, help="sample titles to print per source")
    args = ap.parse_args()
    setup_logging()
    only = set(args.sources.split(",")) if args.sources else None
    return asyncio.run(_cli(args.once, only, args.show))


if __name__ == "__main__":
    sys.exit(main())
