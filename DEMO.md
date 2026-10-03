# Demo — how to run it

**One command** (after `tasks.ps1 setup` has been run once):

```powershell
powershell -ExecutionPolicy Bypass -File tasks.ps1 demo          # or: .venv\Scripts\python.exe scripts\run_demo.py
powershell -ExecutionPolicy Bypass -File tasks.ps1 demo-offline  # same, network not needed (models from ./models)
```

Then open:

- Dashboard: <http://127.0.0.1:8501>
- API docs (Swagger): <http://127.0.0.1:8000/docs>

`run_demo.py` starts the API and the dashboard, resets the demo state, and plays the scripted story
`data/scenarios/demo_story.json`, with one step every 10 s. All story headlines are **SYNTHETIC** and labelled
that way everywhere. They go through exactly the same NLP pipeline as live data.

| Step | Headline (SYNTHETIC) | Expected outcome |
|---|---|---|
| 1 | Nvidia unveils new GPU lineup for gamers (social) | Product Launch, impact 3.6 **Low**: no trigger |
| 2 | Moody's downgrades Tata Motors to junk as SEBI opens probe | Credit Event, 8.7 **Critical** → idiosyncratic stress on Tata Motors (0.41%, GREEN; the CDS hedge offsets) |
| 3 | Russia launches invasion of neighbouring state; West readies sweeping sanctions | Geopolitical / MARKET, 7.0 **High** → `geopolitical_moderate` (1.32%, AMBER) |
| 4 | Invasion confirmed as troops cross border; sanctions and market sell-off spread worldwide (second source) | 2 corroborating sources, 9.1 **Critical** → `geopolitical_severe` (2.45%, RED) |

The outcomes above are the outputs of `scripts/run_demo.py` on the developer laptop. They are deterministic: the same
story and the same seed-42 portfolio give the same results every run.

Stress results come from a simplified, illustrative hackathon stress model. They are not a production or regulatory
risk model.

## Other modes (sidebar → "Mode & demo control")

- **REPLAY** streams real articles captured earlier by `scripts/capture_cache.py` (badge: CACHED_REAL, with the capture time).
- **LIVE** polls the real sources (Google News, Reddit RSS, Mastodon; GDELT, StockTwits, Finnhub and Bluesky are
  best-effort or optional).
- **⟲ Reset** clears demo, replay and API signals and all stress runs.

## Backup plan

If the network or API fails during a presentation, see `docs/demo_script.md` → "Backup plan". In short: `tasks.ps1 demo-offline`
works without any network, REPLAY shows real cached data, and `docs/screenshots/` holds static images of every page.
