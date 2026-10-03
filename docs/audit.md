# Final audit

| Req | Requirement | Implemented? | Where | How demonstrated | Potential issue | Fix / mitigation |
|---|---|---|---|---|---|---|
| R1 | Ingest real-time unstructured text | Yes | `risk_engine/ingestion/*`, `scheduler.py` | LIVE mode, LIVE badges, Source Health page | Only 3 keyless sources pass reliably; Reddit throttles hard | REPLAY of CACHED_REAL captures; optional Finnhub/Bluesky keys |
| R2 | ≥ 2 source types (news + social) | Yes | Google News (news); Reddit + Mastodon (social) | Feed page source/type columns; probe table | Social sources are unofficial, best-effort | Documented in data_sources.md; health panel |
| R3 | Sentiment in [−1, 1] | Yes | `sentiment/finbert.py` | Signal JSON, Explainability page | FinBERT on headlines only; PRELIMINARY accuracy 0.653 | Human label review; full-text sources |
| R4 | Event classification | Yes | `event_classifier/` | Event distribution chart, evidence chips | Keyword false positives (figurative "war") | Corroboration and cooldown; future fine-tuned classifier |
| R5 | Impact 1–10, transparent | Yes | `impact_scoring/` | Factor bar + formula; `/methodology` | Uncalibrated priors; positive news raises impact | Stated openly; calibration is future work |
| R6 | Structured output downstream | Yes | FastAPI, SQLite, `/signals/export.jsonl`, `/signals/stream` | Swagger examples; API tests | No auth | Local prototype; auth is future work |
| R7 | Module B stress testing | Yes | `portfolio/` | Stress page | Illustrative model | Disclaimer on every view |
| R8 | Portfolio from provided data, else synthetic | Synthetic (no data provided) | `generate_portfolio.py`, `loader.py` | Portfolio page badge "SYNTHETIC (generated, seed 42)" | Loader expects our schema for provided data | Mapping layer documented as the extension point |
| R9 | Mix of loans, bonds, derivatives | Yes | 49 positions: Loan/Bond/IRS/CDS/FX/Equity | Composition chart | Mix measured on gross exposure | Documented (D8) |
| R10 | High-impact event triggers stress | Yes | `triggers.py`, bus subscription | Alert banner + audit log with trigger signal_id | Systemic false positives from real data | Cooldown; suppressed-trigger log |
| R11 | Before vs after visualisation | Yes | Waterfall, top-10, heatmap | Stress page | — | — |
| R12 | Public repo, runnable | Local git only (no remote yet) | README quickstart | Fresh-clone check (M7) | User must create the GitHub repo | Listed in OVERNIGHT_REPORT |
| R13 | ≤ 5-min demo | Yes | `DEMO.md`, `scripts/run_demo.py`, `docs/demo_script.md` | Deterministic offline run | Not yet rehearsed by a human | Rehearse twice |
| R14 | ≤ 7 slides | Outline only | `docs/slides_outline.md` (exactly 7) | — | Slides not yet built | User builds the deck from the outline |

## Harsh scores (/100, honest self-assessment)

| Dimension | Score | Why not higher |
|---|---:|---|
| Technical quality | 78 | Clean modular code, 142 tests, 88% coverage, drills. Single process; in-process bus; SQLite |
| NLP | 62 | FinBERT + rules + resolver work, but there's no fine-tuning, keyword false positives, headline-only input, and the evaluation is PRELIMINARY with same-author bias |
| Financial reasoning | 66 | Correct sign conventions, hedges, triggers, HHI, RAG; but illustrative shocks, no correlations or FX translation, synthetic book |
| Business relevance | 74 | Clear triage-to-portfolio story with an audit trail; no user validation |
| Innovation | 68 | Provenance everywhere, corroboration-escalated stress, one pipeline across modes; components are standard |
| UI/UX | 72 | All 12 sections, readable on a projector, explainability; Streamlit limits polish; light theme only |
| Reliability | 82 | Offline drill 7/7, source-kill test, backoffs, deterministic demo; a long-running LIVE soak test was not done |
| Presentation | 60 | Outline, script and Q&A are ready; the deck itself isn't built and there's no recording yet |
| Demo | 76 | One command, offline, deterministic, with a backup plan; not rehearsed by a human |
| **Overall** | **70** | A solid, honest MVP; weakest on evaluation rigour and model calibration |
