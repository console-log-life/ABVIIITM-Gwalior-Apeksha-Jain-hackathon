"""Process-level failure drill (M6): the real API runs with
  * HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1 (models must come from ./models), and
  * every outbound HTTP request forced to fail (HTTP(S)_PROXY -> a dead local port; localhost exempt),
then checks that SCENARIO works, LIVE degrades gracefully (all sources fail, the API keeps serving and /health
shows it), REPLAY of cached real data works, and every dashboard page still renders.

Usage:  python src/scripts/failure_drill.py     (uses ports 8010/none; separate DB under .tmp/)
Exit code 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PORT = 8010
API = f"http://127.0.0.1:{PORT}"
DEAD_PROXY = "http://127.0.0.1:9"  # nothing listens on the discard port -> connection refused


def wait_status(predicate, timeout: float, every: float = 1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = predicate()
            if v:
                return v
        except httpx.HTTPError:
            pass
        time.sleep(every)
    return None


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = ROOT / ".tmp" / "drill"
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob("drill.db*"):
        f.unlink()
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HTTP_PROXY": DEAD_PROXY,
           "HTTPS_PROXY": DEAD_PROXY, "ALL_PROXY": DEAD_PROXY, "NO_PROXY": "127.0.0.1,localhost",
           "APP_MODE": "SCENARIO", "DB_PATH": str(tmp / "drill.db"), "REPLAY_LIMIT": "10", "REPLAY_DELAY_S": "0",
           "API_BASE_URL": API, "PYTHONIOENCODING": "utf-8"}
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append((name, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name:<46} {detail}")

    log = open(ROOT / "logs" / "failure_drill_api.log", "w", encoding="utf-8")
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "--app-dir", "src", "app.main:app", "--host",
                            "127.0.0.1", "--port", str(PORT)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    client = httpx.Client(base_url=API, timeout=30, trust_env=False)
    try:
        h = wait_status(lambda: (r := client.get("/health")).status_code == 200 and
                        r.json()["model"]["backend"] != "loading" and r.json(), 240)
        check("API starts offline", bool(h), f"mode={h and h['mode']}")
        check("FinBERT loads from ./models with network blocked", h and h["model"]["backend"] == "finbert",
              f"backend={h and h['model']['backend']}")

        client.post("/demo/reset")
        client.post("/demo/start", json={"mode": "SCENARIO", "step_seconds": 0})
        wait_status(lambda: not client.get("/demo/status").json().get("running"), 120)
        sigs = client.get("/signals").json()
        runs = client.get("/stress-runs").json()["runs"]
        check("SCENARIO story runs offline", len(sigs) == 4 and len(runs) == 3,
              f"{len(sigs)} signals, {len(runs)} stress runs")

        client.post("/mode", json={"mode": "LIVE"})
        h = wait_status(lambda: (s := client.get("/health").json()["sources"]) and
                        {x["source"] for x in s} >= {"google_news", "reddit", "mastodon"} and
                        all(x["status"] != "OK" or x.get("observed_in") for x in s) and
                        any(x["status"] in ("DEGRADED", "DOWN") for x in s) and s, 150, every=3)
        statuses = {x["source"]: x["status"] for x in (h or [])}
        check("LIVE with network dead: sources fail, not OK", bool(h) and "OK" not in statuses.values(),
              str(statuses))
        alive = client.get("/signals").status_code == 200 and client.get("/health").status_code == 200
        check("API keeps serving while every source fails", alive, "GET /signals and /health -> 200")

        client.post("/mode", json={"mode": "REPLAY"})
        wait_status(lambda: not client.get("/demo/status").json().get("running"), 180)
        cached = client.get("/signals", params={"provenance": "CACHED_REAL"}).json()
        check("REPLAY of cached real data works offline", len(cached) > 0, f"{len(cached)} CACHED_REAL signals")

        dash = subprocess.run([sys.executable, str(ROOT / "src" / "scripts" / "check_dashboard.py")], cwd=ROOT,
                              env={**env, "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": ""},
                              capture_output=True, text=True, encoding="utf-8", timeout=600)
        last = (dash.stdout.strip().splitlines() or ["no output"])[-1]
        check("Dashboard pages render during the outage", dash.returncode == 0, last)
    finally:
        client.close()
        api.terminate()
        try:
            api.wait(timeout=15)
        except subprocess.TimeoutExpired:
            api.kill()
        log.close()

    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} drill checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
