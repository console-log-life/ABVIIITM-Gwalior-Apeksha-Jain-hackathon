# Verification report

Full function verification after the move to the `src/` submission layout, run on 2026-10-07 on the development
laptop (Windows 11, Python 3.11.9, 8 GB RAM, CPU only). Every row was produced by a command in this repository; the
detailed per-check logs are linked. Where a check failed, the fix is in the "fix" column and the check was re-run.

**Summary:** tests 270 fast + 5 FinBERT passed (93% coverage) · API 87/87 checks · dashboard 55/55 steps · every script
`--help` and a real run · `tasks.ps1 demo` and `demo-offline` end to end · fresh clone following the README Quickstart
(setup, tests, offline demo): PASS after one fix ([section 6](#6-fresh-clone-following-the-readme-quickstart)).
Ten defects were found and fixed ([section 7](#7-defects-found-and-fixed)).

## 1. Test suite

| check | command | result |
|---|---|---|
| fast suite + coverage | `python -m pytest -m "not model" --cov=app --cov=risk_engine --cov=portfolio` | PASS: 270 passed, coverage 93% (3861 statements, 286 missed) |
| FinBERT model tests (separate process) | `python -m pytest -m model --cov=...` | PASS: 5 passed |
| lint | `ruff check src tests` | PASS |
| untested public functions | `python src/scripts/list_untested.py --coverage .tmp/coverage.json .tmp/coverage_model.json` | 5 of 286 (was 30): [verification/untested.md](verification/untested.md) |

The 25 functions that were never executed now have tests in `tests/test_untested_functions.py`: `GET /methodology`,
`POST /history/load` (builds and loads a history from a test cache), LIVE mode through `POST /mode` with a fake adapter
(no network), the scheduler's `run_forever` loop, `build_live_adapters`, the StockTwits parser (channel kept, author
dropped), Mastodon state round-trip, source-health upsert, `EventBus.subscriber_count`, `EventResult.distinct_patterns`,
the replay CLI, `generate_portfolio.main`, and (model test) the module-level `pipeline.process` / `process_batch` /
`main` entry points.

The 5 still without a unit test, and how they were verified instead:

| function | why no unit test | verified by |
|---|---|---|
| `zero_shot.get_zero_shot`, `ZeroShotTieBreaker.pick` | optional 1.6 GB model, off by default (it lowered event macro-F1 by 0.015) | the zero-shot comparison in `docs/evaluation.md` (`src/scripts/evaluate.py` without `--no-zero-shot`) |
| `scheduler.main`, `print_reports`, `log_sink` | CLI that calls the real sources | real run `tasks.ps1 ingest-once` (section 4): PASS |

## 2. API: every endpoint, valid and invalid input

`python src/scripts/verify_api.py --live --out docs/verification/api.md` starts its own API on a throw-away database,
loads the REAL history (1325 signals, 54 runs) and calls all 26 routes plus `/docs`, `/openapi.json` and an unknown
route. **87/87 checks PASS**: full table with every request and status code in
[verification/api.md](verification/api.md).

Covered: 200 paths of every route; 404 for unknown signal, run, issuer and `since_id`; 422 for every validated
parameter (bad event type, impact out of range, bad timestamp, hours out of range, empty or 101-item batch, invalid
JSON, unknown scenario, missing shocks, shocks out of range, issuer not held, unknown mode, LIVE through
`/demo/start`, `format=docx`, bad boolean); the SSE stream (`text/event-stream`, 2 events with `max_events=2`); the
JSONL export (188 lines, one JSON object each, all with impact ≥ 7); `X-Duplicate` deduplication on `/analyze`; the
credit-brief PDF (`%PDF-` header); the scripted story (3 stress runs, GREEN → AMBER → RED; Tata Motors
WATCH-NEGATIVE); REPLAY; LIVE on the real network for 20 s and back; `/demo/reset`. The server log has no error or
traceback and no 5xx response (126 requests).

## 3. Dashboard: every page and every control, in a real browser

`python src/scripts/verify_dashboard.py --out docs/verification/dashboard.md --shots docs/verification/screenshots`
starts its own API and dashboard and drives them with Playwright in headless Microsoft Edge (1440×900). A step fails on
a Streamlit exception box, an error box, a failed expectation or an error in either server log. **55/55 steps PASS**:
[verification/dashboard.md](verification/dashboard.md), one screenshot per step in
[verification/screenshots/](verification/screenshots/).

| page | controls exercised |
|---|---|
| sidebar (every page) | time machine slider back, **Latest** button, auto-refresh toggle on/off, Mode radio + **Apply mode** (REPLAY), **▶ Scenario demo**, **⟲ Reset** |
| Home | KPIs before and after the story |
| Early Warning Watchlist | window selector (72 h), "show all held issuers" checkbox, issuer expander, **Credit brief** toggle, **⬇ Download PDF** (file checked), **Explain →** link (opens Explainability with the signal), propagated-exposure link (opens Risk Propagation with the issuer) |
| Risk Propagation | issuer selector, "show positions of" selector |
| News & Social Feed | source type, provenance and source filters |
| NLP Risk Signals | risk-level pills, event-type selector (and back to All), minimum-impact slider, ticker multiselect |
| Portfolio | page render |
| Stress Test | stress-run selector, 4 result tabs, what-if "start from" selector, HY spread slider, compare toggle, manual scenario selector, idiosyncratic scenario + issuer selector, **Run stress test** |
| Explainability | signal selector, both tabs, **Analyse your own headline** (text + ticker hint → Analyse; result: Negative −0.915, Credit Event) |
| Source Health | page render |

`python src/scripts/check_dashboard.py` (Streamlit AppTest against the running demo API): 9/9 pages without errors.

## 4. Every script: `--help` and a real run

All 27 scripts and the 4 module CLIs exit 0 on `--help` with a usage line. Real runs (outputs that are committed were
either written to a temporary location or compared with the committed file and restored):

| script | real run | result |
|---|---|---|
| `setup_models.py --verify-only` | offline load of FinBERT and spaCy | PASS: all models ready (offline-capable) |
| `preflight.py` | full checklist incl. source probe | PASS: GO (1 warning: free RAM < 2 GB) |
| `probe_sources.py` | every source from this machine | PASS: Google News US/IN, Reddit, Mastodon ×2; GDELT 429, StockTwits 403, Bluesky skipped (no credentials), as documented |
| `capture_cache.py --sources google_news` | into an empty temporary `CACHE_DIR` | PASS: 579 new documents written as CACHED_REAL |
| `build_cache_sample.py` | on a copy of the captures | PASS: 50 headlines (differs from the committed sample only because the cache has grown since) |
| `scrub_cache.py --dry-run` | local captures | PASS: 0 author handles remaining |
| `build_real_history.py` | fingerprint check | PASS: fresh (1325 signals, 54 runs) |
| `evaluate.py --no-zero-shot` | full evaluation (n = 147) | PASS: sentiment 0.653, event 0.81, entity 0.898: identical to the committed results |
| `benchmark_latency.py --out-dir .tmp/...` | 200 documents | PASS: median 177.1 ms (committed: 204.7 ms; same machine, varies with load) |
| `replay_trigger_report.py --label verify --captured-before 2026-10-04` | 911 real documents | PASS: 50 stress runs, identical to the committed result (84 before the fixes) |
| `build_label_review.py` → `import_label_review.py --no-evaluate` | round trip on a copy of the labels | PASS: 147 rows, file byte-identical after the round trip |
| `import_trained_models.py` | no zip yet | PASS: clean error and exit 1 (`trained_models.zip` not downloaded yet) |
| `datasets/prepare_public.py` | downloads both public datasets | FAIL → fixed → PASS: identical split ids and SHA-256 |
| `build_training_notebook.py` | regenerate the notebook | PASS: byte-identical |
| `render_architecture.py` | regenerate `docs/architecture.png` | PASS: byte-identical |
| `crop_screenshots.py` | regenerate the deck crops | PASS: byte-identical |
| `build_presentation.py` | rebuild the 7-slide deck | PASS: every slide part identical (only zip timestamps differ) |
| `render_slides.ps1` | PowerPoint COM, to a temporary folder | PASS: 7 previews + PDF |
| `build_submission.py` | checks + HTML | PASS: 22/22 checks; "NOT READY TO SUBMIT: 6 placeholders" (expected until the links are filled) |
| `screenshot_dashboard.py --size 800x600` | against the running demo | PASS (output deleted) |
| `check_dashboard.py` | against the running demo | PASS: 9/9 pages |
| `failure_drill.py` | network blocked, models offline | FAIL → fixed → PASS: 7/7 |
| `run_demo.py` | via `tasks.ps1 demo` / `demo-offline` | PASS (section 5) |
| `verify_api.py`, `verify_dashboard.py`, `list_untested.py` | sections 1–3 | PASS |
| `record_demo_video.py` | full recording (API + dashboard + Edge) | PASS: 16 scenes; idle waits trimmed afterwards (section 8) |
| `python -m risk_engine.pipeline "Moody's downgrades Tata Motors to junk"` | | PASS: Negative, Credit Event, impact 7.6 |
| `python -m risk_engine.ingestion.replay --limit 20` (`tasks.ps1 replay`) | | FAIL → fixed → PASS |
| `python -m risk_engine.ingestion.scheduler --once` (`tasks.ps1 ingest-once`) | real sources | FAIL → fixed → PASS: Reddit 25, Mastodon 140 fetched; GDELT/StockTwits backoff |
| `python -m portfolio.generate_portfolio` (`tasks.ps1 portfolio`) | | FAIL → fixed → PASS: identical to the committed CSV (seed 42) |

Other `tasks.ps1` targets run: `lint`, `submission`, `real-history`, `preflight`: PASS.

## 5. Demo end to end

| run | result |
|---|---|
| `tasks.ps1 demo-offline` | PASS: API + dashboard up, REAL history 1325 signals / 54 runs, dashboard HTTP 200, 9/9 pages, story via the API: idiosyncratic 0.41% GREEN → geopolitical moderate 1.32% AMBER → severe 2.45% RED; no error in `logs/demo_api.log` or `logs/demo_ui.log` |
| `tasks.ps1 demo` | PASS: same start-up, REAL history loaded, dashboard HTTP 200, clean logs |

## 6. Fresh clone following the README Quickstart

`git clone` of this repository into `.tmp/fresh_clone/`, then the Windows commands of the README **Quickstart**
exactly as written:

| step | result |
|---|---|
| `tasks.ps1 setup` (new venv, `pip install -r requirements.txt`, FinBERT + spaCy into `./models`) | PASS: exit 0 in 37.2 min (first run, including all downloads); "ALL MODELS READY (offline-capable)" |
| `tasks.ps1 test` | **FAIL → fixed → PASS.** First run: collection error, `No module named 'capture_cache'` (defect 10 below). After the fix (`git pull` in the clone): exit 0 in 3.3 min; 267 passed + 1 module skipped (the 3 label-review tests need `requirements-dev.txt`), coverage 93%; FinBERT tests 5 passed |
| `tasks.ps1 demo-offline` | PASS: REAL history built at start-up from the published 50-headline sample (50 signals, 2 runs) in ~50 s; dashboard HTTP 200; `check_dashboard.py` 9/9 pages; scripted story 0.41% GREEN → 1.32% AMBER → 2.45% RED, Tata Motors WATCH-NEGATIVE (identical to the development copy); no errors in either server log; the clone's working tree stayed clean |

The Linux/macOS `make` targets run the same commands (`Makefile`, also `PYTHONPATH=src`); they were not executed on
Linux for this report.

## 7. Defects found and fixed

| # | defect | found by | fix |
|---|---|---|---|
| 1 | `tasks.ps1 replay`, `ingest-once`, `portfolio` (and the Makefile targets) failed with `No module named 'risk_engine'` after the move to `src/` | real run of `tasks.ps1 replay` | both task runners set `PYTHONPATH=src`; module docstrings say so |
| 2 | `GET /history` could report `state: ready` with an empty event range (status read after the range) | API verifier (4 checks failed with an empty `as_of`) | the status is snapshotted before the range is read |
| 3 | failure drill reported "SCENARIO story" as failed: with the REAL history loaded, the unfiltered counts hit the 50-row default, and its REPLAY check could no longer fail | real run of `failure_drill.py` | the drill runs without the history and counts only the story's and REPLAY's own signals (4 SYNTHETIC, GREEN → AMBER → RED; 10 replayed) |
| 4 | `prepare_public.py` without arguments exited with "invalid choice" (Python 3.11 argparse checks the default list against `choices`) | real run | manual validation of the dataset names |
| 5 | `benchmark_latency.py --out-dir` printed the default output paths | real run | prints the paths it wrote |
| 6 | `render_slides.ps1` usage line pointed at the old `scripts\` folder | `--help` review | path updated |
| 7 | README test counts were stale (259 + 4) | this report | 270 + 5, coverage 93% |
| 8 | 25 public functions had no test | `list_untested.py` | `tests/test_untested_functions.py` |
| 9 | 9 scripts had no `--help` | `--help` loop | argparse with the module docstring |
| 10 | on a fresh clone `tests/test_replay_capture.py` failed to import `capture_cache`: it still pointed at the pre-move `scripts/` folder and only passed locally because another test module had added `src/scripts` first | fresh clone (section 6) | `src/scripts` on pytest's `pythonpath`; path in the test corrected; every test file now also passes on its own |

Earlier in the same compliance pass (see git history): a lint error that slipped into the layout commit (a piped
`ruff` hid its exit code), the REAL-history fingerprint going stale after the move (YAML now hashed by content), the
deck renderer's default paths, and white space around the architecture image.

## 8. Notes and limits

- `record_demo_video.py` (it failed for lack of RAM before this pass) completed this time: 16 scenes, raw capture
  9:03 because the recorder waits for each story step on the live API; the idle waits were cut out afterwards
  (about 4:19 kept, scenes unchanged) and `docs/DEMO.md` now describes the current flow. It is a silent backup; the
  narrated video for the submission still has to be recorded by a person (`docs/demo_script.md`, version a).

- The zero-shot comparison was not re-run (`evaluate.py --no-zero-shot`) to stay within the laptop's RAM; its
  committed numbers come from the earlier full run.
- `tasks.ps1 capture` was run only against a temporary cache directory (the real cache is the REPLAY data).
- `import_trained_models.py` waits for `trained_models.zip` from the GPU notebook run.
