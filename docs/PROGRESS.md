# PROGRESS (build memory — read this first after any restart)

> Git history was rewritten on 2026-10-05 (task 2). Commit hashes quoted in older entries below are the pre-rewrite hashes; use `git log --oneline` for current ones.

**Current task:** NIGHT 2 — task 7 (final consistency + report)
**Last commit:** 8d332b6
**Next step:** task 7: docs/submission numbers, build_submission, NIGHT2_REPORT, end-of-night capture

Mode: AUTONOMOUS OVERNIGHT (user instruction 2026-10-03): self-gates instead of stops; commit `M<n>: …` after
each milestone; run `scripts/capture_cache.py` at the start of each milestone; spec = BUILD_PROMPT.md
plus overrides recorded below. No pushes, no remotes, no `git reset --hard`, nothing outside the project dir.

## Night 2 (autonomous, 2026-10-05/06)

Brief: 1 restore classification / 2-pattern rule only in triggers · 2 remaining false positives (idiosyncratic needs s <= -0.25, verdict guard, rate cut vs hike + macro_rate_cut scenario) · 3 demo stability (FinBERT threads, warm-up, test split, preflight) · 4 label-review xlsx + import · 5 7-slide pptx · 6 silent demo video + GitHub (push only if a remote exists) · 7 final consistency + NIGHT2_REPORT.
Rules: no AI attribution in commits; no history rewrite; keep .tmp/backup/pre-rewrite.bundle; FinBERT once per process, 2 torch threads, never two model processes at once.

### Night 2 · Task 1: classification restored, 2-cue rule only in triggers (DONE)
- `classify_and_resolve` no longer demotes. `TriggerEngine` blocks a SYSTEMIC run when a MARKET-wide Geo/Macro signal
  has < 2 evidence cues of its class (`RuleEventClassifier.class_evidence_count` over the stored `event_evidence`).
- Evaluate (PRELIMINARY, n=147): event acc/F1 0.762/0.768 → **0.81/0.795**; entity 0.857 → **0.898**; sentiment
  0.653/0.648 unchanged; zero-shot 0.795 vs 0.78 → off. History table in docs/evaluation.md (`data/eval/eval_history.json`).
- Trigger replay on the fixed 911-doc set (`--captured-before 2026-10-04`): 84 (before) → 59 (night 1) → **59** (task 1);
  systemic 50, idiosyncratic 9, social-triggered 0. `trigger_replay_after.json` renamed `trigger_replay_night1.json`.
- Tests: 157 fast passed; ruff clean.

### Night 2 · Task 2: remaining false positives (DONE)
- (a) Idiosyncratic stress needs sentiment <= -0.25 (`TRIGGER_IDIOSYNCRATIC_MAX_SENTIMENT`). The real model scores the
  Adani court relief and the Jio SEBI clearance above the gate (model-marked test).
- (b) Litigation 'verdict' ignores analyst/opinion phrasing ("strong verdict for X stock", "analyst verdict", "our verdict",
  "verdict on the stock"); "jury verdict", "court delivers verdict" stay Litigation.
- (c) `risk_engine/event_classifier/rate_direction.py`: cut → new `macro_rate_cut` scenario (rates −50 bp, IG −10, HY −25,
  equity +2%, PD ×0.95, EM FX 0 since the brief gave no value); hike → macro_rate_shock_<severity>; unclear (no verb, a hold,
  or both) → no systemic run. Every pricer's sign is tested under the new scenario (net GAIN on this book, GREEN).
  Known limits: "little chance of a rate hike", "investors cut bets on rate rises" read as hikes.
- (d) Replay, fixed 911-doc set: 84 → 59 → 59 → **50** (systemic 45, idiosyncratic 5, social 0; scenarios:
  geopolitical_moderate 29, geopolitical_severe 5, macro_rate_shock_moderate 7, macro_rate_shock_severe 2, macro_rate_cut 2,
  idiosyncratic 5).
- Evaluate unchanged (0.653/0.648 · 0.81/0.795 · 0.898). Tests: 174 fast + 3 model (one shared FinBERT load per process).

