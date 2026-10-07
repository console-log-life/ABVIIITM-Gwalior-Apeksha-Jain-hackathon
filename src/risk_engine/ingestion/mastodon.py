"""Mastodon public hashtag timelines (keyless). Added after it PASSED src/scripts/probe_sources.py.
Uses since_id per tag so each cycle only asks for posts newer than the last one seen."""

from __future__ import annotations

from typing import Any

from risk_engine.ingestion.base import BaseAdapter, SourceSkip, parse_iso
from risk_engine.preprocessing.clean import clean_text, make_title, scrub_mentions
from risk_engine.schemas import Provenance, RawDocument, Source


def parse_mastodon_statuses(statuses: list[dict], tag: str) -> list[RawDocument]:
    docs: list[RawDocument] = []
    for st in statuses:
        if st.get("reblog"):  # boosts duplicate the original post
            continue
        if st.get("language") not in (None, "en"):
            continue
        text = scrub_mentions(clean_text(st.get("content")))
        if not text:
            continue
        docs.append(RawDocument.build(
            source=Source.MASTODON, title=make_title(text), text=text, url=st.get("url") or st.get("uri"),
            provenance=Provenance.LIVE, published_at=parse_iso(st.get("created_at")),
            publisher=f"#{tag}",  # the channel, never the author (privacy)
        ))
    return docs


class MastodonAdapter(BaseAdapter):
    name = "mastodon"
    source = Source.MASTODON
    config_key = "mastodon"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.since_ids: dict[str, str] = {}

    def export_state(self) -> dict[str, Any]:
        return {**super().export_state(), "since_ids": dict(self.since_ids)}

    def import_state(self, state: dict[str, Any]) -> None:
        super().import_state(state)
        self.since_ids = dict(state.get("since_ids") or {})

    async def _fetch(self) -> list[RawDocument]:
        instance = self.cfg.get("instance", "mastodon.social")
        docs: list[RawDocument] = []
        for tag in self.cfg.get("tags", []):
            params: dict[str, Any] = {"limit": int(self.cfg.get("limit", 40))}
            if tag in self.since_ids:
                params["since_id"] = self.since_ids[tag]
            try:
                resp = await self.request("GET", f"https://{instance}/api/v1/timelines/tag/{tag}", params=params)
            except SourceSkip:
                if docs:
                    break
                raise
            statuses = resp.json()
            if not isinstance(statuses, list):
                raise ValueError(f"unexpected Mastodon payload for #{tag}")
            if statuses:
                self.since_ids[tag] = str(max(statuses, key=lambda s: int(s.get("id", 0)))["id"])
            docs.extend(parse_mastodon_statuses(statuses, tag))
        return docs
