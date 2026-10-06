"""Crop focused regions from docs/screenshots/*.png into docs/presentation/assets/ for the slide deck.

Boxes are (left, top, right, bottom) in screenshot pixels (1600 px wide captures from scripts/screenshot_dashboard.py).
Re-run after refreshing screenshots; check docs/presentation/assets/_contact_sheet.png.

Usage:  python scripts/crop_screenshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "docs" / "presentation" / "assets"
CROPS = {  # dark theme, 1600-px full-page captures (scripts/screenshot_dashboard.py without --size)
    "stress_banner.png": ("05_stress.png", (405, 255, 1525, 520)),
    "stress_waterfall.png": ("05_stress.png", (405, 540, 1525, 960)),
    "stress_top10_heatmap.png": ("05_stress.png", (405, 975, 1525, 1430)),
    "home_kpis.png": ("01_home.png", (405, 140, 1525, 335)),
    "explain_factors.png": ("06_explain.png", (405, 870, 1525, 1180)),
    "watchlist.png": ("08_watchlist.png", (405, 120, 1525, 720)),
    "propagation_graph.png": ("09_propagation.png", (405, 300, 1080, 790)),
    "credit_brief.png": ("10_credit_brief.png", (0, 0, 1068, 560)),
}
README_DIR = ROOT / "docs" / "screenshots" / "readme"
README_CROPS = {  # the three images at the top of README.md
    "1_home.png": ("01_home.png", (405, 60, 1525, 700)),
    "2_propagation.png": ("09_propagation.png", (405, 60, 1525, 870)),
    "3_stress.png": ("05_stress.png", (405, 60, 1525, 960)),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for name, (src, box) in CROPS.items():
        img = Image.open(SHOTS / src).convert("RGB")
        w, h = img.size
        box = (box[0], box[1], min(box[2], w), min(box[3], h))
        img.crop(box).save(OUT / name)
        made.append((name, img.crop(box)))
        print(f"{name}: {box} from {src} ({w}x{h})")
    sheet_w = 1100
    rows = [(n, im.resize((sheet_w, int(im.height * sheet_w / im.width)))) for n, im in made]
    sheet = Image.new("RGB", (sheet_w, sum(im.height + 30 for _, im in rows)), "white")
    y, draw = 0, ImageDraw.Draw(sheet)
    for n, im in rows:
        draw.text((5, y + 5), n, fill="black")
        sheet.paste(im, (0, y + 25))
        y += im.height + 30
    sheet.save(OUT / "_contact_sheet.png")
    README_DIR.mkdir(parents=True, exist_ok=True)
    for name, (src, box) in README_CROPS.items():
        img = Image.open(SHOTS / src).convert("RGB")
        img = img.crop((box[0], box[1], min(box[2], img.width), min(box[3], img.height)))
        img.thumbnail((1100, 1100))
        img.save(README_DIR / name, optimize=True)
        print(f"readme/{name}: {img.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