### Night 2 · Task 3: demo stability (DONE)
- FinBERT: process-wide singleton (`load_finbert`, cached per model+dir), `torch.set_num_threads(TORCH_THREADS=2)`,
  log lines "Loading FinBERT … (once per process; torch threads=2)" / "FinBERT ready in 6.8 s", warm-up inference at
  API startup (0.12 s). Model tests share one session fixture (`finbert_engine`).
- `tasks.ps1 test` = fast suite + coverage, then model tests in a SEPARATE process; new `test-model`, `preflight`
  (same in Makefile). Result: 174 passed (87%) + 3 passed.
- `scripts/preflight.py`: RAM (WARN < 2 GB), FinBERT files + spaCy offline, DB writable, ports 8000/8501, demo story,
  portfolio, REPLAY data, live probe (non-blocking, 60 s cap) → GO / NO-GO. Tonight: GO with 1 warning (1.7 GB free).
- Demo end-to-end twice (`run_demo.py --exit-after-story`, then `--offline --exit-after-story`, both with the
  dashboard): identical to before: 3.6 Low · 8.7 → idiosyncratic 0.41% GREEN · 7.0 → moderate 1.32% AMBER ·
  9.1 (2 sources) → severe 2.45% RED. No demo numbers changed, so DEMO.md / demo_script / submission are unaffected.

### Night 2 · Task 4: label review spreadsheet (DONE)
- `data/eval/label_review.xlsx` (`scripts/build_label_review.py`, `tasks.ps1 label-review`): sheet "Review" has 147 rows
  with id, text, source, source_type, draft sentiment/event/ticker (grey), yellow input columns sentiment_corrected
  (dropdown Negative/Neutral/Positive), event_corrected (dropdown, the 11 classes), ticker_corrected (free text),
  label_status (dropdown draft_agent/human_reviewed), reviewer_notes, and agent_notes. Header + id/text frozen,
  wrapped text, Arial. A "How to review" sheet has the legend and an example row (never imported). NO model predictions.
- `scripts/import_label_review.py` (`tasks.ps1 import-labels`): corrected-or-draft per row, validates everything
  (nothing written on any error), keeps CSV text/metadata, then runs evaluate.py with a history label.
- Round trip: unchanged import on a copy reproduces the CSV byte-for-byte; tests cover corrections, status,
  invalid values and the absence of predictions (skipped when openpyxl is absent). Excel (COM) opens the file cleanly
  with the dropdowns intact. Tests: 177 fast passed.

### Night 2 · Task 5: 7-slide deck (DONE)
- `docs/presentation/Risk_Signal_Engine.pptx`, built by `scripts/build_presentation.py` (python-pptx, in requirements-dev.txt):
  EXACTLY 7 slides, 16:9, white background, navy + teal accent, risk colours only on RAG items, body text ≥ 18 pt, ≤ 5 bullets,
  speaker notes on every slide. Architecture drawn as native shapes. Real dashboard crops (`scripts/crop_screenshots.py`
  from refreshed `docs/screenshots/`, demo story then REPLAY 40).
- Every number is read at build time from script outputs (eval_results.json, benchmark_results.json,
  trigger_replay_{before,n2_task2}.json, StressEngine.run, weights.yaml). Accuracy is labelled "Preliminary (labels pending
  human review)"; stress figures are labelled "Illustrative model, synthetic portfolio".
- Rendered with PowerPoint COM (`scripts/render_slides.ps1`, LibreOffice not installed) to `docs/presentation/preview/slide-1..7.png`
  and inspected. Fixed over 3 passes: mid-word breaks in chevrons → boxes + arrows; image overflowing slide 6; rounded
  numbers → exact script values; sub-18 pt body text raised; label wrap; shape shadows. `tasks.ps1 deck` rebuilds all.

### Night 2 · Task 6: silent demo video + GitHub (DONE)
- `scripts/record_demo_video.py` (`tasks.ps1 video`): starts the API (offline) + dashboard, resets, plays the SYNTHETIC story with
  15 s steps, and drives the INSTALLED Microsoft Edge via Playwright (channel msedge, no browser download) with on-screen
  captions. Playwright's ffmpeg (needed for video) was installed into `.tmp/ms-playwright` (git-ignored), not the user profile.
