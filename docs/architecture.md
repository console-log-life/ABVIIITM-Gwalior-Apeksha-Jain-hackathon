# Architecture

```
            ┌──────────────────────── Sources ────────────────────────┐
            │ Google News RSS · Reddit RSS · Mastodon tags  (keyless)  │
            │ GDELT · StockTwits (best-effort) · Finnhub · Bluesky (opt)│
            └───────────────┬─────────────────────────────────────────┘
                            │ adapters: token bucket, timeouts, ≤2 retries, backoff, health
  data/cache (CACHED_REAL) ─┤ REPLAY          SCENARIO (SYNTHETIC story) ─┐   POST /analyze
                            ▼                                             ▼        │
                     clean · language · dedup (SHA-1 + rapidfuzz ≥ 92)             │
                            │                                                       │
                            ▼          risk_engine.pipeline.process_batch()  ◄──────┘
        entity resolution → FinBERT sentiment → rule events → corroboration → impact score
                            │
                            ▼  RiskSignal (Pydantic, provenance on every record)
                 SQLite store ── bus: signal.created ──► Stress engine (Module B)
                     │                                     │ triggers → pricers → results
                     │                bus: stress.completed ◄┘ (stored with trigger signal_id)
                     ▼
            FastAPI: REST · SSE /signals/stream · JSONL export · Swagger /docs
                     │
                     ▼
            Streamlit dashboard (12 sections + watchlist, via api_client.py)
```

## Components

| Layer | Code | Notes |
|---|---|---|
| Config | `src/app/config.py` | pydantic-settings, `.env`, runs with zero keys |
| Ingestion | `src/risk_engine/ingestion/` | `base.py` (rate limit, retries, health), one adapter per source, `scheduler.py` (LIVE), `replay.py`, `scenario.py`, `state.py` (shared with `capture_cache.py`) |
| Preprocessing | `src/risk_engine/preprocessing/` | `clean.py`, `dedup.py` |
| NLP | `risk_engine/{entity_resolution,sentiment,event_classifier,impact_scoring}/`, `pipeline.py` | one pipeline for every mode |
| Persistence / messaging | `src/risk_engine/store.py`, `src/risk_engine/bus.py` | SQLite (5 tables, indexed); in-process async pub/sub |
| Runtime | `src/app/runtime.py` | owns store, bus, pipeline, LIVE task, demo playback; restart-safe corroboration window |
| API | `src/app/main.py`, `src/app/api/` | `/health /methodology /analyze /analyze/batch /signals /signals/{ticker} /signals/stream /signals/export.jsonl /portfolio /portfolio/scenarios /portfolio/stress-test /stress-runs /demo/* /mode` |
| Module B | `portfolio/` | generator, loader, pricers, scenarios, triggers, stress engine |
| Dashboard | `src/app/dashboard/` | Streamlit + Plotly, talks only to the API |
| Tooling | `src/scripts/` | probe, setup_models, capture_cache, build_cache_sample, scrub_cache, replay_trigger_report, evaluate, benchmark_latency, run_demo, failure_drill, check_dashboard, screenshot_dashboard |

## Reliability design

- **No source failure crashes the app.** Each adapter call has a timeout (≤ 10 s, GDELT ≤ 20 s), at most 2 retries
  (transport errors and 5xx), and a backoff. HTTP 429 and 403 park the source. Every outcome is reported on `/health`
  and in the dashboard health panel.
- **Offline demo.** Models are cached in `./models`. `HF_HUB_OFFLINE=1` works, as verified by `src/scripts/failure_drill.py`
  (7/7 checks with all outbound HTTP blocked).
- **Idempotent ingestion.** `doc_id` is unique in the store, so a duplicate article never produces a second signal or a
  second stress run.
- **Determinism.** The same demo story and the seed-42 portfolio give identical outputs on every run.

## Scaling path (not built)

1. Replace the in-process bus with Kafka or Redis Streams.
2. Replace SQLite with Postgres or Timescale.
3. Run the adapters as separate workers.
4. Serve FinBERT behind a batching inference server.
5. Add authentication and role-based access on the API.
