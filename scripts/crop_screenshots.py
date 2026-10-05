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
CROPS = {
    "stress_banner.png": ("05_stress.png", (415, 355, 1515, 700)),
    "stress_waterfall.png": ("05_stress.png", (415, 690, 1515, 1110)),
    "stress_top10_heatmap.png": ("05_stress.png", (415, 1130, 1515, 1590)),
    "signals_charts.png": ("03_signals.png", (419, 1005, 1518, 1395)),
    "signals_table.png": ("03_signals.png", (419, 470, 1518, 945)),
    "home_kpis.png": ("01_home.png", (410, 205, 1535, 555)),
    "explain_factors.png": ("06_explain.png", (410, 940, 1535, 1300)),
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
