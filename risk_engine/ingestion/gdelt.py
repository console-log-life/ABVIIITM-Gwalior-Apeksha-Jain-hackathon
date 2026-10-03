"""GDELT DOC 2.0 article list — macro/geopolitical background, best-effort only.
GDELT can answer HTTP 200 with a plain-text error, so the body is validated as JSON before use."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote_plus

from risk_engine.ingestion.base import BaseAdapter
from risk_engine.schemas import Provenance, RawDocument, Source


def _parse_seendate(s: str | None) -> datetime | None:
    try:
        return datetime.strptime(s or "", "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_gdelt_body(text: str) -> list[RawDocument]:
    import json

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"GDELT returned non-JSON body: {text[:100]!r}") from exc
    docs: list[RawDocument] = []
    for a in (data.get("articles") or []) if isinstance(data, dict) else []:
        title = (a.get("title") or "").strip()
        if not title or (a.get("language") and a["language"].lower() != "english"):
            continue
        docs.append(RawDocument.build(
            source=Source.GDELT, title=title, url=a.get("url"), provenance=Provenance.LIVE,
            published_at=_parse_seendate(a.get("seendate")), publisher=a.get("domain"),
        ))
    return docs


class GdeltAdapter(BaseAdapter):
    name = "gdelt"
    source = Source.GDELT
    config_key = "gdelt"
    block_max_s = 0.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout_s = self.settings.gdelt_timeout_s

    async def _fetch(self) -> list[RawDocument]:
        q = quote_plus(self.cfg["query"])
        n = int(self.cfg.get("max_records", 50))
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json&maxrecords={n}"
        resp = await self.request("GET", url)
        return parse_gdelt_body(resp.text)
