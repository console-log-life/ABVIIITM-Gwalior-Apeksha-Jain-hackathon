"""Record a SILENT backup video of the dashboard playing the scripted (SYNTHETIC) demo story.

Starts the API (offline) and the dashboard, resets the demo, then drives the installed Microsoft Edge through
Playwright (channel="msedge": no browser download) while the story plays, with on-screen captions.
Output: docs/demo/demo_walkthrough.webm (~3-4 min). A narrated recording should still be made by a human.

Usage:  python scripts/record_demo_video.py        (requires requirements-dev.txt: playwright)
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
# Playwright's ffmpeg (needed for video) lives inside the project, not in the user profile:
#   PLAYWRIGHT_BROWSERS_PATH=.tmp/ms-playwright python -m playwright install ffmpeg
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tmp" / "ms-playwright"))
from playwright.sync_api import Page, sync_playwright  # noqa: E402

OUT_DIR = ROOT / "docs" / "demo"
OUT = OUT_DIR / "demo_walkthrough.webm"
API, UI = "http://127.0.0.1:8000", "http://127.0.0.1:8501"
STEP_S = 15  # seconds between story steps while recording
SIZE = {"width": 1600, "height": 900}

CAPTION_JS = """(t) => {
  let d = document.getElementById('demo-caption');
  if (!d) { d = document.createElement('div'); d.id = 'demo-caption'; document.body.appendChild(d); }
  d.textContent = t;
  Object.assign(d.style, {position: 'fixed', left: '50%', bottom: '28px', transform: 'translateX(-50%)',
    background: 'rgba(31,42,68,0.92)', color: '#fff', padding: '12px 22px', borderRadius: '10px',
    font: '600 22px Calibri, Arial, sans-serif', zIndex: 99999, maxWidth: '1300px', textAlign: 'center'});
}"""


def wait_http(url: str, timeout: float) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"{url} did not come up")


def show(page: Page, path: str, caption: str, dwell: float, scroll_to: str | None = None) -> None:
    page.goto(f"{UI}/{path}")
    page.wait_for_timeout(6000)  # Streamlit renders over a websocket after load
    if scroll_to:
        loc = page.get_by_text(scroll_to, exact=False).first
        try:
            loc.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
    page.evaluate(CAPTION_JS, caption)
    page.wait_for_timeout(int(dwell * 1000))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for port in (8000, 8501):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                print(f"port {port} busy: stop the running server first")
                return 2
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "APP_MODE": "SCENARIO",
           "API_BASE_URL": API}
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"], cwd=ROOT, env=env,
                         stdout=open(logs / "video_api.log", "w"), stderr=subprocess.STDOUT),
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app/dashboard/Home.py", "--server.port", "8501",
                          "--server.headless", "true"], cwd=ROOT, env=env,
                         stdout=open(logs / "video_ui.log", "w"), stderr=subprocess.STDOUT),
    ]
    tmp_video = ROOT / ".tmp" / "video"
    shutil.rmtree(tmp_video, ignore_errors=True)
    try:
        wait_http(f"{API}/health", 180)
        while httpx.get(f"{API}/health", timeout=5).json()["model"].get("backend") == "loading":
            time.sleep(1)
        wait_http(f"{UI}/_stcore/health", 120)
        httpx.post(f"{API}/demo/reset", timeout=30)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            ctx = browser.new_context(viewport=SIZE, record_video_dir=str(tmp_video), record_video_size=SIZE)
            page = ctx.new_page()
            show(page, "", "Risk Signal Engine: SYNTHETIC demo story (silent backup recording)", 6)
            httpx.post(f"{API}/demo/start", json={"mode": "SCENARIO", "step_seconds": STEP_S}, timeout=30)
            show(page, "News_Social_Feed", "Step 1: Nvidia product launch seen on social media (SYNTHETIC badge)", 8)
            show(page, "NLP_Risk_Signals", "Impact 3.6 Low: positive news on a small holding, no stress trigger", 8)
            page.wait_for_timeout(STEP_S * 1000 - 20000 if STEP_S * 1000 > 20000 else 0)
            show(page, "NLP_Risk_Signals", "Step 2: Moody's downgrade + SEBI probe at Tata Motors (held issuer)", 8)
            show(page, "Explainability", "Explainability: sentiment probabilities, evidence phrases, weighted factors",
                 14)
            show(page, "Stress_Test", "Issuer-only stress test triggered: loss partly offset by the CDS hedge", 12)
            show(page, "NLP_Risk_Signals", "Step 3: invasion headline (news wire), market-wide Geopolitical signal",
                 10)
            show(page, "Stress_Test", "Systemic stress: moderate first; a second source escalates it to severe",
                 14, scroll_to="Before vs after")
            show(page, "Stress_Test", "Waterfall, top-10 positions (hedges green) and sector × asset heatmap", 14,
                 scroll_to="Top-10 contributing")
            show(page, "Stress_Test", "Audit log: every run stores the signal that triggered it", 10,
                 scroll_to="Audit log")
            show(page, "Portfolio", "Portfolio: 49 SYNTHETIC positions (seed 42): loans, bonds, IRS, CDS, FX, "
                 "equity", 10)
            show(page, "", "Executive overview. Simplified, illustrative stress model; not investment advice", 10)
            video_path = page.video.path()
            ctx.close()
            browser.close()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(video_path), OUT)
        size_mb = OUT.stat().st_size / 1e6
        print(f"wrote {OUT.relative_to(ROOT)} ({size_mb:.1f} MB)")
        return 0
    finally:
        for pr in procs:
            pr.terminate()
        for pr in procs:
            try:
                pr.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pr.kill()


if __name__ == "__main__":
    sys.exit(main())
