"""Record a SILENT backup video of the dashboard playing the demo (step 0 real headlines + SYNTHETIC story).

Starts the API (offline) and the dashboard, resets the demo, then drives the installed Microsoft Edge through
Playwright (channel="msedge": no browser download) while the story plays, with on-screen captions.

The recording follows the story instead of sleeping blindly: before each scene it waits (via the API) until the
step's signal or stress run exists, switches page through the sidebar (no full reload), and waits until Streamlit has
finished rendering and the scene's expected text is on screen. Only then is the caption shown and the dwell counted.
Every page is opened once, unrecorded, before recording starts, so the video does not open on Streamlit's first-run
loading skeleton.
Each caption's start/end time in the video is written to docs/demo/demo_walkthrough_captions.json so captions can be
checked against frames.

Output: docs/demo/demo_walkthrough.webm (~3-4 min). A narrated recording should still be made by a human.

Usage:  python scripts/record_demo_video.py        (requires requirements-dev.txt: playwright)
"""

from __future__ import annotations

import json
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
CAPTION_LOG = OUT_DIR / "demo_walkthrough_captions.json"
API, UI = "http://127.0.0.1:8000", "http://127.0.0.1:8501"
STEP_S = 20  # seconds between story steps while recording (the story adds its own 20 s hold after step 2)
SIZE = {"width": 1600, "height": 900}
NAV = {"home": "Home", "watchlist": "Early Warning Watchlist", "feed": "News Social Feed",
       "signals": "NLP Risk Signals", "portfolio": "Portfolio", "stress": "Stress Test",
       "explain": "Explainability"}

WARM_PATHS = ["", "Early_Warning_Watchlist", "News_Social_Feed", "NLP_Risk_Signals", "Portfolio", "Stress_Test",
              "Explainability"]

CAPTION_JS = """(t) => {
  let d = document.getElementById('demo-caption');
  if (!d) { d = document.createElement('div'); d.id = 'demo-caption'; document.body.appendChild(d); }
  d.textContent = t;
  Object.assign(d.style, {position: 'fixed', left: '50%', bottom: '28px', transform: 'translateX(-50%)',
    background: 'rgba(31,42,68,0.92)', color: '#fff', padding: '12px 22px', borderRadius: '10px',
    font: '600 22px Calibri, Arial, sans-serif', zIndex: 99999, maxWidth: '1300px', textAlign: 'center'});
}"""
# Streamlit is done when its "Running..." status widget and any skeleton placeholders are gone.
IDLE_JS = """() => !document.querySelector('[data-testid="stStatusWidget"]')
                && !document.querySelector('[data-testid="stSkeleton"]')"""


class Recorder:
    def __init__(self, page: Page):
        self.page = page
        self.t0 = time.monotonic()  # the video starts when the page is created
        self.log: list[dict] = []
        self.current = "home"

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 1)

    def caption(self, text: str) -> None:
        self.page.evaluate(CAPTION_JS, text)

    def ready(self, expect: str | None, timeout_s: float = 60) -> None:
        """Wait until the page has rendered: title present, Streamlit idle, expected text visible."""
        p = self.page
        p.wait_for_selector("h1", timeout=timeout_s * 1000)
        if expect:
            p.get_by_text(expect, exact=False).first.wait_for(state="visible", timeout=timeout_s * 1000)
        p.wait_for_function(IDLE_JS, timeout=timeout_s * 1000)
        p.wait_for_timeout(700)  # let charts finish their first paint

    def go(self, key: str) -> None:
        """Client-side page switch through the sidebar (keeps the websocket; no blank reload). Re-showing the
        current page needs a reload, because clicking its own link does not re-run it."""
        if key == self.current:
            self.page.reload()
        else:
            self.page.locator('[data-testid="stSidebarNav"]').get_by_text(NAV[key], exact=True).first.click()
        self.current = key

    def scene(self, key: str | None, caption: str, dwell: float, expect: str | None = None,
              scroll_to: str | None = None, click_text: str | None = None) -> None:
        self.caption(caption)  # visible while the next page renders
        if click_text:
            self.page.get_by_text(click_text, exact=False).first.click()
            self.current = None
        elif key:
            self.go(key)
        self.page.wait_for_timeout(400)
        self.ready(expect)
        if scroll_to:
            try:
                self.page.get_by_text(scroll_to, exact=False).first.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass
        self.caption(caption)  # re-inject: a full navigation (click-through) drops the overlay
        start = self.now()
        self.page.wait_for_timeout(int(dwell * 1000))
        self.log.append({"start_s": start, "end_s": self.now(), "page": key or click_text, "caption": caption})


