"""SCENARIO mode: play a scripted, deterministic sequence of SYNTHETIC documents (e.g. the demo story).

File format (JSON):
{
  "name": "demo_story",
  "description": "...",
  "real_opening": {"path": "data/cache/sample/sample_google_news.jsonl", "doc_ids": ["..."], "delay_s": 4},
  "steps": [
    {"delay_s": 0, "imitates": "google_news", "source_type": "news", "title": "...", "text": "...",
     "publisher": "...", "hint_ticker": "AAPL", "hold_after_s": 0}
  ]
}
Every emitted story document has source='scenario', provenance=SYNTHETIC and imitated_source=<imitates>.

`real_opening` (optional, "step 0"): before the story, replay the listed REAL documents from a committed
CACHED_REAL sample, unchanged (their own source, provenance CACHED_REAL and captured_at). A listed doc_id that is
missing from the file is logged and skipped. `hold_after_s` adds a pause after a step even when a fixed
`step_seconds` is used (the demo holds after step 2 so the presenter can show the watchlist).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from risk_engine.logging_setup import get_logger
from risk_engine.schemas import SOURCE_TYPE_OF, Provenance, RawDocument, Source, SourceType, utcnow

log = get_logger(__name__)


class ScenarioStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delay_s: float = Field(default=0.0, ge=0)
    imitates: Source
    source_type: SourceType | None = None
    title: str = Field(min_length=1)
    text: str | None = None
    publisher: str | None = None
    hint_ticker: str | None = None
    user_sentiment_tag: str | None = None
    hold_after_s: float = Field(default=0.0, ge=0)


class RealOpening(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path
    doc_ids: list[str] = Field(min_length=1, max_length=10)
    delay_s: float = Field(default=4.0, ge=0)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    real_opening: RealOpening | None = None
    steps: list[ScenarioStep] = Field(min_length=1)


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def step_to_document(step: ScenarioStep, scenario_name: str, index: int) -> RawDocument:
    st = step.source_type or SOURCE_TYPE_OF.get(step.imitates, SourceType.NEWS)
    return RawDocument.build(
        source=Source.SCENARIO, source_type=st, provenance=Provenance.SYNTHETIC, title=step.title,
        text=step.text or step.title, url=f"scenario://{scenario_name}/{index}", captured_at=utcnow(),
        published_at=utcnow(), publisher=step.publisher or f"SYNTHETIC ({step.imitates.value})",
        hint_ticker=step.hint_ticker, user_sentiment_tag=step.user_sentiment_tag,
        imitated_source=step.imitates,
    )


def load_opening(opening: RealOpening, root: Path) -> list[RawDocument]:
    """The listed CACHED_REAL documents, in the listed order. Missing ids are logged, never invented."""
    path = opening.path if opening.path.is_absolute() else root / opening.path
    found: dict[str, RawDocument] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    doc = RawDocument.model_validate_json(line)
                    if doc.doc_id in opening.doc_ids:
                        found[doc.doc_id] = doc
    else:
        log.warning("scenario real opening: sample file not found: %s", path)
    docs = []
    for doc_id in opening.doc_ids:
        doc = found.get(doc_id)
        if doc is None:
            log.warning("scenario real opening: doc_id %s not in %s; skipped", doc_id, path.name)
        elif doc.provenance is not Provenance.CACHED_REAL:
            log.warning("scenario real opening: %s is %s, not CACHED_REAL; skipped", doc_id, doc.provenance.value)
        else:
            docs.append(doc)
    return docs


async def run_scenario(path: Path, sink: Callable[[list[RawDocument]], Awaitable[None]],
                       step_seconds: float | None = None, root: Path | None = None) -> int:
    """Optional real opening, then each story step after its delay (or a fixed `step_seconds` if given), plus any
    `hold_after_s`. Deterministic order. Returns the number of documents emitted."""
    sc = load_scenario(path)
    n = 0
    if sc.real_opening is not None:
        gap = sc.real_opening.delay_s if step_seconds is None else min(step_seconds, sc.real_opening.delay_s)
        opening = load_opening(sc.real_opening, root or Path.cwd())
        for i, doc in enumerate(opening):
            if i and gap > 0:
                await asyncio.sleep(gap)
            log.info("scenario %s step 0 (real data) %d/%d: %s", sc.name, i + 1, len(opening), doc.title[:80])
            await sink([doc])
            n += 1
    hold = 0.0
    for i, step in enumerate(sc.steps):
        wait = step.delay_s if step_seconds is None else (step_seconds if (i or n) else 0.0)
        if wait + hold > 0:
            await asyncio.sleep(wait + hold)
        doc = step_to_document(step, sc.name, i)
        log.info("scenario %s step %d/%d: %s", sc.name, i + 1, len(sc.steps), doc.title[:80])
        await sink([doc])
        n += 1
        hold = step.hold_after_s
    return n
