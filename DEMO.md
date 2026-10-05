# Demo — how to run it

**One command** (after `tasks.ps1 setup` has been run once):

```powershell
powershell -ExecutionPolicy Bypass -File tasks.ps1 demo          # or: .venv\Scripts\python.exe scripts\run_demo.py
powershell -ExecutionPolicy Bypass -File tasks.ps1 demo-offline  # same, network not needed (models from ./models)
```

Then open:

- Dashboard: <http://127.0.0.1:8501>
- API docs (Swagger): <http://127.0.0.1:8000/docs>

`run_demo.py` starts the API and the dashboard, resets the demo state, and plays `data/scenarios/demo_story.json`:
first a **real-data opening (step 0)**, then the scripted story with one step every 10 s and a **20 s pause after
step 2** for the watchlist. The step 0 headlines are REAL and unchanged from the committed sample
`data/cache/sample/sample_google_news.jsonl` (badge **CACHED_REAL**, with capture time). They were chosen because none
of them triggers a stress run, so the scripted results below are unaffected. Steps 1–4 are **SYNTHETIC** and labelled
that way everywhere. Everything goes through exactly the same NLP pipeline as live data.

| Step | Headline | Expected outcome |
|---|---|---|
| 0 | REAL (CACHED_REAL, captured 2026-10-03), 4 s apart: "India's HDFC Bank appoints outsider Anup Bagchi as CEO" · "Tesla Q3 Deliveries Top Expectations; The Stock Is Rising" · "Harley-Davidson's Credit Rating Downgraded to Junk Status by S&P" · "Infosys, Wipro shares slump to six year lows; brokerages flag muted Q2 growth outlook" | Management 4.9 · Other 5.5 · Credit Event 7.3 (Harley-Davidson is not held) · Earnings 7.6. **No stress run.** These are dated by their original publication, so they sit outside the watchlist's 24 h window |
| 1 | Nvidia unveils new GPU lineup for gamers (social) | Product Launch, impact 3.6 **Low**: no trigger |
| 2 | Moody's downgrades Tata Motors to junk as SEBI opens probe | Credit Event, 8.7 **Critical** → idiosyncratic stress on Tata Motors (0.41%, GREEN; the CDS hedge offsets). **Early Warning Watchlist: Tata Motors WATCH-NEGATIVE, rank 1** (impact 8.7 ≥ 7 with sentiment −0.90; 4.94% of the funded book, rating bucket BB). Story pauses 20 s: show the watchlist |
| 3 | Russia launches invasion of neighbouring state; West readies sweeping sanctions | Geopolitical / MARKET, 7.0 **High** → `geopolitical_moderate` (1.32%, AMBER) |
| 4 | Invasion confirmed as troops cross border; sanctions and market sell-off spread worldwide (second source) | 2 corroborating sources, 9.1 **Critical** → `geopolitical_severe` (2.45%, RED) |

Steps 1–4 are SYNTHETIC; the step 0 headlines are real. The outcomes above are the outputs of `scripts/run_demo.py`
on the developer laptop. They are deterministic: the same
story and the same seed-42 portfolio give the same results every run.

Stress results come from a simplified, illustrative hackathon stress model. They are not a production or regulatory
risk model.

## Other modes (sidebar → "Mode & demo control")

- **REPLAY** streams real articles captured earlier by `scripts/capture_cache.py` (badge: CACHED_REAL, with the capture time).
  On a fresh clone it uses the published 50-headline Google News sample.
- **LIVE** polls the real sources (Google News, Reddit RSS, Mastodon; GDELT, StockTwits, Finnhub and Bluesky are
  best-effort or optional).
- **⟲ Reset** clears demo, replay and API signals and all stress runs.

## Backup plan

If the network or API fails during a presentation, see `docs/demo_script.md` → "Backup plan". In short: `tasks.ps1 demo-offline`
works without any network, REPLAY shows real cached data, and `docs/screenshots/` holds static images of every page.

Before presenting, run `tasks.ps1 preflight` (GO / NO-GO: RAM, model files, DB, free ports, demo data).

A **silent backup recording** of this story is in `docs/demo/demo_walkthrough.webm` (3:30, 1600×900, captions on
screen; re-record with `tasks.ps1 video`). A narrated recording still has to be made by a person.
