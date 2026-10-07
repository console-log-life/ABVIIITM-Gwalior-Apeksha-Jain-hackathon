"""One-command demo: start the API + dashboard, load the REAL history, reset demo state, then either wait for the
presenter (default) or play the scripted SYNTHETIC story.

  python src/scripts/run_demo.py                  # API :8000 + dashboard :8501 on REAL data; presenter starts the story
                                              # from the sidebar (▶ Scenario demo) at ~2:30 of the 5-minute flow
  python src/scripts/run_demo.py --offline        # same, HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1 (no network)
  python src/scripts/run_demo.py --play-story     # also play the story now (step 0 real headlines + steps 1-4)
  python src/scripts/run_demo.py --replay 30      # after the story, stream the 30 most recent CACHED_REAL documents
  python src/scripts/run_demo.py --exit-after-story --no-dashboard   # automation / drills (implies --play-story)

Deterministic: the same story and the same portfolio (seed 42) give the same signals and stress results every run.
Press Ctrl+C to stop both servers.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from app.config import STRESS_DISCLAIMER, get_settings  # noqa: E402

PY = sys.executable


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, timeout: float, what: str) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = httpx.get(url, timeout=3)
            if r.status_code == 200:
                return r.json() if "json" in r.headers.get("content-type", "") else {}
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"{what} did not come up within {timeout:.0f} s ({url})")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="force Hugging Face offline mode (models from ./models)")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--step-seconds", type=float, default=None, help="seconds between story steps (default config)")
    ap.add_argument("--replay", type=int, default=0, help="after the story, replay N cached real documents")
    ap.add_argument("--exit-after-story", action="store_true", help="stop servers when the story has finished")
    ap.add_argument("--play-story", action="store_true", help="play the scripted story right away")
    ap.add_argument("--api-port", type=int, default=8000)
    ap.add_argument("--ui-port", type=int, default=8501)
    args = ap.parse_args()

    s = get_settings()
    step = s.demo_step_seconds if args.step_seconds is None else args.step_seconds
    api = f"http://127.0.0.1:{args.api_port}"
    env = {**os.environ, "APP_MODE": "SCENARIO", "API_BASE_URL": api, "PYTHONIOENCODING": "utf-8"}
    if args.offline:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    for port in [args.api_port] + ([] if args.no_dashboard else [args.ui_port]):
        if port_in_use(port):
            print(f"port {port} is already in use — stop the other server first (or pass --api-port/--ui-port)")
            return 2

    logs = s.resolve(s.log_dir)
    logs.mkdir(parents=True, exist_ok=True)
    procs: list[subprocess.Popen] = []
    try:
        print(f"[1/5] starting API on {api}  (log: {logs / 'demo_api.log'})")
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "--app-dir", "src", "app.main:app", "--host", "127.0.0.1", "--port",
             str(args.api_port)],
            cwd=ROOT, env=env, stdout=open(logs / "demo_api.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        wait_for(f"{api}/health", 180, "API")
        t0 = time.time()
        while True:  # wait for the model warm-up so step 1 is not slowed down
            h = httpx.get(f"{api}/health", timeout=5).json()
            if h["model"].get("backend") not in ("loading", None) or time.time() - t0 > 180:
                break
            time.sleep(1)
        fallback = h["model"].get("fallback_reason") if h["model"].get("backend") != "finbert" else None
        print(f"      sentiment model: {h['model'].get('backend')}" + (f"  (fallback: {fallback})" if fallback else ""))

        if not args.no_dashboard:
            print(f"[2/5] starting dashboard on http://127.0.0.1:{args.ui_port}  (log: {logs / 'demo_ui.log'})")
            procs.append(subprocess.Popen(
                [PY, "-m", "streamlit", "run", str(ROOT / "src" / "app" / "dashboard" / "Home.py"), "--server.port",
                 str(args.ui_port), "--server.headless", "true"],
                cwd=ROOT, env=env, stdout=open(logs / "demo_ui.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT))
            wait_for(f"http://127.0.0.1:{args.ui_port}/_stcore/health", 90, "dashboard")
        else:
            print("[2/5] dashboard skipped (--no-dashboard)")

        reset = httpx.post(f"{api}/demo/reset", timeout=30).json()
        print(f"[3/5] demo state reset: {reset}")
        t0, last = time.time(), None
        while time.time() - t0 < 1200:  # the REAL history (CACHED_REAL) is loaded or built by the API at start-up
            hist = httpx.get(f"{api}/history", timeout=10).json()
            st = hist["status"]
            if st.get("state") in ("ready", "error"):
                break
            if st.get("progress") and st["progress"] != last:
                last = st["progress"]
                print(f"      building the REAL history: {last[0]}/{last[1]} documents")
            time.sleep(2)
        meta = hist.get("meta") or {}
        if st.get("state") == "ready":
            print(f"      REAL history: {meta.get('signals')} CACHED_REAL signals, {meta.get('stress_runs')} simulated "
                  f"stress runs; event time up to {str(hist.get('event_to'))[:16]} ({meta.get('source')})")
        else:
            print(f"      REAL history not available: {st.get('error') or st}")

        if not (args.play_story or args.exit_after_story):
            print("[4/5] ready on REAL data. 5-minute flow (docs/DEMO.md): Home + time machine → Watchlist → Explainability "
                  "→ Risk Propagation → sidebar ▶ Scenario demo (SYNTHETIC) → What-if → Credit brief")
            print(f"      * {STRESS_DISCLAIMER}")
            print(f"      Dashboard: http://127.0.0.1:{args.ui_port}   API docs: {api}/docs")
            print("      servers keep running — press Ctrl+C to stop")
            while all(p.poll() is None for p in procs):
                time.sleep(1)
            print("a server exited unexpectedly — see logs/")
            return 1

        print(f"[4/5] playing the demo: step 0 = REAL headlines (CACHED_REAL sample), then the SYNTHETIC story "
              f"({step:g} s between steps, 20 s pause after step 2 for the watchlist)")
        httpx.post(f"{api}/demo/start", json={"mode": "SCENARIO", "step_seconds": step}, timeout=30).raise_for_status()
        seen_sig, seen_runs = set(), set()

        def poll() -> None:
            for sig in reversed(httpx.get(f"{api}/signals", params={"limit": 50}, timeout=10).json()):
                if sig.get("origin") == "real":  # the loaded REAL history is not part of this session's story
                    continue
                if sig["signal_id"] not in seen_sig:
                    seen_sig.add(sig["signal_id"])
                    print(f"      SIGNAL [{sig['provenance']}] {sig['impact_score']:>4} {sig['risk_level']:<8} "
                          f"{sig['company'][:22]:<22} {sig['event_type']:<14} {sig['text_excerpt'][:60]}")
            for run in reversed(httpx.get(f"{api}/stress-runs", timeout=10).json()["runs"]):
                if run["run_id"].startswith("real-"):
                    continue
                if run["run_id"] not in seen_runs:
                    seen_runs.add(run["run_id"])
                    print(f"      STRESS {run['scenario']:<26} {run.get('scope_issuer_id') or 'MARKET':<14} "
                          f"loss {run['loss_pct']:.2f}%  {run['rag']}")
        while httpx.get(f"{api}/demo/status", timeout=10).json().get("running"):
            poll()
            time.sleep(1)
        poll()  # final poll: the last step's signal and stress runs may land after the status flips
        for row in httpx.get(f"{api}/watchlist", timeout=10).json()["issuers"]:
            if row["status"] != "STABLE":
                print(f"      WATCHLIST {row['status']:<15} {row['issuer_name'][:24]:<24} {row['status_reason']}")

        if args.replay:
            print(f"      replaying {args.replay} cached real documents (CACHED_REAL)")
            httpx.post(f"{api}/demo/start", json={"mode": "REPLAY", "limit": args.replay, "step_seconds": 0.5},
                       timeout=30).raise_for_status()
            while httpx.get(f"{api}/demo/status", timeout=10).json().get("running"):
                time.sleep(1)

        print(f"[5/5] done: {len(seen_sig)} signals, {len(seen_runs)} stress runs")
        print(f"      * {STRESS_DISCLAIMER}")
        print(f"      API docs:  {api}/docs")
        if not args.no_dashboard:
            print(f"      Dashboard: http://127.0.0.1:{args.ui_port}")
        if args.exit_after_story:
            return 0
        print("      servers keep running — press Ctrl+C to stop")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("a server exited unexpectedly — see logs/")
        return 1
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, httpx.HTTPError) as exc:
        print(f"demo failed: {exc}  (see logs/demo_api.log, logs/demo_ui.log)")
        return 1
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
