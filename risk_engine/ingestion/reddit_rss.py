"""Reddit public subreddit RSS (keyless, best-effort). Reddit throttles unauthenticated feeds hard, so:
- ONE subreddit per cycle, rotating through the configured list;
- at least `min_gap_s` (120 s) between ANY two Reddit requests (token bucket, capacity 1, never waits);
- HTTP 429 parks the source for `backoff_429_s` (15 min).
Rotation index and backoff are exportable so separate capture runs continue the rotation."""

from __future__ import annotations

from typing import Any

import feedparser

from risk_engine.ingestion.base import BaseAdapter, SourceSkip, SourceStatus, from_struct_time
from risk_engine.preprocessing.clean import clean_text
from risk_engine.schemas import Provenance, RawDocument, Source


def parse_reddit_feed(content: bytes, subreddit: str) -> list[RawDocument]:
    feed = feedparser.parse(content)
    docs: list[RawDocument] = []
    for e in feed.entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        body_html = (e.get("content") or [{}])[0].get("value") or e.get("summary") or ""
        body = clean_text(body_html)
        text = f"{title}. {body}" if body and body != title else title
        docs.append(RawDocument.build(
            source=Source.REDDIT, title=title, text=text, url=e.get("link"), provenance=Provenance.LIVE,
            published_at=from_struct_time(e.get("published_parsed") or e.get("updated_parsed")),
            publisher=f"r/{subreddit}",
        ))
    return docs


class RedditRSSAdapter(BaseAdapter):
    name = "reddit"
    source = Source.REDDIT
    config_key = "reddit"
    block_max_s = 0.0  # never sleep 120 s inside a cycle — skip and try next cycle

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subreddits: list[str] = list(self.cfg.get("subreddits", ["stocks"]))
        self.next_index = 0
        self.last_subreddit: str | None = None

    def export_state(self) -> dict[str, Any]:
        return {**super().export_state(), "next_index": self.next_index}

    def import_state(self, state: dict[str, Any]) -> None:
        super().import_state(state)
        self.next_index = int(state.get("next_index", 0)) % max(1, len(self.subreddits))

    async def _fetch(self) -> list[RawDocument]:
        sub = self.subreddits[self.next_index % len(self.subreddits)]
        try:
            resp = await self.request("GET", f"https://www.reddit.com/r/{sub}/new/.rss")
        except SourceSkip as skip:
            if skip.status is not SourceStatus.RATE_LIMITED:  # a request was sent and failed
                self._advance(sub)
            raise  # RATE_LIMITED: nothing was sent, so retry this same subreddit next cycle
        except Exception:
            self._advance(sub)  # one bad subreddit must not block the others
            raise
        self._advance(sub)
        return parse_reddit_feed(resp.content, sub)

    def _advance(self, sub: str) -> None:
        self.last_subreddit = sub
        self.next_index = (self.next_index + 1) % len(self.subreddits)
