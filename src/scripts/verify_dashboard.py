"""Open EVERY dashboard page in a real browser and use every interactive control; fail on any Streamlit exception
box, error box or server-log error. One screenshot per step.

  python src/scripts/verify_dashboard.py [--out docs/verification/dashboard.md] [--shots docs/verification/screenshots]

Starts its own API (port 8766, throw-away database, REAL history loaded) and dashboard (port 8502), drives them with
Playwright + the installed Microsoft Edge (headless), then stops both. Exit code 0 = every step passed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".tmp" / "verify_dashboard"
API_PORT, UI_PORT = 8766, 8502
API, UI = f"http://127.0.0.1:{API_PORT}", f"http://127.0.0.1:{UI_PORT}"
IDLE = ("() => !document.querySelector('[data-testid=\"stStatusWidget\"]') && "
        "!document.querySelector('[data-testid=\"stSkeleton\"]') && !document.querySelector('[data-stale=\"true\"]')")

results: list[tuple[str, str, bool, str]] = []  # (page, step, ok, detail)


class Driver:
    def __init__(self, page, shots: Path):
        self.page = page
        self.shots = shots
        self.n = 0

    # ---- waiting and checking
    def settle(self, extra_ms: int = 600) -> None:
        """Wait until Streamlit has been idle (no running script, skeleton or stale element) for ~1 s: a click can
        trigger st.rerun(), i.e. two script runs back to back."""
        self.page.wait_for_timeout(extra_ms)
        for _ in range(3):
            self.page.wait_for_function(IDLE, timeout=180_000)
            self.page.wait_for_timeout(350)

    def goto(self, path: str) -> None:
        self.page.goto(f"{UI}/{path}")
        self.page.wait_for_selector("h1", timeout=180_000)
        self.settle(1500)

    def problems(self) -> list[str]:
        out = []
        for sel, kind in (('[data-testid="stException"]', "exception"),
                          ('[data-testid="stAlertContentError"]', "error")):
            loc = self.page.locator(sel)
            for i in range(loc.count()):
                out.append(f"{kind}: {loc.nth(i).inner_text()[:160]!r}")
        return out

    def step(self, page_name: str, name: str, action: Callable[[], str | None] | None = None,
             expect: Callable[[], bool] | None = None) -> bool:
        detail = ""
        ok = True
        try:
            if action:
                detail = action() or ""
            self.settle()
            if expect and not expect():
                ok, detail = False, (detail + " expectation not met").strip()
        except Exception as exc:  # noqa: BLE001 - every failure becomes a FAIL row
            ok, detail = False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
        bad = self.problems()
        if bad:
            ok, detail = False, (detail + " " + "; ".join(bad)).strip()
        self.n += 1
        shot = self.shots / f"{self.n:02d}_{re.sub(r'[^a-z0-9]+', '_', (page_name + ' ' + name).lower())[:60]}.jpg"
        try:
            self.page.screenshot(path=str(shot), type="jpeg", quality=50, full_page=True)
            detail = (detail + f" [{shot.name}]").strip()
        except Exception:  # noqa: BLE001
            pass
        results.append((page_name, name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {page_name:<22} {name:<48} {detail[:110]}", flush=True)
        return ok

    # ---- widget helpers (Streamlit 1.41 DOM)
    def widget(self, testid: str, label: str, scope=None):
        return (scope or self.page).locator(f'[data-testid="{testid}"]').filter(has_text=label).first

    def select(self, label: str, index: int = 1, scope=None) -> str:
        box = self.widget("stSelectbox", label, scope)
        box.locator('div[data-baseweb="select"]').click()
        opts = self.page.locator('[role="option"]')
        opts.first.wait_for(timeout=10_000)
        i = min(index, opts.count() - 1)
        text = opts.nth(i).inner_text()
        opts.nth(i).click()
        return f"chose {text[:50]!r}"

    def multiselect_drop_last(self, label: str) -> str:
        box = self.widget("stMultiSelect", label)
        tags = box.locator('[data-baseweb="tag"]')
        before = tags.count()
        box.locator("input").click()
        self.page.keyboard.press("Backspace")
        self.page.keyboard.press("Escape")
        return f"tags {before} -> {tags.count()}"

    def slider_keys(self, label: str, key: str, times: int = 3, scope=None) -> str:
        thumb = self.widget("stSlider", label, scope).locator('[role="slider"]').first
        before = thumb.get_attribute("aria-valuenow")
        thumb.focus()
        for _ in range(times):
            self.page.keyboard.press(key)
        self.page.wait_for_timeout(300)
        return f"value {before} -> {thumb.get_attribute('aria-valuenow')}"

    def click_label(self, testid: str, label: str, scope=None) -> str:
        self.widget(testid, label, scope).locator("label").first.click()
        return f"toggled {label!r}"

    def button(self, name: str, scope=None) -> str:
        (scope or self.page).get_by_role("button", name=name).first.click()
        return f"clicked {name!r}"


def wait_api_idle(timeout: float = 900) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if not httpx.get(f"{API}/demo/status", timeout=10).json().get("running"):
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError("demo/replay still running")


def run(d: Driver) -> None:
    p = d.page
    sb = p.locator('[data-testid="stSidebar"]')

    # ---------------------------------------------------------------- Home + sidebar (on every page)
    d.goto("")
    d.step("Home", "open page", expect=lambda: p.locator("h1").count() > 0)
    d.step("Home", "time machine: drag back", lambda: d.slider_keys("", "ArrowLeft", 12, sb),
           expect=lambda: sb.get_by_text("◷ as of").count() > 0)
    d.step("Home", "time machine: Latest button", lambda: d.button("Latest", sb),
           expect=lambda: sb.get_by_text("● latest data").count() > 0)
    d.step("Home", "auto-refresh on (6 s)", lambda: (d.click_label("stCheckbox", "Auto-refresh", sb),
                                                     p.wait_for_timeout(6500))[0])
    d.step("Home", "auto-refresh off", lambda: d.click_label("stCheckbox", "Auto-refresh", sb))
    sb.get_by_text("Mode & demo control").first.click()
    d.step("Home", "mode switch: REPLAY + Apply", lambda: (sb.get_by_text("REPLAY", exact=True).first.click(),
                                                           d.button("Apply mode", sb))[1])
    wait_api_idle()
    d.step("Home", "after REPLAY finished", lambda: p.reload() and None)
    sb.get_by_text("Mode & demo control").first.click()
    d.step("Home", "▶ Scenario demo", lambda: d.button("▶ Scenario demo", sb))
    wait_api_idle()
    d.goto("")
    d.step("Home", "after scenario story", expect=lambda: p.get_by_text("Tata", exact=False).count() > 0)

    # ---------------------------------------------------------------- Early Warning Watchlist
    d.goto("Early_Warning_Watchlist")
    d.step("Watchlist", "open page")
    d.step("Watchlist", "window selector -> 72 h", lambda: d.select("Window", 2))
    d.step("Watchlist", "show all held issuers", lambda: d.click_label("stCheckbox", "Show all held issuers"))
    exp = p.locator('[data-testid="stExpander"]').filter(has_text="Tata Motors").first

    def open_tata() -> str:
        if exp.locator("details").get_attribute("open") is None:
            exp.locator("summary").click()
            return "expanded"
        return "already expanded (WATCH-NEGATIVE)"
    d.step("Watchlist", "Tata Motors expander open", open_tata,
           expect=lambda: exp.get_by_text("Credit brief").count() > 0)
    d.step("Watchlist", "credit brief toggle", lambda: d.click_label("stCheckbox", "Credit brief", exp),
           expect=lambda: exp.get_by_text("Download PDF").count() > 0)

    def download() -> str:
        with p.expect_download(timeout=60_000) as dl:
            exp.get_by_role("button", name="⬇ Download PDF").click()
        path = WORK / "brief.pdf"
        dl.value.save_as(path)
        head = path.read_bytes()[:5]
        if head != b"%PDF-":
            raise AssertionError(f"not a PDF: {head!r}")
        return f"PDF {path.stat().st_size:,} bytes"
    d.step("Watchlist", "download credit brief PDF", download)
    d.step("Watchlist", "Explain → link", lambda: exp.get_by_role("link", name="Explain →").first.click() and None,
           expect=lambda: "Explainability" in p.url and "signal_id=" in p.url)
    d.settle(1500)
    d.step("Explainability", "opened from Explain link", expect=lambda: p.get_by_text("Impact").count() > 0)
    d.goto("Early_Warning_Watchlist")
    d.step("Watchlist", "propagated-exposure link (table)",
           lambda: p.locator("a[href^='Risk_Propagation?issuer_id=']").first.click() and None,
           expect=lambda: "Risk_Propagation" in p.url)
    d.settle(1500)

    # ---------------------------------------------------------------- Risk Propagation
    d.step("Propagation", "opened from watchlist link", expect=lambda: "issuer_id=" in p.url)
    d.goto("Risk_Propagation")
    d.step("Propagation", "open page")
    d.step("Propagation", "issuer selector", lambda: d.select("Issuer (held", 1))
    d.step("Propagation", "positions selector", lambda: d.select("Show positions of", 1))

    # ---------------------------------------------------------------- News & Social Feed
    d.goto("News_Social_Feed")
    d.step("Feed", "open page", expect=lambda: p.locator('[data-testid="stDataFrame"]').count() > 0)
    d.step("Feed", "source type filter (drop one)", lambda: d.multiselect_drop_last("Source type"))
    d.step("Feed", "provenance filter (drop one)", lambda: d.multiselect_drop_last("Provenance"))
    d.step("Feed", "source filter (drop one)", lambda: d.multiselect_drop_last("Source"))

    # ---------------------------------------------------------------- NLP Risk Signals
    d.goto("NLP_Risk_Signals")
    d.step("NLP signals", "open page", expect=lambda: p.locator('[data-testid="stDataFrame"]').count() > 0)
    d.step("NLP signals", "risk level pills (deselect Low)",
           lambda: p.locator('[data-testid="stButtonGroup"]').get_by_role("button", name="Low").first.click() and None)
    d.step("NLP signals", "event type selector", lambda: d.select("Event type", 1))
    d.step("NLP signals", "event type back to All", lambda: d.select("Event type", 0))
    d.step("NLP signals", "minimum impact slider", lambda: d.slider_keys("Minimum impact", "ArrowRight", 4))
    d.step("NLP signals", "ticker trend multiselect", lambda: d.multiselect_drop_last("Tickers for the sentiment"))

    # ---------------------------------------------------------------- Portfolio
    d.goto("Portfolio")
    d.step("Portfolio", "open page", expect=lambda: p.locator('[data-testid="stDataFrame"]').count() > 0)

    # ---------------------------------------------------------------- Stress Test
    d.goto("Stress_Test")
    d.step("Stress Test", "open page")
    d.step("Stress Test", "stress run selector", lambda: d.select("Stress run (newest first)", 1))
    for tab in ("By sector", "By country", "Shocks applied", "By issuer"):
        d.step("Stress Test", f"tab {tab}", lambda tab=tab: p.get_by_role("tab", name=tab).first.click() and None)
    d.step("Stress Test", "what-if: start from", lambda: d.select("Start from", 1))
    d.step("Stress Test", "what-if: HY spread slider", lambda: d.slider_keys("HY", "ArrowRight", 5))
    d.step("Stress Test", "what-if: compare toggle", lambda: d.click_label("stCheckbox", "Compare with"))
    d.step("Stress Test", "manual: scenario selector", lambda: d.select("Scenario", 0))
    scen = d.widget("stSelectbox", "Scenario")
    scen.locator('div[data-baseweb="select"]').click()
    idio = p.locator('[role="option"]').filter(has_text="idiosyncratic")
    d.step("Stress Test", "manual: idiosyncratic scenario", lambda: idio.first.click() and None,
           expect=lambda: d.widget("stSelectbox", "Issuer (held)").count() > 0)
    d.step("Stress Test", "manual: issuer selector", lambda: d.select("Issuer (held)", 2))
    d.step("Stress Test", "Run stress test", lambda: d.button("Run stress test"))

    # ---------------------------------------------------------------- Explainability
    d.goto("Explainability")
    d.step("Explainability", "open page")
    d.step("Explainability", "signal selector", lambda: d.select("Signal (highest impact first)", 3))
    d.step("Explainability", "tab: Analyse your own headline",
           lambda: p.get_by_role("tab", name="Analyse your own headline").click() and None)

    def analyse() -> str:
        d.widget("stTextArea", "Headline or post").locator("textarea").fill(
            "Moody's downgrades Reliance Industries as SEBI opens probe into accounts")
        d.widget("stTextInput", "Optional ticker hint").locator("input").fill("RELIANCE.NS")
        p.get_by_role("button", name="Analyse").click()
        return "submitted"
    d.step("Explainability", "Analyse your own headline", analyse,
           expect=lambda: p.get_by_text(re.compile("Credit Event|impact", re.I)).count() > 0)

    # ---------------------------------------------------------------- Source Health
    d.goto("Source_Health")
    d.step("Source Health", "open page", expect=lambda: p.locator('[data-testid="stDataFrame"]').count() > 0)

    # ---------------------------------------------------------------- reset
    d.goto("")
    sb.get_by_text("Mode & demo control").first.click()
    d.step("Home", "⟲ Reset", lambda: d.button("⟲ Reset", sb))
    d.goto("")
    d.step("Home", "after reset")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="write the results as Markdown")
    ap.add_argument("--shots", default=str(WORK / "screenshots"), help="screenshot folder (one JPEG per step)")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "logs").mkdir(parents=True)
    shots = Path(args.shots)
    shutil.rmtree(shots, ignore_errors=True)
    shots.mkdir(parents=True)
    env = {**os.environ, "DB_PATH": str(WORK / "api.db"), "LOG_DIR": str(WORK / "logs"), "APP_MODE": "SCENARIO",
           "DEMO_STEP_SECONDS": "0", "REPLAY_DELAY_S": "0", "REAL_HISTORY_AUTOLOAD": "true",
           "API_BASE_URL": API, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT / "src")}
    api_log, ui_log = WORK / "api.log", WORK / "ui.log"
    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "--app-dir", "src", "app.main:app", "--host",
                               "127.0.0.1", "--port", str(API_PORT)], cwd=ROOT, env=env,
                              stdout=open(api_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT)]
    try:
        t0 = time.time()
        while True:  # API up and REAL history loaded
            try:
                h = httpx.get(f"{API}/history", timeout=10).json()
                if h["status"].get("state") in ("ready", "error"):
                    break
            except (httpx.HTTPError, KeyError, ValueError):
                pass
            if time.time() - t0 > 900:
                raise SystemExit("API / REAL history did not come up")
            time.sleep(2)
        procs.append(subprocess.Popen([sys.executable, "-m", "streamlit", "run", "src/app/dashboard/Home.py",
                                       "--server.port", str(UI_PORT), "--server.headless", "true",
                                       "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env,
                                      stdout=open(ui_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tmp" / "ms-playwright"))
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=not args.headed)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            for _ in range(60):
                try:
                    httpx.get(UI, timeout=5)
                    break
                except httpx.HTTPError:
                    time.sleep(2)
            run(Driver(page, shots))
            try:
                browser.close()
            except Exception as exc:  # noqa: BLE001 - teardown only; the steps above are already recorded
                print(f"(browser close: {exc})")
    finally:
        for proc in procs:
            proc.terminate()
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.kill()
    for name, path in (("API", api_log), ("dashboard", ui_log)):
        text = path.read_text(encoding="utf-8", errors="replace")
        bad = [ln for ln in text.splitlines() if re.search(r"Traceback|\bERROR\b|Exception|HTTP/1.1\" 5\d\d", ln)]
        results.append(("server logs", f"{name} log clean", not bad, f"{len(bad)} bad lines"
                        + (f": {bad[0][:140]}" if bad else "")))
        print(f"{'PASS' if not bad else 'FAIL'}  {name} log: {len(bad)} error lines")
    n_ok = sum(1 for r in results if r[2])
    print(f"\n{n_ok}/{len(results)} steps passed")
    if args.out:
        md = [f"# Dashboard verification ({time.strftime('%Y-%m-%d %H:%M')})", "",
              f"`python src/scripts/verify_dashboard.py`: **{n_ok}/{len(results)} steps passed**. Own API + "
              "dashboard, headless Microsoft Edge (Playwright), 1440×900; a step fails on any Streamlit exception box, "
              "error box, failed expectation or server-log error. Screenshot per step in brackets.", "",
              "| result | page | step | detail |", "|---|---|---|---|"]
        md += [f"| {'PASS' if ok else '**FAIL**'} | {pg} | {st} | {det.replace('|', '/')} |"
               for pg, st, ok, det in results]
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