def wait_api(cond, what: str, timeout: float = 120) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {what}")


def n_signals() -> int:
    return len(httpx.get(f"{API}/signals", params={"limit": 50}, timeout=10).json())


def n_runs() -> int:
    return len(httpx.get(f"{API}/stress-runs", timeout=10).json()["runs"])


def wait_http(url: str, timeout: float) -> None:
    wait_api(lambda: httpx.get(url, timeout=3).status_code == 200, url, timeout)


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
        wait_api(lambda: httpx.get(f"{API}/health", timeout=5).json()["model"].get("backend") != "loading",
                 "model warm-up", 180)
        wait_http(f"{UI}/_stcore/health", 120)
        httpx.post(f"{API}/demo/reset", timeout=30)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            warm = browser.new_page(viewport=SIZE)  # NOT recorded: the first run of each page is slow (skeletons)
            for path in WARM_PATHS:
                warm.goto(f"{UI}/{path}")
                warm.wait_for_selector("h1", timeout=90_000)
                warm.wait_for_function(IDLE_JS, timeout=90_000)
            warm.close()
            ctx = browser.new_context(viewport=SIZE, record_video_dir=str(tmp_video), record_video_size=SIZE)
            rec = Recorder(ctx.new_page())
            rec.page.goto(UI)
            rec.ready("Executive Risk Overview")
            rec.scene(None, "Risk Signal Engine: demo walkthrough (silent backup recording)", 5)

            httpx.post(f"{API}/demo/start", json={"mode": "SCENARIO", "step_seconds": STEP_S}, timeout=30)
            wait_api(lambda: n_signals() >= 4, "step 0 (4 real headlines)")
            rec.scene("feed", "Step 0: four REAL headlines from the published sample, badged CACHED_REAL with "
                      "capture time", 9, expect="4 of 4 documents")
            rec.scene("signals", "Real data, same pipeline: Harley-Davidson junk downgrade scores 7.3, but it is not "
                      "held, so no stress run", 7, expect="NLP Risk Signals")

            wait_api(lambda: n_signals() >= 5, "step 1")
            rec.scene("signals", "Step 1 (SYNTHETIC from here on): Nvidia product launch on social media, "
                      "impact 3.6 Low, no trigger", 6, expect="NLP Risk Signals")

            wait_api(lambda: n_signals() >= 6 and n_runs() >= 1, "step 2 and its issuer stress run")
            rec.scene("stress", "Step 2: Moody's downgrade + SEBI probe at Tata Motors (held issuer), impact 8.7 → "
                      "issuer-only stress 0.41% GREEN", 9, expect="Idiosyncratic credit event")
            rec.scene("watchlist", "Early Warning Watchlist: Tata Motors is WATCH-NEGATIVE, ranked first "
                      "(the story pauses here)", 10, expect="WATCH-NEGATIVE")
            rec.scene(None, "Click-through: why the signal scored 8.7 (probabilities, evidence, weighted "
                      "factors)", 9, expect="Opened from the Early Warning Watchlist", click_text="Explain →")

            wait_api(lambda: n_signals() >= 7 and n_runs() >= 2, "step 3 and its systemic stress run", 90)
            rec.scene("stress", "Step 3: invasion headline from a news wire (market-wide, impact 7.0) → systemic "
                      "stress, moderate, 1.32% AMBER", 8, expect="Geopolitical shock (moderate)")

            wait_api(lambda: n_signals() >= 8 and n_runs() >= 3, "step 4 and the severe run", 90)
            rec.scene("stress", "Step 4: a second independent source corroborates: severe, 2.45% RED, above the "
                      "2% risk appetite", 10, expect="Geopolitical shock (severe)")
            rec.scene(None, "Waterfall, top-10 positions (hedges green) and sector × asset heatmap", 10,
                      expect="Geopolitical shock (severe)", scroll_to="Top-10")
            rec.scene(None, "Audit log: every run stores the signal that triggered it", 8,
                      expect="Geopolitical shock (severe)", scroll_to="Audit log")
            rec.scene("portfolio", "Portfolio: 49 SYNTHETIC positions (seed 42): loans, bonds, IRS, CDS, FX, "
                      "equity", 8, expect="Portfolio Overview")
            rec.scene("home", "Executive overview. Simplified, illustrative stress model; not investment advice",
                      8, expect="Executive Risk Overview")
            video_path = rec.page.video.path()
            ctx.close()
            browser.close()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(video_path), OUT)
        CAPTION_LOG.write_text(json.dumps(rec.log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB) and "
              f"{CAPTION_LOG.relative_to(ROOT)} ({len(rec.log)} scenes, last ends at {rec.log[-1]['end_s']} s)")
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