- Output `docs/demo/demo_walkthrough.webm`: 3:30, 1600×900, VP8, 18.1 MB (< 20 MB, so committed). Spot-checked frames:
  explainability, stress banner + waterfall with caption, portfolio. One sampled frame (0:20) shows a page still loading
  (Streamlit render under memory pressure). Acceptable for a silent backup; a narrated recording is still a human task.
- GitHub: no `origin` remote and no `GITHUB_REMOTE_URL`, so nothing pushed and no repo created; push commands are in
  docs/NIGHT2_REPORT.md.

## Capture log (CACHED_REAL growth)

| When (UTC) | Milestone start | New docs | Cache total |
|---|---|---|---|
| 2026-10-03 17:22 | M1 (first run) | 726 | 726 |
| 2026-10-03 17:22 | M1 (second run) | 53 | 779 |
| 2026-10-03 17:38 | M2 | 40 | 819 |
| 2026-10-03 17:55 | M3 | 36 | 855 |
| 2026-10-03 18:16 | M4 | 36 | 891 |
| 2026-10-03 18:25 | M5 | 5 | 896 |
| 2026-10-03 18:32 | M5 (health snapshot run) | 3 | 899 |
| 2026-10-03 18:39 | M6 | 4 | 903 |
| 2026-10-03 18:55 | M7 | 1 | 904 |
| 2026-10-03 19:37 | M8 | 7 | 911 |
| 2026-10-05 19:24 | Night 2 start | 372 (263 news, 109 social) | 1283 |

## Milestones

### M0 — skeleton (commit 4736c1f) — DONE, user-confirmed
Config, schemas, logging, probe_sources.py, setup_models.py (FinBERT + spaCy, offline-verified), 20 tests.

### M1 — ingestion (commit ca7bc1d) — DONE, user-confirmed
Adapters: Google News, Finnhub (key optional), GDELT, Reddit RSS (1 sub/cycle, 120 s gap, 15 min 429 backoff),
Mastodon (passed probe), Bluesky (auth, skips w/o creds), StockTwits. Clean + dedup (cross-source near-dups kept
for corroboration), capture_cache.py, replay, scenario, scheduler. 51 tests.

