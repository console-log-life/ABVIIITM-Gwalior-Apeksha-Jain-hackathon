from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.config import Settings
from risk_engine.ingestion.base import HealthRegistry


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, finnhub_api_key="", bluesky_handle="", bluesky_app_password="")


@pytest.fixture
def health() -> HealthRegistry:
    return HealthRegistry()


class Recorder:
    """httpx MockTransport handler that records requests and answers from a user function."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]):
        self.respond = respond
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


@pytest.fixture
def recorder_factory() -> Callable[[Callable[[httpx.Request], httpx.Response]], Recorder]:
    return Recorder


@pytest.fixture(scope="session")
def finbert_engine():
    """ONE FinBERT load per test process (memory: this laptop has ~7.7 GB RAM). Only model-marked tests use it."""
    from risk_engine.sentiment.finbert import SentimentEngine

    return SentimentEngine(Settings(sentiment_backend="finbert"))


@pytest.fixture(autouse=True)
def _no_history_autoload(monkeypatch):
    """Tests start with an empty store; the REAL history is exercised explicitly in tests/test_history.py."""
    monkeypatch.setenv("REAL_HISTORY_AUTOLOAD", "false")
