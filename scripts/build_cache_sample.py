"""Build the small, publishable REPLAY sample: data/cache/sample/sample_google_news.jsonl.

Takes ~50 Google News headlines (news only, never social posts) from the local capture cache
(data/cache/captures/, which is git-ignored), keeping provenance CACHED_REAL and the real capture timestamps.
REPLAY falls back to this sample when captures/ is empty (e.g. on a fresh clone).

Usage:  python scripts/build_cache_sample.py [--n 50] [--seed 42]
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from risk_engine.ingestion.replay import SAMPLE_FILE, captures_dir, load_cached_documents, sample_dir  # noqa: E402
from risk_engine.schemas import Provenance, Source  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cache = get_settings().cache_path
    if not any(captures_dir(cache).glob("capture_*.jsonl")):
        print(f"no captures in {captures_dir(cache)}; run scripts/capture_cache.py first")
        return 1
    docs = [d for d in load_cached_documents(cache, use_sample=False)
            if d.source is Source.GOOGLE_NEWS and d.provenance is Provenance.CACHED_REAL]
    seen, unique = set(), []
    for d in docs:
        key = d.title.lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    rng = random.Random(args.seed)
    picked = sorted(rng.sample(unique, min(args.n, len(unique))), key=lambda d: (d.published_at or d.captured_at))
    out = sample_dir(cache) / SAMPLE_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        for d in picked:
            fh.write(d.model_dump_json() + "\n")
    print(f"wrote {len(picked)} Google News headlines (CACHED_REAL) to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
