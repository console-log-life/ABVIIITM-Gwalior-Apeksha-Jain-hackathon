"""Call EVERY API endpoint with valid and invalid input and check the status codes (incl. SSE and JSONL).

  python src/scripts/verify_api.py [--out docs/verification/api.md] [--live]

Starts its own API (uvicorn, port 8765) on a throw-away database in .tmp/verify_api/, loads the REAL history into it,
runs the checks, then scans the server log for errors. --live also switches to LIVE mode for a few seconds (real
network requests to the public sources, rate-limited as usual), otherwise LIVE is checked only through its 422 path.
Exit code 0 = every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".tmp" / "verify_api"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

results: list[tuple[str, str, int | str, str, bool]] = []  # (method, path, status, note, ok)


def check(c: httpx.Client, method: str, path: str, expect: int, note: str = "", **kw: Any) -> httpx.Response:
    try:
        r = c.request(method, path, **kw)
        status: int | str = r.status_code
    except httpx.HTTPError as exc:
        r, status = None, type(exc).__name__  # type: ignore[assignment]
    ok = status == expect
    label = path + (f"?{httpx.QueryParams(kw['params'])}" if kw.get("params") else "")
    body = kw.get("json")
    if body is not None:
        label += " " + json.dumps(body)[:70]
    results.append((method, label, status, note or f"expect {expect}", ok))
    print(f"{'PASS' if ok else 'FAIL'}  {method:<4} {label[:100]:<100} {status}")
    return r


def assert_that(name: str, cond: bool, detail: str = "") -> None:
    results.append(("", name, "", detail, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")


def wait(c: httpx.Client, fn, timeout: float, what: str) -> Any:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn(c)
            if v:
                return v
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        time.sleep(1)
    raise SystemExit(f"timed out waiting for {what}")


def run_checks(c: httpx.Client, live: bool) -> None:
    check(c, "GET", "/health", 200)
    check(c, "GET", "/docs", 200, "Swagger UI")
    check(c, "GET", "/openapi.json", 200)
    check(c, "GET", "/methodology", 200)
    check(c, "GET", "/nope", 404, "unknown route")

    st = wait(c, lambda c: (h := c.get("/history").json())["status"].get("state") in ("ready", "error") and h,
              900, "REAL history")
    assert_that("REAL history loaded", st["status"]["state"] == "ready",
                f"{st['status'].get('loaded')} event {st.get('event_from')} .. {st.get('event_to')}")
    check(c, "GET", "/history", 200)
    check(c, "POST", "/history/load", 200, "fresh cache: reload only")
    check(c, "POST", "/history/load", 422, "bad boolean", params={"rebuild": "maybe"})

    as_of = st.get("event_to")
    check(c, "GET", "/overview", 200, params={"as_of": as_of, "hours": 24})
    check(c, "GET", "/overview", 422, "hours < 1", params={"hours": 0})
    check(c, "GET", "/overview", 422, "bad timestamp", params={"as_of": "yesterday-ish"})

    sigs = check(c, "GET", "/signals", 200, params={"limit": 5}).json()
    assert_that("GET /signals returns rows", len(sigs) == 5, f"{len(sigs)} rows")
    check(c, "GET", "/signals", 200, params={"as_of": as_of, "hours": 24, "min_impact": 5})
    check(c, "GET", "/signals", 200, params={"provenance": "CACHED_REAL", "event_type": "Credit Event"})
    check(c, "GET", "/signals", 422, "unknown event type", params={"event_type": "Weather"})
    check(c, "GET", "/signals", 422, "min_impact > 10", params={"min_impact": 11})
    check(c, "GET", "/signals", 422, "unknown provenance", params={"provenance": "MADE_UP"})
    check(c, "GET", "/signals", 422, "hours > 720", params={"hours": 1000})
    check(c, "GET", "/signals", 404, "unknown since_id", params={"since_id": "nope"})
    check(c, "GET", "/signals", 200, params={"since_id": sigs[-1]["signal_id"]})
    check(c, "GET", f"/signals/by-id/{sigs[0]['signal_id']}", 200)
    check(c, "GET", "/signals/by-id/does-not-exist", 404)
    ticker = next((s["ticker"] for s in c.get("/signals", params={"limit": 500}).json() if s.get("ticker")), "AAPL")
    agg = check(c, "GET", f"/signals/{ticker}", 200, params={"limit": 5}).json()
    assert_that(f"GET /signals/{ticker} aggregates", agg.get("ticker") == ticker, f"{agg.get('count', '')}")
    check(c, "GET", "/signals/ZZZZ", 200, "unknown ticker: empty aggregate")

    r = check(c, "GET", "/signals/export.jsonl", 200, params={"min_impact": 7})
    lines = r.text.strip().splitlines()
    parsed = [json.loads(x) for x in lines]
    assert_that("JSONL export: one JSON object per line", bool(parsed) and all(p["impact_score"] >= 7 for p in parsed),
                f"{len(parsed)} lines, content-type {r.headers.get('content-type')}")
    check(c, "GET", "/signals/export.jsonl", 422, "min_impact < 1", params={"min_impact": 0})

    with c.stream("GET", "/signals/stream", params={"replay_last": 2, "max_events": 2}) as s:
        events = [ln for ln in s.iter_lines() if ln.startswith("data:")]
        ctype = s.headers.get("content-type", "")
    results.append(("GET", "/signals/stream?replay_last=2&max_events=2", s.status_code, "SSE", s.status_code == 200))
    assert_that("SSE: text/event-stream with 2 signal events",
                ctype.startswith("text/event-stream") and len(events) == 2
                and all("signal_id" in json.loads(e[5:]) for e in events), f"{len(events)} events")
    check(c, "GET", "/signals/stream", 422, "max_events < 1", params={"max_events": 0})

    body = {"text": "Moody's downgrades Reliance Industries as SEBI opens probe into accounts"}
    r1 = check(c, "POST", "/analyze", 200, json=body)
    r2 = check(c, "POST", "/analyze", 200, "same text again", json=body)
    assert_that("POST /analyze dedups (X-Duplicate)", r1.headers.get("X-Duplicate") == "false"
                and r2.headers.get("X-Duplicate") == "true", f"{r1.json().get('event_type')} "
                f"impact {r1.json().get('impact_score')}")
    check(c, "POST", "/analyze", 422, "missing text", json={})
    check(c, "POST", "/analyze", 422, "empty text", json={"text": ""})
    check(c, "POST", "/analyze", 422, "not JSON", content=b"hello", headers={"content-type": "application/json"})
    check(c, "POST", "/analyze/batch", 200, json={"items": [{"text": "Fed cuts rates as inflation cools"},
                                                            {"text": "HDFC Bank profit beats estimates"}]})
    check(c, "POST", "/analyze/batch", 422, "empty batch", json={"items": []})
    check(c, "POST", "/analyze/batch", 422, "101 items", json={"items": [{"text": "a b c"}] * 101})

    check(c, "GET", "/portfolio", 200)
    check(c, "GET", "/portfolio/scenarios", 200)
    run = check(c, "POST", "/portfolio/stress-test", 200, json={"scenario": "geopolitical_severe"}).json()
    check(c, "POST", "/portfolio/stress-test", 200, json={"scenario": "idiosyncratic_credit",
                                                          "issuer_id": "IN-TATAMOTORS"})
    check(c, "POST", "/portfolio/stress-test", 200, json={"custom": {"hy_spread_bp": 250, "equity_pct": -0.1}})
    check(c, "POST", "/portfolio/stress-test", 422, "unknown scenario", json={"scenario": "nope"})
    check(c, "POST", "/portfolio/stress-test", 422, "neither scenario nor custom", json={})
    check(c, "GET", "/portfolio/stress-test", 200, "latest run")
    check(c, "GET", "/portfolio/stress-test", 404, "no run before 2000", params={"as_of": "2000-01-01T00:00:00Z"})
    check(c, "GET", "/stress-runs", 200, params={"limit": 5})
    check(c, "GET", f"/stress-runs/{run['run_id']}", 200)
    check(c, "GET", "/stress-runs/nope", 404)
    check(c, "POST", "/portfolio/what-if", 200, json={"shocks": {"hy_spread_bp": 300}})
    check(c, "POST", "/portfolio/what-if", 422, "equity_pct out of range", json={"shocks": {"equity_pct": -5}})
    check(c, "POST", "/portfolio/what-if", 422, "issuer not held", json={"shocks": {}, "issuer_id": "XX-NOPE"})
    check(c, "POST", "/portfolio/what-if", 422, "missing shocks", json={})

    check(c, "GET", "/watchlist", 200, params={"as_of": as_of, "hours": 24})
    check(c, "GET", "/watchlist", 422, "hours < 1", params={"hours": 0})
    check(c, "GET", "/propagation", 200, params={"issuer_id": "IN-TATAMOTORS", "as_of": as_of})
    check(c, "GET", "/propagation", 404, "issuer not held", params={"issuer_id": "XX-NOPE"})
    check(c, "GET", "/propagation", 422, "issuer_id missing")
    for fmt in ("json", "html", "pdf"):
        r = check(c, "GET", "/credit-brief/IN-TATAMOTORS", 200, params={"format": fmt})
    assert_that("credit brief PDF is a PDF", r.content[:5] == b"%PDF-", f"{len(r.content)} bytes")
    check(c, "GET", "/credit-brief/XX-NOPE", 404)
    check(c, "GET", "/credit-brief/IN-TATAMOTORS", 422, "format docx", params={"format": "docx"})

    check(c, "GET", "/demo/status", 200)
    check(c, "POST", "/demo/start", 422, "LIVE goes through /mode", json={"mode": "LIVE"})
    check(c, "POST", "/demo/start", 422, "unknown mode", json={"mode": "FOO"})
    check(c, "POST", "/demo/start", 422, "step_seconds > 120", json={"mode": "SCENARIO", "step_seconds": 500})
    runs_before = len(c.get("/stress-runs", params={"limit": 500}).json()["runs"])
    check(c, "POST", "/demo/start", 200, json={"mode": "SCENARIO", "step_seconds": 0})
    wait(c, lambda c: not c.get("/demo/status").json().get("running"), 600, "scenario demo")
    after = c.get("/stress-runs", params={"limit": 500}).json()["runs"]
    runs_after = len(after)
    story = [r["rag"] for r in after[: runs_after - runs_before]][::-1]
    wl = c.get("/watchlist").json()
    tata = next((r for r in wl["issuers"] if r.get("issuer_id") == "IN-TATAMOTORS"), {})
    assert_that("scenario demo triggered stress runs", runs_after > runs_before,
                f"{runs_before} -> {runs_after}, RAG {' -> '.join(story)}")
    assert_that("Tata Motors on the watchlist after the story", bool(tata), str(tata.get("status", ""))[:40])

    check(c, "POST", "/mode", 422, "missing mode", json={})
    check(c, "POST", "/mode", 422, "unknown mode", json={"mode": "FOO"})
    check(c, "POST", "/mode", 200, "REPLAY", json={"mode": "REPLAY"})
    wait(c, lambda c: not c.get("/demo/status").json().get("running"), 900, "replay")
    if live:
        r = check(c, "POST", "/mode", 200, "LIVE (real network)", json={"mode": "LIVE"})
        assert_that("LIVE ingestion running", r.json().get("live_running") is True)
        time.sleep(20)
        check(c, "GET", "/health", 200, "health during LIVE")
        check(c, "POST", "/mode", 200, "back to SCENARIO stops LIVE", json={"mode": "SCENARIO"})
        wait(c, lambda c: not c.get("/demo/status").json().get("running"), 600, "scenario demo")
    check(c, "POST", "/demo/reset", 200)
    check(c, "GET", "/health", 200, "after reset")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="write the results as Markdown")
    ap.add_argument("--live", action="store_true", help="also switch to LIVE for ~20 s (real network)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "logs").mkdir(parents=True)
    env = {**os.environ, "DB_PATH": str(WORK / "api.db"), "LOG_DIR": str(WORK / "logs"), "APP_MODE": "SCENARIO",
           "DEMO_STEP_SECONDS": "0", "REPLAY_DELAY_S": "0", "REAL_HISTORY_AUTOLOAD": "true",
           "PYTHONIOENCODING": "utf-8"}
    log_path = WORK / "server.log"
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "--app-dir", "src", "app.main:app", "--host",
                                 "127.0.0.1", "--port", str(PORT)], cwd=ROOT, env=env, stdout=log,
                                stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=BASE, timeout=300) as c:
            wait(c, lambda c: c.get("/health").status_code == 200, 600, "API start")
            run_checks(c, args.live)
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            proc.kill()
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    bad = [ln for ln in log_text.splitlines() if re.search(r"Traceback|\bERROR\b|Exception in ASGI", ln)]
    assert_that("server log has no errors or tracebacks", not bad, f"{len(bad)} bad lines" + (f": {bad[0][:120]}"
                                                                                            if bad else ""))
    statuses = re.findall(r'"(GET|POST) [^"]+" (\d{3})', log_text)
    five = [s for s in statuses if s[1].startswith("5")]
    assert_that("no 5xx responses in the access log", not five, f"{len(statuses)} requests logged")

    n_ok = sum(1 for r in results if r[4])
    print(f"\n{n_ok}/{len(results)} checks passed")
    if args.out:
        md = [f"# API verification ({time.strftime('%Y-%m-%d %H:%M')})", "",
              f"`python src/scripts/verify_api.py{' --live' if args.live else ''}`: **{n_ok}/{len(results)} checks "
              "passed**. Own API on a throw-away database with the REAL history loaded.", "",
              "| result | method | request | status | note |", "|---|---|---|---|---|"]
        md += [f"| {'PASS' if ok else '**FAIL**'} | {m} | `{p}` | {s} | {n} |".replace("|`", "| `")
               for m, p, s, n, ok in results]
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
