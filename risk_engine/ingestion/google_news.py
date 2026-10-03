"""Google News RSS search (keyless). Headline + publisher + timestamp only; links are Google redirects
and are stored as-is (never decoded)."""

from __future__ import annotations

from urllib.parse import quote_plus

import feedparser

from risk_engine.ingestion.base import BaseAdapter, SourceSkip, from_struct_time
from risk_engine.logging_setup import get_logger
from risk_engine.schemas import Provenance, RawDocument, Source

log = get_logger(__name__)


def parse_google_news_feed(content: bytes, ticker: str | None = None, limit: int = 100) -> list[RawDocument]:
    feed = feedparser.parse(content)
    docs: list[RawDocument] = []
    for e in feed.entries[:limit]:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        publisher = (e.get("source") or {}).get("title")
        docs.append(RawDocument.build(
            source=Source.GOOGLE_NEWS, title=title, url=e.get("link"), provenance=Provenance.LIVE,
            published_at=from_struct_time(e.get("published_parsed")), publisher=publisher, hint_ticker=ticker,
        ))
    return docs


class GoogleNewsAdapter(BaseAdapter):
    name = "google_news"
    source = Source.GOOGLE_NEWS
    config_key = "google_news"

    def url_for(self, query: str, edition: str) -> str:
        params = self.cfg["editions"][edition]
        return f"https://news.google.com/rss/search?q={quote_plus(query)}&{params}"

    async def _fetch(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        errors: list[str] = []
        limit = int(self.cfg.get("max_items_per_query", 40))
        for q in self.cfg.get("queries", []):
            try:
                resp = await self.request("GET", self.url_for(q["q"], q.get("edition", "US")))
            except SourceSkip:
                if docs:  # keep what we already have; the source is now parked / rate limited
                    break
                raise
            except Exception as exc:  # one bad query must not lose the others
                errors.append(f"{q['q']}: {type(exc).__name__}")
                continue
            docs.extend(parse_google_news_feed(resp.content, q.get("ticker"), limit))
        if errors:
            log.warning("google_news: %d/%d queries failed: %s", len(errors), len(self.cfg["queries"]), errors[:3])
            if not docs:
                raise RuntimeError(f"all queries failed: {errors[:3]}")
        return docs
