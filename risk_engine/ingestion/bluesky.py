"""Bluesky post search via authenticated app.bsky.feed.searchPosts.

Auth: com.atproto.server.createSession with BLUESKY_HANDLE + BLUESKY_APP_PASSWORD (an app password,
never the account password). The session is reused; an expired access token is refreshed once with
refreshSession, then re-created. Skips cleanly when credentials are not set.
"""

from __future__ import annotations

from typing import Any

from risk_engine.ingestion.base import BaseAdapter, HTTPStatusFailure, SourceSkip, parse_iso
from risk_engine.logging_setup import get_logger
from risk_engine.preprocessing.clean import clean_text, make_title, scrub_mentions
from risk_engine.schemas import Provenance, RawDocument, Source

log = get_logger(__name__)
PDS = "https://bsky.social/xrpc"


def parse_bluesky_posts(posts: list[dict], ticker: str | None, query: str = "") -> list[RawDocument]:
    docs: list[RawDocument] = []
    for p in posts:
        record = p.get("record") or {}
        text = scrub_mentions(clean_text(record.get("text")))
        if not text:
            continue
        handle = (p.get("author") or {}).get("handle") or "unknown"
        rkey = (p.get("uri") or "").rsplit("/", 1)[-1]
        docs.append(RawDocument.build(
            source=Source.BLUESKY, title=make_title(text), text=text,
            url=f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else None,
            provenance=Provenance.LIVE, published_at=parse_iso(record.get("createdAt") or p.get("indexedAt")),
            publisher=f"search: {query}" if query else None, hint_ticker=ticker,  # never the author
        ))
    return docs


class _AuthExpired(Exception):
    pass


class BlueskyAdapter(BaseAdapter):
    name = "bluesky"
    source = Source.BLUESKY
    config_key = "bluesky"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._access: str | None = None
        self._refresh: str | None = None

    def enabled(self) -> tuple[bool, str]:
        if self.settings.has_bluesky:
            return True, ""
        return False, "BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set (optional source)"

    async def _create_session(self) -> None:
        resp = await self.request("POST", f"{PDS}/com.atproto.server.createSession", json={
            "identifier": self.settings.bluesky_handle.strip(),
            "password": self.settings.bluesky_app_password.strip(),
        })
        data = resp.json()
        self._access, self._refresh = data["accessJwt"], data["refreshJwt"]
        log.info("bluesky: session created for %s", data.get("handle"))

    async def _refresh_session(self) -> bool:
        if not self._refresh:
            return False
        try:
            resp = await self.request("POST", f"{PDS}/com.atproto.server.refreshSession",
                                      headers={"Authorization": f"Bearer {self._refresh}"})
        except HTTPStatusFailure:
            return False
        data = resp.json()
        self._access, self._refresh = data["accessJwt"], data["refreshJwt"]
        return True

    async def _search(self, q: str) -> list[dict]:
        params: dict[str, Any] = {"q": q, "limit": int(self.cfg.get("limit", 25)), "sort": "latest", "lang": "en"}
        try:
            resp = await self.request("GET", f"{PDS}/app.bsky.feed.searchPosts", params=params,
                                      headers={"Authorization": f"Bearer {self._access}"})
        except HTTPStatusFailure as exc:
            if exc.status_code in (400, 401) and "xpired" in str(exc):
                raise _AuthExpired from exc
            raise
        return resp.json().get("posts") or []

    async def _search_with_auth(self, q: str) -> list[dict]:
        if not self._access:
            await self._create_session()
        try:
            return await self._search(q)
        except _AuthExpired:
            if not await self._refresh_session():
                await self._create_session()
            return await self._search(q)

    async def _fetch(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for item in self.cfg.get("queries", []):
            try:
                posts = await self._search_with_auth(item["q"])
            except SourceSkip:
                if docs:
                    break
                raise
            docs.extend(parse_bluesky_posts(posts, item.get("ticker"), item["q"]))
        return docs
