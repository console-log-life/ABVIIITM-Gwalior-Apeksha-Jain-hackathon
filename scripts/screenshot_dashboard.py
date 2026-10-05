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
         "05_stress": "Stress_Test", "06_explain": "Explainability", "07_health": "Source_Health"}
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


async def shoot(ws_url: str, url: str, out: Path, wait: float) -> None:
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

        await call("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000, "deviceScaleFactor": 1,
                                                          "mobile": False})
        await call("Page.enable")
        await call("Page.navigate", {"url": url})
        await asyncio.sleep(wait)  # Streamlit renders over a websocket after load; wait real time
        height = (await call("Runtime.evaluate", {
            "expression": "Math.max(document.querySelector('section.main, [data-testid=\"stMain\"]')?.scrollHeight"
                          " || 0, document.body.scrollHeight)", "returnByValue": True}))["result"].get("value", 2000)
        await call("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": int(min(max(height, 1000), 6000)),
                                                          "deviceScaleFactor": 1, "mobile": False})
        await asyncio.sleep(2)
        shot = await call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        out.write_bytes(base64.b64decode(shot["data"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8501")
    ap.add_argument("--wait", type=float, default=12.0)
    ap.add_argument("--pages", default="", help="comma-separated subset of page keys, e.g. 02_feed,03_signals")
    args = ap.parse_args()
    wanted = {p.strip() for p in args.pages.split(",") if p.strip()}
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
            out = OUT / f"{name}.png"
            asyncio.run(shoot(page["webSocketDebuggerUrl"], f"{args.base}/{path}", out, args.wait))
            print(f"{name}: {out.stat().st_size:,} bytes")
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
