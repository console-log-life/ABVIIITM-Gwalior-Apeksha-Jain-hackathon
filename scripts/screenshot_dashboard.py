"""Capture dashboard screenshots headlessly with a locally installed Edge/Chrome via the DevTools protocol.
(Dev tooling for docs/screenshots; the dashboard and API must be running.)

Usage:  python scripts/screenshot_dashboard.py [--base http://127.0.0.1:8501] [--wait 12]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PAGES = {"01_home": "", "02_feed": "News_Social_Feed", "03_signals": "NLP_Risk_Signals", "04_portfolio": "Portfolio",
         "05_stress": "Stress_Test", "06_explain": "Explainability", "07_health": "Source_Health",
         "08_watchlist": "Early_Warning_Watchlist"}
CANDIDATES = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", "msedge", "google-chrome", "chromium"]
PORT = 9333


def find_browser() -> str | None:
    for c in CANDIDATES:
        if Path(c).exists():
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


async def shoot(ws_url: str, url: str, out: Path, wait: float, width: int = 1600, height0: int = 1000,
                full: bool = True) -> None:
    async with websockets.connect(ws_url, max_size=50_000_000) as ws:
        msg_id = 0

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                data = json.loads(await ws.recv())
                if data.get("id") == msg_id:
                    return data.get("result", {})

        await call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height0, "deviceScaleFactor": 1,
                                                          "mobile": False})
        await call("Page.enable")
        await call("Page.navigate", {"url": url})
        await asyncio.sleep(wait)  # Streamlit renders over a websocket after load; wait real time
        height = (await call("Runtime.evaluate", {
            "expression": "Math.max(document.querySelector('section.main, [data-testid=\"stMain\"]')?.scrollHeight"
                          " || 0, document.body.scrollHeight)", "returnByValue": True}))["result"].get("value", 2000)
        if not full:
            height = height0  # viewport only: what a projector shows without scrolling
        full_h = int(min(max(height, height0), 6000))
        await call("Emulation.setDeviceMetricsOverride", {"width": width, "height": full_h,
                                                          "deviceScaleFactor": 1, "mobile": False})
        await asyncio.sleep(2)
        shot = await call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        out.write_bytes(base64.b64decode(shot["data"]))


def shoot_viewports(base: str, size: str, wanted: set[str], wait: float) -> int:
    """Viewport-only screenshots (what a projector shows) with Playwright + the installed Edge, waiting until
    Streamlit has finished rendering. Output: docs/screenshots/<WxH>/<page>.png"""
    import os

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tmp" / "ms-playwright"))
    from playwright.sync_api import sync_playwright

    w, h = (int(x) for x in size.lower().split("x"))
    out_dir = OUT / size
    out_dir.mkdir(parents=True, exist_ok=True)
    idle = ("() => !document.querySelector('[data-testid=\"stStatusWidget\"]') && "
            "!document.querySelector('[data-testid=\"stSkeleton\"]')")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": w, "height": h})
        for name, path in PAGES.items():
            if wanted and name not in wanted:
                continue
            page.goto(f"{base}/{path}")
            page.wait_for_selector("h1", timeout=90_000)
            page.wait_for_timeout(1500)
            page.wait_for_function(idle, timeout=90_000)
            page.wait_for_timeout(int(wait * 1000))
            out = out_dir / f"{name}.png"
            page.screenshot(path=str(out))
            print(f"{size}/{name}: {out.stat().st_size:,} bytes")
        browser.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8501")
    ap.add_argument("--wait", type=float, default=12.0)
    ap.add_argument("--pages", default="", help="comma-separated subset of page keys, e.g. 02_feed,03_signals")
    ap.add_argument("--size", default="", help="WxH viewport, e.g. 1366x768; output docs/screenshots/<WxH>/ "
                                               "(viewport only, as on a projector)")
    args = ap.parse_args()
    wanted = {p.strip() for p in args.pages.split(",") if p.strip()}
    if args.size:
        return shoot_viewports(args.base, args.size, wanted, min(args.wait, 4.0))
    browser = find_browser()
    if not browser:
        print("no Edge/Chrome found; skipping screenshots")
        return 1
    profile = ROOT / ".tmp" / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                targets = httpx.get(f"http://127.0.0.1:{PORT}/json", timeout=2).json()
                page = next(t for t in targets if t.get("type") == "page")
                break
            except (httpx.HTTPError, StopIteration, ValueError):
                time.sleep(0.5)
        else:
            print("browser DevTools endpoint did not come up")
            return 1
        for name, path in PAGES.items():
            if wanted and name not in wanted:
                continue
            if args.size:
                w, h = (int(x) for x in args.size.lower().split("x"))
                (OUT / args.size).mkdir(parents=True, exist_ok=True)
                out = OUT / args.size / f"{name}.png"
                asyncio.run(shoot(page["webSocketDebuggerUrl"], f"{args.base}/{path}", out, args.wait, w, h, False))
            else:
                out = OUT / f"{name}.png"
                asyncio.run(shoot(page["webSocketDebuggerUrl"], f"{args.base}/{path}", out, args.wait))
            print(f"{name}: {out.stat().st_size:,} bytes")
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
