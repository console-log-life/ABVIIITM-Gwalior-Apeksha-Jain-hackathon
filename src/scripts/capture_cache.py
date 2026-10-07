"""Capture real articles/posts from every live source into data/cache/ for REPLAY mode.

Run it 2-3 times a day. Each run:
  - fetches from all configured live sources once (sources without keys are skipped cleanly);
  - cleans + dedups against EVERYTHING already in the cache (exact + same-source near-duplicates);
  - writes only new documents to data/cache/captures/capture_<UTC timestamp>.jsonl,
    labelled provenance=CACHED_REAL with captured_at = the real fetch time;
  - persists per-source state (Reddit rotation, backoffs, Mastodon since_ids) in data/cache/state.json,
    so consecutive runs rotate subreddits and respect Reddit's 120 s gap / 15 min backoff.

Usage:  python src/scripts/capture_cache.py [--sources google_news,reddit] [--show 3] [-v]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from risk_engine.ingestion.base import HEALTH, BaseAdapter, SourceStatus  # noqa: E402
from risk_engine.ingestion.replay import captures_dir, load_cached_documents  # noqa: E402
from risk_engine.ingestion.scheduler import (  # noqa: E402
    CycleReport,
    build_live_adapters,
    fetch_with_timeout,
    make_http_client,
    print_reports,
    process_result,
)
from risk_engine.ingestion.state import apply_state, save_health_snapshot, save_state  # noqa: E402
from risk_engine.logging_setup import setup_logging  # noqa: E402
from risk_engine.preprocessing.dedup import Deduplicator  # noqa: E402
from risk_engine.schemas import Provenance, RawDocument  # noqa: E402


def write_capture(cache_dir: Path, docs: list[RawDocument], stamp: datetime) -> Path | None:
    if not docs:
        return None
    out_dir = captures_dir(cache_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"capture_{stamp.strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        for d in docs:
            fh.write(d.model_dump_json() + "\n")
    os.replace(tmp, path)  # atomic: replay never sees a half-written file
    return path


async def capture(
    adapters: list[BaseAdapter], cache_dir: Path, threshold: int = 92
) -> tuple[list[CycleReport], Path | None]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    apply_state(adapters, cache_dir)

    dedup = Deduplicator(threshold)
    dedup.seed(load_cached_documents(cache_dir, use_sample=False))  # dedup against real captures only

    stamp = datetime.now(UTC)
    results = await asyncio.gather(*(fetch_with_timeout(a) for a in adapters))
    reports = [process_result(r, dedup) for r in results]

    new_docs = [d.model_copy(update={"provenance": Provenance.CACHED_REAL}) for r in reports for d in r.docs]
    path = write_capture(cache_dir, new_docs, stamp)
    save_state(cache_dir, adapters)
    save_health_snapshot(cache_dir, HEALTH.snapshot())
    return reports, path


async def _main(only: set[str] | None, show: int) -> int:
    settings = get_settings()
    cache_dir = settings.cache_path
    async with make_http_client(settings) as client:
        adapters = build_live_adapters(client, settings, only)
        reports, path = await capture(adapters, cache_dir, settings.near_dup_threshold)

    print_reports(reports, show)
    total_new = sum(r.new for r in reports)
    by_type = Counter(d.source_type.value for r in reports for d in r.docs)
    print(f"\nnew documents: {total_new}  (news={by_type.get('news', 0)}, social={by_type.get('social', 0)})")
    print(f"written to:    {path if path else '(nothing new — no file written)'}")
    total = len(load_cached_documents(cache_dir, use_sample=False))
    print(f"cache total:   {total} documents in {captures_dir(cache_dir)}")
    working = [r for r in reports if r.status in (SourceStatus.OK, SourceStatus.EMPTY)]
    return 0 if working else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", help="comma-separated subset of sources")
    ap.add_argument("--show", type=int, default=2, help="sample new titles to print per source")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    setup_logging("INFO" if args.verbose else "WARNING")
    only = set(args.sources.split(",")) if args.sources else None
    return asyncio.run(_main(only, args.show))


if __name__ == "__main__":
    sys.exit(main())
