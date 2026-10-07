"""Build the processed REAL history cache (data/real_history.db) from the CACHED_REAL capture cache.

  python src/scripts/build_real_history.py            # rebuild only if missing/stale
  python src/scripts/build_real_history.py --force    # rebuild anyway

Run it while the API is NOT running (one FinBERT load per process; ~7 GB laptop). The API also builds the cache itself
at startup when it is missing or stale, reusing its own FinBERT.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from app.config import get_settings  # noqa: E402
from risk_engine import history  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    if not args.force and history.is_fresh(s):
        print(f"fresh: {history.history_path(s)} {history.read_meta(history.history_path(s))}")
        return 0
    t0 = time.time()

    def progress(done: int, total: int) -> None:
        print(f"\r  {done}/{total} documents ({time.time() - t0:.0f} s)", end="", flush=True)

    meta = history.build_history(s, progress=progress)
    print(f"\nbuilt {history.history_path(s)}: {meta['signals']} signals, {meta['stress_runs']} simulated stress runs "
          f"from {meta['documents']} {meta['source']} documents ({meta['first_capture']} → {meta['last_capture']}) "
          f"in {meta['build_seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
