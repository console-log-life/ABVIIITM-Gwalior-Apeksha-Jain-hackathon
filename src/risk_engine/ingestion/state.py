"""Per-source ingestion state shared by src/scripts/capture_cache.py and LIVE mode (data/cache/state.json):
rate-limit timestamps, backoffs, Reddit rotation index, Mastodon since_ids."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from risk_engine.ingestion.base import BaseAdapter

STATE_FILE = "state.json"


def load_state(cache_dir: Path) -> dict[str, Any]:
    p = cache_dir / STATE_FILE
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply_state(adapters: list[BaseAdapter], cache_dir: Path) -> None:
    state = load_state(cache_dir)
    for a in adapters:
        a.import_state(state.get(a.name, {}))


HEALTH_KEY = "_last_capture_health"


def save_health_snapshot(cache_dir: Path, snapshot: list[dict[str, Any]]) -> None:
    """Keep the per-source health of the last capture run, so the dashboard can show it outside LIVE mode."""
    state = load_state(cache_dir)
    state[HEALTH_KEY] = [{**h, "observed_in": "last capture run"} for h in snapshot]
    _write(cache_dir, state)


def last_capture_health(cache_dir: Path) -> list[dict[str, Any]]:
    return list(load_state(cache_dir).get(HEALTH_KEY) or [])


def _write(cache_dir: Path, state: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, cache_dir / STATE_FILE)


def save_state(cache_dir: Path, adapters: list[BaseAdapter]) -> None:
    state = load_state(cache_dir)
    for a in adapters:
        state[a.name] = a.export_state()
    _write(cache_dir, state)
