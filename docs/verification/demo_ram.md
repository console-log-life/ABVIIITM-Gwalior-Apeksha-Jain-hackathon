# Demo RAM measurement

`python src/scripts/measure_demo_ram.py` on 2026-10-07 22:53 (offline demo, FinBERT fp32, 2 torch threads).

- free RAM before start: 0.79 GB
- ready on REAL data after 32 s
- peak RAM of the demo (API + dashboard + launcher, summed RSS): 0.88 GB
- peak during start-up: 0.87 GB
- peak during pages: 0.56 GB
- peak during story: 0.88 GB
- lowest free system RAM during the run: 0.40 GB
- dashboard pages: 9/9 HTTP 200
- story: 0.41% GREEN → 1.32% AMBER → 2.45% RED
- error lines in logs/demo_api.log + demo_ui.log: 0
- RESULT: PASS

Caveats: the page check is HTTP only (Streamlit runs a page's script when a browser connects; the browser's own memory is not counted; every page and control is rendered in a real browser by src/scripts/verify_dashboard.py). Under memory pressure Windows trims working sets, so the peak may be understated. Free RAM was below the 1.5 GB preflight threshold during this run: harder conditions than the 2 GB target.
