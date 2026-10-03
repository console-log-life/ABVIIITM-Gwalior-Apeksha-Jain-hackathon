"""StockTwits symbol stream (unofficial, best-effort; currently 403-blocked from our network).
Messages may carry a user Bullish/Bearish tag, kept as a weak label."""

from __future__ import annotations

from risk_engine.ingestion.base import BaseAdapter, SourceSkip, parse_iso
from risk_engine.preprocessing.clean import clean_text, make_title, scrub_mentions
from risk_engine.schemas import Provenance, RawDocument, Source


def parse_stocktwits(payload: dict, symbol: str) -> list[RawDocument]:
    docs: list[RawDocument] = []
    for m in payload.get("messages") or []:
        body = scrub_mentions(clean_text(m.get("body")))
        if not body:
            continue
        user = (m.get("user") or {}).get("username") or "unknown"
        tag = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        docs.append(RawDocument.build(
            source=Source.STOCKTWITS, title=make_title(body), text=body,
            url=f"https://stocktwits.com/{user}/message/{m.get('id')}", provenance=Provenance.LIVE,
            published_at=parse_iso(m.get("created_at")), hint_ticker=symbol,
            publisher=f"${symbol} stream",  # the channel, never the author (privacy)
            user_sentiment_tag=tag if tag in ("Bullish", "Bearish") else None,
        ))
    return docs


class StockTwitsAdapter(BaseAdapter):
    name = "stocktwits"
    source = Source.STOCKTWITS
    config_key = "stocktwits"

    async def _fetch(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for sym in self.cfg.get("symbols", []):
            try:
                resp = await self.request("GET", f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json")
            except SourceSkip:
                if docs:
                    break
                raise
            docs.extend(parse_stocktwits(resp.json(), sym))
        return docs
