"""Replay, scenario, capture_cache and scheduler — all offline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from risk_engine.ingestion.base import SourceStatus
from risk_engine.ingestion.reddit_rss import RedditRSSAdapter
from risk_engine.ingestion.replay import captures_dir, load_cached_documents, run_replay
from risk_engine.ingestion.scenario import load_scenario, run_scenario
from risk_engine.ingestion.scheduler import IngestionScheduler
from risk_engine.schemas import Provenance, RawDocument, Source, SourceType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import capture_cache  # noqa: E402

REDDIT_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Infosys wins large deal from European bank client</title>
<link href="https://www.reddit.com/r/x/comments/1"/><updated>2026-10-03T09:00:00+00:00</updated></entry>
</feed>"""


def _cached(title: str, captured: str, published: str | None = None) -> RawDocument:
    return RawDocument.build(source=Source.GOOGLE_NEWS, title=title, url=f"u/{title}",
                             provenance=Provenance.CACHED_REAL, captured_at=captured, published_at=published)


def test_replay_loads_sorted_cached_real_and_skips_bad_lines(tmp_path):
    d = captures_dir(tmp_path)
    d.mkdir(parents=True)
    later = _cached("Later story about bonds", "2026-10-03T12:00:00Z")
    earlier = _cached("Earlier story about rates", "2026-10-02T12:00:00Z")
    live = RawDocument.build(source=Source.GDELT, title="Mislabelled live doc", provenance=Provenance.LIVE,
                             captured_at="2026-10-01T00:00:00Z")
    (d / "capture_20261003T120000Z.jsonl").write_text(
        later.model_dump_json() + "\n{not json}\n" + live.model_dump_json() + "\n", encoding="utf-8")
    (d / "capture_20261002T120000Z.jsonl").write_text(earlier.model_dump_json() + "\n", encoding="utf-8")
    docs = load_cached_documents(tmp_path)
    assert [x.title for x in docs] == ["Mislabelled live doc", "Earlier story about rates", "Later story about bonds"]
    assert all(x.provenance is Provenance.CACHED_REAL for x in docs)
    assert docs[1].captured_at.isoformat().startswith("2026-10-02T12:00")  # capture time preserved


async def test_run_replay_streams_everything(tmp_path):
    d = captures_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "capture_1.jsonl").write_text(
        "".join(_cached(f"Story number {i}", "2026-10-03T00:00:00Z").model_dump_json() + "\n" for i in range(5)),
        encoding="utf-8")
    got: list[RawDocument] = []

    async def sink(batch):
        got.extend(batch)

    assert await run_replay(tmp_path, sink, batch_size=2) == 5 and len(got) == 5


async def test_scenario_emits_synthetic_docs(tmp_path):
    p = tmp_path / "story.json"
    p.write_text(json.dumps({"name": "t", "steps": [
        {"imitates": "google_news", "title": "Example Corp downgraded to junk", "hint_ticker": "AAPL"},
        {"imitates": "reddit", "title": "Everyone is selling Example Corp"},
    ]}), encoding="utf-8")
    assert len(load_scenario(p).steps) == 2
    got: list[RawDocument] = []

    async def sink(batch):
        got.extend(batch)

    await run_scenario(p, sink, step_seconds=0)
    assert all(d.provenance is Provenance.SYNTHETIC and d.source is Source.SCENARIO for d in got)
    assert got[0].imitated_source is Source.GOOGLE_NEWS and got[0].source_type is SourceType.NEWS
    assert got[1].imitated_source is Source.REDDIT and got[1].source_type is SourceType.SOCIAL


async def test_capture_dedups_across_runs_and_persists_rotation(tmp_path, settings, clock, health):
    def respond(r):
        return httpx.Response(200, content=REDDIT_ATOM)

    cfg = {"interval_s": 600, "capacity": 1, "min_gap_s": 120, "backoff_429_s": 900, "subreddits": ["a", "b"]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        reports1, path1 = await capture_cache.capture([RedditRSSAdapter(c, settings, cfg, clock, health)], tmp_path)
        clock.advance(121)
        reports2, path2 = await capture_cache.capture([RedditRSSAdapter(c, settings, cfg, clock, health)], tmp_path)
    assert reports1[0].new == 1 and path1 is not None
    assert reports2[0].status is SourceStatus.OK and reports2[0].new == 0 and path2 is None
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["reddit"]["next_index"] == 0  # a -> b -> a
    saved = load_cached_documents(tmp_path)
    assert len(saved) == 1 and saved[0].provenance is Provenance.CACHED_REAL


async def test_capture_respects_reddit_gap_between_runs(tmp_path, settings, clock, health):
    cfg = {"interval_s": 600, "capacity": 1, "min_gap_s": 120, "subreddits": ["a", "b"]}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=REDDIT_ATOM))
    async with httpx.AsyncClient(transport=transport) as c:
        await capture_cache.capture([RedditRSSAdapter(c, settings, cfg, clock, health)], tmp_path)
        clock.advance(60)
        reports, _ = await capture_cache.capture([RedditRSSAdapter(c, settings, cfg, clock, health)], tmp_path)
    assert reports[0].status is SourceStatus.RATE_LIMITED


async def test_scheduler_survives_sink_failure_and_source_failure(settings, clock, health):
    def respond(r):
        return httpx.Response(200, content=REDDIT_ATOM) if "/r/ok/" in str(r.url) else httpx.Response(500)

    async def bad_sink(docs):
        raise RuntimeError("downstream exploded")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        ok = RedditRSSAdapter(c, settings, {"subreddits": ["ok"], "min_gap_s": 0}, clock, health)
        broken = RedditRSSAdapter(c, settings, {"subreddits": ["broken"], "min_gap_s": 0}, clock, health)
        broken.name = "reddit_broken"
        reports = await IngestionScheduler([ok, broken], bad_sink).run_once()
    by = {r.source: r for r in reports}
    assert by["reddit"].new == 1 and by["reddit"].status is SourceStatus.OK
    assert by["reddit_broken"].status is SourceStatus.DEGRADED
