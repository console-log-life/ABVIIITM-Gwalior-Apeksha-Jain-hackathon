"""Finnhub company news (optional; free key). Skips cleanly when FINNHUB_API_KEY is not set."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from risk_engine.ingestion.base import BaseAdapter, SourceSkip, utc_from_ts
from risk_engine.logging_setup import get_logger
from risk_engine.schemas import Provenance, RawDocument, Source

log = get_logger(__name__)


def parse_finnhub_news(items: list[dict], symbol: str) -> list[RawDocument]:
    docs: list[RawDocument] = []
    for it in items:
        title = (it.get("headline") or "").strip()
        if not title:
            continue
        ts = it.get("datetime")
        docs.append(RawDocument.build(
            source=Source.FINNHUB, title=title, text=(it.get("summary") or title), url=it.get("url"),
            provenance=Provenance.LIVE, published_at=utc_from_ts(ts) if ts else None,
            publisher=it.get("source"), hint_ticker=symbol,
        ))
    return docs


class FinnhubAdapter(BaseAdapter):
    name = "finnhub"
    source = Source.FINNHUB
    config_key = "finnhub"

    def enabled(self) -> tuple[bool, str]:
        return (True, "") if self.settings.has_finnhub else (False, "FINNHUB_API_KEY not set (optional source)")

    async def _fetch(self) -> list[RawDocument]:
        today = datetime.now(UTC).date()
        start = today - timedelta(days=int(self.cfg.get("lookback_days", 2)))
        key = self.settings.finnhub_api_key.strip()
        docs: list[RawDocument] = []
        for sym in self.cfg.get("symbols", []):
            try:
                resp = await self.request(
                    "GET", "https://finnhub.io/api/v1/company-news",
                    params={"symbol": sym, "from": str(start), "to": str(today)},
                    headers={"X-Finnhub-Token": key},  # header, not query string, so the key never appears in logs
                )
            except SourceSkip:
                if docs:
                    break
                raise
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError(f"unexpected Finnhub payload for {sym}: {str(data)[:80]}")
            docs.extend(parse_finnhub_news(data, sym))
        return docs
