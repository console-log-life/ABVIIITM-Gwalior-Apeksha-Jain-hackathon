"""SCENARIO mode: play a scripted, deterministic sequence of SYNTHETIC documents (e.g. the demo story).

File format (JSON):
{
  "name": "demo_story",
  "description": "...",
  "steps": [
    {"delay_s": 0, "imitates": "google_news", "source_type": "news", "title": "...", "text": "...",
     "publisher": "...", "hint_ticker": "AAPL"}
  ]
}
Every emitted document has source='scenario', provenance=SYNTHETIC and imitated_source=<imitates>.
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


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
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


async def run_scenario(path: Path, sink: Callable[[list[RawDocument]], Awaitable[None]],
                       step_seconds: float | None = None) -> int:
    """Emit each step after its delay (or a fixed `step_seconds` if given). Deterministic order."""
    sc = load_scenario(path)
    for i, step in enumerate(sc.steps):
        wait = step.delay_s if step_seconds is None else (step_seconds if i else 0.0)
        if wait > 0:
            await asyncio.sleep(wait)
        doc = step_to_document(step, sc.name, i)
        log.info("scenario %s step %d/%d: %s", sc.name, i + 1, len(sc.steps), doc.title[:80])
        await sink([doc])
    return len(sc.steps)
