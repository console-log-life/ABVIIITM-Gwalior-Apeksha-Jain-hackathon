"""In-process async pub/sub (spec 7.2). Topics: signal.created, stress.completed.

- Handlers (async callables) run in subscription order; one failing handler is logged and does not stop others.
- Queue subscribers (SSE clients) get a bounded asyncio.Queue; if a slow client's queue is full the event is
  dropped for that client only.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from risk_engine.logging_setup import get_logger

log = get_logger(__name__)
SIGNAL_CREATED = "signal.created"
STRESS_COMPLETED = "stress.completed"
TOPICS = (SIGNAL_CREATED, STRESS_COMPLETED)
Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self, queue_size: int = 1000):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._queues: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self.queue_size = queue_size
        self.published: dict[str, int] = defaultdict(int)

    @staticmethod
    def _check(topic: str) -> None:
        if topic not in TOPICS:
            raise ValueError(f"unknown topic {topic!r}; expected one of {TOPICS}")

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._check(topic)
        self._handlers[topic].append(handler)

    def open_queue(self, topic: str) -> asyncio.Queue:
        self._check(topic)
        q: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._queues[topic].add(q)
        return q

    def close_queue(self, topic: str, q: asyncio.Queue) -> None:
        self._queues[topic].discard(q)

    def subscriber_count(self, topic: str) -> int:
        return len(self._handlers[topic]) + len(self._queues[topic])

    async def publish(self, topic: str, payload: Any) -> None:
        self._check(topic)
        self.published[topic] += 1
        for q in list(self._queues[topic]):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("bus: dropping %s event for a slow queue subscriber", topic)
        for h in list(self._handlers[topic]):
            try:
                await h(payload)
            except Exception:
                log.exception("bus: handler %r failed on %s", getattr(h, "__qualname__", h), topic)
