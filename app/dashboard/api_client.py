"""Thin HTTP client: the dashboard talks to the FastAPI service ONLY through this module.
Every failure becomes ApiError with a human-readable message (the UI shows it instead of a stack trace)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 15.0):
        self.base_url = (base_url or get_settings().api_base_url).rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                 allow_404: bool = False) -> Any:
        url = f"{self.base_url}{path}"
        try:
            r = httpx.request(method, url, params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                              json=json, timeout=self.timeout)
        except httpx.ConnectError as exc:
            raise ApiError(f"The API is not reachable at {self.base_url}. Start it with: "
                           f"python -m uvicorn app.main:app --port 8000  (or tasks.ps1 api)") from exc
        except httpx.TimeoutException as exc:
            raise ApiError(f"The API at {self.base_url} did not answer within {self.timeout:.0f} s "
                           f"(it may still be loading the FinBERT model).") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Request to {path} failed: {type(exc).__name__}") from exc
        if r.status_code == 404 and allow_404:
            return None
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:200]
            if isinstance(detail, list):
                detail = "; ".join(str(d.get("msg", d)) for d in detail)
            raise ApiError(f"{method} {path} → HTTP {r.status_code}: {detail}")
        return r.json()

    # ---- read
    def health(self) -> dict:
        return self._request("GET", "/health")

    def methodology(self) -> dict:
        return self._request("GET", "/methodology")

    def signals(self, limit: int = 500, as_of: str | None = None, **filters: Any) -> list[dict]:
        return self._request("GET", "/signals", params={"limit": limit, "as_of": as_of, **filters})

    def ticker(self, ticker: str) -> dict:
        return self._request("GET", f"/signals/{ticker}")

    def signal(self, signal_id: str) -> dict | None:
        return self._request("GET", f"/signals/by-id/{signal_id}", allow_404=True)

    def watchlist(self, hours: int | None = None, as_of: str | None = None) -> dict:
        return self._request("GET", "/watchlist", params={"hours": hours, "as_of": as_of})

    def history(self) -> dict:
        return self._request("GET", "/history")

    def history_load(self, rebuild: bool = False) -> dict:
        return self._request("POST", "/history/load", params={"rebuild": str(rebuild).lower()})

    def overview(self, as_of: str | None = None, hours: int = 24) -> dict:
        return self._request("GET", "/overview", params={"as_of": as_of, "hours": hours})

    def portfolio(self) -> dict:
        return self._request("GET", "/portfolio")

    def scenarios(self) -> dict:
        return self._request("GET", "/portfolio/scenarios")

    def latest_stress(self, as_of: str | None = None) -> dict | None:
        return self._request("GET", "/portfolio/stress-test", params={"as_of": as_of}, allow_404=True)

    def stress_runs(self, limit: int = 100, as_of: str | None = None) -> dict:
        return self._request("GET", "/stress-runs", params={"limit": limit, "as_of": as_of})

    def stress_run(self, run_id: str) -> dict | None:
        return self._request("GET", f"/stress-runs/{run_id}", allow_404=True)

    def demo_status(self) -> dict:
        return self._request("GET", "/demo/status")

    # ---- write
    def analyze(self, text: str, ticker: str | None = None, source: str = "manual") -> dict:
        return self._request("POST", "/analyze", json={"text": text, "ticker": ticker or None, "source": source})

    def run_stress(self, body: dict) -> dict:
        return self._request("POST", "/portfolio/stress-test", json=body)

    def demo_start(self, mode: str = "SCENARIO", step_seconds: float | None = None) -> dict:
        return self._request("POST", "/demo/start", json={"mode": mode, "step_seconds": step_seconds})

    def demo_reset(self) -> dict:
        return self._request("POST", "/demo/reset")

    def set_mode(self, mode: str) -> dict:
        return self._request("POST", "/mode", json={"mode": mode})
