"""Per-source ingestion state shared by scripts/capture_cache.py and LIVE mode (data/cache/state.json):
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


def save_state(cache_dir: Path, adapters: list[BaseAdapter]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(cache_dir)
    for a in adapters:
        state[a.name] = a.export_state()
    tmp = cache_dir / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, cache_dir / STATE_FILE)
