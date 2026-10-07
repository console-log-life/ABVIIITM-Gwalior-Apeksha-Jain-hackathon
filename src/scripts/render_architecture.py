"""Render docs/architecture.png (3840 px wide) from docs/architecture_diagram.html with the installed Edge.

Usage:  python src/scripts/render_architecture.py      (requires requirements-dev.txt: playwright)
"""

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tmp" / "ms-playwright"))
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
        pg.goto((ROOT / "docs" / "architecture_diagram.html").as_uri())
        pg.wait_for_timeout(800)
        pg.locator(".wrap").screenshot(path=str(ROOT / "docs" / "architecture.png"))
        b.close()
    print("wrote docs/architecture.png")


if __name__ == "__main__":
    main()
