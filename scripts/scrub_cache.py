"""Privacy scrub for existing captures: remove author handles from data/cache/captures/*.jsonl.

- `publisher` values that are author handles ("@name") are replaced by the channel the post came from
  (StockTwits: "$TICKER stream"; others: the source name). Subreddit names ("r/stocks") are kept.
- @mentions inside social titles/text are replaced by "@user".
- Post URLs are kept (user decision: source + post URL may remain).
Idempotent; files are rewritten atomically. Exit code 1 if any handle remains afterwards.

Usage:  python scripts/scrub_cache.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from risk_engine.ingestion.replay import CAPTURE_GLOB, captures_dir  # noqa: E402
from risk_engine.preprocessing.clean import scrub_mentions  # noqa: E402

SOCIAL = {"reddit", "mastodon", "bluesky", "stocktwits"}
HANDLE_PUBLISHER = re.compile(r'"publisher":\s*"@')


def scrub_record(rec: dict) -> tuple[dict, bool]:
    changed = False
    pub = rec.get("publisher")
    if isinstance(pub, str) and pub.startswith("@"):
        rec["publisher"] = f"${rec['hint_ticker']} stream" if rec.get("source") == "stocktwits" and rec.get(
            "hint_ticker") else rec.get("source")
        changed = True
    if rec.get("source") in SOCIAL:
        for field in ("title", "text"):
            if isinstance(rec.get(field), str):
                new = scrub_mentions(rec[field])
                if new != rec[field]:
                    rec[field], changed = new, True
    return rec, changed


def scrub_file(path: Path, dry_run: bool) -> int:
    out_lines, n_changed = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec, changed = scrub_record(json.loads(line))
        n_changed += changed
        out_lines.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
    if n_changed and not dry_run:
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    return n_changed


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(captures_dir(get_settings().cache_path).glob(CAPTURE_GLOB))
    total = 0
    for f in files:
        n = scrub_file(f, args.dry_run)
        total += n
        print(f"{f.name}: {n} records {'would be ' if args.dry_run else ''}scrubbed")
    remaining = sum(len(HANDLE_PUBLISHER.findall(f.read_text(encoding="utf-8"))) for f in files)
    print(f"\ntotal scrubbed: {total}; author-handle publishers remaining: {remaining}")
    return 0 if (remaining == 0 or args.dry_run) else 1


if __name__ == "__main__":
    sys.exit(main())
