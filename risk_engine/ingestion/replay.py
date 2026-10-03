"""REPLAY mode: stream real articles captured earlier by scripts/capture_cache.py.

Cache layout: data/cache/captures/capture_<YYYYMMDDTHHMMSSZ>.jsonl, one RawDocument per line, provenance
CACHED_REAL, `captured_at` = the moment it was fetched live. Replay never alters captured_at, so the UI can
show when the data was really captured.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from pydantic import ValidationError

from risk_engine.logging_setup import get_logger
from risk_engine.preprocessing.clean import repair_hashtag_spacing
from risk_engine.schemas import Provenance, RawDocument

log = get_logger(__name__)
CAPTURE_GLOB = "capture_*.jsonl"


def captures_dir(cache_dir: Path) -> Path:
    return cache_dir / "captures"


def load_cached_documents(cache_dir: Path) -> list[RawDocument]:
    """All cached docs, oldest first (by published_at, falling back to captured_at). Bad lines are skipped."""
    docs: list[RawDocument] = []
    seen: set[str] = set()
    for f in sorted(captures_dir(cache_dir).glob(CAPTURE_GLOB)):
        with open(f, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    doc = RawDocument.model_validate_json(line)
                except ValidationError as exc:
                    log.warning("replay: skipping invalid line %s:%d (%s)", f.name, lineno, exc.error_count())
                    continue
                if doc.provenance is not Provenance.CACHED_REAL:
                    log.warning("replay: %s:%d has provenance %s; relabelling CACHED_REAL", f.name, lineno,
                                doc.provenance.value)
                    doc = doc.model_copy(update={"provenance": Provenance.CACHED_REAL})
                fixed = {k: repair_hashtag_spacing(getattr(doc, k)) for k in ("title", "text")}
                if fixed["title"] != doc.title or fixed["text"] != doc.text:  # re-clean older captures on load
                    doc = doc.model_copy(update=fixed)
                if doc.doc_id in seen:
                    continue
                seen.add(doc.doc_id)
                docs.append(doc)
    docs.sort(key=lambda d: (d.published_at or d.captured_at, d.doc_id))
    return docs


async def iter_replay(cache_dir: Path, delay_s: float = 0.0, limit: int | None = None,
                      batch_size: int = 1) -> AsyncIterator[list[RawDocument]]:
    docs = load_cached_documents(cache_dir)
    if limit is not None:
        docs = docs[-limit:]  # most recent captures
    for i in range(0, len(docs), batch_size):
        yield docs[i : i + batch_size]
        if delay_s > 0:
            await asyncio.sleep(delay_s)


async def run_replay(cache_dir: Path, sink: Callable[[list[RawDocument]], Awaitable[None]],
                     delay_s: float = 0.0, limit: int | None = None, batch_size: int = 1) -> int:
    n = 0
    async for batch in iter_replay(cache_dir, delay_s, limit, batch_size):
        await sink(batch)
        n += len(batch)
    log.info("replay: streamed %d cached documents", n)
    return n


def main() -> int:
    """CLI: python -m risk_engine.ingestion.replay [--limit 10] [--delay 0.5]"""
    import argparse
    import sys

    from app.config import get_settings

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Stream cached real documents (REPLAY mode)")
    ap.add_argument("--limit", type=int, default=10, help="most recent N documents (0 = all)")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between documents")
    args = ap.parse_args()

    async def printer(batch: list[RawDocument]) -> None:
        for d in batch:
            print(f"[{d.provenance.value} captured {d.captured_at:%Y-%m-%d %H:%M}Z] "
                  f"{d.source.value:<11} {d.title[:90]}")

    n = asyncio.run(run_replay(get_settings().cache_path, printer, args.delay, args.limit or None))
    print(f"\nreplayed {n} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
