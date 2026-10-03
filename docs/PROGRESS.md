# PROGRESS (build memory — read this first after any restart)

**Current milestone:** M4 (portfolio + stress engine) — starting
**Last commit:** see `git log -1` (M3 committed)
**Next step:** M4 capture run, then generate_portfolio.py / pricers.py / scenarios.yaml / triggers.py / stress_engine.py

Mode: AUTONOMOUS OVERNIGHT (user instruction 2026-10-03): self-gates instead of stops; commit `M<n>: …` after
each milestone; run `scripts/capture_cache.py` at the start of each milestone; spec = BUILD_PROMPT.md
plus overrides recorded below. No pushes, no remotes, no `git reset --hard`, nothing outside the project dir.

## Capture log (CACHED_REAL growth)

| When (UTC) | Milestone start | New docs | Cache total |
|---|---|---|---|
| 2026-10-03 17:22 | M1 (first run) | 726 | 726 |
| 2026-10-03 17:22 | M1 (second run) | 53 | 779 |
| 2026-10-03 17:38 | M2 | 40 | 819 |
| 2026-10-03 17:55 | M3 | 36 | 855 |

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

## Stretch ideas

(none yet)
