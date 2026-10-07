# Demo — how to run it

**One command** (after `tasks.ps1 setup` has been run once):

```powershell
powershell -ExecutionPolicy Bypass -File tasks.ps1 preflight     # GO / NO-GO: RAM, models, DB, ports, REAL history
powershell -ExecutionPolicy Bypass -File tasks.ps1 demo-offline  # API + dashboard on REAL data, no network needed
```

Then open the dashboard at <http://127.0.0.1:8501> (API docs: <http://127.0.0.1:8000/docs>).

`run_demo.py` starts the API and the dashboard, resets the demo state and waits until the **REAL history** is loaded:
every document in the local capture cache (1,325 real headlines and posts, CACHED_REAL), processed through the same
pipeline and trigger rules (`tasks.ps1 real-history` builds the cache ahead of time; otherwise the API builds it at
start-up, about 7 minutes on the demo laptop). Then it waits for the presenter. The scripted story is started from the
sidebar (**Mode & demo control → ▶ Scenario demo**). `--play-story` plays it immediately (automation).

## What is real and what is synthetic

| Part of the demo | Provenance |
|---|---|
| Home, Watchlist, Feed, Signals, Explainability, Propagation before the scenario | **CACHED_REAL**: real captured documents (capture time on every badge). Time machine = replay by publication time |
| Stress runs in the REAL history (54) | Triggered by CACHED_REAL signals; **simulated** with the illustrative model on the SYNTHETIC portfolio |
| Scenario demo: step 0 | 4 real headlines from the committed sample (CACHED_REAL), none triggers stress |
| Scenario demo: steps 1–4 (Nvidia launch, Tata Motors downgrade, invasion ×2) | **SYNTHETIC** scripted headlines |
| Portfolio (49 positions, seed 42), what-if results, credit-brief stress figures | **SYNTHETIC** portfolio, **simulated** results |

## The 5-minute flow (timed script with talking points: `docs/demo_script.md`)

| Time | Screen | What happens |
|---|---|---|
| 0:00 | Home (REAL) | KPIs over the last 24 h of real news (as of 5 Oct 20:03 UTC on the current cache: 326 signals, 18 held issuers on watch, 7 WATCH-NEGATIVE, ▲ vs the previous 24 h). Drag the **time machine** back a day, then **Latest**. The latest real-triggered run (rate shock, 4.24% RED) came from an opinion headline: a known false-positive type, shown openly |
| 0:45 | Early Warning Watchlist → Explainability | Top real issuer: **HDFC Bank** (WATCH-NEGATIVE, worst impact 8.1, sentiment −0.95). Sparkline = impact over 24 h + 6 h rolling max. **Explain →** opens the signal: probabilities, evidence, weighted factors |
| 1:45 | Risk Propagation | HDFC Bank: direct vs propagated exposure over curated links (peer SBI); graph sized by exposure, coloured by status; click a node for its positions |
| 2:30 | Sidebar **▶ Scenario demo** (SYNTHETIC) | Tata Motors downgrade 8.7 → issuer stress 0.41% GREEN (CDS hedge) → watchlist WATCH-NEGATIVE, Ford/Tesla flagged by propagation (⇄) → invasion 7.0 → 1.32% AMBER → second source 9.1 → **2.45% RED**. The story pauses 20 s after the downgrade |
| 3:45 | Stress Test → **What-if** | A judge picks a shock (start from "Geopolitical severe", push HY spreads); compare with the triggered run side by side; nothing is saved |
| 4:20 | Watchlist → Tata Motors → **Credit brief** | One-page, template-based brief; **Download PDF** (`credit_brief_TATAMOTORS_NS_<date>.pdf`). Close |

Scenario outcomes (deterministic: same story, same seed-42 portfolio):

| Step | Headline | Outcome |
|---|---|---|
| 0 | 4 REAL headlines (HDFC CEO, Tesla deliveries, Harley-Davidson junk, Infosys/Wipro slump) | 4.9 · 5.5 · 7.3 · 7.6; **no stress run** |
| 1 | Nvidia unveils new GPU lineup for gamers (social) | Product Launch 3.6 **Low**: no trigger |
| 2 | Moody's downgrades Tata Motors to junk as SEBI opens probe | Credit Event 8.7 **Critical** → idiosyncratic stress 0.41% GREEN; Tata Motors WATCH-NEGATIVE |
| 3 | Russia launches invasion of neighbouring state; West readies sweeping sanctions | Geopolitical / MARKET 7.0 → `geopolitical_moderate` 1.32% AMBER |
| 4 | Invasion confirmed as troops cross border; sanctions and market sell-off spread worldwide | 2 sources, 9.1 → `geopolitical_severe` 2.45% RED |

Stress results come from a simplified, illustrative hackathon stress model. They are not a production or regulatory
risk model.

## Other modes (sidebar → "Mode & demo control")

- **REPLAY** streams the captured real articles again (CACHED_REAL); **LIVE** polls the real sources. The REAL history
  stays loaded in every mode.
- **⟲ Reset** clears scenario, replay and API signals and their stress runs; the REAL history is kept.

## Backup plan

`tasks.ps1 demo-offline` needs no network. `docs/screenshots/1366x768/` and `1920x1080/` hold every page at projector
sizes. A **silent backup recording** is in `docs/demo/demo_walkthrough.webm` (captions on screen; caption times in
`docs/demo/demo_walkthrough_captions.json`). It still shows the PREVIOUS flow (scenario story, watchlist and
explainability, 3:04): the recorder (`src/scripts/record_demo_video.py`) is already updated for the new flow, but
re-recording needs ~2 GB of free RAM; run `tasks.ps1 video` with other applications closed. A narrated recording still
has to be made by a person.