### M2 — NLP core — DONE (self-gated)
**Files:** `risk_engine/entity_resolution/{universe.yaml,resolver.py}`, `risk_engine/sentiment/{finbert.py,lexicon_fallback.py}`,
`risk_engine/event_classifier/{taxonomy.yaml,rules.py,zero_shot.py}`, `risk_engine/impact_scoring/{weights.yaml,scorer.py,corroboration.py}`,
`risk_engine/pipeline.py`, `scripts/scrub_cache.py`, `tests/test_nlp.py`, `BUILD_PROMPT.md` (spec saved verbatim), privacy changes in social adapters.
**Run:** `.venv\Scripts\python.exe -m risk_engine.pipeline "Moody's downgrades Tata Motors to junk as SEBI opens probe into accounting"`
**Actual output (abridged):** company Tata Motors Ltd., sentiment −0.903 (finbert, conf 0.916), event Credit Event + secondary Regulatory,
evidence [downgrades, junk, moody's, probe, sebi], impact 7.4 High, factors E .90 M .903 X .30 R .60 Q .966 (no portfolio yet → non-held).
**Tests:** 101 passed (incl. 1 `@pytest.mark.model` real-FinBERT test), ruff clean.
**Smoke over real cache:** all 819 cached docs processed, 0 rejected; events: Other 387, Macro 147, Geopolitical 84, Credit 71,
Earnings 66, …; ~216 ms/doc batched on this CPU (to be benchmarked properly in M7).
**Privacy:** social adapters no longer store author handles (publisher = channel: `#tag`, `r/sub`, `$TICKER stream`, `search: q`);
@mentions in social text → `@user`; `scripts/scrub_cache.py` scrubbed 129 existing records; grep confirms 0 `"publisher":"@`.
Remaining `@name` strings exist only inside post URLs (allowed by user decision). Replay re-cleans "# Finance" → "#Finance" on load.
**Impact scorer + corroboration were built in M2** (CLI must print a full RiskSignal) — no stub was needed; M3 wires them to store/API.
**Known issues:** keyword rules give false positives (e.g. "The war on data centres" → Geopolitical); 47% of real docs → Other;
ORG-less headlines from a ticker-specific Google query fall back to the query's ticker hint (macro ones become MARKET).

### M3 — store, bus, API — DONE (self-gated)
**Files:** `risk_engine/store.py` (SQLite: documents, signals, stress_runs, stress_results, source_health; indexes
signals(ticker,timestamp), signals(event_type)), `risk_engine/bus.py` (signal.created, stress.completed), `risk_engine/ingestion/state.py`,
`app/runtime.py` (single ingest/analyze path, LIVE scheduler with capture state, REPLAY/SCENARIO playback, reset),
`app/main.py`, `app/api/{models,deps,routes_signals,routes_health,routes_demo}.py`, `tests/test_api.py`.
**Run:** `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000` → http://127.0.0.1:8000/docs
**Actual output (real server, FinBERT):** /health status ok, finbert loaded; /docs 200; POST /analyze "US imposes sweeping sanctions on Russia
as invasion fears grow; markets plunge" → MARKET, Geopolitical, 9.1 Critical, SYNTHETIC; empty text → 422; SSE emitted `event: signal`
for it; persisted in /signals and /signals/export.jsonl.
**Tests:** 121 passed (fast + model), ruff clean. Every OpenAPI operation has an example (tested).
**Extra endpoints (small, needed by dashboard):** `POST /mode` (mode switch), `GET /demo/status`.
**Fixes found while testing:** langdetect called "Apple unveils new iPhone lineup" French (0.99999) → language check skipped under
40 chars and overruled by English function words; the pipeline no longer doubles title+text for the language check.
SSE implemented with a plain StreamingResponse (sse-starlette removed from requirements). Ruff B008 configured for FastAPI markers.
**Known issues:** SSE clients that subscribe after an event miss it unless they use `replay_last`; `/demo/reset` deletes all
stress runs (incl. ones triggered by LIVE signals) — acceptable for a demo tool, documented in the endpoint summary.

### M4 — Module B stress engine — DONE (self-gated)
**Files:** `portfolio/{generate_portfolio.py,portfolio_data.csv,loader.py,pricers.py,scenarios.yaml,triggers.py,stress_engine.py}`,
`app/api/routes_portfolio.py` (GET /portfolio, GET /portfolio/scenarios, GET+POST /portfolio/stress-test, GET /stress-runs, GET /stress-runs/{id}),
`tests/test_stress.py`; runtime/main wiring (stress engine subscribes to `signal.created`; scorer gets portfolio exposures).
**Portfolio:** 49 SYNTHETIC positions (seed 42), funded MV 830.0m USD; gross mix Loan 40% / Bond 35% / IRS 8% / Equity 8% / FX 5% / CDS 4%;
3 CDS protection-bought hedges (Tata Motors, Adani, Ford); 23 held issuers (Walmart, Pfizer deliberately not held).
**Scenario losses (loss % of funded MV, `StressEngine.run`):** geopolitical_severe 2.45% RED, geopolitical_moderate 1.32% AMBER,
macro_rate_shock_severe 8.06% RED, macro_rate_shock_moderate 4.24% RED, systemic_credit_severe 3.65% RED,
systemic_credit_moderate 1.90% AMBER, idiosyncratic_credit (Tata Motors) 0.41% GREEN. Sanity band 0.5–15% for severe: PASS, no recalibration.
**E2E on real server (FinBERT):** "China blockades Taiwan …" → MARKET Geopolitical 8.8 Critical → geopolitical_severe run 2.45% RED with
trigger_signal_id; "Moody's downgrades Adani Enterprises to junk as SEBI widens fraud probe" → Credit Event 9.0 (X .957 held) →
idiosyncratic_credit IN-ADANIENT 0.15% GREEN (CDS hedge offsets).
**Tests:** 139 passed, ruff clean.

### M5 — Dashboard — DONE (self-gated)
**Files:** `app/dashboard/{Home.py,api_client.py}`, `app/dashboard/components/{ui.py,charts.py}`,
`app/dashboard/pages/{1_News_Social_Feed,2_NLP_Risk_Signals,3_Portfolio,4_Stress_Test,5_Explainability,6_Source_Health}.py`,
`.streamlit/config.toml`, `scripts/check_dashboard.py` (AppTest every page against the running API),
`scripts/screenshot_dashboard.py` (headless Edge via DevTools), `docs/screenshots/*.png`, `data/scenarios/demo_story.json`,
`GET /methodology` endpoint (weights/priors/thresholds for the explainability view).
**Sections:** 1 Executive overview (Home: KPI cards, alert banner, top signals, data mix) · 2 Feed (provenance incl. capture time) ·
3 Signals table (risk colours + text) · 4 Sentiment trend · 5 Event distribution · 6 Impact distribution + top-10 · 7 Portfolio ·
8 Trigger banner (signal + scenario + rule) · 9 Waterfall · 10 Top-10 positions (hedges green) · 11 Sector×asset-class heatmap ·
12 Explainability (+ "Analyse your own headline"); sidebar: mode switch, demo start/reset, auto-refresh, source health; disclaimer on stress views.
**Verified:** `scripts/check_dashboard.py` → 7/7 pages render without errors both on an empty DB and after demo story + REPLAY(40)
(Signals page 3 charts, Stress page 3 charts + 5 tables, Explainability 2 charts, Portfolio 4 charts). Real `streamlit run` served
(/_stcore/health ok) and 7 screenshots captured headlessly (docs/screenshots/). API-down path shows a clear error (ApiError → st.error).
**Demo story (SYNTHETIC) scored by the real pipeline:** (1) Nvidia GPU launch via social → 3.6 Low, no trigger; (2) Moody's/SEBI Tata Motors
→ 8.7 Critical → idiosyncratic_credit 0.41%; (3) invasion wire → 7.0 High → geopolitical_moderate 1.32%; (4) corroborating source →
9.1 Critical, 2 sources → geopolitical_severe 2.45%.
**Found during verification:** REPLAY of real data turned a fund's quarterly letter ("inflation remained above the Fed's target") into
MARKET Macroeconomic 7.1 → macro_rate_shock_moderate (4.24%). This is a real systemic false positive of the keyword rules (judge Q&A).
**Tests:** 139 passed, ruff clean.

### M6 — Demo, drills, full suite — DONE (self-gated)
**Files:** `scripts/run_demo.py` (one command: API + dashboard + reset + story; `--offline`, `--replay N`, `--exit-after-story`),
`scripts/failure_drill.py` (process-level offline/outage drill), `tests/test_failure_drills.py` (source killed mid-run), `DEMO.md`,
tasks.ps1/Makefile targets (api, dashboard, demo, demo-offline, drill, check-dashboard, screenshots, portfolio, capture, test).
**Determinism:** `run_demo.py --offline --exit-after-story --step-seconds 2` run twice → identical signals/scores/stress results
(3.6 Low · 8.7 Critical → idiosyncratic 0.41% GREEN · 7.0 High → geopolitical_moderate 1.32% AMBER · 9.1 Critical (2 sources) →
geopolitical_severe 2.45% RED). (A display race that hid the last signal in the console was fixed with a final poll.)
**Offline + outage drill (`scripts/failure_drill.py`): 7/7 PASS** — API starts with HF offline + all outbound HTTP via a dead proxy;
FinBERT loads from ./models; SCENARIO story 4 signals / 3 runs; LIVE → google_news/mastodon/reddit DEGRADED, gdelt/stocktwits BACKOFF,
finnhub/bluesky DISABLED, none OK; API keeps serving; REPLAY 10 CACHED_REAL signals; dashboard 7/7 pages during the outage.
**Source-kill drill (pytest):** google_news killed after cycle 1 → DEGRADED, DEGRADED, DOWN; reddit stays OK and keeps feeding signals;
/health shows DOWN with the ConnectError.
**Bug found + fixed:** token-bucket float rounding made a source with more requests than burst capacity report RATE_LIMITED after
waiting (Mastodon in the M6 capture); now sleeps wait + 50 ms; regression test added.
**Tests:** 142 passed (141 fast + 1 model), coverage 88% (`tasks.ps1 test`, coverage.xml), ruff clean. Screenshots refreshed from a real
demo run (story + REPLAY 30).
**Known issues:** REPLAY of real data produces systemic false positives (e.g. a Cyprus investment-fund article → MARKET Macroeconomic
8.0 → macro_rate_shock_moderate 4.24% RED); the demo story itself is unaffected (REPLAY is opt-in via `--replay`).

### M7 — Evaluation + docs — DONE (self-gated)
**Eval set:** `data/eval/labelled_headlines.csv`, n=147 real CACHED_REAL items (75 random, seed 42, stratified by source; 72
keyword-targeted for rarer classes); gold labels drafted by the agent, every row `label_status=draft_agent`; labels never taken
from model outputs; predictions kept separately in `data/eval/predictions.csv`.
**`scripts/evaluate.py` (PRELIMINARY):** FinBERT sentiment acc 0.653 / macro-F1 0.648; lexicon fallback 0.68 / 0.675; rule events
acc 0.803 / macro-F1 0.792; entity acc 0.891 (all n=147); random subset (n=75): sentiment 0.60, events 0.827, entities 0.853.
Zero-shot (typeform/distilbert-base-uncased-mnli): rules 0.792 vs rules+zero-shot 0.770 macro-F1 → kept OFF.
StockTwits tag agreement: not measured (n=0, blocked). Same-author-bias caveat written into docs/evaluation.md.
**`scripts/benchmark_latency.py`:** n=200 real docs, median 204.7 ms, p95 1085.2 ms, mean 374.8 ms per document; batched 278.9 ms/doc
(after length-sorted batching; was 532.2 before the fix); model load 5.5 s.
**Docs:** README (full §14), docs/{architecture,methodology,slides_outline (exactly 7),demo_script (5:00 + backup),judge_qa (28 Q,
⚠️ flagged),audit (table + harsh scores, overall 70/100),benchmark,evaluation}.md; data_sources.md re-probe (Google/Reddit/Mastodon PASS).
**Fresh-clone check:** `git clone` → `.tmp/clone` → `tasks.ps1 setup` (exit 0: venv, pinned install, FinBERT+spaCy verified offline)
→ `tasks.ps1 test` → 142 passed, coverage 88%; clone deleted afterwards.
**Transient:** one `setup_models.py --zero-shot` run reported FinBERT offline-verify FAIL with empty stderr while the machine was out
of process resources (bash fork errors at the same time); `--verify-only` re-run PASSED for all three models.

### M8 — DoSelect submission pack — DONE (self-gated; links pending from user)
**Files:** `docs/submission/doselect_answer.md` (source), `docs/submission/doselect_answer.html` (paste this; tags h2/h3/p/ul/li/strong only),
`scripts/build_submission.py` (renderer + 19 mechanical checks), tasks.ps1/Makefile targets `evaluate`, `benchmark`, `submission`.
**Check result:** 19/19 PASS — sections in order, 1,047 words, exec summary 73 words, 7 feature bullets, no code, allowed HTML tags,
claimed sources {google_news, reddit, mastodon} = probe PASS set, every Results number (12) traced to eval/benchmark JSON or a live
StressEngine run, only the 3 link placeholders, SYNTHETIC/CACHED_REAL/simulated present, "not investment advice" present,
5 limitations with required topics, capture-date phrase matches the cache, PRELIMINARY flagged.
**NOT READY TO SUBMIT** until the user supplies the 3 links → replace placeholders → `tasks.ps1 submission` → confirm 0 placeholders.
**Manual review (non-mechanical items):** every feature named in the answer exists and is visible in the demo (provenance badges, one
pipeline, explainability page, corroboration escalation in story step 4, trigger audit log, 12-section dashboard + headline box,
offline drill). README uses the same numbers and the same source list.
**Final state:** 142 tests passed, coverage 88%, ruff clean.

### Post-M8 task 1: trigger false positives (DONE)
**Changes:**
- Systemic stress only from news sources (`SYSTEMIC_TRIGGER_SOURCES` = google_news, finnhub, gdelt; scenario docs use
  the imitated source); social posts only add corroboration.
- A MARKET-wide Macroeconomic/Geopolitical call needs >= 2 distinct matched patterns (`market_min_distinct_patterns`),
  else demoted to secondary/Other (`pipeline.classify_and_resolve`, shared with evaluate.py).
- Figurative-war guards (price/talent/culture/bidding/turf/streaming/console/fare war; "war on <lowercase>").
- Adjectival country forms (Russian, Iranian, …).
- Fuzzy entity match needs all distinctive tokens ("SEC" no longer resolves to Government of India via "G-Sec").
- Regression tests: `tests/test_trigger_regressions.py`, using the exact real headlines.
**Replay over all 911 cached docs** (`scripts/replay_trigger_report.py` → docs/trigger_replay.md): stress runs 84 → 59;
systemic 74 → 50; idiosyncratic 10 → 9; social-triggered 11 → 0; 26 removed (some genuine single-cue stories: recall
cost), 1 added (cooldown side effect). Remaining FPs: positive court/regulatory news (Adani court relief, Jio SEBI
clearance) fires idiosyncratic; "Verdict" in an analyst headline → Litigation; rate cuts map to the hike scenario family.
**Evaluate (PRELIMINARY, n=147):** FinBERT 0.653/0.648 unchanged; events 0.803/0.792 → 0.762/0.768; entities
0.891 → 0.857; zero-shot 0.768 vs 0.751 → stays off. The drop is the guard demoting single-cue macro headlines that
the draft labels call MARKET Macroeconomic.
**Demo story unchanged:** 3.6 Low · 8.7 → idiosyncratic 0.41% · 7.0 → moderate 1.32% · 9.1 → severe 2.45%.
**Environment note:** a full pytest run segfaulted inside torch while loading FinBERT (Windows access violation) with
0.7–1.0 GB RAM free (other applications holding memory); the model test passed when run alone. No code fault found.
**Tests:** 155 fast passed + 1 model test passed (separate processes); ruff clean; build_submission 19/19 (1,064 words).

### Post-M8 task 2: public-repo data hygiene (DONE)
- `data/cache/captures/` removed from ALL history (`git filter-branch --index-filter`) and git-ignored; the 10 local
  capture files are kept on disk (backup also in `.tmp/backup/`, git-ignored).
- `data/cache/sample/sample_google_news.jsonl`: 50 Google News headlines (news only, CACHED_REAL, real capture
  timestamps 2026-10-03), built by `scripts/build_cache_sample.py`. REPLAY falls back to it when captures/ is empty;
  capture dedup and the cache count use captures only.
- Every `Co-Authored-By` line removed from all commit messages (`--msg-filter`); no attribution lines are added any more.
- Purged `refs/original`, expired the reflog, `gc --prune=now --aggressive`: only `refs/heads/main` remains.
- **Verification:** `git log --all --format=%B | findstr /i "co-authored"` printed nothing (exit 1); 0 `captures/` paths
  in `git log --all --name-only`; 0 `captures` objects in `git rev-list --all --objects`; no "generated with",
  "claude", "anthropic" or "noreply@" in any message.
- **Fresh clone** (`.tmp/clone2`, deleted afterwards): 0 capture files, 50-line sample; 157 fast tests + 1 FinBERT test passed
  (existing venv, identical pinned deps); REPLAY streamed from the sample. `build_submission.py` now reports a clear FAIL
  (not a crash) when `data/probe_results.json` is missing, since the probe is machine-specific.
- A pre-rewrite bundle of the old history is at `.tmp/backup/pre-rewrite.bundle` (local only; it still contains the
  old captures and attribution lines). Delete it once you are happy.
- Coverage (fast suite, `--cov`): 87%.

### Post-M8 task 3: docs consistency (DONE)
README, DEMO.md, docs/{data_sources,methodology,architecture,judge_qa,slides_outline,audit,OVERNIGHT_REPORT}.md and the
DoSelect answer now state: news-only systemic triggers; the 84 → 59 replay figure comes from the LOCAL (unpublished)
capture cache; only a 50-headline news sample is published; tests 158 (157 fast + 1 model); coverage 87% (fast suite);
evaluation numbers from the latest PRELIMINARY run. OVERNIGHT_REPORT hashes were updated to the rewritten history.
build_submission 19/19 (1,068 words; 3 link placeholders remain).

## User overrides / decisions given (2026-10-03, before overnight run)
- Portfolio: synthetic, seed 42, labelled SYNTHETIC.
- Finnhub/Bluesky only if keys in .env at run time (none present tonight).
- Zero-shot OFF unless evaluate.py shows macro-F1 gain; record comparison either way.
- Prioritise working end-to-end demo over polish (deadline unknown).
- Privacy: no author handles in RawDocument/captures; scripts/scrub_cache.py removes them from existing captures.
- Old "# Finance" hashtag spacing: re-clean on load.
- LIVE mode loads capture state.json at startup (M3).
- Eval labels drafted by the agent must carry label_status=draft_agent; metrics marked PRELIMINARY.

## Blockers / decisions

- D19 (task 1): manual/API text (source `manual`) can no longer trigger SYSTEMIC stress (not a news source); idiosyncratic triggers are unchanged. The e2e API test now submits as google_news.
- D20 (task 1): kept the >= 2-pattern rule at classification level as instructed, even though it lowers event accuracy on the draft labels; an alternative is applying it only at trigger level (user decision).

- D1 (M2): `token_set_ratio` is 100 for any token subset ("Bank" vs "Bank of America"), so fuzzy matching runs only on spaCy
  ORG spans and requires a shared non-generic token; ORG spans made only of ambiguous brand words need context like aliases.
- D2 (M2): ambiguous aliases must also be capitalised in the alias step ("apple pie" never matches).
- D3 (M2): a document's ticker hint (from a ticker-specific Google News query) is used only when the text names no company,
  and is overridden by MARKET for Geopolitical/Macroeconomic events.
- D4 (M2): corroboration for MARKET additionally requires one shared evidence phrase (otherwise any two geopolitical
  headlines in 6 h would "corroborate" each other). Earlier signals are not rewritten when later ones corroborate them.
- D5 (M2): manual/CLI/API text without an explicit provenance is labelled SYNTHETIC (user-supplied, not fetched).
- D6 (M2): event tie-break order = taxonomy.yaml order (most severe first) unless zero-shot is enabled.
- D7 (M2): rating buckets in universe.yaml are illustrative approximations, labelled as such.
- D8 (M4): portfolio mix (~40/35/≤10) is measured on gross exposure (MV for loans/bonds/equity, notional for derivative
  overlays); loss % is measured against funded MV (derivatives start at MV 0).
- D9 (M4): IRS DV01 stored positive; pay_fixed ΔV = +DV01×Δbp (gains when rates rise) — corrects the spec's sign typo.
- D10 (M4): bonds split rate and spread duration (US Treasuries have spread duration 0, so no credit-spread shock);
  for corporates this equals the spec formula.
- D11 (M4): loan PD multiplier per bucket = 1 + (scenario PD× − 1) × sensitivity (AAA-AA .5 … B-or-below 1.5).
- D12 (M4): added `systemic_credit_moderate` (half of severe) because the spec table has no moderate credit scenario.
- D13 (M4): FX shock applies only to FX forwards (direction refers to the EM currency); FX translation of INR-denominated
  loans/bonds/equity is NOT modelled (they are carried in USD equivalent) — limitation.
- D14 (M4): a corroborated (≥2 sources) credit event on a held issuer fires BOTH systemic and idiosyncratic triggers (spec rules
  overlap); each is a separate audited run. Cooldown uses wall-clock processing time.
- D15 (M4): Walmart and Pfizer are not held so the "non-held resolved" exposure path (X=0.3) is demonstrable.
- D16 (M5): under the spec weights a POSITIVE product-launch headline about a LARGE holding cannot score "Low" (Apple via a news
  source = 5.3 Medium: positive sentiment still adds M×0.6, and X/R are high). Weights were NOT changed; demo step 1 uses a small
  holding (Nvidia, X .55) seen on a social source (R .40) → 3.6 Low. The score measures materiality/attention, not downside only.
- D17 (M5): Streamlit theme fixed to light (projector); no dark mode for the dashboard.
- D18 (M5): source-health panel falls back to the last capture_cache.py run (labelled as such) when the API is not polling live.

## Stretch ideas

(none yet)
