"""Shared ingestion machinery: rate limiting, backoff, bounded retries, source health, adapter base class.

Every adapter returns a FetchResult and NEVER raises: failures become a logged, user-visible status
(`/health` reads HealthRegistry) and the caller falls back to other sources / cached data.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from risk_engine.logging_setup import get_logger
from risk_engine.schemas import RawDocument, Source

log = get_logger(__name__)
SOURCES_YAML = Path(__file__).with_name("sources.yaml")


@lru_cache(maxsize=1)
def load_sources_config(path: str | None = None) -> dict[str, Any]:
    with open(path or SOURCES_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# --------------------------------------------------------------------------- rate limiting / backoff

class TokenBucket:
    """`capacity` requests may burst; one token refills every `min_gap_s` seconds. Wall-clock based so
    state can be persisted across processes (capture runs)."""

    def __init__(self, capacity: int, min_gap_s: float, clock: Callable[[], float] = time.time):
        self.capacity = max(1, int(capacity))
        self.min_gap_s = float(min_gap_s)
        self._clock = clock
        self._tokens = float(self.capacity)
        self._updated = clock()
        self.last_taken: float | None = None

    def _refill(self) -> None:
        now = self._clock()
        if self.min_gap_s > 0:
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) / self.min_gap_s)
        else:
            self._tokens = float(self.capacity)
        self._updated = now

    def wait_time(self) -> float:
        self._refill()
        return 0.0 if self._tokens >= 1 else (1 - self._tokens) * self.min_gap_s

    def try_acquire(self) -> bool:
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            self.last_taken = self._clock()
            return True
        return False

    def restore(self, last_taken: float) -> None:
        """Rebuild state as if the most recent request happened at `last_taken` (wall clock)."""
        self.last_taken = last_taken
        self._tokens = 0.0
        self._updated = last_taken
        self._refill()


class SourceStatus(str, Enum):
    OK = "OK"
    EMPTY = "EMPTY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    BACKOFF = "BACKOFF"
    RATE_LIMITED = "RATE_LIMITED"
    DISABLED = "DISABLED"


@dataclass
class SourceHealth:
    source: str
    status: SourceStatus = SourceStatus.OK
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    last_count: int = 0
    last_error: str | None = None
    consecutive_failures: int = 0
    backoff_until: datetime | None = None
    total_docs: int = 0

    def as_dict(self) -> dict[str, Any]:
        d = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.__dict__.items()}
        d["status"] = self.status.value
        return d


class HealthRegistry:
    def __init__(self) -> None:
        self._by_source: dict[str, SourceHealth] = {}

    def get(self, name: str) -> SourceHealth:
        return self._by_source.setdefault(name, SourceHealth(source=name))

    def snapshot(self) -> list[dict[str, Any]]:
        return [h.as_dict() for h in sorted(self._by_source.values(), key=lambda h: h.source)]

    def reset(self) -> None:
        self._by_source.clear()


HEALTH = HealthRegistry()


# --------------------------------------------------------------------------- errors and results

class SourceSkip(Exception):
    """Expected, non-error reason not to fetch now (disabled, rate limit, active backoff)."""

    def __init__(self, status: SourceStatus, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class HTTPStatusFailure(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        super().__init__(f"HTTP {status_code} {detail}".strip())
        self.status_code = status_code


class _Retryable(Exception):
    """5xx responses — retried like transport errors."""


@dataclass
class FetchResult:
    source: str
    status: SourceStatus
    docs: list[RawDocument] = field(default_factory=list)
    detail: str = ""
    elapsed_s: float = 0.0


def utc_from_ts(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


def from_struct_time(st: time.struct_time | None) -> datetime | None:
    """feedparser *_parsed fields are UTC struct_time."""
    if not st:
        return None
    try:
        return datetime(*st[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


# --------------------------------------------------------------------------- adapter base

class BaseAdapter(ABC):
    """Subclasses implement `_fetch()`; `fetch()` adds rate limiting, backoff and health bookkeeping."""

    name: str
    source: Source
    config_key: str
    block_max_s: float = 3.0  # wait at most this long for a token, otherwise skip this cycle

    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None,
                 config: dict[str, Any] | None = None, clock: Callable[[], float] = time.time,
                 health: HealthRegistry | None = None):
        self.client = client
        self.settings = settings or get_settings()
        self.cfg = config if config is not None else load_sources_config().get(self.config_key, {})
        self.clock = clock
        self.health = health or HEALTH
        self.interval_s = float(self.cfg.get("interval_s", 600))
        self.bucket = TokenBucket(self.cfg.get("capacity", 1), self.cfg.get("min_gap_s", 1.0), clock)
        self.backoff_until: float = 0.0
        self.timeout_s = self.settings.http_timeout_s

    # ---- hooks
    def enabled(self) -> tuple[bool, str]:
        return True, ""

    @abstractmethod
    async def _fetch(self) -> list[RawDocument]: ...

    # ---- persisted state (capture_cache runs are separate processes)
    def export_state(self) -> dict[str, Any]:
        return {"backoff_until": self.backoff_until, "last_request_at": self.bucket.last_taken}

    def import_state(self, state: dict[str, Any]) -> None:
        self.backoff_until = float(state.get("backoff_until") or 0.0)
        if state.get("last_request_at"):
            self.bucket.restore(float(state["last_request_at"]))

    # ---- helpers for subclasses
    def park(self, seconds: float, reason: str) -> None:
        self.backoff_until = self.clock() + seconds
        log.warning("source %s backing off %.0fs: %s", self.name, seconds, reason)

    async def acquire(self) -> None:
        wait = self.bucket.wait_time()
        if wait > self.block_max_s:
            raise SourceSkip(SourceStatus.RATE_LIMITED, f"rate limit: next request allowed in {wait:.0f}s")
        if wait > 0:
            # small margin: sleeping exactly `wait` can leave the bucket at 0.9999 tokens (float rounding)
            await asyncio.sleep(wait + 0.05)
        if not self.bucket.try_acquire():
            raise SourceSkip(SourceStatus.RATE_LIMITED, "rate limit (token not refilled after wait)")

    async def request(self, method: str, url: str, *, timeout: float | None = None,
                      **kwargs: Any) -> httpx.Response:
        """One logical request: token bucket, timeout, max N retries on transport errors / 5xx.
        429 parks the source (backoff_429_s); 403 parks it (backoff_403_s); other 4xx raise."""
        await self.acquire()
        attempts = 1 + self.settings.http_max_retries
        resp: httpx.Response | None = None
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=0.5, max=4),
            retry=retry_if_exception_type((httpx.TransportError, _Retryable)),
            reraise=True,
        ):
            with attempt:
                resp = await self.client.request(method, url, timeout=timeout or self.timeout_s, **kwargs)
                if resp.status_code >= 500:
                    raise _Retryable(f"HTTP {resp.status_code}")
        assert resp is not None
        if resp.status_code == 429:
            self.park(float(self.cfg.get("backoff_429_s", 900)), "HTTP 429")
            raise SourceSkip(SourceStatus.BACKOFF, "HTTP 429 — rate limited by source")
        if resp.status_code == 403:
            self.park(float(self.cfg.get("backoff_403_s", 3600)), "HTTP 403")
            raise SourceSkip(SourceStatus.BACKOFF, "HTTP 403 — blocked by source")
        if resp.status_code >= 400:
            raise HTTPStatusFailure(resp.status_code, resp.text[:120])
        return resp

    # ---- public entry point
    async def fetch(self) -> FetchResult:
        h = self.health.get(self.name)
        t0 = time.perf_counter()
        now_dt = datetime.now(UTC)
        h.last_attempt = now_dt
        ok, why = self.enabled()
        if not ok:
            h.status, h.last_error = SourceStatus.DISABLED, why
            return FetchResult(self.name, SourceStatus.DISABLED, detail=why)
        if self.clock() < self.backoff_until:
            remaining = self.backoff_until - self.clock()
            h.status, h.backoff_until = SourceStatus.BACKOFF, utc_from_ts(self.backoff_until)
            return FetchResult(self.name, SourceStatus.BACKOFF, detail=f"backing off, {remaining:.0f}s left")
        try:
            docs = await self._fetch()
        except SourceSkip as skip:
            h.status, h.last_error = skip.status, skip.detail
            h.backoff_until = utc_from_ts(self.backoff_until) if self.backoff_until > self.clock() else None
            log.info("source %s skipped: %s", self.name, skip.detail)
            return FetchResult(self.name, skip.status, detail=skip.detail, elapsed_s=time.perf_counter() - t0)
        except Exception as exc:  # any failure becomes a status, never a crash
            h.consecutive_failures += 1
            h.status = SourceStatus.DOWN if h.consecutive_failures >= 3 else SourceStatus.DEGRADED
            h.last_error = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("source %s failed (%d in a row): %s", self.name, h.consecutive_failures, h.last_error)
            return FetchResult(self.name, h.status, detail=h.last_error, elapsed_s=time.perf_counter() - t0)
        h.consecutive_failures, h.last_error, h.backoff_until = 0, None, None
        h.status = SourceStatus.OK if docs else SourceStatus.EMPTY
        h.last_success, h.last_count = now_dt, len(docs)
        h.total_docs += len(docs)
        return FetchResult(self.name, h.status, docs=docs, elapsed_s=time.perf_counter() - t0)
