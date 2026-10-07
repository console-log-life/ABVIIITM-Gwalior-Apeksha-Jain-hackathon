"""Measure the RAM the offline demo needs: start it like `tasks.ps1 demo-offline`, play the story, load the pages.

  python src/scripts/measure_demo_ram.py [--out docs/verification/demo_ram.md]

Samples once per second: the summed resident memory (RSS) of the demo's whole process tree (run_demo, API, dashboard)
and the system's free RAM. Steps: wait for "ready on REAL data" (API up, REAL history loaded, dashboard up), request
every dashboard page over HTTP, play the scripted story through the API, then stop everything. Exit code 0 only if the
demo started cleanly (no error in the logs) and the story produced GREEN -> AMBER -> RED.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[2]
API, UI = "http://127.0.0.1:8000", "http://127.0.0.1:8501"
CAVEAT = ("Caveats: the page check is HTTP only (Streamlit runs a page's script when a browser connects; the "
          "browser's own memory is not counted; every page and control is rendered in a real browser by "
          "src/scripts/verify_dashboard.py). Under memory pressure Windows trims working sets, so the peak may be "
          "understated.")
PAGES = ["","Early_Warning_Watchlist", "Risk_Propagation", "News_Social_Feed", "NLP_Risk_Signals", "Portfolio",
         "Stress_Test", "Explainability", "Source_Health"]


class Sampler(threading.Thread):
    def __init__(self, root_pid: int):
        super().__init__(daemon=True)
        self.root = psutil.Process(root_pid)
        self.peak_tree_mb = 0.0
        self.min_free_mb = float("inf")
        self.free_at_start_mb = psutil.virtual_memory().available / 2**20
        self.stop = threading.Event()
        self.phase_peaks: dict[str, float] = {}
        self.phase = "start-up"

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                procs = [self.root, *self.root.children(recursive=True)]
                mb = sum(p.memory_info().rss for p in procs if p.is_running()) / 2**20
            except psutil.Error:
                mb = 0.0
            self.peak_tree_mb = max(self.peak_tree_mb, mb)
            self.phase_peaks[self.phase] = max(self.phase_peaks.get(self.phase, 0.0), mb)
            self.min_free_mb = min(self.min_free_mb, psutil.virtual_memory().available / 2**20)
            time.sleep(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="write the result as Markdown")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    log = ROOT / ".tmp" / "measure_demo_ram.log"
    log.parent.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen([sys.executable, "src/scripts/run_demo.py", "--offline"], cwd=ROOT, env=env,
                                stdout=fh, stderr=subprocess.STDOUT)
    s = Sampler(proc.pid)
    s.start()
    ok, notes = True, []
    try:
        while "ready on REAL data" not in log.read_text(encoding="utf-8", errors="replace"):
            if proc.poll() is not None or time.time() - t0 > 900:
                raise SystemExit("demo did not start: see " + str(log))
            time.sleep(1)
        ready_s = time.time() - t0
        s.phase = "pages"
        codes = [httpx.get(f"{UI}/{p}", timeout=60).status_code for p in PAGES]
        notes.append(f"dashboard pages: {codes.count(200)}/{len(PAGES)} HTTP 200")
        ok &= codes.count(200) == len(PAGES)
        s.phase = "story"
        httpx.post(f"{API}/demo/start", json={"mode": "SCENARIO", "step_seconds": 0}, timeout=60)
        while httpx.get(f"{API}/demo/status", timeout=30).json().get("running"):
            time.sleep(1)
        runs = httpx.get(f"{API}/stress-runs", params={"limit": 3}, timeout=30).json()["runs"][::-1]
        story = [f"{r['loss_pct']:.2f}% {r['rag']}" for r in runs]
        notes.append("story: " + " → ".join(story))
        ok &= [r["rag"] for r in runs] == ["GREEN", "AMBER", "RED"]
    finally:
        s.stop.set()
        for p in [proc, *psutil.Process(proc.pid).children(recursive=True)] if proc.poll() is None else [proc]:
            try:
                p.kill()
            except (psutil.Error, OSError):
                pass
    bad = []
    for name in ("demo_api.log", "demo_ui.log"):
        f = ROOT / "logs" / name
        if f.exists():
            bad += [ln for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()
                    if re.search(r"Traceback|\bERROR\b|\" 5\d\d", ln)]
    notes.append(f"error lines in logs/demo_api.log + demo_ui.log: {len(bad)}")
    ok &= not bad
    lines = [f"free RAM before start: {s.free_at_start_mb / 1024:.2f} GB",
             f"ready on REAL data after {ready_s:.0f} s",
             f"peak RAM of the demo (API + dashboard + launcher, summed RSS): {s.peak_tree_mb / 1024:.2f} GB",
             *(f"  peak during {k}: {v / 1024:.2f} GB" for k, v in s.phase_peaks.items()),
             f"lowest free system RAM during the run: {s.min_free_mb / 1024:.2f} GB", *notes,
             f"RESULT: {'PASS' if ok else 'FAIL'}"]
    print("\n".join(lines))
    if args.out:
        Path(args.out).write_text("# Demo RAM measurement\n\n`python src/scripts/measure_demo_ram.py` on "
                                  f"{time.strftime('%Y-%m-%d %H:%M')} (offline demo, FinBERT fp32, 2 torch threads)."
                                  "\n\n" + "\n".join(f"- {ln.strip()}" for ln in lines) + "\n\n" + CAVEAT + "\n",
                                  encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
